"""Blend 1X2 probabilities — reference (EU/AH/hist) vs 竞彩 SP."""

from __future__ import annotations

from typing import Any

import config as cfg
from analysis.signals.odds import build_market_signals
from eu_implied_metrics import compute_eu_implied
from jingcai_pick import SP_CN, jingcai_market_mode

_COMPONENT_LABELS = {
    "live_eu": "临盘欧",
    "open_eu": "初盘欧",
    "ah": "亚盘",
    "hist": "历史",
    "jingcai": "竞彩SP",
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


def _blend_components(
    planned: list[tuple[str, float, dict[str, float] | None]],
    *,
    prefix: str,
) -> tuple[dict[str, float], str, dict[str, float]]:
    components = [(name, weight, rates) for name, weight, rates in planned if rates]
    if not components:
        return {"home": 1 / 3, "draw": 1 / 3, "away": 1 / 3}, f"{prefix}数据不足", {}

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
    return blended, f"{prefix}" + "、".join(parts), shares


def blend_reference_1x2(
    cur: dict,
    hist_rates: dict[str, float] | None,
) -> tuple[dict[str, float], str, dict[str, float]]:
    """欧赔+亚盘+历史参考研判（不含竞彩）。"""
    planned = [
        ("live_eu", cfg.ODDS_W_LIVE_EU, eu_fair_rates(cur.get("eu_home"), cur.get("eu_draw"), cur.get("eu_away"))),
        ("open_eu", cfg.ODDS_W_OPEN_EU, eu_fair_rates(cur.get("eu_open_home"), cur.get("eu_open_draw"), cur.get("eu_open_away"))),
        ("ah", cfg.ODDS_W_AH, ah_signal_rates(cur)),
        ("hist", cfg.ODDS_W_HIST, hist_rates),
    ]
    return _blend_components(planned, prefix="参考融合：")


def blend_odds_1x2(
    cur: dict,
    hist_rates: dict[str, float] | None,
    jingcai: dict | None = None,
) -> tuple[dict[str, float], str, dict[str, float]]:
    """Backward-compatible alias — reference blend only."""
    return blend_reference_1x2(cur, hist_rates)


def jingcai_sp_summary(jc: dict | None) -> str:
    if not jc or jingcai_market_mode(jc) != "sp":
        return ""
    rates = jingcai_sp_rates(jc)
    if not rates:
        return ""
    top = max(rates, key=rates.get)
    sp_map = {"home": jc.get("sp_home"), "draw": jc.get("sp_draw"), "away": jc.get("sp_away")}
    return (
        f"竞彩SP 主{sp_map['home']}/平{sp_map['draw']}/客{sp_map['away']}"
        f" → 隐含{SP_CN[top]}"
    )


def check_jingcai_reference_divergence(
    reference_key: str,
    reference_rates: dict[str, float],
    jc: dict | None,
) -> dict[str, Any] | None:
    """Flag when 竞彩 SP implied direction differs from 欧亚参考研判."""
    jc_rates = jingcai_sp_rates(jc)
    if not jc_rates or reference_key in ("skip", ""):
        return None
    jc_top = max(jc_rates, key=jc_rates.get)
    if jc_top == reference_key:
        return None
    ref_p = reference_rates.get(reference_key, 0.0)
    jc_p = jc_rates.get(reference_key, 0.0)
    jc_top_p = jc_rates.get(jc_top, 0.0)
    gap = jc_top_p - jc_p
    if gap < cfg.JINGCAI_REFERENCE_DIVERGENCE_PP:
        return None
    return {
        "divergence": True,
        "reference_key": reference_key,
        "reference_cn": SP_CN[reference_key],
        "jingcai_implied_key": jc_top,
        "jingcai_implied_cn": SP_CN[jc_top],
        "gap_pp": round(gap * 100, 1),
        "note": (
            f"【竞彩·参考分歧】欧亚参考研判{SP_CN[reference_key]}，"
            f"竞彩SP隐含更倾向{SP_CN[jc_top]}（差约{gap * 100:.0f}pp）；"
            f"可购方向仍按参考{SP_CN[reference_key]}，下单前请对照SP"
        ),
        "jingcai_sp_summary": jingcai_sp_summary(jc),
    }


def apply_light_trap_penalties(rates: dict[str, float], trap) -> dict[str, float]:
    scale = cfg.ODDS_FIRST_TRAP_SCALE
    out = dict(rates)
    for key in out:
        penalty = trap.penalties.get(key, 1.0)
        out[key] *= 1.0 - (1.0 - penalty) * scale
    total = sum(out.values()) or 1.0
    return {k: v / total for k, v in out.items()}
