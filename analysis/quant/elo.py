"""Elo ratings context for a fixture."""

from __future__ import annotations

from typing import Any

from elo_ratings import load_ratings, match_elo_context


def apply_elo(pred: dict, home: str, away: str, quant: dict[str, Any]) -> None:
    if not home or not away:
        return
    quant["elo"] = match_elo_context(home, away, ratings=load_ratings())
