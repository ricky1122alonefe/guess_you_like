"""Kelly criterion calculator for stake sizing."""

from __future__ import annotations

from typing import Any

RESULT_KEY = {"主胜": "home", "平局": "draw", "客胜": "away", "平": "draw"}
RESULT_CN = {"home": "主胜", "draw": "平局", "away": "客胜"}


def decimal_from_water(water: float) -> float:
    """Asian handicap water → decimal odds on full win (stake + water*stake)."""
    return 1.0 + float(water)


def compute_kelly(
    probability: float,
    *,
    decimal_odds: float | None = None,
    water: float | None = None,
    bankroll: float | None = None,
    fraction: float = 1.0,
    max_stake_pct: float = 0.25,
) -> dict[str, Any]:
    """
    Kelly fraction f* = (p * D - 1) / (D - 1).

    probability: win probability in 0–1.
    decimal_odds: European decimal odds, OR derive from water (1 + water).
    fraction: apply fractional Kelly (0.5 = half Kelly).
    max_stake_pct: cap recommended stake as % of bankroll (risk guard).
    """
    p = float(probability)
    if not 0 < p < 1:
        return {"ok": False, "error": "胜率须在 0–100% 之间（不含 0 和 100%）"}

    d: float | None = None
    if decimal_odds is not None:
        try:
            d = float(decimal_odds)
        except (TypeError, ValueError):
            d = None
    elif water is not None:
        try:
            d = decimal_from_water(float(water))
        except (TypeError, ValueError):
            d = None

    if d is None or d <= 1:
        return {"ok": False, "error": "赔率无效（欧赔须 > 1，或水位 ≥ 0）"}

    b = d - 1.0
    q = 1.0 - p
    full_kelly = (p * d - 1.0) / b
    implied = 1.0 / d
    edge = p - implied
    ev = p * d - 1.0

    frac = max(0.0, min(float(fraction), 1.0))
    adjusted = full_kelly * frac
    capped = min(adjusted, max_stake_pct) if adjusted > 0 else adjusted

    stake = None
    if bankroll is not None:
        try:
            br = float(bankroll)
            if br > 0 and capped > 0:
                stake = round(br * capped, 2)
        except (TypeError, ValueError):
            pass

    if full_kelly <= 0:
        verdict = "无正 EV，Kelly 为负，不建议下注"
        tone = "negative"
    elif full_kelly < 0.02:
        verdict = "边缘极薄，即使正 EV 也建议观望或极小仓"
        tone = "warn"
    elif frac < 1.0:
        verdict = f"有正 EV，建议采用 {frac * 100:.0f}% Kelly 控风险"
        tone = "ok"
    else:
        verdict = "有正 EV；全 Kelly 波动大，实战常用半 Kelly 或四分之一 Kelly"
        tone = "ok"

    return {
        "ok": True,
        "probability": round(p, 6),
        "probability_pct": round(p * 100, 2),
        "decimal_odds": round(d, 4),
        "net_odds": round(b, 4),
        "implied_probability": round(implied, 6),
        "implied_probability_pct": round(implied * 100, 2),
        "edge": round(edge, 6),
        "edge_pp": round(edge * 100, 2),
        "ev_per_unit": round(ev, 4),
        "ev_pct": round(ev * 100, 2),
        "full_kelly": round(full_kelly, 6),
        "full_kelly_pct": round(full_kelly * 100, 2),
        "fraction": frac,
        "adjusted_kelly": round(adjusted, 6),
        "adjusted_kelly_pct": round(adjusted * 100, 2),
        "capped_kelly_pct": round(capped * 100, 2) if capped > 0 else 0.0,
        "stake_amount": stake,
        "bankroll": bankroll,
        "half_kelly_pct": round(full_kelly * 50, 2) if full_kelly > 0 else 0.0,
        "quarter_kelly_pct": round(full_kelly * 25, 2) if full_kelly > 0 else 0.0,
        "verdict": verdict,
        "tone": tone,
        "formula": "f* = (p×D − 1) / (D − 1)",
    }


