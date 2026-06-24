"""2026 World Cup group-stage motivation model (R2/R3 默契球 vs 拼命球)."""

from __future__ import annotations

import json
import logging
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from share_card import split_teams

log = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

GROUPS_PATH = _PROJECT_ROOT / "data" / "wc2026_groups.json"
_CACHE: dict[str, Any] = {"ts": 0.0, "data": None}
_CACHE_TTL = 300

MATCH_TYPES = {
    "must_win": "拼命球",
    "draw_friendly": "守平局",
    "collusion_watch": "默契球观察",
    "gd_race": "净胜球战",
    "conservative_favorite": "控节奏",
    "open_race": "开放混战",
    "dead_rubber": "出线已定",
    "normal": "常规战意",
}


def _load_config() -> dict[str, Any]:
    if not GROUPS_PATH.is_file():
        return {}
    return json.loads(GROUPS_PATH.read_text(encoding="utf-8"))


def _team_maps() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    data = _load_config()
    team_to_group: dict[str, str] = {}
    tiers: dict[str, str] = {}
    for group, teams in (data.get("groups") or {}).items():
        for t in teams:
            team_to_group[t] = group
    tiers.update(data.get("team_strength_tiers") or {})
    alias_to_cn: dict[str, str] = {}
    for cn, aliases in (data.get("aliases") or {}).items():
        alias_to_cn[cn] = cn
        for a in aliases:
            alias_to_cn[a] = cn
    return team_to_group, tiers, alias_to_cn


def _normalize(name: str) -> str:
    from wc_standings_fetch import normalize_team
    _, _, alias = _team_maps()
    s = normalize_team(name)
    return alias.get(s, s)


def _standing_row_to_dict(row) -> dict[str, Any]:
    return {
        "team": row.team,
        "played": row.played,
        "won": row.won,
        "drawn": row.drawn,
        "lost": row.lost,
        "gf": row.gf,
        "ga": row.ga,
        "gd": row.gd,
        "points": row.points,
        "rank": row.rank,
        "form": getattr(row, "form", ""),
    }


def fetch_live_snapshot(*, force: bool = False) -> dict[str, Any]:
    """Standings + fixtures from 500.com with short TTL cache."""
    now = time.time()
    if not force and _CACHE["data"] and now - _CACHE["ts"] < _CACHE_TTL:
        return _CACHE["data"]

    from wc_standings_fetch import fetch_all_group_fixtures, fetch_group_standings

    try:
        standings_raw = fetch_group_standings()
        fixtures = fetch_all_group_fixtures()
    except Exception as exc:
        log.warning("拉取小组积分榜失败: %s", exc)
        if _CACHE["data"]:
            return _CACHE["data"]
        return {"ok": False, "error": str(exc), "standings": {}, "fixtures": []}

    standings = {
        g: [_standing_row_to_dict(r) for r in rows]
        for g, rows in standings_raw.items()
    }
    fx_list = []
    for f in fixtures:
        fx_list.append({
            "fixture_id": f.fixture_id,
            "group": f.group,
            "round": f.round,
            "kickoff": f.kickoff,
            "home": f.home,
            "away": f.away,
            "home_score": f.home_score,
            "away_score": f.away_score,
            "status": f.status,
            "is_finished": f.is_finished,
            "match_name": f.match_name,
            "eu_home": f.eu_home,
            "eu_draw": f.eu_draw,
            "eu_away": f.eu_away,
        })

    r1_total = sum(1 for x in fx_list if x["round"] == 1)
    r1_done = sum(1 for x in fx_list if x["round"] == 1 and x["is_finished"])
    r2_total = sum(1 for x in fx_list if x["round"] == 2)
    r2_done = sum(1 for x in fx_list if x["round"] == 2 and x["is_finished"])

    data = {
        "ok": True,
        "standings": standings,
        "fixtures": fx_list,
        "round_summary": {
            "r1_finished": r1_done,
            "r1_total": r1_total,
            "r2_finished": r2_done,
            "r2_total": r2_total,
            "stage_label": _stage_label(r1_done, r1_total, r2_done, r2_total),
        },
        "format": (_load_config().get("format") or {}),
    }
    _CACHE["ts"] = now
    _CACHE["data"] = data
    return data


