"""Shared helpers for quant analyzers."""

from __future__ import annotations

from typing import Any

from eu_implied_metrics import compute_eu_implied
from share_card import split_teams


def coerce_odds_dict(cur: Any) -> dict:
    """Accept odds snapshot dict or parser.MatchOdds dataclass."""
    if not cur:
        return {}
    if isinstance(cur, dict):
        return cur
    d = getattr(cur, "__dict__", None)
    return d if isinstance(d, dict) else {}


def ensure_eu_implied(pred: dict, cur: dict) -> dict | None:
    eu_imp = pred.get("eu_implied")
    if eu_imp:
        return eu_imp
    m = compute_eu_implied(cur.get("eu_home"), cur.get("eu_draw"), cur.get("eu_away"))
    if m:
        eu_imp = m.to_dict()
        pred["eu_implied"] = eu_imp
        return eu_imp
    return None


def avg_goals_from_similarity(pred: dict) -> float | None:
    sim = pred.get("similarity_analysis") or {}
    for block in sim.get("open") or []:
        if block.get("avg_total_goals"):
            return block.get("avg_total_goals")
    return None


def resolve_team_names(pred: dict) -> tuple[str, str]:
    hr, ar = split_teams(pred.get("match") or "")
    if hr and ar:
        try:
            from wc_standings_fetch import normalize_team

            hr, ar = normalize_team(hr), normalize_team(ar)
        except Exception:
            pass
    return hr, ar
