"""竞彩 EV / edge from fair probability vs SP."""

from __future__ import annotations

from typing import Any

from jingcai_pick import actionable_jingcai_pick, resolve_jingcai_sp

PICK_TO_FAIR = {"home": "fair_home_pct", "draw": "fair_draw_pct", "away": "fair_away_pct"}


def compute_jingcai_ev(pred: dict) -> dict[str, Any] | None:
    """EV per unit stake: P_fair × SP − 1 (竞彩口径)."""
    jc = actionable_jingcai_pick(pred)
    if not jc:
        return None

    pick_key = jc.get("pick_key")
    sp = resolve_jingcai_sp(pred, pick_key=pick_key, market=jc.get("market"))
    if not sp or not pick_key or pick_key == "skip":
        return None

    eu_imp = pred.get("eu_implied") or {}
    fair_key = PICK_TO_FAIR.get(pick_key)
    fair_pct = eu_imp.get(fair_key) if fair_key else None
    if fair_pct is None:
        adj = pred.get("adjusted_probability") or pred.get("implied_probability") or {}
        cn_map = {"home": "主胜", "draw": "平", "away": "客胜"}
        fair_pct = adj.get(cn_map.get(pick_key, ""))

    if fair_pct is None:
        sm = (pred.get("quant") or {}).get("score_model") or {}
        probs = sm.get("prob_1x2_pct") or {}
        fair_pct = probs.get(pick_key)

    try:
        p = float(fair_pct) / 100.0 if fair_pct is not None else None
        sp_f = float(sp)
    except (TypeError, ValueError):
        return None

    if p is None or p <= 0 or sp_f <= 1:
        return None

    ev = p * sp_f - 1.0
    implied_from_sp = 1.0 / sp_f
    edge_pp = (p - implied_from_sp) * 100.0

    return {
        "pick_key": pick_key,
        "pick_cn": jc.get("pick_cn") or pred.get("final_pick_cn"),
        "market": jc.get("market"),
        "market_label": jc.get("market_label"),
        "jingcai_sp": round(sp_f, 2),
        "fair_prob_pct": round(p * 100, 1),
        "implied_from_sp_pct": round(implied_from_sp * 100, 1),
        "edge_pp": round(edge_pp, 2),
        "ev_per_unit": round(ev, 4),
        "ev_pct": round(ev * 100, 2),
        "value_bet": ev > 0.03,
        "label": _ev_label(ev, edge_pp),
    }


def _ev_label(ev: float, edge_pp: float) -> str:
    if ev >= 0.08:
        return "正EV·可考虑"
    if ev >= 0.03:
        return "边际正EV"
    if ev >= -0.03:
        return "接近公平"
    return "负EV·慎跟"