def _stage_label(r1_done: int, r1_total: int, r2_done: int, r2_total: int) -> str:
    if r1_done < r1_total:
        return f"第一轮尾声（{r1_done}/{r1_total}）"
    if r2_done == 0:
        return "第二轮即将/正在进行"
    if r2_done < r2_total:
        return f"第二轮进行中（{r2_done}/{r2_total}）"
    return "第三轮/末轮阶段"


def best_third_cutoff_points(best_thirds: list[dict] | None) -> int:
    """Points of the 8th-ranked group third (best-third qualification bar)."""
    if best_thirds and len(best_thirds) >= 8:
        return int(best_thirds[7].get("points") or 3)
    return 3


def second_place_points(table: list[dict]) -> int:
    """Current second-place points in a group table (0 if unknown)."""
    rows = [r for r in table if int(r.get("played") or 0) > 0]
    if len(rows) < 2:
        return 0
    sorted_t = sorted(
        rows,
        key=lambda x: (-int(x.get("points") or 0), -int(x.get("gd") or 0), -int(x.get("gf") or 0)),
    )
    return int(sorted_t[1].get("points") or 0)


def rank_best_third_places(
    standings: dict[str, list[dict]],
    fixtures: list[dict] | None = None,
) -> list[dict]:
    """Rank 12 group thirds for 8 best-third slots (FIFA table order when fixtures given)."""
    from analysis.tournament.group_tiebreak import rank_group_table

    thirds: list[dict] = []
    for group, table in standings.items():
        if len(table) < 3:
            continue
        grp_fx = [f for f in (fixtures or []) if f.get("group") == group]
        sorted_t = rank_group_table(table, grp_fx or None)
        row = dict(sorted_t[2])
        row["group"] = group
        thirds.append(row)
    thirds.sort(key=lambda x: (-x["points"], -x["gd"], -x["gf"]))
    for i, row in enumerate(thirds, start=1):
        row["third_rank"] = i
        row["in_best8_zone"] = i <= 8
    return thirds


def _team_situation(
    team: str,
    table: list[dict],
    *,
    round_num: int,
    best_thirds: list[dict],
) -> dict[str, Any]:
    _, tiers, _ = _team_maps()
    row = next((r for r in table if r["team"] == team), None)
    if not row:
        return {"team": team, "known": False}

    sorted_t = sorted(table, key=lambda x: (-x["points"], -x["gd"], -x["gf"], x["team"]))
    rank = next(i for i, r in enumerate(sorted_t, 1) if r["team"] == team)
    remaining = max(0, 3 - row["played"])
    tier = tiers.get(team, "mid")

    needs: list[str] = []
    top2_pts = second_place_points(table)
    bt_cut = best_third_cutoff_points(best_thirds)
    draw_pts = int(row["points"]) + 1
    decisive = round_num >= 3 or remaining <= 1
    draw_dead = decisive and top2_pts > 0 and draw_pts < top2_pts and draw_pts < bt_cut

    if row["points"] == 0 and remaining <= 2:
        needs.append("下场再丢分则出线形势极其被动，必须抢分")
    elif row["points"] == 1:
        if draw_dead:
            needs.append(
                f"末轮平局仅{draw_pts}分，无法威胁前二({top2_pts}分)，"
                f"亦难挤入最佳第三(门槛约{bt_cut}分)，必须争胜"
            )
        elif decisive and top2_pts > 0 and draw_pts < top2_pts:
            needs.append(
                f"末轮平局仅{draw_pts}分，无法威胁前二({top2_pts}分)，须全取三分才仍有出线可能"
            )
        else:
            needs.append("平局仍有战略价值，抢3分可跃升榜首")
    elif row["points"] >= 3 and rank <= 2:
        needs.append("已占晋级主动，可接受小胜/平局但需留意净胜球")
    elif rank == 3:
        bt = next((t for t in best_thirds if t["team"] == team), None)
        if bt:
            zone = "在" if bt.get("in_best8_zone") else "不在"
            needs.append(f"暂列小组第三，{zone}最佳8第三晋级区（全组第{bt['third_rank']}）")
        else:
            needs.append("争夺小组第三或前二，净胜球可能关键")
    elif rank == 4:
        if draw_dead:
            needs.append(
                f"榜末末轮须争胜：平局仅{draw_pts}分，前二({top2_pts}分)与最佳第三({bt_cut}分)均不可达"
            )
        elif decisive and top2_pts > 0 and draw_pts < top2_pts:
            needs.append(f"榜末末轮须抢3分，平局{draw_pts}分无法威胁前二({top2_pts}分)")
        else:
            needs.append("榜末抢分压力大，平局价值取决于其他队赛果")

    pressure = "low"
    if row["points"] == 0:
        pressure = "high"
    elif row["points"] == 1 and remaining >= 2:
        pressure = "medium"
    elif row["points"] >= 3 and rank <= 2:
        pressure = "medium-low"

    return {
        "team": team,
        "known": True,
        "rank": rank,
        "points": row["points"],
        "played": row["played"],
        "gd": row["gd"],
        "gf": row["gf"],
        "remaining": remaining,
        "tier": tier,
        "pressure": pressure,
        "needs": needs,
    }


