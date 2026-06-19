"""Build final recommendation from historical stats."""

from __future__ import annotations

import math

import config as cfg
from analysis.rules.types import (
    AH_CN,
    CONFIDENCE_CN,
    MIN_SAMPLES_FOR_PICK,
    OU_CN,
    RESULT_CN,
    Recommendation,
)
from analysis.signals.market_control import LEVEL_CN, RISK_CN, analyze_control
from analysis.signals.odds import MarketSignals
from analysis.signals.traps import TrapAnalysis, analyze_traps, apply_penalties


def _get_hist_rates(stats: dict, eu_stats: dict) -> tuple[dict[str, float], str] | None:
    ah_count = stats.get("count") or 0
    eu_count = eu_stats.get("count") or 0
    if ah_count == 0 and eu_count == 0:
        return None
    ah_ready = ah_count >= MIN_SAMPLES_FOR_PICK
    eu_ready = eu_count >= MIN_SAMPLES_FOR_PICK
    if ah_ready and eu_ready:
        ah_rates = {
            "home": stats.get("home_win_rate") or 0,
            "draw": stats.get("draw_rate") or 0,
            "away": stats.get("away_win_rate") or 0,
        }
        eu_rates = {
            "home": eu_stats.get("home_win_rate") or 0,
            "draw": eu_stats.get("draw_rate") or 0,
            "away": eu_stats.get("away_win_rate") or 0,
        }
        ah_w = math.sqrt(ah_count)
        eu_w = min(math.sqrt(eu_count), ah_w * cfg.HIST_EU_BLEND_MAX_WEIGHT_RATIO)
        total_w = ah_w + eu_w
        rates = {
            k: (ah_rates[k] * ah_w + eu_rates[k] * eu_w) / total_w
            for k in ("home", "draw", "away")
        }
        return rates, "blended"
    if ah_count >= MIN_SAMPLES_FOR_PICK:
        rates = {
            "home": stats.get("home_win_rate") or 0,
            "draw": stats.get("draw_rate") or 0,
            "away": stats.get("away_win_rate") or 0,
        }
        return rates, "asian"
    if eu_count >= MIN_SAMPLES_FOR_PICK:
        rates = {
            "home": eu_stats.get("home_win_rate") or 0,
            "draw": eu_stats.get("draw_rate") or 0,
            "away": eu_stats.get("away_win_rate") or 0,
        }
        return rates, "european"
    return None


def _pick_1x2(
    stats: dict,
    eu_stats: dict,
    market: MarketSignals | None = None,
) -> tuple[str, str, float, dict[str, float], str] | None:
    """Return (pick, cn, hist_top_rate, combined_rates, hist_only_pick)."""
    got = _get_hist_rates(stats, eu_stats)
    if got is None:
        return None
    hist_rates, _ = got
    hist_best = max(hist_rates, key=hist_rates.get)

    combined = dict(hist_rates)
    if market:
        for k in combined:
            combined[k] = combined[k] + market.bias_1x2.get(k, 0)

    best = max(combined, key=combined.get)
    return best, RESULT_CN[best], hist_rates, combined, hist_best


