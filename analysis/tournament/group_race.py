"""Group-stage final-round race logic: lock status, chaos, likely R32 opponents."""

from __future__ import annotations

import re
from typing import Any

from analysis.tournament.group_tiebreak import (
    finished_match_log,
    rank_group_table,
    scenario_analysis,
    team_rank_in_table,
)
from analysis.tournament.knockout import (
    _load_bracket,
    _load_groups_config,
    _matches_for_slot,
    _opponent_slot_for_fixed_match,
    path_for_rank,
    slot_label,
)
from analysis.tournament.group_stage import (
    best_third_cutoff_points,
    rank_best_third_places,
    second_place_points,
)


def _sort_table(table: list[dict]) -> list[dict]:
    return rank_group_table(table, None)


def max_points(row: dict) -> int:
    rem = max(0, 3 - int(row.get("played") or 0))
    return int(row.get("points") or 0) + 3 * rem


def min_points(row: dict) -> int:
    return int(row.get("points") or 0)


def _row_by_team(table: list[dict], team: str) -> dict | None:
    for r in table:
        if r.get("team") == team:
            return r
    return None


def _rank_of(table: list[dict], team: str, fixtures: list[dict] | None = None) -> int:
    return team_rank_in_table(team, rank_group_table(table, fixtures))


def can_still_finish_rank(
    row: dict,
    table: list[dict],
    target_rank: int,
    *,
    fixtures: list[dict] | None = None,
) -> bool:
    """Can team still finish at target_rank (1/2/3) in the group table?"""
    if not row:
        return False
    if fixtures:
        sa = scenario_analysis(
            row["team"],
            table,
            fixtures,
            best_third_cutoff=best_third_cutoff_points(None),
        )
        if sa.get("known"):
            return target_rank in (sa.get("achievable_ranks") or [])

    my_max = max_points(row)
    sorted_t = _sort_table(table)
    n = len(sorted_t)
    if target_rank < 1 or target_rank > n:
        return False

    if target_rank == 1:
        leader = sorted_t[0]
        if row["team"] == leader["team"]:
            second = sorted_t[1] if n > 1 else None
            if not second:
                return True
            return max_points(second) >= min_points(row)
        return my_max >= min_points(leader)

    if target_rank == 2:
        if n < 2:
            return False
        second = sorted_t[1]
        if row["team"] == second["team"]:
            return True
        if _rank_of(table, row["team"]) >= 3:
            return my_max >= min_points(second)
        return my_max >= min_points(sorted_t[0]) or my_max >= min_points(second)

    if target_rank == 3:
        if n < 3:
            return False
        third = sorted_t[2]
        if row["team"] == third["team"]:
            return True
        if _rank_of(table, row["team"]) >= 4:
            return my_max >= min_points(third)
        return my_max >= min_points(third)

    return False


def is_locked_first(row: dict, table: list[dict], *, fixtures: list[dict] | None = None) -> bool:
    if not row:
        return False
    if fixtures:
        sa = scenario_analysis(row["team"], table, fixtures, best_third_cutoff=3)
        if sa.get("known"):
            return sa.get("achievable_ranks") == [1]
        return False
    others = [r for r in table if r.get("team") != row.get("team")]
    if not others:
        return True
    return all(max_points(o) < int(row.get("points") or 0) for o in others)


def is_locked_top2(row: dict, table: list[dict], *, fixtures: list[dict] | None = None) -> bool:
    if not row:
        return False
    if fixtures:
        sa = scenario_analysis(row["team"], table, fixtures, best_third_cutoff=3)
        if sa.get("known"):
            ranks = sa.get("achievable_ranks") or []
            return bool(ranks) and max(ranks) <= 2
        return False
    sorted_t = _sort_table(table)
    if len(sorted_t) < 3:
        return is_locked_first(row, table, fixtures=fixtures)
    third = sorted_t[2]
    return min_points(row) > max_points(third)


def qualification_points_floor(table: list[dict], best_thirds: list[dict] | None) -> int:
    top2 = second_place_points(table)
    bt = best_third_cutoff_points(best_thirds)
    if top2 > 0:
        return max(bt, top2)
    return bt