def _max_points_row(row: dict) -> int:
    rem = max(0, 3 - int(row.get("played") or 0))
    return int(row.get("points") or 0) + 3 * rem


def _is_decisive_round(hs: dict, aws: dict, round_num: int) -> bool:
    return round_num >= 3 or (
        int(hs.get("remaining") or 0) <= 1 and int(aws.get("remaining") or 0) <= 1
    )


def _row_for_team(table: list[dict], team: str) -> dict | None:
    for r in table:
        if r.get("team") == team:
            return r
    return None


def _equal_points_duel_outlook(
    home: str,
    away: str,
    *,
    hp: int,
    ap: int,
    table: list[dict],
    round_num: int,
    hs: dict,
    aws: dict,
    best_thirds: list[dict] | None = None,
) -> dict[str, Any]:
    """Whether a draw actually helps both teams given live table (esp. R3)."""
    top2_pts = second_place_points(table)
    bt_cut = best_third_cutoff_points(best_thirds)
    draw_pts = hp + 1
    h_row = _row_for_team(table, home)
    a_row = _row_for_team(table, away)
    h_max = _max_points_row(h_row) if h_row else draw_pts
    a_max = _max_points_row(a_row) if a_row else draw_pts
    draw_reaches_top2 = draw_pts >= top2_pts
    win_can_threat_top2 = h_max >= top2_pts or a_max >= top2_pts
    decisive = _is_decisive_round(hs, aws, round_num)

    if decisive and not draw_reaches_top2:
        bt_clause = (
            f"亦无法进入最佳第三竞争(门槛约{bt_cut}分)，"
            if draw_pts < bt_cut
            else ""
        )
        if win_can_threat_top2:
            return {
                "kind": "must_win",
                "reason": (
                    f"{home}({hp}分) vs {away}({ap}分) 末轮直接对话："
                    f"平局仅各{draw_pts}分，低于目前第二名({top2_pts}分)，无法威胁前二；"
                    f"{bt_clause}必须争胜才仍有出线可能，守平动机弱。"
                ),
                "likely_cn": "分胜负、抢三分",
            }
        return {
            "kind": "must_win",
            "reason": (
                f"{home}({hp}分) vs {away}({ap}分) 末轮对话："
                f"平局各{draw_pts}分仍无法追平前二({top2_pts}分)，"
                f"{bt_clause}双方出线希望已极渺茫，平局无战略价值。"
            ),
            "likely_cn": "分胜负",
        }
    if hp == ap == 1:
        return {
            "kind": "draw_friendly",
            "reason": "双方均1分，平局可同时抬升积分、保留出线希望，守平动机较强。",
            "likely_cn": "平局权重上升",
        }
    return {
        "kind": "draw_friendly",
        "reason": f"双方同分({hp}分)，平局对两队都是可接受结果，守平动机较强。",
        "likely_cn": "平局或小比分",
    }


