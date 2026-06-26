"""竞彩 SP / 让球胜平负 — 所有最终推荐以国内竞彩可售玩法为准."""

from __future__ import annotations

import re
from typing import Any

from product_focus import score_prediction_enabled

RQ_CN = {"home": "胜", "draw": "平", "away": "负", "skip": "观望"}
SP_CN = {"home": "主胜", "draw": "平局", "away": "客胜", "skip": "观望"}
KEY_FROM_RQ_CN = {"胜": "home", "平": "draw", "负": "away", "观望": "skip"}
KEY_FROM_SP_CN = {"主胜": "home", "平局": "draw", "客胜": "away", "观望": "skip"}
NO_JINGCAI = "暂无竞彩"
RQSP_LARGE_HANDICAP_ABS = 2


def jingcai_market_mode(jc: dict | None) -> str:
    """Return sp | rqsp | none — which Jingcai product is buyable."""
    if not jc:
        return "none"
    if jc.get("has_sp"):
        return "sp"
    if jc.get("has_rqsp"):
        return "rqsp"
    return "none"


def handicap_label(jc: dict) -> str:
    label = jc.get("handicap_label")
    if label not in (None, ""):
        return str(label)
    h = jc.get("handicap")
    if h is None:
        return "—"
    if int(h) > 0:
        return f"+{int(h)}"
    return str(int(h))


def market_label(jc: dict, mode: str) -> str:
    if mode == "sp":
        return "胜平负"
    if mode == "rqsp":
        hcap = handicap_label(jc)
        return f"让球({hcap})" if hcap != "—" else "让球胜平负"
    return "—"


def settle_handicap(home_goals: int, away_goals: int, handicap: int) -> str:
    """Handicap applied to home side (竞彩规则：+2 表示主队加 2 球后比较)."""
    adj = home_goals + handicap
    if adj > away_goals:
        return "home"
    if adj == away_goals:
        return "draw"
    return "away"


def parse_score_text(text: str) -> tuple[int, int, float] | None:
    if not text:
        return None
    m = re.search(r"(\d+)\s*[-:：]\s*(\d+)", str(text))
    if not m:
        return None
    w = 1.0
    pm = re.search(r"([\d.]+)\s*%", str(text))
    if pm:
        try:
            w = float(pm.group(1))
        except ValueError:
            w = 1.0
    return int(m.group(1)), int(m.group(2)), w


def _collect_scores(pred: dict) -> list[str]:
    scores = pred.get("likely_scores_detail") or pred.get("likely_scores") or []
    if isinstance(scores, str):
        scores = re.split(r"[、,，/]", scores)
    row = pred.get("predict_row") or {}
    extra = row.get("推荐比分") or ""
    if extra and isinstance(extra, str):
        scores = list(scores) + re.split(r"[、,，/]", extra)
    out: list[str] = []
    for s in scores:
        s = str(s).strip()
        if s and s not in out:
            out.append(s)
    return out[:6]


def _resolve_eu_fair_probs(pred: dict) -> dict[str, float]:
    """Fair 1X2 % from foreign EU odds (去水欧赔)."""
    eu = pred.get("eu_implied") or {}
    probs = {
        "home": float(eu.get("fair_home_pct") or 0),
        "draw": float(eu.get("fair_draw_pct") or 0),
        "away": float(eu.get("fair_away_pct") or 0),
    }
    if max(probs.values()) > 0:
        return probs
    odds = pred.get("odds_snapshot") or {}
    try:
        from eu_implied_metrics import compute_eu_implied

        m = compute_eu_implied(odds.get("eu_home"), odds.get("eu_draw"), odds.get("eu_away"))
        if m:
            return {
                "home": float(m.fair_home_pct),
                "draw": float(m.fair_draw_pct),
                "away": float(m.fair_away_pct),
            }
    except Exception:
        pass
    return probs