def can_still_qualify_knockout(
    row: dict,
    table: list[dict],
    *,
    best_thirds: list[dict] | None = None,
    fixtures: list[dict] | None = None,
) -> bool:
    """Still has a path into the round of 32 (top 2 or best 8 thirds)."""
    if not row:
        return False
    if fixtures:
        sa = scenario_analysis(
            row["team"],
            table,
            fixtures,
            best_third_cutoff=best_third_cutoff_points(best_thirds),
        )
        if sa.get("known"):
            return bool(sa.get("can_qualify"))

    mx = max_points(row)
    top2_pts = second_place_points(table)
    qual_floor = qualification_points_floor(table, best_thirds)
    if mx >= top2_pts and can_still_finish_rank(row, table, 2, fixtures=fixtures):
        return True
    if mx >= qual_floor and can_still_finish_rank(row, table, 3, fixtures=fixtures):
        return True
    return False


def is_effectively_out(
    row: dict,
    table: list[dict],
    *,
    best_thirds: list[dict] | None = None,
    fixtures: list[dict] | None = None,
) -> bool:
    if not row:
        return False
    if is_locked_first(row, table, fixtures=fixtures) or is_locked_top2(row, table, fixtures=fixtures):
        return False
    return not can_still_qualify_knockout(
        row, table, best_thirds=best_thirds, fixtures=fixtures,
    )


def qualifying_possible_ranks(
    row: dict,
    table: list[dict],
    *,
    best_thirds: list[dict] | None = None,
    fixtures: list[dict] | None = None,
) -> list[int]:
    if is_effectively_out(row, table, best_thirds=best_thirds, fixtures=fixtures):
        return []
    if fixtures:
        sa = scenario_analysis(
            row["team"],
            table,
            fixtures,
            best_third_cutoff=best_third_cutoff_points(best_thirds),
        )
        if sa.get("known"):
            ranks: list[int] = []
            for rk in sa.get("achievable_ranks") or []:
                if rk <= 2:
                    ranks.append(rk)
                elif rk == 3 and sa.get("can_qualify_best3"):
                    ranks.append(3)
            return sorted(set(ranks))

    mx = max_points(row)
    top2_pts = second_place_points(table)
    qual_floor = qualification_points_floor(table, best_thirds)
    ranks = []
    for target in (1, 2, 3):
        if not can_still_finish_rank(row, table, target, fixtures=fixtures):
            continue
        if target == 3 and mx < top2_pts and mx < qual_floor:
            continue
        ranks.append(target)
    return ranks


def _out_note(
    team: str,
    *,
    mx: int,
    top2_pts: int,
    qual_floor: int,
) -> str:
    bits = [f"{team} 已确认出局"]
    if mx < top2_pts:
        bits.append(f"最高{mx}分无法直通前二({top2_pts}分)")
    if mx < qual_floor:
        bits.append(f"亦难挤入8个最佳第三名额(门槛约{qual_floor}分)")
    return "；".join(bits) + "。"


def _must_win_qualification_note(
    team: str,
    *,
    draw_pts: int,
    top2_pts: int,
    bt_cut: int,
) -> str:
    bits = [f"{team} 末轮须全取三分"]
    if top2_pts > 0 and draw_pts < top2_pts:
        bits.append(f"平局仅{draw_pts}分无法威胁前二({top2_pts}分)")
    if draw_pts < bt_cut:
        bits.append(f"亦无法进入最佳第三竞争(门槛约{bt_cut}分)")
    return "，".join(bits) + "。"


