"""Lightweight Elo for national teams — free strength prior."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

TIER_SEED = {"elite": 2100, "strong": 2000, "mid": 1900, "weak": 1750}
DEFAULT_RATING = 1900
K_FACTOR = 32
HOME_ADV = 50

_DATA = Path(__file__).resolve().parent / "data" / "elo_ratings.json"


def _load_groups_config() -> dict:
    path = Path(__file__).resolve().parent / "data" / "wc2026_groups.json"
    return json.loads(path.read_text(encoding="utf-8"))


def seed_ratings() -> dict[str, float]:
    cfg = _load_groups_config()
    tiers = cfg.get("team_strength_tiers") or {}
    ratings: dict[str, float] = {}
    for teams in (cfg.get("groups") or {}).values():
        for t in teams:
            ratings[t] = float(TIER_SEED.get(tiers.get(t, "mid"), DEFAULT_RATING))
    return ratings


def load_ratings() -> dict[str, float]:
    if _DATA.is_file():
        try:
            data = json.loads(_DATA.read_text(encoding="utf-8"))
            if isinstance(data.get("ratings"), dict):
                return {k: float(v) for k, v in data["ratings"].items()}
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    return seed_ratings()


def save_ratings(ratings: dict[str, float]) -> None:
    _DATA.parent.mkdir(parents=True, exist_ok=True)
    _DATA.write_text(
        json.dumps({"ratings": ratings}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def expected_score(r_a: float, r_b: float, *, home_adv: float = HOME_ADV) -> float:
    return 1.0 / (1.0 + 10 ** ((r_b - (r_a + home_adv)) / 400.0))


def update_elo(ratings: dict[str, float], home: str, away: str, hg: int, ag: int) -> None:
    ra = ratings.setdefault(home, DEFAULT_RATING)
    rb = ratings.setdefault(away, DEFAULT_RATING)
    if hg > ag:
        sa, sb = 1.0, 0.0
    elif hg == ag:
        sa, sb = 0.5, 0.5
    else:
        sa, sb = 0.0, 1.0
    ea = expected_score(ra, rb)
    eb = 1.0 - ea
    ratings[home] = ra + K_FACTOR * (sa - ea)
    ratings[away] = rb + K_FACTOR * (sb - eb)


def apply_finished_results(results: list[dict]) -> dict[str, float]:
    ratings = load_ratings()
    for r in results:
        home = r.get("home_team") or r.get("home")
        away = r.get("away_team") or r.get("away")
        hs, aws = r.get("home_score"), r.get("away_score")
        if not home or not away or hs is None or aws is None:
            continue
        try:
            update_elo(ratings, str(home), str(away), int(hs), int(aws))
        except (TypeError, ValueError):
            continue
    save_ratings(ratings)
    return ratings


def match_elo_context(home: str, away: str, *, ratings: dict[str, float] | None = None) -> dict[str, Any]:
    ratings = ratings or load_ratings()
    rh = ratings.get(home, DEFAULT_RATING)
    ra = ratings.get(away, DEFAULT_RATING)
    eh = expected_score(rh, ra)
    return {
        "home": home,
        "away": away,
        "home_elo": round(rh, 0),
        "away_elo": round(ra, 0),
        "elo_diff": round(rh - ra, 0),
        "home_win_prob_pct": round(eh * 100, 1),
        "away_win_prob_pct": round((1 - eh) * 100 * 0.85, 1),
        "draw_hint_pct": round((1 - eh) * 100 * 0.15, 1),
    }