def _rq_prob_pct_from_eu_odds(pred: dict, handicap: int) -> dict[str, float] | None:
    """Map foreign EU odds → 竞彩让球 胜/平/负 胜率（Poisson，不输出比分）."""
    sm = (pred.get("quant") or {}).get("score_model") or {}
    lam_h, lam_a = sm.get("lambda_home"), sm.get("lambda_away")
    if lam_h is None or lam_a is None:
        fair = _resolve_eu_fair_probs(pred)
        if max(fair.values()) <= 0:
            return None
        odds = pred.get("odds_snapshot") or {}
        from score_models import build_score_model

        built = build_score_model(
            eu_home=odds.get("eu_home"),
            eu_draw=odds.get("eu_draw"),
            eu_away=odds.get("eu_away"),
            fair_home_pct=fair.get("home"),
            fair_draw_pct=fair.get("draw"),
            fair_away_pct=fair.get("away"),
        )
        if not built:
            return None
        lam_h, lam_a = built.get("lambda_home"), built.get("lambda_away")
    if lam_h is None or lam_a is None:
        return None
    from score_models import score_matrix

    cells = score_matrix(float(lam_h), float(lam_a))
    counts = {"home": 0.0, "draw": 0.0, "away": 0.0}
    for (i, j), prob in cells.items():
        counts[settle_handicap(i, j, handicap)] += prob
    total = sum(counts.values()) or 1.0
    return {k: round(v / total * 100, 1) for k, v in counts.items()}


def _rq_prob_pct_from_similar_samples(pred: dict, handicap: int) -> tuple[dict[str, float] | None, int, str]:
    """Foreign-odds similar samples → 竞彩让球三向历史胜率."""
    sim = pred.get("similarity_analysis") or {}
    best: dict | None = None
    for layer in ("live", "open"):
        for block in sim.get(layer) or []:
            src = block.get("source") or ""
            if src not in ("open_ah", "live_ah", "open_eu", "live_eu"):
                continue
            cnt = int(block.get("count") or 0)
            if cnt < 15:
                continue
            if best is None or cnt > int(best.get("count") or 0):
                best = block
    if not best:
        return None, 0, ""

    counts = {"home": 0.0, "draw": 0.0, "away": 0.0}
    used = 0
    for sample in best.get("samples") or []:
        parsed = parse_score_text(str(sample.get("score") or ""))
        if not parsed:
            continue
        h, a, _ = parsed
        counts[settle_handicap(h, a, handicap)] += 1.0
        used += 1
    if used < 8:
        return None, 0, best.get("title") or best.get("source") or "相似样本"

    total = sum(counts.values()) or 1.0
    probs = {k: round(v / total * 100, 1) for k, v in counts.items()}
    title = best.get("title") or best.get("source") or "国外相似样本"
    return probs, used, title


def _format_rq_prob_line(probs: dict[str, float]) -> str:
    return (
        f"胜{probs.get('home', 0):.0f}% / "
        f"平{probs.get('draw', 0):.0f}% / "
        f"负{probs.get('away', 0):.0f}%"
    )


def infer_rq_pick_from_foreign_odds(pred: dict, handicap: int) -> tuple[str, str, dict[str, Any]]:
    """
    RQSP rule pick — foreign odds only (EU implied + similar AH/EU samples).
    Does not use domestic SP, reference 1X2 pick, or score lists.
    """
    sign = f"+{handicap}" if handicap > 0 else str(handicap)
    meta: dict[str, Any] = {"handicap": handicap, "source": None, "probs_pct": {}}

    if abs(handicap) >= RQSP_LARGE_HANDICAP_ABS:
        return (
            "skip",
            f"让球({sign})属于大让球，净胜球弹性过大；规则引擎默认观望，需 AI/人工单独确认",
            meta,
        )

    sim_probs, sim_n, sim_title = _rq_prob_pct_from_similar_samples(pred, handicap)
    eu_probs = _rq_prob_pct_from_eu_odds(pred, handicap)

    probs: dict[str, float] | None = None
    if sim_probs and eu_probs:
        probs = {
            k: round(sim_probs.get(k, 0) * 0.55 + eu_probs.get(k, 0) * 0.45, 1)
            for k in ("home", "draw", "away")
        }
        meta["source"] = "foreign_blend"
        meta["similar_n"] = sim_n
        meta["similar_title"] = sim_title
        reason_prefix = f"国外相似样本{sim_n}场+欧赔隐含"
    elif sim_probs:
        probs = sim_probs
        meta["source"] = "foreign_similar"
        meta["similar_n"] = sim_n
        meta["similar_title"] = sim_title
        reason_prefix = f"{sim_title} {sim_n}场"
    elif eu_probs:
        probs = eu_probs
        meta["source"] = "foreign_eu"
        reason_prefix = "国外欧赔隐含"
    else:
        return "skip", "缺少国外赔率/相似样本，仅让球场次请运行 AI 分析", meta

    meta["probs_pct"] = probs
    best = max(probs, key=probs.get)
    if probs.get(best, 0) < 34.0:
        return "skip", f"国外参考胜率分散（让球{sign} {_format_rq_prob_line(probs)}），建议观望或跑 AI", meta

    reason = (
        f"{reason_prefix}，让球({sign})下 {_format_rq_prob_line(probs)}，取向{RQ_CN[best]}"
    )
    return best, reason, meta


