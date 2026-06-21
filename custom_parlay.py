"""User-selected 2-leg parlay analysis — local odds, minimal noise."""

from __future__ import annotations

import json
import logging
from typing import Any

from daily_picks import _best_actionable_pick, _combined_odds, _eu_odds, _kickoff_date, _kickoff_label, load_kickoff_map
from jingcai_pick import NO_JINGCAI, actionable_jingcai_pick, ensure_match_jingcai, final_recommendation_cn, resolve_jingcai_sp
from time_utils import now_beijing_str

log = logging.getLogger(__name__)

SKIP_PICKS = frozenset({"观望", "—", "", None, NO_JINGCAI})


def _pick_actionable(pick_cn: str) -> bool:
    if not pick_cn or pick_cn in SKIP_PICKS:
        return False
    return "观望" not in pick_cn


def _leg_from_match(m: dict) -> dict[str, Any]:
    m = ensure_match_jingcai(m)
    if not m.get("buy_tier"):
        from analysis.rules.output import attach_post_recommendation

        attach_post_recommendation(m)
    row = m.get("predict_row") or {}
    pick_cn = final_recommendation_cn(m)
    jc_info = m.get("jingcai_pick_info") or {}
    jc = actionable_jingcai_pick(m)
    actionable = _best_actionable_pick(m)

    pick_key = (jc or {}).get("pick_key") or (actionable or {}).get("pick_key")
    market = (jc or {}).get("market") or jc_info.get("jingcai_market") or "none"
    sp = resolve_jingcai_sp(m, pick_key=pick_key, market=market)
    eu = _eu_odds(m, pick_key) if pick_key and pick_key != "skip" else None

    reason = ""
    if actionable:
        reason = actionable.get("actuary_reasoning") or m.get("confidence_reason") or ""
    if not reason:
        reason = (m.get("open_probability_summary") or "")[:150]

    kickoff_map = load_kickoff_map()
    fid = str(m.get("fixture_id") or "")

    return {
        "fixture_id": fid,
        "match": m.get("match") or row.get("比赛") or "",
        "kickoff": _kickoff_label(m, kickoff_map),
        "pick_cn": pick_cn,
        "pick_key": pick_key,
        "jingcai_market": market if market != "none" else (jc or {}).get("market") or jc_info.get("jingcai_market") or "none",
        "jingcai_market_label": row.get("竞彩玩法") or jc_info.get("jingcai_market_label") or "—",
        "jingcai_sp": sp,
        "eu_odds": round(eu, 2) if eu else None,
        "odds_used": sp,
        "odds_source": "jingcai_sp" if sp else "missing",
        "confidence_cn": row.get("置信度") or m.get("confidence_cn") or "—",
        "scores": row.get("推荐比分") or "",
        "asian_handicap_cn": row.get("亚盘") or m.get("asian_handicap_cn") or "—",
        "actionable": _pick_actionable(pick_cn) and jc is not None,
        "model_note": (actionable or {}).get("model_note") or "",
        "reason": reason,
        "value_bet": m.get("value_bet") is True or (actionable or {}).get("value_bet") is True,
        "insufficient_data": bool(m.get("insufficient_data")),
        "source": m.get("recommendation_source") or "rule_engine",
        "market_pattern_summary": m.get("market_pattern_summary") or "",
        "buy_tier": m.get("buy_tier"),
        "buy_tier_cn": m.get("buy_tier_cn"),
        "buy_tier_reason": m.get("buy_tier_reason"),
        "parlay_eligible": m.get("parlay_eligible") is True,
    }


