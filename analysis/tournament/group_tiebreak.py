"""FIFA World Cup 2026 group ranking, tiebreakers, and qualification scenarios.

Regulations Art. 13 (group ranking when level on points):
  Step 1 — among *teams concerned* (all teams tied on group points):
    a) greatest points in matches between those teams
    b) superior goal difference in those matches
    c) greatest goals scored in those matches
    If still tied, repeat a–c using only the still-tied subset.
  Step 2 — among teams still equal:
    d) overall group goal difference
    e) overall group goals scored
    f) fair play (not modelled here)
  Step 3 — FIFA/Coca-Cola ranking (not modelled here)

Knockout: top 2 per group + 8 best third-placed teams (all-group pts/GD/GF, no H2H).
"""

from __future__ import annotations

from functools import cmp_to_key
from itertools import product
from typing import Any, Iterable

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
    """Mini-league stats for *team* in matches only between *tied_teams*."""
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


def _mini_key(team: str, subset: set[str], fixtures: list[dict[str, Any]]) -> tuple[int, int, int]:
    m = h2h_among(team, subset, fixtures)
    return (m["points"], m["gd"], m["gf"])


def _step2_key(stats: dict[str, Any]) -> tuple[int, int]:
    return (int(stats.get("gd") or 0), int(stats.get("gf") or 0))


def _rank_by_step2(teams: list[str], stats: dict[str, dict[str, Any]]) -> list[str]:
    return sorted(teams, key=lambda t: _step2_key(stats[t]), reverse=True)


def _rank_subset_fifa2026(
    teams: list[str],
    stats: dict[str, dict[str, Any]],
    fixtures: list[dict[str, Any]],
) -> list[str]:
    """Rank teams level on group points (Art. 13 step 1, recurse on still-tied subset)."""
    if len(teams) <= 1:
        return teams

    subset = set(teams)
    keys = {t: _mini_key(t, subset, fixtures) for t in teams}

    if len(set(keys.values())) == len(teams):
        return sorted(teams, key=lambda t: keys[t], reverse=True)

    if len(set(keys.values())) == 1:
        return _rank_by_step2(teams, stats)

    buckets: dict[tuple[int, int, int], list[str]] = {}
    for t in teams:
        buckets.setdefault(keys[t], []).append(t)

    result: list[str] = []
    for k in sorted(buckets.keys(), reverse=True):
        bucket = buckets[k]
        if len(bucket) == 1:
            result.append(bucket[0])
        else:
            sub = _rank_subset_fifa2026(bucket, stats, fixtures)
            if len(sub) == len(bucket) and len(set(keys[t] for t in bucket)) == 1:
                result.extend(_rank_by_step2(bucket, stats))
            else:
                result.extend(sub)
    return result


def rank_group_table(
    rows: list[dict[str, Any]],
    fixtures: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Order group rows best-to-worst using FIFA 2026 Art. 13."""
    if not rows:
        return []
    stats = {r["team"]: dict(r) for r in rows}
    fx = list(fixtures or [])

    by_pts: dict[int, list[str]] = {}
    for t, s in stats.items():
        by_pts.setdefault(int(s.get("points") or 0), []).append(t)

    ordered: list[str] = []
    for pts in sorted(by_pts.keys(), reverse=True):
        ordered.extend(_rank_subset_fifa2026(by_pts[pts], stats, fx))

    return [stats[t] for t in ordered]


def compare_teams_fifa2026(
    a: str,
    b: str,
    stats: dict[str, dict[str, Any]],
    fixtures: list[dict[str, Any]],
    all_teams: list[str],
) -> int:
    """Comparator consistent with rank_group_table (negative => *a* above *b*)."""
    ranked = rank_group_table([stats[t] for t in all_teams], fixtures)
    ra = team_rank_in_table(a, ranked)
    rb = team_rank_in_table(b, ranked)
    return ra - rb


def team_rank_in_table(team: str, ranked: list[dict[str, Any]]) -> int:
    for i, r in enumerate(ranked, start=1):
        if r.get("team") == team:
            return i
    return 99


def finished_match_log(team: str, fixtures: list[dict[str, Any]] | None) -> list[str]:
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
    a_lo, a_hi = int(a.get("points") or 0), _max_points(a)
    b_lo, b_hi = int(b.get("points") or 0), _max_points(b)
    return a_hi >= b_lo and b_hi >= a_lo


def _direct_h2h_played(a: str, b: str, fixtures: list[dict[str, Any]]) -> bool:
    for fx in _finished_fixtures(fixtures):
        if {fx.get("home"), fx.get("away")} == {a, b}:
            return True
    return False


def _blocks_first_place_by_h2h(
    team: str,
    table: list[dict[str, Any]],
    fixtures: list[dict[str, Any]] | None,
) -> bool:
    """Two-way tie at the top: lost direct H2H to a rival who can still level on points."""
    row = _row_by_team(table, team)
    if not row:
        return False
    my_max = _max_points(row)
    finished = _finished_fixtures(fixtures)
    for rival in table:
        rname = rival.get("team")
        if not rname or rname == team:
            continue
        if not _could_still_tie_on_points(row, rival):
            continue
        if my_max > _max_points(rival):
            continue
        if not _direct_h2h_played(team, rname, fixtures):
            continue
        mini = h2h_among(team, {team, rname}, finished)
        opp = h2h_among(rname, {team, rname}, finished)
        if mini["points"] < opp["points"]:
            return True
    return False


def _filter_achievable_ranks(
    team: str,
    table: list[dict[str, Any]],
    fixtures: list[dict[str, Any]] | None,
    achievable: list[int],
) -> list[int]:
    ranks = list(achievable)
    if 1 in ranks and _blocks_first_place_by_h2h(team, table, fixtures):
        ranks = [r for r in ranks if r != 1]
    return ranks


def scenario_analysis(
    team: str,
    table: list[dict[str, Any]],
    fixtures: list[dict[str, Any]] | None,
    *,
    best_third_cutoff: int = 3,
) -> dict[str, Any]:
    """Enumerate remaining outcomes using FIFA table ranking on every final table."""
    teams = [r["team"] for r in table if r.get("team")]
    if team not in teams:
        return {"known": False, "team": team}
    if not fixtures:
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

    achievable_sorted = _filter_achievable_ranks(
        team, table, fixtures, sorted(achievable),
    )
    can_qualify = can_top2 or can_best3
    form = finished_match_log(team, fixtures)

    return {
        "known": True,
        "team": team,
        "form_log": form,
        "form_cn": " · ".join(form) if form else "",
        "achievable_ranks": achievable_sorted,
        "can_qualify_top2": can_top2,
        "can_qualify_best3": can_best3,
        "can_qualify": can_qualify,
        "h2h_notes": [],
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
    ranked = rank_group_table(table, fixtures)
    if len(ranked) < 3:
        return None
    return dict(ranked[2])
