"""Compare user-submitted final-round 1X2 picks with AI and rule-engine outlook."""

from __future__ import annotations

import copy
import re
from typing import Any

from analysis.tournament.group_final_copy import collect_match_ai_brief
from analysis.tournament.group_race import build_group_race_context
from analysis.tournament.group_stage import (
    analyze_fixture_motivation,
    fetch_live_snapshot,
    rank_best_third_places,
)
from analysis.tournament.group_tiebreak import build_rows_from_fixtures, rank_group_table
from share_card import NO_JINGCAI
from time_utils import now_beijing_str
from user_final_picks import (
    OUTCOME_CN,
    finalize_user_picks,
    list_locked_picks,
    pick_key_from_cn,
    pick_to_representative_score,
)

VALID_PICKS = frozenset({"home", "draw", "away"})


def outcome_from_scores(home_score: int, away_score: int) -> str:
    if home_score > away_score:
        return "home"
    if home_score < away_score:
        return "away"
    return "draw"


def _normalize_user_entry(item: dict[str, Any]) -> dict[str, Any] | None:
    """Accept 胜平负 pick or legacy home_score/away_score."""
    if not isinstance(item, dict):
        return None
    pick = str(item.get("pick") or item.get("outcome") or "").strip().lower()
    if pick not in VALID_PICKS:
        pick = pick_key_from_cn(str(item.get("pick_cn") or ""))
    if pick in VALID_PICKS:
        out: dict[str, Any] = {"pick": pick}
        fid = str(item.get("fixture_id") or "").strip()
        if fid:
            out["fixture_id"] = fid
        group = str(item.get("group") or "").strip().upper()
        home = str(item.get("home") or "").strip()
        away = str(item.get("away") or "").strip()
        if len(group) == 1 and home and away:
            out["group"] = group
            out["home"] = home
            out["away"] = away
        if out.get("fixture_id") or (out.get("group") and out.get("home") and out.get("away")):
            hg, ag = pick_to_representative_score(pick)
            out["home_score"] = hg
            out["away_score"] = ag
            return out
        return None
    try:
        hs = int(item.get("home_score"))
        ag = int(item.get("away_score"))
    except (TypeError, ValueError):
        return None
    if hs < 0 or ag < 0:
        return None
    out = {"home_score": hs, "away_score": ag, "pick": outcome_from_scores(hs, ag)}
    fid = str(item.get("fixture_id") or "").strip()
    if fid:
        out["fixture_id"] = fid
        return out
    group = str(item.get("group") or "").strip().upper()
    home = str(item.get("home") or "").strip()
    away = str(item.get("away") or "").strip()
    if len(group) == 1 and home and away:
        out["group"] = group
        out["home"] = home
        out["away"] = away
        return out
    return None


def _normalize_user_result(item: dict[str, Any]) -> dict[str, Any] | None:
    return _normalize_user_entry(item)


def rule_aligns_with_outcome(direction_cn: str, outcome: str) -> bool | None:
    direction = direction_cn or ""
    if not direction or direction in ("—", "按实力与盘口"):
        return None
    if outcome == "draw":
        return "平局" in direction
    if outcome in ("home", "away"):
        if "分胜负" in direction or "抢三分" in direction:
            return True
        if direction.strip() == "平局":
            return False
        if "平局" in direction and "或" not in direction:
            return False
        if "小比分" in direction or "或" in direction:
            return True
    return None


def _sort_table(table: list[dict]) -> list[dict]:
    return sorted(
        table,
        key=lambda x: (-int(x.get("points") or 0), -int(x.get("gd") or 0), -int(x.get("gf") or 0), x.get("team") or ""),
    )


def _standings_line(table: list[dict]) -> str:
    if not table:
        return "暂无积分榜"
    parts = []
    for i, r in enumerate(_sort_table(table), start=1):
        parts.append(f"{i}.{r.get('team')} {r.get('points')}分 净{r.get('gd', 0):+d}")
    return " · ".join(parts)