def _pick_1x2_combined(
    open_stats: dict,
    open_eu: dict,
    control,
    trap: TrapAnalysis,
) -> tuple[str, str, dict[str, float], dict[str, float], str] | None:
    """初盘历史 × 规律权重 × 诱盘惩罚 + 临盘信号；高控盘可改推次选。"""
    open_pick = _pick_1x2(open_stats, open_eu, None)
    if open_pick is None:
        return None
    _, _, hist_rates, _, hist_best = open_pick

    combined = {k: v * control.pattern_weight for k, v in hist_rates.items()}
    combined = apply_penalties(combined, trap)
    risk_adjusted_best = max(combined, key=combined.get)

    sig = control.signals
    allow_live_direction = (
        control.level != "high" or cfg.LIVE_SIGNAL_ALLOW_HIGH_CONTROL_DIRECTION
    )
    if sig and allow_live_direction and control.live_signal_scale > cfg.LIVE_SIGNAL_MIN_SCALE:
        scale = control.live_signal_scale * max(cfg.LIVE_SIGNAL_MIN_SCALE, 1 - control.pattern_weight)
        for k in combined:
            combined[k] += sig.bias_1x2.get(k, 0) * scale

    ordered = sorted(combined.items(), key=lambda x: -x[1])
    best_key = ordered[0][0]
    if best_key != risk_adjusted_best:
        risk_score = combined.get(risk_adjusted_best, 0)
        live_margin = combined[best_key] - risk_score
        if live_margin < cfg.LIVE_SIGNAL_SWITCH_MARGIN or trap.flagged_direction == best_key:
            best_key = risk_adjusted_best

    if control.intensity >= cfg.HIGH_CONTROL_TRAP_INTENSITY and len(ordered) >= 2:
        top_k, top_v = ordered[0]
        second_k, second_v = ordered[1]
        margin = top_v - second_v
        if margin < cfg.HIGH_CONTROL_MARGIN_FOR_SWITCH:
            if trap.flagged_direction == top_k:
                best_key = second_k
            elif trap.draw_steam and second_k == "draw":
                best_key = "draw"

    return best_key, RESULT_CN[best_key], hist_rates, combined, hist_best


def _link_ah_with_1x2(
    result: str,
    ah_pick: str,
    ah_reason: str,
    control,
    trap: TrapAnalysis,
) -> tuple[str, str, bool]:
    """1X2 与亚盘联动；返回 (ah_pick, reason, downgrade_confidence)。"""
    conflict = (result == "home" and ah_pick == "away") or (result == "away" and ah_pick == "home")
    downgrade = False

    if conflict:
        if cfg.AH_CONFLICT_FORCE_SKIP_ON_HIGH_CONTROL and control.level == "high":
            return "skip", "1X2与亚盘方向矛盾，高控盘建议观望", True
        ah_reason = f"{ah_reason}；与胜平负分裂，慎跟"
        downgrade = cfg.AH_CONFLICT_DOWNGRADE_CONFIDENCE

    if trap.flagged_direction == "home" and ah_pick == "home":
        ah_reason = f"{ah_reason}；升盘+降水疑诱上盘，慎追"
        downgrade = True
    if trap.flagged_direction == "away" and ah_pick == "away":
        ah_reason = f"{ah_reason}；降盘+降水疑诱下盘，慎追"
        downgrade = True

    return ah_pick, ah_reason, downgrade


def _pick_ah(
    stats: dict,
    market: MarketSignals | None = None,
    *,
    signal_scale: float = 1.0,
) -> tuple[str, str]:
    ah_count = stats.get("count") or 0
    if ah_count < MIN_SAMPLES_FOR_PICK:
        return "skip", f"亚盘相似样本不足 {MIN_SAMPLES_FOR_PICK} 场，不建议"
    home_net = stats.get("ah_home_net")
    away_net = stats.get("ah_away_net")
    if home_net is None or away_net is None:
        return "skip", "历史样本无亚盘结算数据"

    # positive diff => historical lower/away side better
    hist_diff = away_net - home_net
    market_adj = -(market.ah_side_bias if market else 0.0) * signal_scale
    effective = hist_diff + market_adj
    threshold = cfg.AH_EFFECTIVE_THRESHOLD
    if market and abs(market.ah_side_bias) >= cfg.AH_STRONG_BIAS and signal_scale >= 0.4:
        threshold = cfg.AH_EFFECTIVE_THRESHOLD_STRONG

    market_hint = ""
    if market and market.water_summary:
        market_hint = f"；盘口解读：{market.water_summary}"

    if effective >= threshold:
        reason = (
            f"历史中下盘更优（下盘净收益 {away_net:+.2f}/场）"
            f"{market_hint}"
        )
        return "away", reason
    if effective <= -threshold:
        reason = (
            f"历史+水位综合偏上盘（上盘净收益 {home_net:+.2f}/场，"
            f"临盘{'降水' if market and market.ah_side_bias > 0 else '走势'}支持上盘）"
            f"{market_hint}"
        )
        return "home", reason
    if market and market.ah_side_bias >= cfg.AH_STRONG_BIAS and signal_scale >= cfg.AH_SKIP_SIGNAL_SCALE:
        return "home", f"历史上下盘接近，临盘水位偏上盘（风控引导）{market_hint}"
    if market and market.ah_side_bias <= -cfg.AH_STRONG_BIAS and signal_scale >= cfg.AH_SKIP_SIGNAL_SCALE:
        return "away", f"历史上下盘接近，临盘水位偏下盘{market_hint}"
    if signal_scale < cfg.AH_SKIP_SIGNAL_SCALE:
        return "skip", f"控盘强度高，临盘水位不宜作为亚盘依据（有效差 {effective:+.3f}）"
    return "skip", f"亚盘历史与临盘水位均无明显方向（有效差 {effective:+.3f}）"