def analyze_custom_parlay(matches: list[dict]) -> dict[str, Any]:
    """Analyze exactly 2 matches as a 2串1 using stored picks + odds only."""
    if len(matches) != 2:
        raise ValueError("请勾选恰好 2 场比赛")

    kickoff_map = load_kickoff_map()
    match_days = sorted({
        d for m in matches if (d := _kickoff_date(m, kickoff_map))
    })
    if len(match_days) > 1:
        raise ValueError(
            f"2串1 须同一比赛日，当前为 {' / '.join(match_days)}，不可跨天"
        )

    legs = [_leg_from_match(m) for m in matches]
    combined = _combined_odds(legs)

    warnings: list[str] = []
    blockers: list[str] = []

    for leg, m in zip(legs, matches):
        if not leg["actionable"]:
            blockers.append(f"{leg['match']}：推荐为「{leg['pick_cn']}」，不可串关")
        tier = m.get("buy_tier") or leg.get("buy_tier")
        tier_cn = m.get("buy_tier_cn") or leg.get("buy_tier_cn") or tier
        if tier == "C":
            reason = m.get("buy_tier_reason") or leg.get("buy_tier_reason") or ""
            blockers.append(f"{leg['match']}：档位「仅参考」{('——' + reason) if reason else ''}")
        elif not leg.get("parlay_eligible"):
            warnings.append(f"{leg['match']}：档位「{tier_cn or '可单关'}」，串关建议优先选「可串」")
        if not leg.get("jingcai_sp"):
            warnings.append(f"{leg['match']}：暂无竞彩 SP，组合回报无法按国内赔率计算")
        if leg.get("insufficient_data"):
            warnings.append(f"{leg['match']}：样本不足")
        if leg.get("confidence_cn") == "低":
            warnings.append(f"{leg['match']}：置信度低")

    markets = {leg.get("jingcai_market") for leg in legs}
    if markets == {"rqsp"}:
        warnings.append("两场均为仅让球玩法，串关波动更大")
    elif "rqsp" in markets:
        warnings.append("含让球胜平负场次，结果对净胜球敏感")

    for leg in legs:
        try:
            from style_clash import VARIANCE_HIGH, style_clash_for_match
            fake_m = {"match": leg["match"], "fixture_id": leg["fixture_id"]}
            clash = style_clash_for_match(fake_m)
            if clash.get("available") and clash.get("variance_level") == VARIANCE_HIGH:
                warnings.append(f"{leg['match']}：{clash.get('headline')}")
        except Exception:
            pass

    confs = [leg.get("confidence_cn") for leg in legs]
    all_parlay_ok = all(leg.get("parlay_eligible") for leg in legs)
    if all_parlay_ok and all(c in ("高", "中") for c in confs) and not blockers:
        verdict = "可串"
        verdict_detail = "两场均为「可串」档位，组合赔率见下"
    elif blockers:
        verdict = "不建议"
        verdict_detail = "存在不可购或观望场次"
    elif any(c == "低" for c in confs):
        verdict = "慎串"
        verdict_detail = "至少一场置信偏低，建议减小仓位或改选"
    else:
        verdict = "可小串"
        verdict_detail = "两场均有方向，注意让球与样本风险"

    implied_pct = None
    if combined and combined > 1:
        implied_pct = round(100 / combined, 1)

    payout_100 = round(combined * 100, 0) if combined else None
    explanation = _build_explanation(
        legs, combined, verdict, verdict_detail, warnings, blockers,
    )

    return {
        "ok": True,
        "generated_at": now_beijing_str(),
        "match_date": match_days[0] if match_days else None,
        "parlay_type": "2串1",
        "legs": legs,
        "combined_odds": combined,
        "implied_win_pct": implied_pct,
        "payout_per_100": payout_100,
        "verdict": verdict,
        "verdict_detail": verdict_detail,
        "warnings": warnings,
        "blockers": blockers,
        "summary": _format_summary(legs, combined, verdict),
        "explanation": explanation,
        "source": "local",
    }


