"""Backward-compatible shim — use analysis.tournament.group_stage."""

from analysis.tournament.group_stage import (
    MATCH_TYPES,
    adjust_rates_for_group_stage,
    analyze_fixture_motivation,
    analyze_match_from_name,
    build_group_stage_report,
    fetch_live_snapshot,
    invalidate_cache,
    rank_best_third_places,
)

__all__ = [
    "MATCH_TYPES",
    "analyze_fixture_motivation",
    "analyze_match_from_name",
    "adjust_rates_for_group_stage",
    "build_group_stage_report",
    "fetch_live_snapshot",
    "invalidate_cache",
    "rank_best_third_places",
]