def infer_rq_pick_from_probs(pred: dict, handicap: int) -> tuple[str, str]:
    """Backward-compatible wrapper — RQSP uses foreign odds only."""
    pick, reason, _ = infer_rq_pick_from_foreign_odds(pred, handicap)
    return pick, reason


def infer_rq_pick_from_scores(scores: list[str], handicap: int) -> tuple[str, str]:
    """Return (pick_key, reason) from likely scores under handicap line."""
    counts = {"home": 0.0, "draw": 0.0, "away": 0.0}
    used = 0
    for s in scores:
        parsed = parse_score_text(s)
        if not parsed:
            continue
        h, a, w = parsed
        outcome = settle_handicap(h, a, handicap)
        counts[outcome] += w
        used += 1
    if used == 0:
        return "skip", "无可用比分推演让球结果"
    best = max(counts, key=counts.get)
    total = sum(counts.values()) or 1.0
    pct = counts[best] / total * 100
    hcap = handicap
    sign = f"+{hcap}" if hcap > 0 else str(hcap)
    reason = (
        f"按推荐比分在让球({sign})下推演，{RQ_CN[best]}概率约 {pct:.0f}%"
        f"（{used} 个比分样本）"
    )
    return best, reason


def _sp_for_pick(jc: dict, mode: str, pick_key: str) -> float | None:
    if pick_key in ("skip", ""):
        return None
    if mode == "sp":
        mapping = {"home": "sp_home", "draw": "sp_draw", "away": "sp_away"}
    else:
        mapping = {"home": "rqsp_home", "draw": "rqsp_draw", "away": "rqsp_away"}
    val = jc.get(mapping.get(pick_key, ""))
    try:
        return round(float(val), 2) if val is not None else None
    except (TypeError, ValueError):
        return None


def _analytical_result_cn(pred: dict) -> str:
    row = pred.get("predict_row") or {}
    if row.get("赛果预测"):
        return str(row["赛果预测"])
    if pred.get("match_result_1x2_cn"):
        return str(pred["match_result_1x2_cn"])
    return str(row.get("胜平负") or pred.get("result_1x2_cn") or "—")


