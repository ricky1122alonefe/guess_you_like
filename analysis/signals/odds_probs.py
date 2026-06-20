"""Blend 1X2 probabilities from live EU, open EU, AH signals, history, and Jingcai SP."""

from __future__ import annotations

from typing import Any

import config as cfg
from analysis.signals.odds import build_market_signals
from eu_implied_metrics import compute_eu_implied
from jingcai_pick import jingcai_market_mode

_COMPONENT_LABELS = {
    "live_eu": "临盘欧",
    "open_eu": "初盘欧",
    "ah": "亚盘",
    "hist": "历史",
    "jingcai": "竞彩",
}


def eu_fair_rates(h, d, a) -> dict[str, float] | None:
    metrics = compute_eu_implied(h, d, a)
    if not metrics:
        return None
    return {
        "home": metrics.fair_home_pct / 100.0,
        "draw": metrics.fair_draw_pct / 100.0,
        "away": metrics.fair_away_pct / 100.0,
    }


def jingcai_sp_rates(jc: dict | None) -> dict[str, float] | None:
    if not jc or jingcai_market_mode(jc) != "sp":
        return None
    return eu_fair_rates(jc.get("sp_home"), jc.get("sp_draw"), jc.get("sp_away"))


def ah_signal_rates(cur: dict) -> dict[str, float]:
    sig = build_market_signals(cur)
    base = {"home": 1 / 3, "draw": 1 / 3, "away": 1 / 3}
    for key in base:
        base[key] += sig.bias_1x2.get(key, 0.0) * 2.0
    total = sum(base.values()) or 1.0
    return {k: max(v, 0.0) / total for k, v in base.items()}


def blend_odds_1x2(
    cur: dict,
    hist_rates: dict[str, float] | None,
    jingcai: dict | None = None,
) -> tuple[dict[str, float], str, dict[str, float]]:
    """Return (blended rates, summary text, normalized weight shares)."""
    planned: list[tuple[str, float, dict[str, float] | None]] = [
        ("live_eu", cfg.ODDS_W_LIVE_EU, eu_fair_rates(cur.get("eu_home"), cur.get("eu_draw"), cur.get("eu_away"))),
        ("open_eu", cfg.ODDS_W_OPEN_EU, eu_fair_rates(cur.get("eu_open_home"), cur.get("eu_open_draw"), cur.get("eu_open_away"))),
        ("ah", cfg.ODDS_W_AH, ah_signal_rates(cur)),
        ("hist", cfg.ODDS_W_HIST, hist_rates),
        ("jingcai", cfg.ODDS_W_JINGCAI, jingcai_sp_rates(jingcai)),
    ]
    components = [(name, weight, rates) for name, weight, rates in planned if rates]
    if not components:
        fallback = hist_rates or {"home": 1 / 3, "draw": 1 / 3, "away": 1 / 3}
        return fallback, "赔率数据不足，回退历史/均匀分布", {}

    total_w = sum(weight for _, weight, _ in components)
    blended = {k: 0.0 for k in ("home", "draw", "away")}
    shares: dict[str, float] = {}
    for name, weight, rates in components:
        share = weight / total_w
        shares[name] = round(share, 3)
        for key in blended:
            blended[key] += rates[key] * share

    parts = [
        f"{_COMPONENT_LABELS.get(name, name)}{shares[name] * 100:.0f}%"
        for name, _, _ in components
    ]
    summary = "赔率融合：" + "、".join(parts)
    return blended, summary, shares


def apply_light_trap_penalties(rates: dict[str, float], trap) -> dict[str, float]:
    scale = cfg.ODDS_FIRST_TRAP_SCALE
    out = dict(rates)
    for key in out:
        penalty = trap.penalties.get(key, 1.0)
        out[key] *= 1.0 - (1.0 - penalty) * scale
    total = sum(out.values()) or 1.0
    return {k: v / total for k, v in out.items()}