def analyze_team_race(
    team: str,
    table: list[dict],
    *,
    best_thirds: list[dict] | None = None,
    fixtures: list[dict] | None = None,
) -> dict[str, Any]:
    row = _row_by_team(table, team)
    if not row:
        return {"team": team, "known": False}

    bt_cut = best_third_cutoff_points(best_thirds)
    sa = scenario_analysis(team, table, fixtures, best_third_cutoff=bt_cut) if fixtures else {"known": False}
    form_cn = sa.get("form_cn") or " · ".join(finished_match_log(team, fixtures))

    rank = _rank_of(table, team, fixtures)
    rem = max(0, 3 - int(row.get("played") or 0))
    mx = max_points(row)
    top2_pts = second_place_points(table)
    qual_floor = qualification_points_floor(table, best_thirds)
    draw_pts = int(row.get("points") or 0) + (1 if rem >= 1 else 0)
    draw_no_top2 = rem <= 1 and top2_pts > 0 and draw_pts < top2_pts

    possible = qualifying_possible_ranks(
        row, table, best_thirds=best_thirds, fixtures=fixtures,
    )
    locked_1 = is_locked_first(row, table, fixtures=fixtures)
    locked_2 = is_locked_top2(row, table, fixtures=fixtures)
    out = is_effectively_out(row, table, best_thirds=best_thirds, fixtures=fixtures)
    still_qualifies = can_still_qualify_knockout(
        row, table, best_thirds=best_thirds, fixtures=fixtures,
    )

    if locked_1:
        status, status_cn = "locked_1st", "已锁定小组第一"
        note = f"{team} 积分 {row['points']}，其余球队最高可达 {max(max_points(o) for o in table if o['team']!=team)} 分，已无法超越。"
    elif locked_2:
        status, status_cn = "locked_top2", "已锁定前二出线"
        note = f"{team} 至少确保小组前二；末轮战意以轮换/控节奏为主。"
    elif out:
        status, status_cn = "out", "确认出局"
        if sa.get("known"):
            note = _out_note(team, mx=mx, top2_pts=top2_pts, qual_floor=qual_floor)
        else:
            note = f"{team} 最高可达 {mx} 分，已无法进入32强。"
    elif still_qualifies and draw_no_top2 and mx >= qual_floor:
        status, status_cn = "must_win", "必须争胜"
        note = _must_win_qualification_note(
            team, draw_pts=draw_pts, top2_pts=top2_pts, bt_cut=bt_cut,
        )
    elif 1 in possible and len([
        t for t in table
        if 1 in qualifying_possible_ranks(
            t, table, best_thirds=best_thirds, fixtures=fixtures,
        )
    ]) >= 3:
        status, status_cn = "fight_1st", "仍争夺小组第一"
        note = f"{team} 末轮仍可能夺头名，战意与控分/挑对手需结合淘汰赛签位。"
    elif 1 in possible:
        status, status_cn = "fight_1st", "仍可能夺头名"
        note = f"{team} 末轮赛果将直接影响头名归属与 32 强签位。"
    elif 2 in possible and 3 in possible:
        status, status_cn = "fight_2nd_3rd", "争第二 / 最佳第三"
        if draw_no_top2:
            note = _must_win_qualification_note(
                team, draw_pts=draw_pts, top2_pts=top2_pts, bt_cut=bt_cut,
            )
        else:
            note = f"{team} 需在「直通前二」与「争最佳第三」之间权衡。"
    elif 2 in possible:
        status, status_cn = "fight_2nd", "争小组第二"
        if draw_no_top2:
            note = _must_win_qualification_note(
                team, draw_pts=draw_pts, top2_pts=top2_pts, bt_cut=bt_cut,
            )
        else:
            note = f"{team} 末轮主要争夺小组第二出线。"
    elif 3 in possible:
        status, status_cn = "fight_3rd", "争最佳第三"
        note = f"{team} 目标小组第三并冲击8个最佳第三名额（同分看相互战绩）。"
    else:
        status, status_cn = "out", "确认出局"
        note = _out_note(team, mx=mx, top2_pts=top2_pts, qual_floor=qual_floor)

    return {
        "team": team,
        "known": True,
        "rank": rank,
        "points": row["points"],
        "played": row["played"],
        "gd": row.get("gd", 0),
        "remaining": rem,
        "max_points": mx,
        "possible_ranks": possible,
        "achievable_ranks": sa.get("achievable_ranks") if sa.get("known") else [],
        "form_log": sa.get("form_log") or finished_match_log(team, fixtures),
        "form_cn": form_cn,
        "h2h_notes": sa.get("h2h_notes") or [],
        "can_qualify_top2": sa.get("can_qualify_top2") if sa.get("known") else None,
        "can_qualify_best3": sa.get("can_qualify_best3") if sa.get("known") else None,
        "locked_first": locked_1,
        "locked_top2": locked_2,
        "effectively_out": out,
        "status": status,
        "status_cn": status_cn,
        "note": note,
    }