def _pick_key(pred: dict) -> str | None:
    key = pred.get("result_1x2")
    if key in ("home", "draw", "away"):
        return key
    cn = pred.get("result_1x2_cn") or (pred.get("predict_row") or {}).get("胜平负")
    return RESULT_KEY.get(str(cn or "").strip())


def _historical_rate(pred: dict, pick: str) -> float | None:
    sim = pred.get("similarity_analysis") or {}
    for block in sim.get("open") or []:
        if block.get("source") != "open_ah" and "亚盘" not in (block.get("title") or ""):
            continue
        rate_key = {"home": "home_win_rate", "draw": "draw_rate", "away": "away_win_rate"}.get(pick)
        val = block.get(rate_key) if rate_key else None
        if val is not None:
            return float(val)
    for block in sim.get("open") or []:
        rate_key = {"home": "home_win_rate", "draw": "draw_rate", "away": "away_win_rate"}.get(pick)
        val = block.get(rate_key) if rate_key else None
        if val is not None:
            return float(val)
    return None


def kelly_prefill_from_prediction(pred: dict | None, *, fixture_id: str = "") -> dict[str, Any]:
    """Build Kelly calculator defaults from a stored match prediction."""
    if not pred:
        return {"available": False}

    pick = _pick_key(pred)
    row = pred.get("predict_row") or {}
    snap = pred.get("odds_snapshot") or {}
    eu_imp = pred.get("eu_implied") or {}
    ah_pick = pred.get("asian_handicap_pick")

    pick_cn = pred.get("result_1x2_cn") or row.get("胜平负") or "—"
    match = pred.get("match") or row.get("比赛") or "—"

    market_prob: float | None = None
    if pick == "home" and eu_imp.get("fair_home_pct") is not None:
        market_prob = float(eu_imp["fair_home_pct"]) / 100
    elif pick == "draw" and eu_imp.get("fair_draw_pct") is not None:
        market_prob = float(eu_imp["fair_draw_pct"]) / 100
    elif pick == "away" and eu_imp.get("fair_away_pct") is not None:
        market_prob = float(eu_imp["fair_away_pct"]) / 100

    hist_prob = _historical_rate(pred, pick) if pick else None

    eu_odds: float | None = None
    if pick == "home":
        eu_odds = snap.get("eu_home")
    elif pick == "draw":
        eu_odds = snap.get("eu_draw")
    elif pick == "away":
        eu_odds = snap.get("eu_away")

    ah_water: float | None = None
    if ah_pick == "home":
        ah_water = snap.get("ah_home_water")
    elif ah_pick == "away":
        ah_water = snap.get("ah_away_water")

    jingcai_sp = row.get("竞彩SP")
    try:
        jingcai_sp = float(jingcai_sp) if jingcai_sp not in (None, "", "—") else None
    except (TypeError, ValueError):
        jingcai_sp = None

    default_prob = hist_prob if hist_prob is not None else market_prob
    default_odds_type = "decimal"
    default_odds = eu_odds
    if ah_pick in ("home", "away") and ah_water is not None:
        default_odds_type = "water"
        default_odds = ah_water
    elif jingcai_sp and jingcai_sp > 1:
        default_odds_type = "decimal"
        default_odds = jingcai_sp

    return {
        "available": default_prob is not None or default_odds is not None,
        "fixture_id": fixture_id or pred.get("fixture_id"),
        "match": match,
        "pick_cn": pick_cn,
        "pick_key": pick,
        "asian_handicap_cn": pred.get("asian_handicap_cn"),
        "probability_pct": round(default_prob * 100, 2) if default_prob is not None else None,
        "market_probability_pct": round(market_prob * 100, 2) if market_prob is not None else None,
        "historical_probability_pct": round(hist_prob * 100, 2) if hist_prob is not None else None,
        "odds_type": default_odds_type,
        "odds_value": default_odds,
        "eu_odds": eu_odds,
        "ah_water": ah_water,
        "jingcai_sp": jingcai_sp,
        "notes": [
            "默认胜率优先取初盘相似样本历史频率，其次欧赔去水隐含概率",
            "默认赔率：有亚盘推荐用水位，否则用欧赔或竞彩 SP",
            "Kelly 仅作仓位参考，实战建议半 Kelly 或四分之一 Kelly",
        ],
    }