def _pick_scores_from_history(
    stats: dict,
    eu_stats: dict,
    result: str,
    hist_rates: dict[str, float],
    *,
    ah_count: int,
    eu_count: int,
) -> list[tuple[str, str | None]]:
    """
    Top-3 scores by joint probability within the similarity-weighted score pool:
      P(score) ≈ P(1X2 outcome in score pool) × P(score | outcome)
    """
    if ah_count >= MIN_SAMPLES_FOR_PICK:
        pool = stats
    elif eu_count >= MIN_SAMPLES_FOR_PICK:
        pool = eu_stats
    else:
        return []

    by_result = pool.get("score_top_by_result") or {}
    if not by_result:
        overall = pool.get("score_top") or []
        if overall and isinstance(overall[0], dict):
            return [(e["score"], f"{e['pct']}%") for e in overall[:3]]
        return [(sc, None) for sc, _ in overall[:3]]

    # 1X2 比例与比分来自同一 score pool（最相似 Top-N），避免与全量样本脱节
    outcome_weight = {
        outcome: sum(e.get("count", 0) for e in entries if isinstance(e, dict))
        for outcome, entries in by_result.items()
    }
    rate_sum = sum(outcome_weight.values()) or 1.0
    norm_rates = {k: outcome_weight.get(k, 0) / rate_sum for k in ("home", "draw", "away")}

    weighted: list[tuple[str, float, str]] = []
    for outcome, entries in by_result.items():
        if not entries or not isinstance(entries[0], dict):
            continue
        outcome_total = sum(e.get("count", 0) for e in entries)
        if outcome_total <= 0:
            continue
        p_outcome = norm_rates.get(outcome, 0)
        for e in entries:
            cond = e["count"] / outcome_total
            joint_pct = round(p_outcome * cond * 100, 1)
            weighted.append((e["score"], joint_pct, outcome))

    if not weighted:
        overall = pool.get("score_top") or []
        if overall and isinstance(overall[0], dict):
            return [(e["score"], f"{e['pct']}%") for e in overall[:3]]
        return []

    weighted.sort(key=lambda x: (-x[1], x[0]))

    primary = [x for x in weighted if x[2] == result]
    if not primary:
        return [(sc, f"{joint}%") for sc, joint, _ in weighted[:3]]

    ordered = sorted(norm_rates.items(), key=lambda kv: -kv[1])
    runner = next((o for o, _ in ordered if o != result), None)
    runner_rate = norm_rates.get(runner, 0) if runner else 0
    runner_scores = [x for x in weighted if runner and x[2] == runner]

    picked: list[tuple[str, str | None]] = []
    seen: set[str] = set()

    def _take_from(items: list[tuple[str, float, str]]) -> None:
        for sc, joint, _ in items:
            if sc in seen or len(picked) >= 3:
                continue
            seen.add(sc)
            picked.append((sc, f"{joint}%"))

    # ① 第一个必须与推荐赛果一致（主胜→不含 1-1 打头）
    _take_from(primary[:1])
    # ② 再取 1 个同赛果高分比分
    _take_from(primary[1:])
    # ③ 次选赛果（通常平局）≥22% 时补 1 个备选，不含反向赛果如 1-2
    if len(picked) < 3 and runner and runner_rate >= cfg.SCORE_RUNNER_MIN_RATE:
        _take_from(runner_scores)
    # ④ 仍不足则继续同赛果
    if len(picked) < 3:
        _take_from(primary)
    return picked[:3]