def analyze_group_chaos(
    table: list[dict],
    *,
    round_num: int = 3,
    fixtures: list[dict] | None = None,
) -> dict[str, Any]:
    fighters_1st = [
        r["team"] for r in table
        if 1 in qualifying_possible_ranks(
            r, table, fixtures=fixtures,
        )
    ]
    fighters_2nd = [
        r["team"] for r in table
        if 2 in qualifying_possible_ranks(
            r, table, fixtures=fixtures,
        )
    ]
    n = len(table)
    if len(fighters_1st) >= 3:
        level, level_cn = "high", "末轮混战"
        summary = f"{'、'.join(fighters_1st)} 等 {len(fighters_1st)} 队仍可能夺头名，末轮任何结果都可能改写排名。"
    elif len(fighters_1st) == 2 and round_num >= 3:
        level, level_cn = "medium", "头名双雄"
        summary = f"{' vs '.join(fighters_1st)} 末轮直接对话或同轮竞逐头名，战意拉满。"
    elif n >= 4 and len(fighters_1st) == 4:
        level, level_cn = "high", "全员争第一"
        summary = "本组四队末轮均仍可能夺头名，典型开放乱局。"
    else:
        level, level_cn = "low", "形势相对清晰"
        locked = [r["team"] for r in table if is_locked_first(r, table, fixtures=fixtures)]
        if locked:
            summary = f"{'、'.join(locked)} 已基本锁定头名，其余球队争第二/第三。"
        else:
            summary = f"头名争夺主要在 {('、'.join(fighters_1st) if fighters_1st else '前两名')} 之间。"

    return {
        "chaos_level": level,
        "chaos_level_cn": level_cn,
        "fighting_1st": fighters_1st,
        "fighting_2nd": fighters_2nd,
        "summary": summary,
        "round_num": round_num,
    }


def _parse_fixed_slot(slot: str) -> tuple[int, str] | None:
    m = re.match(r"^([12])([A-L])$", slot or "")
    if not m:
        return None
    return int(m.group(1)), m.group(2)


def resolve_opponent_slot(
    opponent_slot: str,
    *,
    match: dict | None = None,
    all_standings: dict[str, list[dict]] | None = None,
    best_thirds: list[dict] | None = None,
    fixtures: list[dict] | None = None,
) -> dict[str, Any]:
    all_standings = all_standings or {}
    best_thirds = best_thirds or rank_best_third_places(all_standings)

    parsed = _parse_fixed_slot(opponent_slot)
    if parsed:
        rank, grp = parsed
        table = all_standings.get(grp) or []
        if not table:
            return {"slot": opponent_slot, "label": opponent_slot, "teams": [], "note": "暂无积分榜"}
        grp_fx = [f for f in (fixtures or []) if f.get("group") == grp]
        sorted_t = rank_group_table(table, grp_fx)
        current = sorted_t[rank - 1]["team"] if len(sorted_t) >= rank else "—"
        contenders = [
            r["team"] for r in table
            if rank in qualifying_possible_ranks(
                r, table, best_thirds=best_thirds,
                fixtures=grp_fx or None,
            )
        ]
        locked = len(contenders) == 1
        if locked:
            note = f"{grp}组第{rank}已基本确定为 {current}"
        elif len(contenders) <= 2:
            note = f"{grp}组第{rank}将在 {(' / '.join(contenders))} 之间产生"
        else:
            note = f"{grp}组第{rank}仍开放，当前暂列 {current}"
        return {
            "slot": opponent_slot,
            "label": f"{rank}{grp}组",
            "teams": contenders or [current],
            "current": current,
            "contenders": contenders,
            "certainty": "locked" if locked else "open",
            "note": note,
        }

    if opponent_slot.startswith("最佳第三") or opponent_slot == "3rd" or (match and match.get("third_pool")):
        pool = (match or {}).get("third_pool") or []
        cands = [t for t in best_thirds if t.get("group") in pool]
        names = [f"{t.get('team')}({t.get('group')}组)" for t in cands[:5]]
        in_zone = [t for t in cands if t.get("in_best8_zone")]
        return {
            "slot": "3rd",
            "label": f"最佳第三({''.join(pool)})" if pool else "最佳第三",
            "teams": [t.get("team") for t in in_zone[:4]],
            "current": " / ".join(names[:3]) if names else "—",
            "contenders": [t.get("team") for t in cands],
            "certainty": "pool",
            "note": "小组赛结束后按 FIFA 表锁定具体对阵；当前为签位池内候选。",
        }

    return {"slot": opponent_slot, "label": opponent_slot, "teams": [], "note": "—"}