def analyze_fixture_motivation(
    *,
    home: str,
    away: str,
    group: str,
    standings: dict[str, list[dict]],
    round_num: int,
    best_thirds: list[dict] | None = None,
) -> dict[str, Any]:
    """Classify R2/R3 match: 默契球 / 拼命球 / 控节奏 etc."""
    table = standings.get(group) or []
    best_thirds = best_thirds or rank_best_third_places(standings)
    home = _normalize(home)
    away = _normalize(away)

    hs = _team_situation(home, table, round_num=round_num, best_thirds=best_thirds)
    aws = _team_situation(away, table, round_num=round_num, best_thirds=best_thirds)
    hp, ap = hs.get("points"), aws.get("points")

    match_type = "normal"
    reasoning: list[str] = []
    draw_bias = 0.0
    home_bias = 0.0
    away_bias = 0.0
    ah_hint = ""
    likely_cn = "按实力与盘口"

    points_set = {r["points"] for r in table if r.get("played")}
    if len(points_set) == 1 and 1 in points_set and all(r["played"] == 1 for r in table):
        match_type = "open_race"
        reasoning.append("本组首轮后四队同分，次轮任何平局都能保留出线希望，开放混战格局。")
        draw_bias += 0.10

    if hp is not None and ap is not None:
        if hp >= 6 and ap >= 6:
            match_type = "dead_rubber"
            reasoning.append("双方均已6分提前出线，末轮战意偏低，轮换/控节奏概率高。")
            draw_bias += 0.08
            ah_hint = "热门不穿/小比分"
        elif hp >= 3 and ap >= 3 and abs(hp - ap) <= 1 and round_num >= 2:
            match_type = "collusion_watch"
            reasoning.append(
                f"{home}({hp}分) vs {away}({ap}分)：双方已有胜场，平局可同时保住晋级主动权，默契球/守平局需重点防范。"
            )
            draw_bias += 0.14
            home_bias -= 0.04
            away_bias -= 0.04
            ah_hint = "平局分流/热门不穿"
            likely_cn = "平局或小比分"
        elif (hp == 0 and ap >= 3) or (ap == 0 and hp >= 3):
            match_type = "must_win"
            desperate = home if hp == 0 else away
            leader = away if hp == 0 else home
            reasoning.append(
                f"{desperate} 0分急需抢分（拼命球），{leader} 已3分可领先后控节奏，热门赢球不穿风险上升。"
            )
            draw_bias += 0.03
            ah_hint = "弱队拼命、强队控节奏"
            likely_cn = "领先方小胜或平局"
        elif hp == 0 and ap == 0:
            match_type = "must_win"
            reasoning.append("双方均未得分，次轮直接对话属于典型拼命球，平局对双方仍优于输球。")
            draw_bias += 0.05
            likely_cn = "分胜负但比分可能不大"
        elif hp == 1 and ap == 1 and round_num >= 2 and len(points_set) == 1 and 1 in points_set:
            match_type = "open_race"
            reasoning.append("本组仍处同分混战，次轮平局对双方都能保留出线主动权。")
            draw_bias += 0.10
            likely_cn = "平局或小比分"
        elif hp == ap and hp is not None:
            outlook = _equal_points_duel_outlook(
                home, away, hp=hp, ap=ap, table=table, round_num=round_num, hs=hs, aws=aws,
                best_thirds=best_thirds,
            )
            match_type = outlook["kind"]
            reasoning.append(outlook["reason"])
            if match_type == "draw_friendly":
                draw_bias += 0.11
            elif match_type == "must_win":
                draw_bias += 0.02
                home_bias += 0.04
                away_bias += 0.04
            likely_cn = outlook["likely_cn"]
        elif max(hp or 0, ap or 0) >= 3 and min(hp or 0, ap or 0) <= 1:
            _, tiers, _ = _team_maps()
            weak = home if (aws.get("tier") == "weak" or hp <= 1) else away
            strong = away if weak == home else home
            if tiers.get(strong) in ("elite", "strong") and tiers.get(weak) in ("weak", "mid"):
                match_type = "gd_race"
                reasoning.append(f"{strong} 对 {weak}：领先方可能抢净胜球，但领先后亦可能控节奏。")
                ah_hint = "穿盘不稳"

    if hs.get("pressure") == "high" and aws.get("pressure") != "high":
        match_type = match_type if match_type != "normal" else "must_win"
        home_bias += 0.06
    elif aws.get("pressure") == "high" and hs.get("pressure") != "high":
        match_type = match_type if match_type != "normal" else "must_win"
        away_bias += 0.06

    if hp is not None and ap is not None and hp >= 3 and ap >= 3 and match_type not in ("collusion_watch", "dead_rubber"):
        match_type = "conservative_favorite"
        reasoning.append("双方都有胜场，次轮再胜可接近锁定出线，但领先方领先后控节奏仍常见。")
        draw_bias += 0.06
        ah_hint = ah_hint or "热门谨慎追让"

    if not reasoning:
        reasoning.append("按当前积分与48队赛制，战意接近常规小组赛次轮。")

    pred_key = "draw" if draw_bias >= 0.12 else (
        "home" if home_bias > away_bias + 0.04 else (
            "away" if away_bias > home_bias + 0.04 else "none"
        )
    )

    return {
        "group": group,
        "round": round_num,
        "home": home,
        "away": away,
        "match_type": match_type,
        "match_type_cn": MATCH_TYPES.get(match_type, match_type),
        "draw_bias": round(draw_bias, 4),
        "home_bias": round(home_bias, 4),
        "away_bias": round(away_bias, 4),
        "likely_direction_cn": likely_cn,
        "model_pick_hint": pred_key,
        "ah_hint": ah_hint,
        "reasoning": reasoning,
        "home_situation": hs,
        "away_situation": aws,
    }


