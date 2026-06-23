"""Run quant analyzers in configured order."""

from __future__ import annotations

from typing import Any

from analysis.quant.common import (
    avg_goals_from_similarity,
    coerce_odds_dict,
    ensure_eu_implied,
    resolve_team_names,
)
from analysis.quant.elo import apply_elo
from analysis.quant.ev import apply_ev
from analysis.quant.mc import apply_mc
from analysis.quant.poisson import apply_poisson
from analysis.registry import quant_steps


def run_quant_analysis(
    pred: dict,
    *,
    cur: dict | None = None,
    output_root=None,
    steps: tuple[str, ...] | None = None,
) -> dict:
    """Mutate pred with quant block (score model, Elo, EV, optional MC)."""
    cur = coerce_odds_dict(cur or pred.get("odds_snapshot") or {})
    eu_imp = ensure_eu_implied(pred, cur)
    avg_goals = avg_goals_from_similarity(pred)
    home, away = resolve_team_names(pred)
    quant: dict[str, Any] = {}
    active = steps or quant_steps(output_root)

    if "poisson" in active:
        apply_poisson(pred, cur, eu_imp, avg_goals, quant)
    if "elo" in active:
        apply_elo(pred, home, away, quant)
    if quant:
        pred["quant"] = quant
    if "ev" in active:
        apply_ev(pred, quant or pred.setdefault("quant", {}))
    if "mc" in active:
        apply_mc(pred, home, away, pred.setdefault("quant", {}))
    try:
        from product_focus import score_prediction_enabled

        if score_prediction_enabled():
            from analysis.score_recommend import attach_score_recommendation

            attach_score_recommendation(pred)
    except Exception:
        pass
    return pred
