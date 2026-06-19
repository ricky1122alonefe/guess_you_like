"""Backward-compatible shim — use analysis.tournament.knockout."""

from analysis.tournament.knockout import (
    TIER_SCORE,
    analyze_opponent_picking,
    bracket_flow_steps,
    build_group_bracket_overview,
    build_match_knockout_context,
    path_for_rank,
    project_scenarios,
    slot_label,
)

__all__ = [
    "TIER_SCORE",
    "slot_label",
    "path_for_rank",
    "bracket_flow_steps",
    "build_group_bracket_overview",
    "analyze_opponent_picking",
    "project_scenarios",
    "build_match_knockout_context",
]
