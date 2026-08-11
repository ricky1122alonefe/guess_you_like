"""P4: 串关 EV 计算。

公式（独立假设）：
  单腿 EV = p_model * odds - 1
  串关 p_parlay = Π p_i
  串关 odds_parlay = Π odds_i
  串关 EV = p_parlay * odds_parlay - 1

结算赔率优先级：竞彩 SP 若可购 > 否则欧赔对应项
模型概率：该场 devig 后 p_pick
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

MAX_LEGS = 3


def compute_leg_ev(pick: str, p_model: float, odds: float) -> dict[str, Any]:
    """单腿 EV。

    Args:
        pick: "home" / "draw" / "away"
        p_model: devig 后该方向概率
        odds: 结算赔率（竞彩 SP 或欧赔）
    """
    ev = p_model * odds - 1.0 if (p_model > 0 and odds > 0) else None
    return {
        "pick": pick,
        "p_model": round(p_model, 4),
        "odds": round(odds, 2) if odds else None,
        "ev": round(ev, 4) if ev is not None else None,
        "ev_pct": f"{ev:+.1%}" if ev is not None else "—",
    }


def compute_parlay_ev(legs: list[dict[str, Any]]) -> dict[str, Any]:
    """2~3 场串关 EV。

    Args:
        legs: [{pick, p_model, odds, match_name}, ...]

    Returns:
        {ok, legs_ev, parlay_odds, parlay_p, parlay_ev, parlay_ev_pct, disclaimer}
    """
    if not (2 <= len(legs) <= MAX_LEGS):
        return {"ok": False, "error": f"串关需 {2}~{MAX_LEGS} 场，当前 {len(legs)} 场"}

    legs_ev = []
    for leg in legs:
        ev = compute_leg_ev(
            leg.get("pick", ""),
            float(leg.get("p_model") or 0),
            float(leg.get("odds") or 0),
        )
        ev["match"] = leg.get("match_name", "")
        ev["odds_source"] = leg.get("odds_source", "")
        legs_ev.append(ev)

    # 组合
    parlay_odds = 1.0
    parlay_p = 1.0
    valid = True
    for leg in legs_ev:
        if leg["odds"] is None or leg["p_model"] <= 0:
            valid = False
            break
        parlay_odds *= leg["odds"]
        parlay_p *= leg["p_model"]

    if not valid:
        return {
            "ok": False,
            "error": "部分腿缺赔率或概率",
            "legs_ev": legs_ev,
        }

    parlay_ev = parlay_p * parlay_odds - 1.0
    stake_example = 100
    payout_example = round(stake_example * parlay_odds, 2)

    return {
        "ok": True,
        "n_legs": len(legs),
        "legs_ev": legs_ev,
        "parlay_odds": round(parlay_odds, 2),
        "parlay_p": round(parlay_p, 6),
        "parlay_ev": round(parlay_ev, 4),
        "parlay_ev_pct": f"{parlay_ev:+.1%}",
        "stake_example": stake_example,
        "payout_example": payout_example,
        "profit_example": round(payout_example - stake_example, 2),
        "disclaimer": "独立假设（各场结果互不影响）。EV>0 不保证盈利，仅供研究参考。",
    }