def _leg_reason_text(leg: dict) -> str:
    parts: list[str] = []
    conf = leg.get("confidence_cn")
    if conf == "高":
        parts.append("置信度高")
    elif conf == "低":
        parts.append("置信偏低，需控仓")
    if leg.get("value_bet"):
        parts.append("模型认为该方向有价值")
    note = (leg.get("model_note") or "").strip()
    if note:
        parts.append(note)
    reason = (leg.get("reason") or "").strip()
    if reason:
        parts.append(reason[:120])
    elif leg.get("scores"):
        parts.append(f"参考比分 {leg['scores']}")
    if leg.get("market_pattern_summary"):
        parts.append(f"欧亚转换：{leg['market_pattern_summary']}")
    if leg.get("jingcai_market") == "rqsp":
        parts.append("让球玩法，需赢够让球数")
    sp = leg.get("odds_used")
    if sp:
        parts.append(f"竞彩 SP {sp}")
    return "；".join(parts) if parts else f"推荐 {leg.get('pick_cn')}"


def _stake_advice(verdict: str, combined: float | None, confs: list[str]) -> str:
    if verdict == "不建议":
        return "存在观望或不可购场次，不建议下注，可改选其他场次。"
    if verdict == "慎串":
        return "建议小仓位试水（如常规单的 30%–50%），或单场分开买。"
    if verdict == "可串" and combined and combined < 3.5:
        return "组合偏稳，可按常规仓位参与；仍建议量力而行。"
    if combined and combined >= 5:
        return "组合赔率较高，适合小注博回报，勿重仓。"
    if all(c == "高" for c in confs):
        return "两场置信均偏高，可按常规仓位；注意让球场次风险。"
    return "可小仓位参与，单场风险叠加后波动更大，勿追注。"


def _build_explanation(
    legs: list[dict],
    combined: float | None,
    verdict: str,
    verdict_detail: str,
    warnings: list[str],
    blockers: list[str],
) -> dict[str, Any]:
    confs = [leg.get("confidence_cn") for leg in legs]
    leg_reasons = [
        {"match": leg["match"], "pick_cn": leg["pick_cn"], "text": _leg_reason_text(leg)}
        for leg in legs
    ]

    reasons: list[str] = []
    if combined:
        if combined < 2.5:
            reasons.append(f"组合 SP 约 {combined:.2f}，偏稳健，100 元约返 {int(round(combined * 100))} 元")
        elif combined < 5.0:
            reasons.append(f"组合 SP 约 {combined:.2f}，回报与风险折中")
        else:
            reasons.append(f"组合 SP 约 {combined:.2f}，搏冷属性较强，命中难度高")

    if all(c == "高" for c in confs):
        reasons.append("两场置信均为「高」，过关概率相对更好")
    elif any(c == "低" for c in confs):
        reasons.append("至少一场置信偏低，串关容错空间小")

    for leg in legs:
        if leg.get("value_bet"):
            reasons.append(f"{leg['match']} 被标为 value 方向")
        if "一致" in (leg.get("model_note") or ""):
            reasons.append(f"{leg['match']} 多模型方向一致")
        try:
            from style_clash import VARIANCE_HIGH, VARIANCE_MEDIUM, style_clash_for_match
            c = style_clash_for_match({"match": leg["match"]})
            if c.get("available") and c.get("variance_level") in (VARIANCE_MEDIUM, VARIANCE_HIGH):
                reasons.append(f"{leg['match']} {c.get('headline')}")
        except Exception:
            pass

    markets = {leg.get("jingcai_market") for leg in legs}
    if markets == {"rqsp"}:
        reasons.append("两场均为让球玩法，净胜球敏感，串关波动大")
    elif "rqsp" in markets:
        reasons.append("含让球场次，需同时满足让球条件")

    stake = _stake_advice(verdict, combined, confs)
    leg_lines = "；".join(f"【{lr['match']}】{lr['text']}" for lr in leg_reasons)
    paragraph = f"{verdict_detail}。{leg_lines}"
    if warnings:
        paragraph += "。注意：" + "；".join(warnings[:3])
    if blockers:
        paragraph += "。阻断：" + "；".join(blockers)

    return {
        "headline": verdict_detail,
        "reasons": reasons,
        "leg_reasons": leg_reasons,
        "stake_advice": stake,
        "paragraph": paragraph[:500],
    }


