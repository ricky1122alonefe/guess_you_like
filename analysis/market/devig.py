"""P1: 去水隐含概率统一 API。

所有结果预测、串关 EV、AI payload 必须用 devig 后的概率，禁止只用 1/odds 不归一。

方法：
  - proportional（默认）：p_i ∝ 1/o_i 再归一
  - shin：Shin 方法（更精确，需 shin 库）
  - power：Power 方法
"""
from __future__ import annotations

from typing import Any


def devig_1x2(
    odds_h: float,
    odds_d: float,
    odds_a: float,
    method: str = "proportional",
) -> dict[str, Any]:
    """去水隐含概率。

    Args:
        odds_h/d/a: 欧/竞彩 1X2 赔率
        method: "proportional"（默认）| "shin" | "power"

    Returns:
        {p_home, p_draw, p_away, overround, fair_odds, method}
        p_* 之和 = 1.0；overround > 0
    """
    h = float(odds_h) if odds_h and float(odds_h) > 1.0 else 0
    d = float(odds_d) if odds_d and float(odds_d) > 1.0 else 0
    a = float(odds_a) if odds_a and float(odds_a) > 1.0 else 0

    if h <= 0 or a <= 0:
        return {
            "p_home": 0.0, "p_draw": 0.0, "p_away": 0.0,
            "overround": 0.0, "fair_odds": {}, "method": method,
        }

    if method == "shin":
        try:
            return _devig_shin(h, d, a)
        except Exception:
            pass  # 回退 proportional

    if method == "power":
        return _devig_power(h, d, a)

    return _devig_proportional(h, d, a)


def _devig_proportional(h: float, d: float, a: float) -> dict[str, Any]:
    """朴素去水：p_i = (1/o_i) / Σ(1/o_j)。"""
    rh = 1.0 / h
    rd = 1.0 / d if d > 0 else 0
    ra = 1.0 / a
    total = rh + rd + ra
    overround = total - 1.0
    p_h = rh / total
    p_d = rd / total
    p_a = ra / total
    return {
        "p_home": round(p_h, 4),
        "p_draw": round(p_d, 4),
        "p_away": round(p_a, 4),
        "overround": round(overround, 4),
        "fair_odds": {
            "home": round(1.0 / p_h, 2) if p_h > 0 else None,
            "draw": round(1.0 / p_d, 2) if p_d > 0 else None,
            "away": round(1.0 / p_a, 2) if p_a > 0 else None,
        },
        "method": "proportional",
    }


def _devig_shin(h: float, d: float, a: float) -> dict[str, Any]:
    """Shin 方法去水（需 shin 库）。"""
    from shin import shin_implied_probabilities

    probs = shin_implied_probabilities([h, d if d > 0 else 999.0, a])
    p_h, p_d, p_a = probs[0], probs[1], probs[2]
    overround = (1.0 / h + (1.0 / d if d > 0 else 0) + 1.0 / a) - 1.0
    return {
        "p_home": round(float(p_h), 4),
        "p_draw": round(float(p_d), 4),
        "p_away": round(float(p_a), 4),
        "overround": round(overround, 4),
        "fair_odds": {
            "home": round(1.0 / float(p_h), 2) if p_h > 0 else None,
            "draw": round(1.0 / float(p_d), 2) if p_d > 0 else None,
            "away": round(1.0 / float(p_a), 2) if p_a > 0 else None,
        },
        "method": "shin",
    }


def _devig_power(h: float, d: float, a: float) -> dict[str, Any]:
    """Power 方法去水：迭代 theta 使 Σ(o_i^(-theta)) = 1。"""
    import scipy.optimize as opt

    def f(theta):
        return h ** (-theta) + (d ** (-theta) if d > 0 else 0) + a ** (-theta) - 1.0

    try:
        theta = opt.brentq(f, 0.01, 5.0)
    except Exception:
        return _devig_proportional(h, d, a)

    p_h = h ** (-theta)
    p_d = d ** (-theta) if d > 0 else 0
    p_a = a ** (-theta)
    total = p_h + p_d + p_a
    p_h, p_d, p_a = p_h / total, p_d / total, p_a / total
    overround = (1.0 / h + (1.0 / d if d > 0 else 0) + 1.0 / a) - 1.0
    return {
        "p_home": round(p_h, 4),
        "p_draw": round(p_d, 4),
        "p_away": round(p_a, 4),
        "overround": round(overround, 4),
        "fair_odds": {
            "home": round(1.0 / p_h, 2) if p_h > 0 else None,
            "draw": round(1.0 / p_d, 2) if p_d > 0 else None,
            "away": round(1.0 / p_a, 2) if p_a > 0 else None,
        },
        "method": "power",
    }


def devig_from_odds(odds_dict: dict, method: str = "proportional") -> dict[str, Any]:
    """从 odds dict（含 home/draw/away 或 eu_home/eu_draw/eu_away）提取去水概率。"""
    h = odds_dict.get("home") or odds_dict.get("eu_home") or odds_dict.get("sp_home")
    d = odds_dict.get("draw") or odds_dict.get("eu_draw") or odds_dict.get("sp_draw")
    a = odds_dict.get("away") or odds_dict.get("eu_away") or odds_dict.get("sp_away")
    return devig_1x2(h, d, a, method=method)
