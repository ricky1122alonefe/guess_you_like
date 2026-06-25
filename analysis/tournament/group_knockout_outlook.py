"""Live group-stage knockout outlook — standings, race, R32 paths, best-third board."""

from __future__ import annotations

from typing import Any

from analysis.tournament.group_race import (
    analyze_group_chaos,
    analyze_team_race,
    build_group_race_context,
    likely_r32_opponents_for_team,
)
from analysis.tournament.group_stage import fetch_live_snapshot, rank_best_third_places
from analysis.tournament.group_tiebreak import rank_group_table
from analysis.tournament.knockout import path_for_rank
from analysis.tournament.wc2026_tournament_rules import (
    tournament_rules_document,
    tournament_rules_system_prompt,
)
from time_utils import now_beijing_str


def _group_is_complete(fixtures: list[dict], group: str) -> bool:
    gfx = [f for f in fixtures if f.get("group") == group]
    return bool(gfx) and all(f.get("is_finished") for f in gfx)


def _rank_scenarios_for_team(
    team: str,
    group: str,
    *,
    standings: dict[str, list[dict]],
    fixtures: list[dict],
    best_thirds: list[dict],
    achievable: list[int],
) -> list[dict[str, Any]]:
    scenarios: list[dict[str, Any]] = []
    for rank in sorted(set(achievable)):
        if rank not in (1, 2, 3):
            continue
        path = path_for_rank(group, rank)
        preview = likely_r32_opponents_for_team(
            team,
            group,
            assumed_rank=rank,
            all_standings=standings,
            best_thirds=best_thirds,
            fixtures=fixtures,
        )
        scenarios.append({
            "rank": rank,
            "rank_cn": path.get("rank_cn") or f"小组第{rank}",
            "r32_summary": preview.get("summary") or path.get("r32_summary") or "—",
            "path": {
                "slot": path.get("slot"),
                "r32_match": path.get("r32_match"),
                "r32_label": path.get("r32_label"),
                "r32_opponent_slot": path.get("r32_opponent_slot"),
                "r16_hint": path.get("r16_hint"),
                "r32_matches": path.get("r32_matches"),
                "narrow_note": path.get("narrow_note"),
            },
            "opponents": preview.get("opponents") or [],
        })
    return scenarios


def build_group_outlook(
    group: str,
    *,
    standings: dict[str, list[dict]],
    fixtures: list[dict],
    best_thirds: list[dict],
    round_num: int = 3,
) -> dict[str, Any]:
    table = standings.get(group) or []
    grp_fx = [f for f in fixtures if f.get("group") == group]
    race_ctx = build_group_race_context(
        group, standings, round_num=round_num, fixtures=grp_fx or None,
    )
    teams_out: list[dict[str, Any]] = []

    for row in rank_group_table(table, grp_fx or None):
        team = row.get("team") or ""
        race = analyze_team_race(
            team, table, best_thirds=best_thirds, fixtures=grp_fx or None,
        )
        achievable = race.get("achievable_ranks") or race.get("possible_ranks") or []
        locked = bool(race.get("locked_first") or race.get("locked_top2"))
        scenarios = _rank_scenarios_for_team(
            team, group,
            standings=standings, fixtures=fixtures,
            best_thirds=best_thirds, achievable=achievable,
        )
        primary = likely_r32_opponents_for_team(
            team, group,
            all_standings=standings, best_thirds=best_thirds, fixtures=fixtures,
        )
        teams_out.append({
            **race,
            "qualification_locked": locked,
            "qualification_note": (
                "末轮输赢与是否出线无关，主要影响轮换与 32 强签位"
                if locked else ""
            ),
            "rank_scenarios": scenarios,
            "primary_r32": {
                "summary": primary.get("summary") or "—",
                "assumed_rank": primary.get("assumed_rank"),
                "path": primary.get("path"),
            },
        })

    remaining_r3 = [
        f for f in grp_fx
        if int(f.get("round") or 0) == round_num and not f.get("is_finished")
    ]
    return {
        "group": group,
        "group_complete": _group_is_complete(fixtures, group),
        "played_rounds": max((int(r.get("played") or 0) for r in table), default=0),
        "remaining_r3": len(remaining_r3),
        "chaos": race_ctx.get("chaos") or {},
        "locked_first_previews": race_ctx.get("locked_first_previews") or [],
        "teams": teams_out,
        "table": rank_group_table(table, grp_fx or None),
    }


def build_best_third_board(best_thirds: list[dict]) -> dict[str, Any]:
    in_zone = [t for t in best_thirds if t.get("in_best8_zone")]
    cutoff_pts = in_zone[-1]["points"] if len(in_zone) >= 8 else None
    cutoff_gd = in_zone[-1]["gd"] if len(in_zone) >= 8 else None
    rows = []
    for t in best_thirds:
        rows.append({
            "third_rank": t.get("third_rank"),
            "group": t.get("group"),
            "team": t.get("team"),
            "points": t.get("points"),
            "gd": t.get("gd"),
            "gf": t.get("gf"),
            "in_best8_zone": t.get("in_best8_zone"),
            "status_cn": "进32强区" if t.get("in_best8_zone") else "出局区",
        })
    return {
        "cutoff_points": cutoff_pts,
        "cutoff_gd": cutoff_gd,
        "in_zone_count": len(in_zone),
        "rows": rows,
    }