def compute_jingcai_pick(pred: dict, jc: dict | None) -> dict[str, Any]:
    """Derive buyable 竞彩 recommendation from prediction + poll jingcai snapshot."""
    mode = jingcai_market_mode(jc)
    empty = {
        "jingcai_market": "none",
        "jingcai_market_label": "—",
        "jingcai_pick": "skip",
        "jingcai_pick_cn": "观望",
        "jingcai_pick_display": NO_JINGCAI,
        "jingcai_sp": None,
        "jingcai_reason": "暂无竞彩开售数据",
    }
    if mode == "none" or not jc:
        return empty

    mkt_label = market_label(jc, mode)
    pick_key = "skip"
    reason = ""

    ai_rq = pred.get("jingcai_rq_pick")
    ai_rq_cn = pred.get("jingcai_rq_pick_cn")
    if mode == "rqsp" and ai_rq in ("home", "draw", "away"):
        pick_key = ai_rq
        reason = pred.get("jingcai_rq_reason") or pred.get("jingcai_reason") or "AI 让球推荐（参考国外赔率）"
    elif mode == "rqsp":
        handicap = jc.get("handicap")
        if handicap is None:
            pick_key = "skip"
            reason = "缺少让球数，无法计算让球推荐"
        else:
            pick_key, reason, rq_ref = infer_rq_pick_from_foreign_odds(pred, int(handicap))
            if rq_ref.get("probs_pct"):
                pred["jingcai_rq_reference"] = rq_ref
    else:
        pick_key = pred.get("reference_result_1x2") or pred.get("result_1x2") or "skip"
        cn = pred.get("reference_result_1x2_cn") or pred.get("result_1x2_cn") or ""
        if pick_key == "skip" and cn in KEY_FROM_SP_CN:
            pick_key = KEY_FROM_SP_CN[cn]
        div = pred.get("jingcai_divergence") or {}
        if pick_key == "skip":
            reason = "参考研判为观望"
        elif div.get("divergence"):
            reason = (
                f"竞彩可购{SP_CN[pick_key]}（参考研判{div.get('reference_cn') or SP_CN[pick_key]}，"
                f"SP隐含偏{div.get('jingcai_implied_cn') or '—'}）"
            )
        else:
            reason = f"竞彩胜平负可购{SP_CN[pick_key]}，与欧亚参考研判一致"

    if mode == "rqsp" and ai_rq_cn in KEY_FROM_RQ_CN and pick_key == "skip":
        pick_key = KEY_FROM_RQ_CN[ai_rq_cn]

    if pick_key == "skip":
        pick_cn = "观望"
        display = f"{mkt_label} 观望"
    elif mode == "rqsp":
        pick_cn = RQ_CN[pick_key]
        display = f"{mkt_label} {pick_cn}"
    else:
        pick_cn = SP_CN[pick_key]
        display = pick_cn

    return {
        "jingcai_market": mode,
        "jingcai_market_label": mkt_label,
        "jingcai_pick": pick_key,
        "jingcai_pick_cn": pick_cn,
        "jingcai_pick_display": display,
        "jingcai_sp": _sp_for_pick(jc, mode, pick_key),
        "jingcai_reason": reason,
    }


def final_recommendation_cn(pred: dict) -> str:
    """Primary user-facing recommendation — always 竞彩 when available."""
    row = pred.get("predict_row") or {}
    for key in ("竞彩推荐", "胜平负", "final_pick_cn"):
        val = row.get(key) if key != "final_pick_cn" else pred.get(key)
        if val and str(val) not in ("—", ""):
            return str(val)
    info = pred.get("jingcai_pick_info") or {}
    display = info.get("jingcai_pick_display")
    if display and display not in ("—", ""):
        return str(display)
    return NO_JINGCAI


def final_pick_key(pred: dict) -> str:
    info = pred.get("jingcai_pick_info") or {}
    key = info.get("jingcai_pick")
    if key and key != "skip":
        return str(key)
    cn = final_recommendation_cn(pred)
    if cn in KEY_FROM_SP_CN:
        return KEY_FROM_SP_CN[cn]
    if cn.endswith(" 胜") or cn == "胜":
        return "home"
    if cn.endswith(" 平") or cn == "平":
        return "draw"
    if cn.endswith(" 负") or cn == "负":
        return "away"
    return "skip"