def _result_lookup(user_results: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    by_id: dict[str, tuple[int, int, str]] = {}
    by_match: dict[tuple[str, str, str], tuple[int, int, str]] = {}
    errors: list[str] = []
    for raw in user_results:
        norm = _normalize_user_entry(raw)
        if not norm:
            errors.append(f"无效选项：{raw!r}")
            continue
        score = (norm["home_score"], norm["away_score"], norm["pick"])
        if norm.get("fixture_id"):
            by_id[norm["fixture_id"]] = score
        else:
            by_match[(norm["group"], norm["home"], norm["away"])] = score
    return {"by_id": by_id, "by_match": by_match}, errors


def _lookup_entry(
    fx: dict[str, Any],
    lookup: dict[str, Any],
) -> tuple[int, int, str] | None:
    fid = str(fx.get("fixture_id") or "").strip()
    if fid and fid in lookup["by_id"]:
        return lookup["by_id"][fid]
    key = (str(fx.get("group") or "").upper(), fx.get("home") or "", fx.get("away") or "")
    return lookup["by_match"].get(key)


def apply_user_results_to_fixtures(
    fixtures: list[dict[str, Any]],
    user_results: list[dict[str, Any]],
    *,
    round_num: int = 3,
) -> tuple[list[dict[str, Any]], list[str]]:
    lookup, errors = _result_lookup(user_results)
    out: list[dict[str, Any]] = []
    for fx in fixtures:
        fx2 = copy.deepcopy(fx)
        if int(fx2.get("round") or 0) != round_num or fx2.get("is_finished"):
            out.append(fx2)
            continue
        score = _lookup_entry(fx2, lookup)
        if score is None:
            out.append(fx2)
            continue
        hg, ag, _pick = score
        fx2["home_score"] = hg
        fx2["away_score"] = ag
        fx2["is_finished"] = True
        out.append(fx2)
    return out, errors


def build_scenario_standings(
    standings: dict[str, list[dict]],
    fixtures: list[dict[str, Any]],
) -> dict[str, list[dict]]:
    out = copy.deepcopy(standings)
    groups = {str(fx.get("group") or "").upper() for fx in fixtures if fx.get("group")}
    for group in groups:
        teams = [r.get("team") for r in (standings.get(group) or []) if r.get("team")]
        if not teams:
            continue
        group_fx = [f for f in fixtures if f.get("group") == group]
        rows = build_rows_from_fixtures(teams, group_fx)
        out[group] = rank_group_table(list(rows.values()), group_fx)
    return out


def _team_status_map(race_ctx: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {t.get("team"): t for t in (race_ctx.get("teams") or []) if t.get("team")}


def _compare_match(
    fx: dict[str, Any],
    *,
    user_score: tuple[int, int],
    user_outcome: str,
    brief: dict[str, Any],
    motivation: dict[str, Any],
) -> dict[str, Any]:
    hg, ag = user_score
    ai_pick = brief.get("jingcai_pick") or "—"
    ai_key = pick_key_from_cn(ai_pick)
    ai_agrees = ai_key not in ("", "skip") and ai_key == user_outcome
    direction = motivation.get("likely_direction_cn") or ""
    rule_align = rule_aligns_with_outcome(direction, user_outcome)

    verdict_parts: list[str] = []
    if ai_key in ("", "skip"):
        verdict_parts.append("AI暂无倾向")
    elif ai_agrees:
        verdict_parts.append("与AI一致")
    else:
        verdict_parts.append("与AI不同")

    if rule_align is True:
        verdict_parts.append("符合规则战意")
    elif rule_align is False:
        verdict_parts.append("与规则倾向相悖")
    else:
        verdict_parts.append("规则倾向中性")

    return {
        "fixture_id": fx.get("fixture_id"),
        "match_name": fx.get("match_name") or f"{fx.get('home')}VS{fx.get('away')}",
        "home": fx.get("home"),
        "away": fx.get("away"),
        "kickoff": fx.get("kickoff") or "",
        "user_score": f"{hg}-{ag}",
        "user_pick": user_outcome,
        "user_outcome": user_outcome,
        "user_outcome_cn": OUTCOME_CN[user_outcome],
        "user_pick_cn": OUTCOME_CN[user_outcome],
        "ai_pick": ai_pick,
        "ai_pick_key": ai_key,
        "ai_agrees": ai_agrees if ai_key not in ("", "skip") else None,
        "has_user_ai": bool(brief.get("has_user_ai")),
        "rule_motivation_cn": motivation.get("match_type_cn") or "",
        "rule_direction_cn": direction,
        "rule_aligns": rule_align,
        "verdict_cn": " · ".join(verdict_parts),
    }


def _team_changes(
    before_ctx: dict[str, Any],
    after_ctx: dict[str, Any],
) -> list[dict[str, Any]]:
    before = _team_status_map(before_ctx)
    after = _team_status_map(after_ctx)
    changes: list[dict[str, Any]] = []
    for team, aft in after.items():
        bef = before.get(team) or {}
        if (
            bef.get("status_cn") == aft.get("status_cn")
            and bef.get("rank") == aft.get("rank")
        ):
            continue
        changes.append({
            "team": team,
            "before_rank": bef.get("rank"),
            "after_rank": aft.get("rank"),
            "before_status_cn": bef.get("status_cn") or "—",
            "after_status_cn": aft.get("status_cn") or "—",
        })
    return changes


def compose_group_compare_narrative(group_payload: dict[str, Any]) -> str:
    lines = [f"【{group_payload.get('group')}组 · 你的设想 vs AI vs 规则】", ""]
    score_bits = [
        f"{m.get('match_name')} {m.get('user_pick_cn') or m.get('user_outcome_cn')}"
        for m in group_payload.get("matches") or []
    ]
    if score_bits:
        lines.append("你的定稿选项：" + " · ".join(score_bits))
    lines.append(
        f"积分榜：{group_payload.get('standings_line_before')} → {group_payload.get('standings_line_after')}"
    )
    lines.append("")
    lines.append("单场比对：")
    for m in group_payload.get("matches") or []:
        ai_txt = m.get("ai_pick") if m.get("ai_pick") not in ("—", "", NO_JINGCAI) else "—"
        ai_mark = ""
        if m.get("ai_agrees") is True:
            ai_mark = " ✓"
        elif m.get("ai_agrees") is False:
            ai_mark = " ✗"
        rule_mark = ""
        if m.get("rule_aligns") is True:
            rule_mark = " ✓"
        elif m.get("rule_aligns") is False:
            rule_mark = " ✗"
        lines.append(
            f"▸ {m.get('match_name')} 你：{m.get('user_pick_cn') or m.get('user_outcome_cn')} | "
            f"AI：{ai_txt}{ai_mark} | 规则：{m.get('rule_motivation_cn')}·{m.get('rule_direction_cn')}{rule_mark}"
        )
    changes = group_payload.get("team_changes") or []
    if changes:
        lines.append("")
        lines.append("出线状态变化：")
        for ch in changes:
            lines.append(
                f"· {ch.get('team')}：第{ch.get('before_rank')}→第{ch.get('after_rank')} · "
                f"{ch.get('before_status_cn')} → {ch.get('after_status_cn')}"
            )
    stats = group_payload.get("stats") or {}
    lines.append("")
    lines.append(
        f"小结：{stats.get('match_count', 0)} 场已填 · "
        f"与AI一致 {stats.get('ai_agree', 0)} · 与AI不同 {stats.get('ai_disagree', 0)} · "
        f"AI未跑 {stats.get('ai_no_pick', 0)} · 符合规则战意 {stats.get('rule_align', 0)}"
    )
    return "\n".join(lines)


def compare_group_scenario(
    output_root,
    group: str,
    *,
    standings: dict[str, list[dict]],
    fixtures: list[dict[str, Any]],
    scenario_fixtures: list[dict[str, Any]],
    scenario_standings: dict[str, list[dict]],
    user_results: list[dict[str, Any]] | None = None,
    round_num: int = 3,
    user_ai_only: bool = True,
) -> dict[str, Any]:
    table_before = standings.get(group) or []
    table_after = scenario_standings.get(group) or []
    group_fx = [f for f in fixtures if f.get("group") == group]
    scenario_group_fx = [f for f in scenario_fixtures if f.get("group") == group]
    best_thirds = rank_best_third_places(standings, fixtures=fixtures)

    before_ctx = build_group_race_context(
        group, standings, round_num=round_num, fixtures=group_fx or None,
    )
    after_ctx = build_group_race_context(
        group, scenario_standings, round_num=round_num, fixtures=scenario_group_fx or None,
    )

    r3_fixtures = [
        f for f in group_fx
        if int(f.get("round") or 0) == round_num and not f.get("is_finished")
    ]
    r3_fixtures.sort(key=lambda x: x.get("kickoff") or "")
    lookup, _ = _result_lookup(user_results or [])

    matches_out: list[dict[str, Any]] = []
    ai_agree = ai_disagree = ai_no_pick = rule_align = 0
    for fx in r3_fixtures:
        scenario_fx = next(
            (
                s for s in scenario_group_fx
                if s.get("home") == fx.get("home") and s.get("away") == fx.get("away")
            ),
            None,
        )
        if not scenario_fx or not scenario_fx.get("is_finished"):
            continue
        entry = _lookup_entry(fx, lookup)
        if entry:
            hg, ag, user_outcome = entry
        else:
            hg, ag = int(scenario_fx["home_score"]), int(scenario_fx["away_score"])
            user_outcome = outcome_from_scores(hg, ag)
        mot = analyze_fixture_motivation(
            home=fx.get("home") or "",
            away=fx.get("away") or "",
            group=group,
            standings=standings,
            round_num=round_num,
            best_thirds=best_thirds,
        )
        brief = collect_match_ai_brief(
            output_root, fx, motivation=mot, user_ai_only=user_ai_only,
        )
        cmp = _compare_match(
            fx,
            user_score=(hg, ag),
            user_outcome=user_outcome,
            brief=brief,
            motivation=mot,
        )
        matches_out.append(cmp)
        if cmp.get("ai_agrees") is True:
            ai_agree += 1
        elif cmp.get("ai_agrees") is False:
            ai_disagree += 1
        else:
            ai_no_pick += 1
        if cmp.get("rule_aligns") is True:
            rule_align += 1

    stats = {
        "match_count": len(matches_out),
        "ai_agree": ai_agree,
        "ai_disagree": ai_disagree,
        "ai_no_pick": ai_no_pick,
        "rule_align": rule_align,
    }
    payload = {
        "group": group,
        "standings_before": table_before,
        "standings_after": table_after,
        "standings_line_before": _standings_line(table_before),
        "standings_line_after": _standings_line(table_after),
        "team_changes": _team_changes(before_ctx, after_ctx),
        "race_before": before_ctx,
        "race_after": after_ctx,
        "matches": matches_out,
        "stats": stats,
    }
    payload["narrative"] = compose_group_compare_narrative(payload)
    return payload


def _parse_groups(raw: str | list[str] | None) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        parts = re.split(r"[,，\s]+", raw.upper())
    else:
        parts = [str(x).upper() for x in raw]
    valid: list[str] = []
    for p in parts:
        p = p.strip()
        if len(p) == 1 and p in "ABCDEFGHIJKL" and p not in valid:
            valid.append(p)
    return valid


def build_scenario_compare_report(
    output_root,
    *,
    user_results: list[dict[str, Any]] | None = None,
    picks: list[dict[str, Any]] | None = None,
    groups: list[str] | None = None,
    round_num: int = 3,
    force_refresh: bool = False,
    user_ai_only: bool = True,
    finalize: bool = False,
) -> dict[str, Any]:
    entries = list(user_results or picks or [])
    snap = fetch_live_snapshot(force=force_refresh)
    if not snap.get("ok"):
        return {"ok": False, "error": snap.get("error") or "无法加载积分榜"}

    fixtures = snap.get("fixtures") or []
    standings = snap.get("standings") or {}
    selected = _parse_groups(groups) if groups else []

    scenario_fixtures, parse_errors = apply_user_results_to_fixtures(
        fixtures, entries, round_num=round_num,
    )
    if not entries:
        return {"ok": False, "error": "请至少提交一场末轮胜平负", "parse_errors": parse_errors}

    affected_groups: set[str] = set()
    lookup, _ = _result_lookup(entries)
    for fx in fixtures:
        if int(fx.get("round") or 0) != round_num or fx.get("is_finished"):
            continue
        if _lookup_entry(fx, lookup) is not None:
            affected_groups.add(str(fx.get("group") or "").upper())

    if not affected_groups:
        return {
            "ok": False,
            "error": "未匹配到任何末轮场次，请检查 fixture_id 或主客队名称",
            "parse_errors": parse_errors,
        }

    target_groups = [g for g in selected if g in affected_groups] if selected else sorted(affected_groups)
    if not target_groups:
        target_groups = sorted(affected_groups)

    scenario_standings = build_scenario_standings(standings, scenario_fixtures)
    groups_out = [
        compare_group_scenario(
            output_root,
            group,
            standings=standings,
            fixtures=fixtures,
            scenario_fixtures=scenario_fixtures,
            scenario_standings=scenario_standings,
            user_results=entries,
            round_num=round_num,
            user_ai_only=user_ai_only,
        )
        for group in target_groups
    ]

    finalize_result = None
    if finalize and groups_out:
        finalize_result = finalize_user_picks(
            output_root,
            entries,
            compare={"groups": groups_out},
        )
        if not finalize_result.get("ok"):
            return {
                "ok": False,
                "error": finalize_result.get("error") or "定稿失败",
                "errors": finalize_result.get("errors") or [],
                "groups": groups_out,
            }

    total_matches = sum(g["stats"]["match_count"] for g in groups_out)
    total_ai_agree = sum(g["stats"]["ai_agree"] for g in groups_out)
    total_ai_disagree = sum(g["stats"]["ai_disagree"] for g in groups_out)
    total_rule_align = sum(g["stats"]["rule_align"] for g in groups_out)

    summary_lines = [
        f"共比对 {len(groups_out)} 个小组、{total_matches} 场末轮定稿。",
        f"与 AI 一致 {total_ai_agree} 场，不同 {total_ai_disagree} 场。",
        f"符合规则战意倾向 {total_rule_align} 场。",
    ]
    if finalize_result:
        summary_lines.insert(0, f"已锁定 {finalize_result.get('locked_count', 0)} 场，定稿后不可修改。")
    if parse_errors:
        summary_lines.append(f"解析警告 {len(parse_errors)} 条。")

    return {
        "ok": True,
        "updated_at": now_beijing_str(),
        "round_num": round_num,
        "selected_groups": target_groups,
        "summary": " ".join(summary_lines),
        "stats": {
            "group_count": len(groups_out),
            "match_count": total_matches,
            "ai_agree": total_ai_agree,
            "ai_disagree": total_ai_disagree,
            "rule_align": total_rule_align,
        },
        "groups": groups_out,
        "parse_errors": parse_errors,
        "finalize": finalize_result,
        "advance_rule_cn": (snap.get("format") or {}).get("advance_rule_cn"),
    }


def build_locked_picks_review(
    output_root,
    *,
    force_refresh: bool = False,
    user_ai_only: bool = True,
) -> dict[str, Any]:
    """Re-run compare for all locked picks (for page load / review)."""
    locked = list_locked_picks(output_root)
    if not locked:
        return {"ok": True, "locked_count": 0, "groups": [], "summary": "暂无定稿场次"}
    entries = [
        {
            "fixture_id": p.get("fixture_id"),
            "group": p.get("group"),
            "home": p.get("home"),
            "away": p.get("away"),
            "pick": p.get("pick"),
        }
        for p in locked
    ]
    groups = sorted({str(p.get("group") or "").upper() for p in locked if p.get("group")})
    report = build_scenario_compare_report(
        output_root,
        picks=entries,
        groups=groups or None,
        force_refresh=force_refresh,
        user_ai_only=user_ai_only,
        finalize=False,
    )
    report["locked_count"] = len(locked)
    report["locked_picks"] = locked
    return report