def analyze_match_from_name(match_name: str, *, snapshot: dict | None = None) -> dict[str, Any] | None:
    home_raw, away_raw = split_teams(match_name or "")
    if not home_raw or not away_raw:
        return None
    home, away = _normalize(home_raw), _normalize(away_raw)
    team_to_group, _, _ = _team_maps()
    group = team_to_group.get(home) or team_to_group.get(away)
    if not group:
        return None

    snap = snapshot or fetch_live_snapshot()
    if not snap.get("ok"):
        return None

    standings = snap.get("standings") or {}
    best_thirds = rank_best_third_places(standings)

    fixture = None
    for f in snap.get("fixtures") or []:
        if f.get("group") != group:
            continue
        if f.get("home") == home and f.get("away") == away:
            fixture = f
            break
    round_num = int((fixture or {}).get("round") or 2)

    analysis = analyze_fixture_motivation(
        home=home,
        away=away,
        group=group,
        standings=standings,
        round_num=round_num,
        best_thirds=best_thirds,
    )
    analysis["fixture_id"] = (fixture or {}).get("fixture_id")
    analysis["kickoff"] = (fixture or {}).get("kickoff")
    analysis["is_finished"] = (fixture or {}).get("is_finished", False)
    return analysis


def adjust_rates_for_group_stage(
    rates: dict[str, float],
    analysis: dict[str, Any] | None,
) -> tuple[dict[str, float], list[str]]:
    """Apply capped draw/home/away nudges from group motivation (risk context, not hard flip)."""
    if not analysis:
        return rates, []
    import config as cfg

    out = dict(rates)
    notes: list[str] = []
    scale = cfg.GROUP_STAGE_BIAS_SCALE
    draw_nudge = min(float(analysis.get("draw_bias") or 0) * scale, cfg.GROUP_STAGE_MAX_DRAW_NUDGE)
    home_nudge = min(max(float(analysis.get("home_bias") or 0) * scale, 0), cfg.GROUP_STAGE_MAX_SIDE_NUDGE)
    away_nudge = min(max(float(analysis.get("away_bias") or 0) * scale, 0), cfg.GROUP_STAGE_MAX_SIDE_NUDGE)
    if float(analysis.get("home_bias") or 0) < 0:
        home_nudge = max(float(analysis.get("home_bias") or 0) * scale, -cfg.GROUP_STAGE_MAX_SIDE_NUDGE)
    if float(analysis.get("away_bias") or 0) < 0:
        away_nudge = max(float(analysis.get("away_bias") or 0) * scale, -cfg.GROUP_STAGE_MAX_SIDE_NUDGE)
    out["draw"] = out.get("draw", 0) + draw_nudge
    out["home"] = out.get("home", 0) + home_nudge
    out["away"] = out.get("away", 0) + away_nudge
    total = sum(out.values()) or 1.0
    out = {k: v / total for k, v in out.items()}
    mt = analysis.get("match_type_cn") or analysis.get("match_type")
    notes.append(
        f"【小组战意·{mt}】{analysis.get('likely_direction_cn', '')}"
        f"（仅风险提示，初盘明确时不改推方向）"
    )
    for line in (analysis.get("reasoning") or [])[:2]:
        notes.append(line)
    return out, notes