def attach_jingcai_recommendation(pred: dict, jingcai: dict | None) -> dict:
    """Attach 竞彩 fields and sync as the sole final recommendation."""
    info = compute_jingcai_pick(pred, jingcai)
    pred["jingcai_pick_info"] = info
    if jingcai:
        pred["jingcai_snapshot"] = jingcai

    mode = info.get("jingcai_market") or "none"
    row = dict(pred.get("predict_row") or {})
    if mode == "rqsp":
        rq_ref = pred.get("jingcai_rq_reference") or {}
        probs = rq_ref.get("probs_pct") or {}
        if probs:
            row["让球参考胜率"] = (
                f"胜{probs.get('home', 0):.0f}% / "
                f"平{probs.get('draw', 0):.0f}% / "
                f"负{probs.get('away', 0):.0f}%"
            )
        analytical = pred.get("reference_result_1x2_cn") or _analytical_result_cn(pred)
        if analytical not in ("—", NO_JINGCAI, ""):
            row["赛果参考"] = analytical
            pred["match_result_1x2_cn"] = analytical
    else:
        analytical = pred.get("reference_result_1x2_cn") or _analytical_result_cn(pred)
        if analytical not in ("—", NO_JINGCAI, ""):
            row["赛果预测"] = analytical
            pred["match_result_1x2_cn"] = analytical

    div = pred.get("jingcai_divergence")
    if div:
        pred["jingcai_divergence"] = div
        tags = list(pred.get("alert_tags") or [])
        if "竞彩·参考分歧" not in tags:
            tags.append("竞彩·参考分歧")
        pred["alert_tags"] = tags

    if mode == "none":
        row["竞彩玩法"] = "—"
        row["竞彩推荐"] = NO_JINGCAI
        row["胜平负"] = NO_JINGCAI
        pred["final_pick_cn"] = NO_JINGCAI
    else:
        row["竞彩玩法"] = info["jingcai_market_label"]
        row["竞彩推荐"] = info["jingcai_pick_display"]
        if info.get("jingcai_sp") is not None:
            row["竞彩SP"] = info["jingcai_sp"]
        if info.get("jingcai_pick") == "skip":
            row["胜平负"] = info["jingcai_pick_display"]
            pred["final_pick_cn"] = info["jingcai_pick_display"]
        else:
            row["胜平负"] = info["jingcai_pick_display"]
            pred["final_pick_cn"] = info["jingcai_pick_display"]

    pred["predict_row"] = row
    return pred


def actionable_jingcai_pick(pred: dict) -> dict[str, Any] | None:
    """Actionable pick for parlays — must have 竞彩开售且非观望."""
    info = pred.get("jingcai_pick_info") or {}
    mode = info.get("jingcai_market") or jingcai_market_mode(pred.get("jingcai_snapshot"))
    if mode == "none":
        return None
    pick_key = info.get("jingcai_pick") or "skip"
    pick_display = final_recommendation_cn(pred)
    if pick_key == "skip" or pick_display in (NO_JINGCAI, "—", "观望", "") or "观望" in pick_display:
        return None
    return {
        "pick_key": pick_key,
        "pick_cn": pick_display,
        "pick_short": info.get("jingcai_pick_cn") or "—",
        "market": mode,
        "market_label": info.get("jingcai_market_label") or "—",
        "sp": info.get("jingcai_sp"),
        "reason": info.get("jingcai_reason") or "",
    }


def resolve_jingcai_sp(
    m: dict,
    *,
    pick_key: str | None = None,
    market: str | None = None,
) -> float | None:
    """竞彩 SP for the buy direction — used for 2串1 payout math."""
    info = m.get("jingcai_pick_info") or {}
    jc = m.get("jingcai_snapshot") or {}
    pk = pick_key or info.get("jingcai_pick")
    mk = market or info.get("jingcai_market") or jingcai_market_mode(jc)
    if not pk or pk == "skip" or mk in (None, "none", ""):
        return None
    if jc:
        sp = _sp_for_pick(jc, mk, pk)
        if sp is not None:
            return sp
    if info.get("jingcai_pick") == pk and info.get("jingcai_sp") is not None:
        try:
            return round(float(info["jingcai_sp"]), 2)
        except (TypeError, ValueError):
            pass
    row = m.get("predict_row") or {}
    if info.get("jingcai_pick") == pk and row.get("竞彩SP") is not None:
        try:
            return round(float(row["竞彩SP"]), 2)
        except (TypeError, ValueError):
            pass
    return None


def ensure_match_jingcai(m: dict) -> dict:
    """Attach latest poll 竞彩 snapshot when prediction cache lacks SP data."""
    jc = m.get("jingcai_snapshot") or {}
    info = m.get("jingcai_pick_info") or {}
    if jc and info.get("jingcai_market") not in (None, "none", ""):
        return m
    fid = str(m.get("fixture_id") or "")
    if not fid:
        return m
    try:
        from timeline_merge import load_latest_poll_meta

        meta = load_latest_poll_meta(fid)
        poll_jc = meta.get("jingcai") or {}
        if not poll_jc:
            return m
        out = dict(m)
        attach_jingcai_recommendation(out, poll_jc)
        from analysis.rules.output import attach_post_recommendation

        attach_post_recommendation(out)
        return out
    except Exception:
        return m