def _pick_scores(
    result: str,
    avg_goals: float | None,
    stats: dict | None = None,
    eu_stats: dict | None = None,
    hist_rates: dict[str, float] | None = None,
    *,
    ah_count: int = 0,
    eu_count: int = 0,
) -> tuple[list[str], list[str]]:
    if stats is not None and eu_stats is not None and hist_rates:
        historical = _pick_scores_from_history(
            stats, eu_stats, result, hist_rates,
            ah_count=ah_count, eu_count=eu_count,
        )
        if historical:
            scores = [sc for sc, _ in historical]
            detail = [
                f"{sc}({pct})" if pct else sc
                for sc, pct in historical
            ]
            return scores, detail

    # 仅样本不足时用模板
    g = avg_goals if avg_goals is not None else 2.5
    if result == "home":
        scores = ["2-1", "2-0", "3-1"] if g >= 2.7 else ["1-0", "2-0", "2-1"]
    elif result == "draw":
        scores = ["1-1", "0-0", "2-2"] if g <= 2.3 else ["1-1", "2-2", "0-0"]
    elif g >= 2.7:
        scores = ["1-2", "0-2", "1-3"]
    else:
        scores = ["0-1", "1-2", "0-2"]
    return scores, scores.copy()


def _pick_ou(avg_goals: float | None) -> tuple[str, str]:
    if avg_goals is None:
        return "neutral", "暂无数据"
    g = avg_goals
    if g >= cfg.OU_OVER_THRESHOLD:
        return "over_2.5", OU_CN["over_2.5"]
    if g <= cfg.OU_UNDER_THRESHOLD:
        return "under_2.5", OU_CN["under_2.5"]
    return "neutral", OU_CN["neutral"]


def _pick_confidence(
    count: int,
    combined_rates: dict[str, float],
    *,
    hist_best: str,
    final_pick: str,
    control,
    trap: TrapAnalysis,
    ah_conflict: bool = False,
) -> tuple[str, str]:
    ordered = sorted(combined_rates.values(), reverse=True)
    top = ordered[0]
    second = ordered[1] if len(ordered) > 1 else 0
    margin = top - second
    reasons: list[str] = []

    if hist_best != final_pick:
        reasons.append(f"初盘最高为{RESULT_CN[hist_best]}，诱盘/风控后改推{RESULT_CN[final_pick]}")
        return "low", "；".join(reasons)
    if trap.flagged_direction == final_pick:
        reasons.append(f"推荐方向存在{trap.flagged_direction}诱盘信号")
    if trap.severe:
        reasons.append("临盘剧烈震荡")
    if ah_conflict:
        reasons.append("1X2与亚盘分裂")
    if top < cfg.CONF_MIN_TOP_RATE:
        reasons.append(f"有效最高概率仅{_pct(top)}")
        return "low", "；".join(reasons) or "概率分散"
    if control.level == "high":
        reasons.append("高控盘")
        return "low", "；".join(reasons) or "高控盘"
    if control.level == "medium":
        if margin >= cfg.CONF_MED_MARGIN:
            return "medium", "中控盘但有效概率领先尚可"
        reasons.append("中控盘且领先幅度小")
        return "low", "；".join(reasons)
    if count >= cfg.CONF_HIGH_SAMPLE and margin >= cfg.CONF_HIGH_MARGIN:
        return "high", "样本充足且有效概率领先明显"
    if count >= MIN_SAMPLES_FOR_PICK and margin >= cfg.CONF_MED_MARGIN:
        return "medium", "有效概率领先适中"
    reasons.append("有效概率领先幅度不足")
    return "low", "；".join(reasons)