def _format_summary(legs: list[dict], combined: float | None, verdict: str) -> str:
    picks = " × ".join(f"{leg['match']} {leg['pick_cn']}" for leg in legs)
    if combined:
        return f"2串1 {verdict}：{picks} · 组合 SP≈{combined:.2f}"
    return f"2串1 {verdict}：{picks} · 赔率数据不完整"


PARLAY_AI_SYSTEM = """你是串关顾问。用户自选 2 场比赛组成竞彩 2串1。
组合回报按国内竞彩 SP 相乘计算（local_analysis.combined_odds / legs[].jingcai_sp），不要用欧赔 eu_odds。
你只能使用用户提供的两场本地分析摘要（推荐方向、竞彩 SP、置信度），禁止编造数据、禁止引入新闻/天气/外部舆情。
输出纯 JSON：
{
  "headline": "一句话结论（≤30字）",
  "verdict": "可串 | 慎串 | 不建议",
  "stake_advice": "仓位建议一句话",
  "key_risks": ["风险1", "风险2"],
  "brief": "2-3句说明，仅基于给定两场数据"
}"""


def run_parlay_ai_brief(
    analysis: dict[str, Any],
    *,
    ai_model: str = "deepseek-chat",
    ai_base_url: str | None = None,
) -> dict[str, Any]:
    """Optional focused AI comment on user-selected parlay (no full match pipeline)."""
    from ai_profiles import get_primary_profile
    from ai_prompt import _extract_json_text
    from deepseek_client import chat

    profile = get_primary_profile(ai_model, ai_base_url)
    api_key = profile.resolve_api_key()
    if not api_key:
        raise RuntimeError(f"未配置 {profile.api_key_env}")

    payload = {
        "local_analysis": analysis,
        "instruction": "仅评价这 2 场串关是否合理，不要展开无关分析",
    }
    content = chat(
        [
            {"role": "system", "content": PARLAY_AI_SYSTEM},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
        ],
        model=profile.model,
        temperature=0.2,
        max_tokens=800,
        base_url=profile.base_url,
        api_key=api_key,
    )
    data = json.loads(_extract_json_text(content))
    return data if isinstance(data, dict) else {"brief": str(data)}


def merge_ai_into_explanation(analysis: dict[str, Any], ai_brief: dict[str, Any]) -> None:
    """Append optional AI brief into local explanation (in-place)."""
    expl = analysis.setdefault("explanation", {})
    if ai_brief.get("brief"):
        expl["ai_note"] = ai_brief["brief"]
    if ai_brief.get("headline"):
        expl["headline"] = ai_brief["headline"]
    if ai_brief.get("stake_advice"):
        expl["stake_advice"] = ai_brief["stake_advice"]
    risks = ai_brief.get("key_risks") or []
    if risks:
        expl.setdefault("reasons", [])
        for r in risks[:3]:
            if r and r not in expl["reasons"]:
                expl["reasons"].append(str(r))
    if ai_brief.get("brief") and expl.get("paragraph"):
        expl["paragraph"] = expl["paragraph"] + " " + ai_brief["brief"]


def load_matches_for_parlay(
    output_root,
    fixture_ids: list[str],
) -> list[dict]:
    from pathlib import Path
    from daily_picks import load_dashboard_matches

    root = Path(output_root)
    ids = [str(x) for x in fixture_ids]
    preds = {str(m.get("fixture_id")): m for m in load_dashboard_matches(root)}
    latest_path = root / "latest.json"
    if latest_path.is_file():
        try:
            data = json.loads(latest_path.read_text(encoding="utf-8"))
            for m in data.get("matches") or []:
                fid = str(m.get("fixture_id") or "")
                if fid:
                    preds[fid] = m
        except json.JSONDecodeError:
            pass

    out: list[dict] = []
    missing: list[str] = []
    for fid in ids:
        m = preds.get(fid)
        if not m:
            missing.append(fid)
        else:
            out.append(ensure_match_jingcai(m))
    if missing:
        raise ValueError(f"未找到比赛：{', '.join(missing)}")
    return out
