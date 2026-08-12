#!/usr/bin/env python3
"""Refresh Elo ratings from settled match_results."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from elo_ratings import load_ratings, refresh_elo_from_match_results


def main() -> None:
    ratings = load_ratings()
    before = len(ratings)
    refresh_elo_from_match_results(ratings)
    after = len(load_ratings())
    print(f"Elo refresh done: {before} -> {after} teams")


if __name__ == "__main__":
    main()