def build_group_stage_report(*, force_refresh: bool = False) -> dict[str, Any]:
    """Full dashboard: standings, best-third zone, R2/R3 predictions."""
    snap = fetch_live_snapshot(force=force_refresh)
    cfg = _load_config()
    if not snap.get("ok"):
        return {"ok": False, "error": snap.get("error"), "groups": []}

    standings = snap["standings"]
    best_thirds = rank_best_third_places(standings)
    cutoff_pts = best_thirds[7]["points"] if len(best_thirds) >= 8 else 3
    cutoff_gd = best_thirds[7]["gd"] if len(best_thirds) >= 8 else 0

    profiles = {}
    try:
        from worldcup_analytics import _build_group_strategy_profiles
        profiles = _build_group_strategy_profiles(
            cfg.get("groups") or {},
            cfg.get("team_strength_tiers") or {},
            cfg.get("tier_labels") or {},
        )
    except Exception:
        pass

    groups_out: list[dict] = []
    upcoming_predictions: list[dict] = []

    for group in "ABCDEFGHIJKL":
        table = standings.get(group) or []
        prof = profiles.get(group) or {}
        group_fixtures = [f for f in snap["fixtures"] if f.get("group") == group]
        upcoming = [f for f in group_fixtures if not f.get("is_finished")]
        upcoming.sort(key=lambda x: (x.get("round") or 9, x.get("kickoff") or ""))

        match_analyses = []
        for f in upcoming[:4]:
            a = analyze_fixture_motivation(
                home=f["home"],
                away=f["away"],
                group=group,
                standings=standings,
                round_num=int(f.get("round") or 2),
                best_thirds=best_thirds,
            )
            a["fixture_id"] = f.get("fixture_id")
            a["kickoff"] = f.get("kickoff")
            a["match_name"] = f.get("match_name")
            match_analyses.append(a)
            upcoming_predictions.append(a)

        groups_out.append({
            "group": group,
            "standings": table,
            "archetype": prof.get("archetype"),
            "strategy_hint": prof.get("strategy_hint"),
            "upcoming": match_analyses,
            "played_round1": all(
                any(x.get("round") == 1 and x.get("is_finished") for x in group_fixtures)
                for _ in [1]
            ) and any(f.get("round") == 1 and f.get("is_finished") for f in group_fixtures),
        })

    type_counts: dict[str, int] = {}
    for p in upcoming_predictions:
        t = p.get("match_type_cn") or "其他"
        type_counts[t] = type_counts.get(t, 0) + 1

    collusion = [p for p in upcoming_predictions if p.get("match_type") == "collusion_watch"]
    must_win = [p for p in upcoming_predictions if p.get("match_type") == "must_win"]

    return {
        "ok": True,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "format": cfg.get("format") or {},
        "advance_rule_cn": (cfg.get("format") or {}).get("advance_rule_cn"),
        "round_summary": snap.get("round_summary") or {},
        "best_third_cutoff": {"points": cutoff_pts, "gd": cutoff_gd},
        "best_third_ranking": best_thirds,
        "type_counts": type_counts,
        "highlights": {
            "collusion_watch": collusion[:6],
            "must_win": must_win[:6],
        },
        "groups": groups_out,
        "upcoming_count": len(upcoming_predictions),
    }


def invalidate_cache() -> None:
    _CACHE["ts"] = 0.0
    _CACHE["data"] = None
