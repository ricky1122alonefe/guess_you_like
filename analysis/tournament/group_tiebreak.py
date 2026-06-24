"""FIFA World Cup 2026 group ranking, tiebreakers, and qualification scenarios.

Regulations (Art. 13): when teams are level on points —
Step 1: head-to-head points / GD / GF among tied teams;
Step 2: overall group GD / GF / fair play;
Step 3: FIFA ranking.

Knockout: top 2 per group + 8 best third-placed teams (points, GD, GF among thirds).
"""

from __future__ import annotations

from functools import cmp_to_key
from itertools import product
from typing import Any, Iterable

# Minimal scorelines for remaining-match enumeration (covers W/D/L + GD swings).
_SCORE_OUTCOMES: tuple[tuple[int, int], ...] = (
    (1, 0), (2, 0), (3, 0), (2, 1), (3, 1), (3, 2),
    (0, 0), (1, 1), (2, 2),
    (0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3),
)


def _blank_row(team: str) -> dict[str, Any]:
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


def _apply_result(row: dict[str, Any], gf: int, ga: int) -> None:
    row["played"] = int(row.get("played") or 0) + 1
    row["gf"] = int(row.get("gf") or 0) + gf
    row["ga"] = int(row.get("ga") or 0) + ga
    row["gd"] = row["gf"] - row["ga"]
    if gf > ga:
        row["won"] = int(row.get("won") or 0) + 1
        row["points"] = int(row.get("points") or 0) + 3
    elif gf == ga:
        row["drawn"] = int(row.get("drawn") or 0) + 1
        row["points"] = int(row.get("points") or 0) + 1
    else:
        row["lost"] = int(row.get("lost") or 0) + 1


def _fixture_scores(fx: dict[str, Any]) -> tuple[int, int] | None:
    hs, aws = fx.get("home_score"), fx.get("away_score")
    if hs is None or aws is None:
        return None
    return int(hs), int(aws)