def _open_prob_summary(open_stats: dict, open_eu: dict) -> tuple[str, str]:
    got = _get_hist_rates(open_stats, open_eu)
    if not got:
        return "", ""
    rates, src = got
    ah_n = open_stats.get("count") or 0
    eu_n = open_eu.get("count") or 0
    n = ah_n if src == "asian" else eu_n
    best = max(rates, key=rates.get)
    src_txt = "亚盘+欧赔融合" if src == "blended" else ("亚盘" if src == "asian" else "欧赔")
    n_txt = f"{ah_n}/{eu_n}" if src == "blended" else str(n)
    txt = (
        f"初盘{src_txt}相似 {n_txt} 场："
        f"主胜 {_pct(rates['home'])}、平 {_pct(rates['draw'])}、"
        f"客胜 {_pct(rates['away'])} → 赛事本身倾向 {RESULT_CN[best]}"
    )
    return RESULT_CN[best], txt


def build_recommendation(payload: dict) -> Recommendation:
    cur = payload["current"]
    stats = payload["stats"]
    eu = payload["eu_stats"]
    open_stats = payload.get("open_stats") or stats
    open_eu = payload.get("open_eu_stats") or eu
    ah_count = stats.get("count") or 0
    eu_count = eu.get("count") or 0
    open_ah_count = open_stats.get("count") or 0
    open_eu_count = open_eu.get("count") or 0
    match_name = cur.get("match_name", "")
    auto_relaxed = payload.get("auto_relaxed", False)
    control = analyze_control(cur)
    trap = analyze_traps(cur, intensity=control.intensity, level=control.level)

    open_cn, open_prob_txt = _open_prob_summary(open_stats, open_eu)
    pick = _pick_1x2_combined(open_stats, open_eu, control, trap)
    if pick is None:
        pick = _pick_1x2_combined(stats, eu, control, trap)

    gs_notes: list[str] = []
    gs_analysis = None
    if pick is not None and match_name:
        try:
            from group_stage_model import analyze_match_from_name, adjust_rates_for_group_stage

            gs_analysis = analyze_match_from_name(match_name)
            if gs_analysis and not gs_analysis.get("is_finished"):
                result, result_cn, hist_rates, combined, hist_best = pick
                combined, gs_notes = adjust_rates_for_group_stage(combined, gs_analysis)
                ordered = sorted(combined.items(), key=lambda x: -x[1])
                new_key = ordered[0][0]
                mt = gs_analysis.get("match_type")
                if mt in ("collusion_watch", "draw_friendly", "open_race"):
                    draw_v = combined.get("draw", 0)
                    if draw_v >= ordered[0][1] - 0.025:
                        new_key = "draw"
                elif mt == "must_win":
                    hs = gs_analysis.get("home_situation") or {}
                    aws = gs_analysis.get("away_situation") or {}
                    if hs.get("pressure") == "high" and aws.get("pressure") != "high":
                        if combined.get("home", 0) >= combined.get("away", 0) - 0.03:
                            new_key = "home"
                    elif aws.get("pressure") == "high" and hs.get("pressure") != "high":
                        if combined.get("away", 0) >= combined.get("home", 0) - 0.03:
                            new_key = "away"
                result, result_cn = new_key, RESULT_CN[new_key]
                pick = (result, result_cn, hist_rates, combined, hist_best)

            from knockout_path import build_match_knockout_context

            kctx = build_match_knockout_context(match_name)
            if kctx and kctx.get("same_group") and not (kctx.get("motivation") or {}).get("is_finished"):
                hint = kctx.get("prediction_hint") or {}
                if kctx.get("picking_level") in ("watch", "medium", "high"):
                    result, result_cn, hist_rates, combined, hist_best = pick
                    bias = float(hint.get("draw_bias") or 0.06)
                    combined = dict(combined)
                    combined["draw"] = combined.get("draw", 0) + bias
                    total = sum(combined.values()) or 1.0
                    combined = {k: v / total for k, v in combined.items()}
                    if hint.get("model_1x2_hint") == "draw":
                        draw_v = combined.get("draw", 0)
                        top = max(combined.values())
                        if draw_v >= top - 0.03:
                            result, result_cn = "draw", "平局"
                    pick = (result, result_cn, hist_rates, combined, hist_best)
                    gs_notes.append("淘汰赛路径：存在挑对手空间，模型略抬平局权重")
                    gs_notes.extend((hint.get("notes") or [])[:2])
                elif hint.get("picking_note"):
                    gs_notes.append(hint["picking_note"])
        except Exception:
            pass

    if pick is None:
        hint = "可尝试加 --relaxed 放宽匹配" if not auto_relaxed else "当前盘口较极端，历史库中缺少相近样本"
        detail = (
            f"初盘相似样本不足（亚盘 {open_ah_count} / 欧赔 {open_eu_count} 场，"
            f"需 ≥{MIN_SAMPLES_FOR_PICK}）。{hint}。"
        )
        return Recommendation(
            match=match_name,
            result_1x2="skip",
            result_1x2_cn="数据不足·暂不建议",
            likely_scores=[],
            likely_scores_detail=[],
            asian_handicap_pick="skip",
            asian_handicap_cn=AH_CN["skip"],
            asian_handicap_reason="样本不足，无法判断亚盘方向",
            over_under_hint="neutral",
            over_under_cn="暂无数据",
            confidence="low",
            confidence_cn=CONFIDENCE_CN["low"],
            summary=detail,
            sample_count=ah_count,
            eu_sample_count=eu_count,
            insufficient_data=True,
            market_notes=control.notes,
            open_result_1x2_cn=open_cn or "—",
            open_probability_summary=open_prob_txt,
            pattern_reference_cn="—",
            control_level_cn=LEVEL_CN[control.level],
            control_trajectory=control.trajectory_tag,
            risk_level_cn=RISK_CN[control.risk_level],
            open_sample_count=open_ah_count,
            open_eu_sample_count=open_eu_count,
        )

    result, result_cn, hist_rates, combined_rates, hist_best = pick
    count = max(open_ah_count, open_eu_count)

    ah_pick, ah_reason = _pick_ah(
        open_stats if open_ah_count >= MIN_SAMPLES_FOR_PICK else stats,
        control.signals,
        signal_scale=control.live_signal_scale,
    )
    ah_pick, ah_reason, ah_downgrade = _link_ah_with_1x2(result, ah_pick, ah_reason, control, trap)
    score_stats = open_stats if open_ah_count >= MIN_SAMPLES_FOR_PICK else open_eu
    score_eu = open_eu
    score_ah_n = open_ah_count
    score_eu_n = open_eu_count
    avg_goals = score_stats.get("avg_total_goals") or score_eu.get("avg_total_goals")
    scores, scores_detail = _pick_scores(
        result, avg_goals, score_stats, score_eu, hist_rates,
        ah_count=score_ah_n, eu_count=score_eu_n,
    )
    ou, ou_cn = _pick_ou(avg_goals)
    conf, conf_reason = _pick_confidence(
        count, combined_rates, hist_best=hist_best, final_pick=result, control=control,
        trap=trap, ah_conflict=ah_downgrade,
    )

    ah_line = cur.get("ah_line")
    if ah_pick == "home":
        ah_cn = f"上盘（主队 {ah_line}）"
    elif ah_pick == "away":
        ah_cn = f"下盘（客队 +{abs(ah_line or 0)}）"
    else:
        ah_cn = AH_CN["skip"]

    pattern_ref = f"{int(control.pattern_weight * 100)}%（{LEVEL_CN[control.level]}控盘）"
    mp = trap.market_patterns
    mp_summary = getattr(mp, "conversion_summary", "") if mp else ""
    mp_names = [p.get("name") for p in (getattr(mp, "patterns", None) or []) if p.get("name")]
    funds_txt = "；".join(trap.notes) if trap.notes else "临盘走势与初盘规律基本一致"
    all_notes = list(control.notes) + [n for n in trap.notes if n not in control.notes]
    if gs_notes:
        all_notes.extend(gs_notes)

    summary = (
        f"【赛事概率】{open_prob_txt}。"
        f"【资金解读】{funds_txt}。"
        f"【综合推荐】{result_cn}，比分 {'、'.join(scores_detail[:3]) if scores_detail else '—'}。"
        f"规律权重 {pattern_ref}。"
    )
    if hist_best != result:
        summary += f"（初盘单项最高 {RESULT_CN[hist_best]}，临盘风控调整后为 {result_cn}）"
    if auto_relaxed:
        summary += "（已自动放宽匹配条件）"
    if gs_analysis:
        summary += f"【小组战意】{gs_analysis.get('match_type_cn')}：{gs_analysis.get('likely_direction_cn')}。"

    return Recommendation(
        match=match_name,
        result_1x2=result,
        result_1x2_cn=result_cn,
        likely_scores=scores,
        likely_scores_detail=scores_detail,
        asian_handicap_pick=ah_pick,
        asian_handicap_cn=ah_cn,
        asian_handicap_reason=ah_reason,
        over_under_hint=ou,
        over_under_cn=ou_cn,
        confidence=conf,
        confidence_cn=CONFIDENCE_CN[conf],
        summary=summary,
        sample_count=ah_count,
        eu_sample_count=eu_count,
        insufficient_data=False,
        market_notes=all_notes,
        trap_notes=trap.notes,
        confidence_reason=conf_reason,
        funds_interpretation=funds_txt,
        open_result_1x2_cn=open_cn,
        open_probability_summary=open_prob_txt,
        pattern_reference_cn=pattern_ref,
        control_level_cn=LEVEL_CN[control.level],
        control_trajectory=control.trajectory_tag,
        risk_level_cn=RISK_CN[control.risk_level],
        open_sample_count=open_ah_count,
        open_eu_sample_count=open_eu_count,
        market_pattern_summary=mp_summary,
        market_pattern_names=mp_names or None,
    )