def likely_r32_opponents_for_team(
    team: str,
    group: str,
    *,
    assumed_rank: int | None = None,
    all_standings: dict[str, list[dict]] | None = None,
    best_thirds: list[dict] | None = None,
    fixtures: list[dict] | None = None,
) -> dict[str, Any]:
    all_standings = all_standings or {}
    table = all_standings.get(group) or []
    grp_fx = [f for f in (fixtures or []) if f.get("group") == group]
    best_thirds = best_thirds or rank_best_third_places(all_standings)
    race = analyze_team_race(team, table, best_thirds=best_thirds, fixtures=grp_fx or None)

    rank = assumed_rank
    if rank is None:
        if race.get("locked_first"):
            rank = 1
        elif race.get("locked_top2") and 2 in (race.get("possible_ranks") or []):
            rank = 2
        else:
            rank = race.get("rank") or 1

    path = path_for_rank(group, rank)
    bracket = _load_bracket()
    opponents: list[dict[str, Any]] = []

    if path.get("r32_matches"):
        for pool in path.get("r32_matches") or []:
            m = next((x for x in (bracket.get("r32") or []) if x.get("match") == pool.get("match")), {})
            opp_slot = pool.get("opponent") or "3rd"
            opponents.append(resolve_opponent_slot(
                str(opp_slot), match=m, all_standings=all_standings,
                best_thirds=best_thirds, fixtures=fixtures,
            ))
    else:
        m = next((x for x in (bracket.get("r32") or []) if x.get("match") == path.get("r32_match")), {})
        opp_slot = path.get("r32_opponent_slot") or _opponent_slot_for_fixed_match(slot_label(group, rank), m)
        opponents.append(resolve_opponent_slot(
            str(opp_slot), match=m, all_standings=all_standings,
            best_thirds=best_thirds, fixtures=fixtures,
        ))

    lines = []
    for o in opponents:
        if o.get("certainty") == "locked" and o.get("current"):
            lines.append(f"32强大概率对阵 {o['current']}（{o['label']}）")
        elif o.get("teams"):
            lines.append(f"32强可能对阵 {' / '.join(o['teams'][:3])}（{o['label']}）")
        else:
            lines.append(o.get("note") or "—")

    return {
        "team": team,
        "group": group,
        "assumed_rank": rank,
        "assumed_rank_cn": path.get("rank_cn") or f"小组第{rank}",
        "path": path,
        "opponents": opponents,
        "summary": " · ".join(lines),
        "race": race,
    }


def build_group_race_context(
    group: str,
    standings: dict[str, list[dict]] | None = None,
    *,
    round_num: int = 3,
    fixtures: list[dict] | None = None,
) -> dict[str, Any]:
    standings = standings or {}
    table = standings.get(group) or []
    grp_fx = [f for f in (fixtures or []) if f.get("group") == group]
    best_thirds = rank_best_third_places(standings)
    chaos = analyze_group_chaos(table, round_num=round_num, fixtures=grp_fx or None)
    teams = [
        analyze_team_race(
            r["team"], table, best_thirds=best_thirds, fixtures=grp_fx or None,
        )
        for r in rank_group_table(table, grp_fx or None)
    ]
    locked_first = [t for t in teams if t.get("locked_first")]
    previews = []
    for t in locked_first:
        previews.append(likely_r32_opponents_for_team(
            t["team"], group, assumed_rank=1,
            all_standings=standings, best_thirds=best_thirds, fixtures=fixtures,
        ))
    return {
        "group": group,
        "round_num": round_num,
        "chaos": chaos,
        "teams": teams,
        "locked_first_previews": previews,
    }


def enrich_knockout_paths(
    pick: dict[str, Any],
    group: str,
    all_standings: dict[str, list[dict]],
) -> dict[str, Any]:
    paths = pick.get("paths") or {}
    bracket = _load_bracket()
    best_thirds = rank_best_third_places(all_standings)
    out_paths: dict[str, Any] = {}
    for key, rank in (("first", 1), ("second", 2), ("third", 3)):
        p = dict(paths.get(key) or {})
        if rank <= 2 and p.get("r32_opponent_slot"):
            m = next((x for x in (bracket.get("r32") or []) if x.get("match") == p.get("r32_match")), {})
            opp = resolve_opponent_slot(
                str(p.get("r32_opponent_slot")),
                match=m,
                all_standings=all_standings,
                best_thirds=best_thirds,
            )
            p["likely_opponent"] = opp
            names = opp.get("teams") or ([opp.get("current")] if opp.get("current") else [])
            if names:
                p["opponent_preview"] = " / ".join(names[:3])
        elif rank == 3 and p.get("r32_matches"):
            previews = []
            for pool in (p.get("r32_matches") or [])[:2]:
                m = next((x for x in (bracket.get("r32") or []) if x.get("match") == pool.get("match")), {})
                opp = resolve_opponent_slot("3rd", match=m, all_standings=all_standings, best_thirds=best_thirds)
                previews.append(opp.get("current") or opp.get("label"))
            p["opponent_preview"] = " · ".join(x for x in previews if x)
        out_paths[key] = p
    pick["paths"] = out_paths
    return pick
