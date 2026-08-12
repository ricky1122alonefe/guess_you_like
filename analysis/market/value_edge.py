"""Value / edge对照：模型概率 vs 去水市场隐含概率。

产品定位：
- 竞彩 SP 优先去水；无 SP 则回落到欧赔收盘去水。
- edge = p_model - p_mkt（分向）。
- half-Kelly 仅作研究比例，封顶并带 disclaimer，非投注建议。
"""

from __future__ import annotations

import logging
from typing import Any

import config
from analysis.market.devig import devig_1x2

log = logging.getLogger(__name__)

MAX_KELLY = float(getattr(config, "VALUE_EDGE_MAX_KELLY", 0.25))
DISCLAIMER = getattr(config, "VALUE_EDGE_DISCLAIMER", "研究用，非投注建议")


def _safe_float(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        return f if f > 1.0 else None
    except (TypeError, ValueError):
        return None


def _extract_jingcai_sp(prediction: dict[str, Any] | None) -> dict[str, float] | None:
    """从 prediction / odds_snapshot 提取竞彩 SP（胜平负）。"""
    if not prediction:
        return None
    for src in (
        prediction.get("jingcai_snapshot") or {},
        prediction.get("predict_row") or {},
        prediction.get("odds_snapshot") or {},
        prediction.get("jingcai") or {},
    ):
        h = _safe_float(src.get("sp_home"))
        d = _safe_float(src.get("sp_draw"))
        a = _safe_float(src.get("sp_away"))
        if h and d and a:
            return {"home": h, "draw": d, "away": a}
    return None


def _market_implied_probabilities(
    odds: dict[str, float],
) -> dict[str, float]:
    """对 1X2 赔率去水得到公平概率。"""
    dev = devig_1x2(odds["home"], odds["draw"], odds["away"])
    return {
        "home": dev["p_home"],
        "draw": dev["p_draw"],
        "away": dev["p_away"],
    }


def _half_kelly(p_model: float, decimal_odds: float) -> float | None:
    """half-Kelly 建议仓位；负数或赔率无效时返回 None。"""
    if p_model is None or not decimal_odds or decimal_odds <= 1.0:
        return None
    edge = p_model * decimal_odds - 1.0
    if edge <= 0:
        return None
    full_kelly = edge / (decimal_odds - 1.0)
    half = 0.5 * full_kelly
    return round(min(max(half, 0.0), MAX_KELLY), 4)


def compute_edge(
    p_model: dict[str, float],
    *,
    sp: dict[str, float] | None = None,
    eu_odds: dict[str, float] | None = None,
    model_source: str = "unknown",
) -> dict[str, Any] | None:
    """计算模型概率 vs 去水市场概率的 edge。

    Args:
        p_model: {"home": ..., "draw": ..., "away": ...}
        sp: 可选竞彩 SP {"home": ..., "draw": ..., "away": ...}
        eu_odds: 可选欧赔收盘 {"home": ..., "draw": ..., "away": ...}
        model_source: 模型来源标签（如 result_forecast / poisson）

    Returns:
        {"market_source": "jingcai_sp"|"eu_closing", "odds": ..., "p_mkt": ...,
         "p_model": ..., "edge": ..., "half_kelly": ..., "disclaimer": ...}
        无有效市场赔率时返回 None。
    """
    if not p_model or not any(p_model.values()):
        return None

    if sp:
        market_source = "jingcai_sp"
        odds = sp
    elif eu_odds:
        market_source = "eu_closing"
        odds = eu_odds
    else:
        return None

    p_mkt = _market_implied_probabilities(odds)
    edge = {
        k: round((p_model.get(k) or 0.0) - p_mkt[k], 4)
        for k in ("home", "draw", "away")
    }
    half_kelly = {
        k: _half_kelly(p_model.get(k), odds[k])
        for k in ("home", "draw", "away")
    }

    return {
        "market_source": market_source,
        "model_source": model_source,
        "odds": {k: round(v, 3) for k, v in odds.items()},
        "p_mkt": p_mkt,
        "p_model": {k: round(p_model.get(k) or 0.0, 4) for k in ("home", "draw", "away")},
        "edge": edge,
        "half_kelly": half_kelly,
        "disclaimer": DISCLAIMER,
    }


def market_info_from_context(
    context: dict[str, Any],
    prediction: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """从 result_forecast context + prediction 提取市场赔率信息。"""
    sp = _extract_jingcai_sp(prediction)
    eu = None
    european = context.get("european")
    if european:
        eu = {
            "home": european["odds"]["home"],
            "draw": european["odds"]["draw"],
            "away": european["odds"]["away"],
        }
    return {"sp": sp, "eu_odds": eu}


def build_model_edges(
    context: dict[str, Any],
    result_forecast: dict[str, Any],
    poisson: dict[str, Any] | None,
    prediction: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """打包融合模型与泊松模型的 edge 对照。"""
    market = market_info_from_context(context, prediction=prediction)
    if not market["sp"] and not market["eu_odds"]:
        return None

    fused_p = {
        "home": result_forecast.get("p_home"),
        "draw": result_forecast.get("p_draw"),
        "away": result_forecast.get("p_away"),
    }
    edges = {
        "market_source": market["sp"] and "jingcai_sp" or "eu_closing",
        "disclaimer": DISCLAIMER,
    }
    if any(v is not None for v in fused_p.values()):
        edges["result_forecast"] = compute_edge(
            fused_p, sp=market["sp"], eu_odds=market["eu_odds"], model_source="result_forecast"
        )
    if poisson and poisson.get("p_1x2"):
        edges["poisson"] = compute_edge(
            poisson["p_1x2"], sp=market["sp"], eu_odds=market["eu_odds"], model_source="poisson"
        )
    return edges
