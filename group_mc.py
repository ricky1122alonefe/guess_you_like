"""Monte Carlo group-stage advancement (free simulation)."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import config as cfg

from elo_ratings import expected_score, load_ratings
from analysis.tournament.group_stage import rank_best_third_places

SIMS = getattr(cfg, "MC_SIMULATIONS", 3000)
GROUPS_PATH = Path(__file__).resolve().parent / "data" / "wc2026_groups.json"


def _load_groups() -> dict[str, list[str]]:
    data = json.loads(GROUPS_PATH.read_text(encoding="utf-8"))
    return data.get("groups") or {}


def _simulate_match(home: str, away: str, ratings: dict[str, float]) -> tuple[int, int]:
    rh = ratings.get(home, 1900)
    ra = ratings.get(away, 1900)
    p_home = expected_score(rh, ra)
    r = random.random()
    if r < p_home * 0.78:
        hg = random.choice([1, 2, 2, 3])
        ag = random.randint(0, hg - 1) if hg > 0 else 0
    elif r < p_home * 0.78 + 0.22:
        hg = ag = random.choice([0, 1, 1, 2])
    else:
        ag = random.choice([1, 2, 2, 3])
        hg = random.randint(0, ag - 1) if ag > 0 else 0
    return hg, ag


def _apply_result(row: dict, hg: int, ag: int) -> None:
    row["played"] += 1
    row["gf"] += hg
    row["ga"] += ag
    row["gd"] = row["gf"] - row["ga"]
    if hg > ag:
        row["won"] += 1
        row["points"] += 3
    elif hg == ag:
        row["drawn"] += 1
        row["points"] += 1
    else:
        row["lost"] += 1


def _standings_row(team: str) -> dict:
    return {
        "team": team,
        "played": 0,
        "won": 0,
        "drawn": 0,
        "lost": 0,
        "gf": 0,
        "ga": 0,
        "gd": 0,
        "points": 0,
    }


def _rank_group(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: (-r["points"], -r["gd"], -r["gf"], r["team"]))


def simulate_group_outcomes(
    group: str,
    *,
    current_standings: list[dict] | None = None,
    remaining_pairs: list[tuple[str, str]] | None = None,
    n_sims: int = SIMS,
) -> dict[str, Any]:
    """MC estimate P(top2), P(best8 third), P(out) for teams in one group."""
    groups = _load_groups()
    teams = groups.get(group) or []
    if len(teams) < 4:
        return {"group": group, "error": "unknown group"}

    ratings = load_ratings()
    base = {t: _standings_row(t) for t in teams}
    if current_standings:
        for r in current_standings:
            t = r.get("team")
            if t in base:
                for k in ("played", "won", "drawn", "lost", "gf", "ga", "gd", "points"):
                    if k in r:
                        base[t][k] = int(r[k])

    if remaining_pairs is None:
        remaining_pairs = []
        try:
            from wc_standings_fetch import fetch_group_fixtures, normalize_team

            for fx in fetch_group_fixtures(group):
                if fx.is_finished:
                    continue
                h, a = normalize_team(fx.home), normalize_team(fx.away)
                if h in base and a in base:
                    remaining_pairs.append((h, a))
        except Exception:
            for a, b in ((teams[0], teams[1]), (teams[0], teams[2]), (teams[0], teams[3]),
                         (teams[1], teams[2]), (teams[1], teams[3]), (teams[2], teams[3])):
                if base[a]["played"] < 3 or base[b]["played"] < 3:
                    remaining_pairs.append((a, b))

    top2 = {t: 0 for t in teams}
    best3 = {t: 0 for t in teams}
    out = {t: 0 for t in teams}

    for _ in range(n_sims):
        st = {t: dict(v) for t, v in base.items()}
        for home, away in remaining_pairs:
            hg, ag = _simulate_match(home, away, ratings)
            _apply_result(st[home], hg, ag)
            _apply_result(st[away], ag, hg)

        ranked = _rank_group(list(st.values()))
        for r in ranked[:2]:
            top2[r["team"]] += 1
        third = ranked[2]
        fourth = ranked[3]
        all_standings = {group: ranked}
        best = rank_best_third_places(all_standings)
        best_teams = {x["team"] for x in best}
        if third["team"] in best_teams:
            best3[third["team"]] += 1
        else:
            out[third["team"]] += 1
        out[fourth["team"]] += 1

    def pct(n: int) -> float:
        return round(n / n_sims * 100, 1)

    return {
        "group": group,
        "simulations": n_sims,
        "teams": [
            {
                "team": t,
                "p_top2_pct": pct(top2[t]),
                "p_best3_pct": pct(best3[t]),
                "p_out_pct": pct(out[t]),
            }
            for t in teams
        ],
    }


def simulate_for_match(home: str, away: str, *, n_sims: int = SIMS) -> dict[str, Any] | None:
    groups = _load_groups()
    group = None
    for g, teams in groups.items():
        if home in teams and away in teams:
            group = g
            break
    if not group:
        return None
    try:
        from wc_standings_fetch import fetch_live_snapshot, normalize_team

        home = normalize_team(home)
        away = normalize_team(away)
        snap = fetch_live_snapshot()
        standings = (snap.get("standings") or {}).get(group) or []
    except Exception:
        standings = []
    return simulate_group_outcomes(group, current_standings=standings, n_sims=n_sims)
