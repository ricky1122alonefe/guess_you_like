"""Run all quant analyzers in order."""

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


def run_quant_analysis(pred: dict, *, cur: dict | None = None) -> dict:
    """Mutate pred with quant block (score model, Elo, EV, optional MC)."""
    cur = coerce_odds_dict(cur or pred.get("odds_snapshot") or {})
    eu_imp = ensure_eu_implied(pred, cur)
    avg_goals = avg_goals_from_similarity(pred)
    quant: dict[str, Any] = {}
    apply_poisson(pred, cur, eu_imp, avg_goals, quant)
    home, away = resolve_team_names(pred)
    apply_elo(pred, home, away, quant)
    pred["quant"] = quant
    apply_ev(pred, quant)
    apply_mc(pred, home, away, quant)
    return pred