def build_group_knockout_outlook_report(
    *,
    force_refresh: bool = False,
    groups: list[str] | None = None,
    round_num: int = 3,
) -> dict[str, Any]:
    snap = fetch_live_snapshot(force=force_refresh)
    if not snap.get("ok"):
        return {"ok": False, "error": snap.get("error") or "无法加载积分榜"}

    standings = snap.get("standings") or {}
    fixtures = snap.get("fixtures") or []
    best_thirds = rank_best_third_places(standings, fixtures=fixtures)
    best_board = build_best_third_board(best_thirds)

    target = groups or list("ABCDEFGHIJKL")
    groups_out = [
        build_group_outlook(
            g, standings=standings, fixtures=fixtures,
            best_thirds=best_thirds, round_num=round_num,
        )
        for g in target if standings.get(g)
    ]
    completed = [g["group"] for g in groups_out if g.get("group_complete")]
    pending = [g["group"] for g in groups_out if not g.get("group_complete")]

    locked_teams = [
        {"group": g["group"], "team": t["team"], "status_cn": t.get("status_cn")}
        for g in groups_out for t in (g.get("teams") or [])
        if t.get("qualification_locked")
    ]
    must_win = [
        {"group": g["group"], "team": t["team"], "note": t.get("note")}
        for g in groups_out for t in (g.get("teams") or [])
        if t.get("status") == "must_win"
    ]

    return {
        "ok": True,
        "updated_at": now_beijing_str(),
        "round_summary": snap.get("round_summary") or {},
        "advance_rule_cn": (snap.get("format") or {}).get("advance_rule_cn"),
        "groups_completed": completed,
        "groups_pending": pending,
        "completed_count": len(completed),
        "pending_count": len(pending),
        "best_third_live": best_board,
        "highlights": {
            "locked_qualification": locked_teams,
            "must_win": must_win[:12],
        },
        "groups": groups_out,
        "rules": tournament_rules_document(),
        "rules_prompt": tournament_rules_system_prompt(compact=True),
    }


def outlook_for_match(
    match_name: str,
    *,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Compact outlook for one match's group — used in AI context."""
    from analysis.tournament.group_stage import analyze_fixture_motivation, team_group_from_name

    snap = fetch_live_snapshot(force=force_refresh)
    if not snap.get("ok"):
        return {"ok": False}

    group = team_group_from_name(match_name)
    if not group:
        return {"ok": False, "error": "未识别小组"}

    report = build_group_knockout_outlook_report(
        force_refresh=False,
        groups=[group],
    )
    grp = (report.get("groups") or [None])[0]
    if not grp:
        return {"ok": False}

    home, _, away = match_name.partition("VS") if "VS" in match_name else (match_name, "", "")
    if not away and "vs" in match_name:
        home, _, away = match_name.partition("vs")
    home, away = home.strip(), away.strip()

    standings = snap.get("standings") or {}
    fixtures = snap.get("fixtures") or []
    best_thirds = rank_best_third_places(standings, fixtures=fixtures)
    mot = analyze_fixture_motivation(
        home=home, away=away, group=group,
        standings=standings, round_num=3, best_thirds=best_thirds,
    )

    return {
        "ok": True,
        "group": group,
        "group_outlook": grp,
        "best_third_live": report.get("best_third_live"),
        "match_motivation": {
            "match_type_cn": mot.get("match_type_cn"),
            "likely_direction_cn": mot.get("likely_direction_cn"),
            "reasoning": (mot.get("reasoning") or [])[:3],
        },
        "rules_prompt_compact": report.get("rules_prompt"),
    }


def compose_outlook_narrative(group_payload: dict[str, Any]) -> str:
    """Human-readable group outlook for copy / UI."""
    g = group_payload.get("group") or "?"
    lines = [f"【{g}组 · 出线与32强签位 outlook】", ""]
    if group_payload.get("group_complete"):
        lines.append("本组小组赛已全部结束，32强签位已锁定（含 Annex C 第三对位）。")
    else:
        lines.append(
            f"本组尚有 {group_payload.get('remaining_r3', 0)} 场末轮未踢；"
            f"第三对位在全部 72 场结束后按 FIFA 表锁定。"
        )
    lines.append("")
    for t in group_payload.get("teams") or []:
        lines.append(
            f"· {t.get('team')} 第{t.get('rank')} {t.get('points')}分 "
            f"→ {t.get('status_cn')}。"
            f"{(' ' + t.get('qualification_note')) if t.get('qualification_note') else ''}"
        )
        if t.get("primary_r32", {}).get("summary"):
            lines.append(f"  32强：{t['primary_r32']['summary']}")
        for sc in t.get("rank_scenarios") or []:
            if len(t.get("rank_scenarios") or []) <= 1:
                break
            lines.append(f"  若第{sc.get('rank')}：{sc.get('r32_summary')}")
    return "\n".join(lines)