def recommendation_to_baseline(rec: Recommendation) -> dict:
    """Rule-based picks used as the single source of truth for final output."""
    return {
        "result_1x2": rec.result_1x2,
        "result_1x2_cn": rec.result_1x2_cn,
        "likely_scores": rec.likely_scores,
        "likely_scores_detail": rec.likely_scores_detail,
        "asian_handicap_pick": rec.asian_handicap_pick,
        "asian_handicap_cn": rec.asian_handicap_cn,
        "asian_handicap_reason": rec.asian_handicap_reason,
        "over_under_hint": rec.over_under_hint,
        "over_under_cn": rec.over_under_cn,
        "confidence": rec.confidence,
        "confidence_cn": rec.confidence_cn,
        "summary": rec.summary,
        "sample_count": rec.sample_count,
        "eu_sample_count": rec.eu_sample_count,
        "insufficient_data": rec.insufficient_data,
        "market_notes": rec.market_notes or [],
        "open_result_1x2_cn": rec.open_result_1x2_cn,
        "open_probability_summary": rec.open_probability_summary,
        "pattern_reference_cn": rec.pattern_reference_cn,
        "control_level_cn": rec.control_level_cn,
        "control_trajectory": rec.control_trajectory,
        "risk_level_cn": rec.risk_level_cn,
        "open_sample_count": rec.open_sample_count,
        "open_eu_sample_count": rec.open_eu_sample_count,
        "trap_notes": rec.trap_notes or [],
        "confidence_reason": rec.confidence_reason,
        "funds_interpretation": rec.funds_interpretation,
        "market_pattern_summary": rec.market_pattern_summary,
        "market_pattern_names": rec.market_pattern_names or [],
    }