def _finished_fixtures(fixtures: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [f for f in (fixtures or []) if f.get("is_finished") and _fixture_scores(f)]


def _remaining_fixtures(fixtures: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [f for f in (fixtures or []) if not f.get("is_finished")]


def build_rows_from_fixtures(
    teams: Iterable[str],
    fixtures: list[dict[str, Any]] | None,
    *,
    extra_results: list[tuple[dict[str, Any], int, int]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Rebuild group table from finished fixtures (+ optional hypothetical results)."""
    rows = {t: _blank_row(t) for t in teams}
    for fx in _finished_fixtures(fixtures):
        sc = _fixture_scores(fx)
        if not sc:
            continue
        h, a = fx["home"], fx["away"]
        if h not in rows or a not in rows:
            continue
        hg, ag = sc
        _apply_result(rows[h], hg, ag)
        _apply_result(rows[a], ag, hg)
    for fx, hg, ag in extra_results or []:
        h, a = fx["home"], fx["away"]
        if h not in rows or a not in rows:
            continue
        _apply_result(rows[h], hg, ag)
        _apply_result(rows[a], ag, hg)
    return rows


def h2h_among(
    team: str,
    tied_teams: set[str],
    fixtures: list[dict[str, Any]],
) -> dict[str, int]:
    """Mini-league stats for *team* vs other *tied_teams* (FIFA step 1)."""
    gf = ga = pts = 0
    opponents = tied_teams - {team}
    if not opponents:
        return {"points": 0, "gd": 0, "gf": 0}
    for fx in fixtures:
        sc = _fixture_scores(fx)
        if not sc:
            continue
        h, a, hg, ag = fx["home"], fx["away"], sc[0], sc[1]
        if h == team and a in opponents:
            gf += hg
            ga += ag
            pts += 3 if hg > ag else (1 if hg == ag else 0)
        elif a == team and h in opponents:
            gf += ag
            ga += hg
            pts += 3 if ag > hg else (1 if ag == hg else 0)
    return {"points": pts, "gd": gf - ga, "gf": gf}


def compare_teams_fifa2026(
    a: str,
    b: str,
    stats: dict[str, dict[str, Any]],
    fixtures: list[dict[str, Any]],
    all_teams: list[str],
) -> int:
    """Comparator: negative => *a* ranks above *b*."""
    sa, sb = stats[a], stats[b]
    if sa["points"] != sb["points"]:
        return sb["points"] - sa["points"]

    tied = {t for t in all_teams if stats[t]["points"] == sa["points"]}
    if len(tied) >= 2:
        ha = h2h_among(a, tied, fixtures)
        hb = h2h_among(b, tied, fixtures)
        for key in ("points", "gd", "gf"):
            if ha[key] != hb[key]:
                return hb[key] - ha[key]

    if sa["gd"] != sb["gd"]:
        return sb["gd"] - sa["gd"]
    if sa["gf"] != sb["gf"]:
        return sb["gf"] - sa["gf"]
    return (a > b) - (a < b)


def rank_group_table(
    rows: list[dict[str, Any]],
    fixtures: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Order group rows best-to-worst using FIFA 2026 tiebreakers."""
    if not rows:
        return []
    stats = {r["team"]: dict(r) for r in rows}
    teams = list(stats.keys())
    fx = list(fixtures or [])
    ordered = sorted(
        teams,
        key=cmp_to_key(lambda a, b: compare_teams_fifa2026(a, b, stats, fx, teams)),
    )
    return [stats[t] for t in ordered]


def team_rank_in_table(team: str, ranked: list[dict[str, Any]]) -> int:
    for i, r in enumerate(ranked, start=1):
        if r.get("team") == team:
            return i
    return 99


def finished_match_log(team: str, fixtures: list[dict[str, Any]] | None) -> list[str]:
    """Human-readable finished results for a team (for narrative context)."""
    lines: list[str] = []
    for fx in sorted(_finished_fixtures(fixtures), key=lambda x: (x.get("round") or 0, x.get("kickoff") or "")):
        h, a = fx.get("home"), fx.get("away")
        sc = _fixture_scores(fx)
        if not sc or team not in (h, a):
            continue
        hg, ag = sc
        if team == h:
            opp, tg, og = a, hg, ag
        else:
            opp, tg, og = h, ag, hg
        if tg > og:
            tag = "胜"
        elif tg == og:
            tag = "平"
        else:
            tag = "负"
        lines.append(f"{tag}{opp} {tg}-{og}")
    return lines


def _enumerate_final_tables(
    teams: list[str],
    fixtures: list[dict[str, Any]] | None,
) -> list[list[dict[str, Any]]]:
    """All final tables reachable from current finished results + remaining fixtures."""
    fx = list(fixtures or [])
    finished = _finished_fixtures(fx)
    remaining = _remaining_fixtures(fx)
    if not remaining:
        rows = build_rows_from_fixtures(teams, fx)
        return [rank_group_table(list(rows.values()), finished)]

    tables: list[list[dict[str, Any]]] = []
    outcome_lists = [_SCORE_OUTCOMES for _ in remaining]
    for combo in product(*outcome_lists):
        extra = [(remaining[i], combo[i][0], combo[i][1]) for i in range(len(remaining))]
        rows = build_rows_from_fixtures(teams, fx, extra_results=extra)
        hypothetical = []
        for i, (hg, ag) in enumerate(combo):
            f = dict(remaining[i])
            f["home_score"] = hg
            f["away_score"] = ag
            f["is_finished"] = True
            hypothetical.append(f)
        ranked = rank_group_table(list(rows.values()), finished + hypothetical)
        tables.append(ranked)
    return tables


def _max_points(row: dict[str, Any]) -> int:
    rem = max(0, 3 - int(row.get("played") or 0))
    return int(row.get("points") or 0) + 3 * rem


def _could_still_tie_on_points(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Whether two teams can still finish level on total group points."""
    a_lo, a_hi = int(a.get("points") or 0), _max_points(a)
    b_lo, b_hi = int(b.get("points") or 0), _max_points(b)
    return a_hi >= b_lo and b_hi >= a_lo


def _qualification_h2h_notes(
    team: str,
    table: list[dict[str, Any]],
    fixtures: list[dict[str, Any]] | None,
    *,
    achievable: list[int],
) -> list[str]:
    """H2H notes that actually block qualification (not every stronger opponent)."""
    row = _row_by_team(table, team)
    if not row:
        return []
    finished = _finished_fixtures(fixtures)
    ranked = rank_group_table(table, fixtures)
    team_rank = team_rank_in_table(team, ranked)
    notes: list[str] = []

    for rival in ranked:
        rname = rival.get("team")
        if not rname or rname == team:
            continue
        if not _could_still_tie_on_points(row, rival):
            continue
        mini = h2h_among(team, {team, rname}, finished)
        opp = h2h_among(rname, {team, rname}, finished)
        if mini["points"] >= opp["points"]:
            continue
        rival_rank = team_rank_in_table(rname, ranked)
        if rival_rank < team_rank or (achievable and min(achievable) >= 3):
            notes.append(
                f"同分相互战绩落后{rname}({mini['points']}分 vs {opp['points']}分)，"
                f"难抢小组{'前三' if rival_rank <= 3 else '名次'}"
            )
    return notes[:2]


def scenario_analysis(
    team: str,
    table: list[dict[str, Any]],
    fixtures: list[dict[str, Any]] | None,
    *,
    best_third_cutoff: int = 3,
) -> dict[str, Any]:
    """Enumerate remaining outcomes; return achievable ranks & knockout paths."""
    teams = [r["team"] for r in table if r.get("team")]
    if team not in teams:
        return {"known": False, "team": team}

    tables = _enumerate_final_tables(teams, fixtures)
    achievable: set[int] = set()
    can_top2 = False
    can_best3 = False

    for ranked in tables:
        rk = team_rank_in_table(team, ranked)
        achievable.add(rk)
        if rk <= 2:
            can_top2 = True
        elif rk == 3:
            third = ranked[2]
            if (
                third.get("team") == team
                and int(third.get("points") or 0) >= best_third_cutoff
            ):
                can_best3 = True

    achievable_sorted = sorted(achievable)
    can_qualify = can_top2 or can_best3
    form = finished_match_log(team, fixtures)

    h2h_notes = _qualification_h2h_notes(
        team, table, fixtures, achievable=achievable_sorted,
    )

    return {
        "known": True,
        "team": team,
        "form_log": form,
        "form_cn": " · ".join(form) if form else "",
        "achievable_ranks": achievable_sorted,
        "can_qualify_top2": can_top2,
        "can_qualify_best3": can_best3,
        "can_qualify": can_qualify,
        "h2h_notes": h2h_notes,
        "scenarios_checked": len(tables),
    }


def _row_by_team(table: list[dict], team: str) -> dict[str, Any]:
    for r in table:
        if r.get("team") == team:
            return r
    return {}


def rank_group_third_for_best8(
    table: list[dict[str, Any]],
    fixtures: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    """Current third-placed team using FIFA ranking (not points-only)."""
    ranked = rank_group_table(table, fixtures)
    if len(ranked) < 3:
        return None
    row = dict(ranked[2])
    return row
