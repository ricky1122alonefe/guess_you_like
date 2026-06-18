"""World Cup tournament ledger: prediction vs result accuracy & opening patterns."""

from __future__ import annotations

import json
import logging
import time
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path
from typing import Any

from db.connection import ping
from db.repository import list_tournament_results
from download_500 import DEFAULT_LEAGUES
from eu_implied_metrics import compute_eu_implied
from market_patterns import analyze_market_patterns
from match_status import RESULT_CN, goals_to_result_1x2
from odds_utils import eu_favorite, odds_from_tick, opening_eu_from_fixture, opening_eu_from_tick
from prediction_archive import load_best_prediction
from time_utils import format_beijing, now_beijing, now_beijing_str, to_beijing
from wc_conclusions import build_opening_conclusions, match_takeaway

log = logging.getLogger(__name__)
TOURNAMENT = "世界杯"
SOURCE = "500"
GROUPS_PATH = Path(__file__).resolve().parent / "data" / "wc2026_groups.json"


def _num(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _pattern_tags(cur: dict) -> list[str]:
    mp = analyze_market_patterns(cur)
    tags = [mp.consistency] if mp.consistency != "unknown" else []
    for p in mp.patterns:
        pid = p.get("id")
        if pid:
            tags.append(str(pid))
    return tags


def _consistency_label(key: str | None) -> str:
    return {
        "aligned": "欧亚基本一致",
        "ah_shallow": "亚盘偏浅",
        "ah_deep": "亚盘偏深",
        "unknown": "欧亚关系不明",
        None: "欧亚关系不明",
    }.get(key, str(key))


def _load_tournament_format_context() -> dict[str, Any]:
    try:
        data = json.loads(GROUPS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    fmt = data.get("format") or {}
    groups = data.get("groups") or {}
    tiers = data.get("team_strength_tiers") or {}
    tier_labels = data.get("tier_labels") or {}
    group_profiles = _build_group_strategy_profiles(groups, tiers, tier_labels)
    return {
        "tournament": data.get("tournament"),
        "format": {
            "teams": fmt.get("teams"),
            "groups": fmt.get("groups"),
            "group_size": fmt.get("group_size"),
            "advance_top2_per_group": fmt.get("advance_top2_per_group"),
            "best_third_count": fmt.get("best_third_count"),
            "knockout_teams": fmt.get("knockout_teams"),
            "advance_rule_cn": fmt.get("advance_rule_cn"),
            "third_rank_tiebreakers": fmt.get("third_rank_tiebreakers") or [],
            "strategy_notes": fmt.get("strategy_notes") or [],
        },
        "groups": groups,
        "team_strength_tiers": tiers,
        "tier_labels": tier_labels,
        "group_game_theory_notes": data.get("group_game_theory_notes") or [],
        "secondary_strategy_notes": data.get("secondary_strategy_notes") or [],
        "group_strategy_profiles": group_profiles,
    }


def _build_group_strategy_profiles(
    groups: dict[str, list[str]],
    tiers: dict[str, str],
    tier_labels: dict[str, str],
) -> dict[str, dict[str, Any]]:
    def archetype(counts: Counter) -> str:
        elite = counts.get("elite", 0)
        strong = counts.get("strong", 0)
        mid = counts.get("mid", 0)
        weak = counts.get("weak", 0)
        if elite >= 1 and strong >= 2 and weak >= 1:
            return "1超2强1弱"
        if strong >= 2 and weak >= 2:
            return "2强2弱"
        if elite >= 1 and strong >= 2:
            return "1超2强混战"
        if elite >= 1 and strong >= 1 and weak >= 1:
            return "1超1强1中1弱"
        if strong >= 2 and mid >= 2:
            return "2强2中"
        if strong >= 2:
            return "2强混战"
        return "均势混战"

    def strategy_hint(kind: str) -> str:
        if kind == "1超2强1弱":
            return "超强队对弱队可能抢净胜球，两强之间先求不败概率较高；弱队的守平价值高。"
        if kind == "2强2弱":
            return "强队对弱队净胜球价值高，两强直接对话防平；热门穿盘需看盘口是否给足。"
        if kind == "1超2强混战":
            return "超强队出线压力较低但两强争位激烈，第二梯队之间平局价值偏高。"
        if kind == "1超1强1中1弱":
            return "超强队领先后可能控节奏，强队对中弱队更重视胜负和净胜球。"
        if kind == "2强2中":
            return "组内差距不极端，中游队抢1分意义大，强队让深时需防赢球不穿。"
        if kind == "2强混战":
            return "两支强队主导出线形势，其他队更容易以平局和小比分为目标。"
        return "均势组1分价值高，平局、小比分和临场降热需要提高权重。"

    profiles: dict[str, dict[str, Any]] = {}
    for group, teams in groups.items():
        counts: Counter = Counter(tiers.get(team, "mid") for team in teams)
        kind = archetype(counts)
        profiles[group] = {
            "archetype": kind,
            "tier_counts": dict(counts),
            "teams": [
                {
                    "team": team,
                    "tier": tiers.get(team, "mid"),
                    "tier_cn": tier_labels.get(tiers.get(team, "mid"), tiers.get(team, "mid")),
                }
                for team in teams
            ],
            "strategy_hint": strategy_hint(kind),
        }
    return profiles


def _team_group_maps() -> tuple[dict[str, str], dict[str, str]]:
    try:
        data = json.loads(GROUPS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}, {}
    team_to_group: dict[str, str] = {}
    alias_to_cn: dict[str, str] = {}
    for group, teams in (data.get("groups") or {}).items():
        for team in teams:
            team_to_group[team] = group
            alias_to_cn[team] = team
    for cn, aliases in (data.get("aliases") or {}).items():
        alias_to_cn[cn] = cn
        for alias in aliases or []:
            alias_to_cn[str(alias)] = cn
    return team_to_group, alias_to_cn


def _group_context_for_match(match_name: str) -> dict[str, Any]:
    from share_card import split_teams

    team_to_group, alias_to_cn = _team_group_maps()
    tournament_ctx = _load_tournament_format_context()
    tiers = tournament_ctx.get("team_strength_tiers") or {}
    tier_labels = tournament_ctx.get("tier_labels") or {}
    profiles = tournament_ctx.get("group_strategy_profiles") or {}
    home_raw, away_raw = split_teams(match_name)
    home = alias_to_cn.get(home_raw, home_raw)
    away = alias_to_cn.get(away_raw, away_raw)
    home_group = team_to_group.get(home)
    away_group = team_to_group.get(away)
    group = home_group if home_group == away_group else (home_group or away_group)
    profile = profiles.get(group) if group else None
    return {
        "group": group,
        "home_team": home,
        "away_team": away,
        "home_tier": tiers.get(home),
        "away_tier": tiers.get(away),
        "home_tier_cn": tier_labels.get(tiers.get(home), tiers.get(home)),
        "away_tier_cn": tier_labels.get(tiers.get(away), tiers.get(away)),
        "group_archetype": (profile or {}).get("archetype"),
        "group_strategy_hint": (profile or {}).get("strategy_hint"),
        "same_group": bool(home_group and home_group == away_group),
    }


def _team_stats_seed(group: str | None = None) -> dict[str, Any]:
    return {"group": group, "played": 0, "points": 0, "gf": 0, "ga": 0, "gd": 0, "last": []}


def _result_points(home_score: int, away_score: int) -> tuple[int, int]:
    if home_score > away_score:
        return 3, 0
    if home_score < away_score:
        return 0, 3
    return 1, 1


def _parse_score_text(score: str | None) -> tuple[int, int] | None:
    if not score or "-" not in str(score):
        return None
    left, right = str(score).split("-", 1)
    try:
        return int(left.strip()), int(right.strip())
    except ValueError:
        return None


def _secondary_group_signals(
    table: list[dict],
    *,
    home_team: str | None = None,
    away_team: str | None = None,
) -> dict[str, Any]:
    """Low-weight hints for opponent-picking and tacit-draw scenarios."""
    max_played = max((r["played"] for r in table), default=0)
    stage = ["pre", "after_r1", "after_r2", "final_round"][min(max_played, 3)]
    signals: dict[str, Any] = {
        "weight": "secondary",
        "round_stage": stage,
        "opponent_picking_notes": [],
        "collusion_watch": None,
        "notes": [],
    }
    if max_played < 2:
        signals["notes"].append("挑对手/默契球：次轮前样本不足，仅作赛制背景提示，权重低。")
        return signals

    by_team = {r["team"]: r for r in table}
    if home_team and away_team:
        home = by_team.get(home_team)
        away = by_team.get(away_team)
        if home and away and home["played"] >= 2 and away["played"] >= 2:
            hp, ap = home["points"], away["points"]
            if hp >= 4 and ap >= 4 and abs(hp - ap) <= 1:
                hint = (
                    f"{home_team}({hp}分) vs {away_team}({ap}分)末轮近分对话："
                    "平局可能同时满足双方晋级/席位目标，需防小比分平局或控节奏（默契球观察）。"
                )
                signals["collusion_watch"] = {
                    "level": "watch",
                    "scenario": "末轮同分/近分对话",
                    "hint": hint,
                }
                signals["notes"].append(hint)
            elif hp >= 6 and ap >= 6:
                signals["notes"].append(
                    "双方均已6分提前出线，末轮战意偏低，轮换/控节奏可能影响穿盘（非典型默契球）。"
                )
            elif max(hp, ap) >= 6 and min(hp, ap) <= 3:
                signals["notes"].append(
                    "一方已出线一方仍争位：热门赢球不穿或领先控节奏可作为次要观察点。"
                )

    leaders = [r for r in table if r["played"] >= 2 and r["points"] >= 6]
    if leaders:
        signals["opponent_picking_notes"].append(
            "已有球队提前出线：末轮可能存在轮换/控节奏，间接影响让步；具体挑对手需看淘汰赛对阵，权重次要。"
        )
    mid_table = [r for r in table if r["played"] >= 2 and 3 <= r["points"] <= 4]
    if len(mid_table) >= 2:
        signals["opponent_picking_notes"].append(
            "中游球队末轮可能比较小组第二/第三或最佳第三的净胜球与对阵利弊，倾向保分而非强攻。"
        )
    if not signals["notes"] and not signals["opponent_picking_notes"]:
        signals["notes"].append(
            "末轮可关注同分对话、提前出线球队控节奏，但权重低于盘口套路与真实战意。"
        )
    return signals


def _build_group_state_context(
    records: list[dict],
    *,
    group: str | None = None,
    home_team: str | None = None,
    away_team: str | None = None,
) -> dict[str, Any]:
    """Summarize current group results/standings from finished World Cup records."""
    from share_card import split_teams

    team_to_group, alias_to_cn = _team_group_maps()
    standings: dict[str, dict[str, Any]] = {}
    matches: list[dict[str, Any]] = []

    for r in records:
        match_name = r.get("match_name") or r.get("match") or ""
        home_raw, away_raw = split_teams(match_name)
        home = alias_to_cn.get(home_raw, home_raw)
        away = alias_to_cn.get(away_raw, away_raw)
        rec_group = r.get("group") or team_to_group.get(home) or team_to_group.get(away)
        if group and rec_group != group:
            continue
        score = _parse_score_text(r.get("score_text"))
        if not rec_group or not home or not away or not score:
            continue

        hs, as_ = score
        hp, ap = _result_points(hs, as_)
        for team, gf, ga, pts in ((home, hs, as_, hp), (away, as_, hs, ap)):
            st = standings.setdefault(team, _team_stats_seed(rec_group))
            st["played"] += 1
            st["points"] += pts
            st["gf"] += gf
            st["ga"] += ga
            st["gd"] = st["gf"] - st["ga"]
        result_text = f"{home}{hs}-{as_}{away}"
        matches.append({
            "group": rec_group,
            "match": match_name,
            "score": r.get("score_text"),
            "result": result_text,
            "takeaway": r.get("takeaway"),
        })
        standings[home]["last"].append({"vs": away, "score": r.get("score_text"), "points": hp})
        standings[away]["last"].append({"vs": home, "score": r.get("score_text"), "points": ap})

    table = sorted(
        (
            {"team": team, **st}
            for team, st in standings.items()
        ),
        key=lambda x: (-x["points"], -x["gd"], -x["gf"], x["team"]),
    )

    try:
        from group_stage_model import analyze_fixture_motivation, fetch_live_snapshot, rank_best_third_places
        snap = fetch_live_snapshot()
        live = (snap.get("standings") or {}).get(group or "") if snap.get("ok") else []
        if live and (not group or len(live) >= len(table)):
            table = live
            for idx, row in enumerate(
                sorted(table, key=lambda x: (-x["points"], -x["gd"], -x["gf"], x["team"])),
                start=1,
            ):
                row["rank"] = idx
    except Exception:
        pass

    for idx, row in enumerate(
        sorted(table, key=lambda x: (-x["points"], -x["gd"], -x["gf"], x["team"])),
        start=1,
    ):
        if "rank" not in row:
            row["rank"] = idx
        row["last"] = row.get("last", [])[-2:]

    notes: list[str] = []
    if matches:
        notes.append(f"本组已有 {len(matches)} 场赛果，需结合积分、净胜球和上一轮结果判断战意。")
        zero_or_one = [r for r in table if r["played"] and r["points"] <= 1]
        leaders = [r for r in table if r["points"] >= 3]
        if zero_or_one:
            notes.append("低分球队下一场抢分/守平价值上升，落后方若赔率偏热需防强攻反受制。")
        if leaders:
            notes.append("已拿3分球队出线压力下降，领先后控节奏和赢球不穿风险上升。")
        if any(abs(r["gd"]) >= 2 for r in table):
            notes.append("净胜球差距已出现，后续对弱队可能存在抢净胜球或保净胜球分化。")
    else:
        notes.append("本组暂无已赛样本，战意主要参考静态小组结构和48队晋级规则。")

    secondary = _secondary_group_signals(table, home_team=home_team, away_team=away_team)

    match_motivation = None
    if home_team and away_team and group:
        try:
            snap = fetch_live_snapshot()
            if snap.get("ok"):
                best3 = rank_best_third_places(snap.get("standings") or {})
                rnd = 2
                for f in snap.get("fixtures") or []:
                    if f.get("group") == group and f.get("home") == home_team and f.get("away") == away_team:
                        rnd = int(f.get("round") or 2)
                        break
                match_motivation = analyze_fixture_motivation(
                    home=home_team,
                    away=away_team,
                    group=group,
                    standings=snap.get("standings") or {group: table},
                    round_num=rnd,
                    best_thirds=best3,
                )
        except Exception:
            pass

    return {
        "group": group,
        "played_matches": len(matches),
        "standings": table,
        "recent_results": matches[-4:],
        "motivation_notes": notes,
        "secondary_signals": secondary,
        "match_motivation": match_motivation,
    }


def _odds_snapshot_for_patterns(m: dict) -> dict[str, Any]:
    snap = m.get("odds_snapshot") or {}
    return {
        "ah_open_line": snap.get("ah_open_line"),
        "ah_open_home_water": snap.get("ah_open_home_water"),
        "ah_open_away_water": snap.get("ah_open_away_water"),
        "ah_line": snap.get("ah_line"),
        "ah_home_water": snap.get("ah_home_water"),
        "ah_away_water": snap.get("ah_away_water"),
        "eu_open_home": snap.get("eu_open_home"),
        "eu_open_draw": snap.get("eu_open_draw"),
        "eu_open_away": snap.get("eu_open_away"),
        "eu_home": snap.get("eu_home"),
        "eu_draw": snap.get("eu_draw"),
        "eu_away": snap.get("eu_away"),
    }


def _fmt_triplet(a, b, c) -> str:
    if a is None and b is None and c is None:
        return "—"
    return f"{a or '—'}/{b or '—'}/{c or '—'}"


def _summary_rate(sim: dict, group: str) -> str:
    blocks = sim.get(group) or []
    parts = []
    for b in blocks[:2]:
        if b.get("count"):
            parts.append(f"{b.get('title')}：{b.get('rate_text')}")
    return "；".join(parts[:2])


def _watch_level(consistency: str | None, patterns: list[dict], confidence: str | None) -> tuple[str, str]:
    names = " ".join(str(p.get("name") or p.get("id") or "") for p in patterns)
    if consistency == "ah_shallow" or "诱" in names or "偏浅" in names:
        return "warn", "警惕"
    if confidence == "高" and consistency == "aligned":
        return "ok", "可重点看"
    if consistency == "ah_deep":
        return "neutral", "偏深复核"
    return "neutral", "观察"


def build_upcoming_opening_watch(
    output_root: str | Path,
    *,
    hours: int = 24,
    records: list[dict] | None = None,
) -> dict[str, Any]:
    """Summarize opening-routine signals for upcoming matches, no AI calls."""
    from daily_picks import load_dashboard_matches, load_kickoff_map
    from jingcai_pick import final_recommendation_cn

    root = Path(output_root)
    now = now_beijing()
    cutoff = now + timedelta(hours=hours)
    kickoff_map = load_kickoff_map(within_days=max(1, hours / 24))
    matches = load_dashboard_matches(root, within_days=max(1, hours / 24))
    records = records if records is not None else load_tournament_records(root)

    rows: list[dict[str, Any]] = []
    counts: Counter = Counter()
    for m in matches:
        fid = str(m.get("fixture_id") or "")
        ko = kickoff_map.get(fid)
        if not ko:
            continue
        ko_bj = to_beijing(ko)
        if ko_bj < now or ko_bj > cutoff:
            continue

        cur = _odds_snapshot_for_patterns(m)
        has_odds = any(cur.get(k) is not None for k in ("eu_open_home", "eu_home", "ah_open_line", "ah_line"))
        mp = analyze_market_patterns(cur) if has_odds else None
        consistency = getattr(mp, "consistency", "unknown") if mp else "unknown"
        patterns = getattr(mp, "patterns", []) if mp else []
        level, level_cn = _watch_level(
            consistency,
            patterns,
            (m.get("predict_row") or {}).get("置信度") or m.get("confidence_cn"),
        )
        counts[consistency] += 1
        if level == "warn":
            counts["warn"] += 1
        if level == "ok":
            counts["ok"] += 1

        snap = m.get("odds_snapshot") or {}
        sim = m.get("similarity_analysis") or {}
        pattern_names = [
            p.get("name") or p.get("id")
            for p in patterns
            if p.get("name") or p.get("id")
        ]
        match_name = m.get("match") or (m.get("predict_row") or {}).get("比赛") or fid
        group_ctx = _group_context_for_match(match_name)
        group_state = _build_group_state_context(
            records,
            group=group_ctx.get("group"),
            home_team=group_ctx.get("home_team"),
            away_team=group_ctx.get("away_team"),
        )
        rows.append({
            "fixture_id": fid,
            "match": match_name,
            "group": group_ctx.get("group"),
            "home_team": group_ctx.get("home_team"),
            "away_team": group_ctx.get("away_team"),
            "home_tier": group_ctx.get("home_tier"),
            "away_tier": group_ctx.get("away_tier"),
            "home_tier_cn": group_ctx.get("home_tier_cn"),
            "away_tier_cn": group_ctx.get("away_tier_cn"),
            "group_archetype": group_ctx.get("group_archetype"),
            "group_strategy_hint": group_ctx.get("group_strategy_hint"),
            "group_state_context": group_state,
            "same_group": group_ctx.get("same_group"),
            "kickoff": format_beijing(ko_bj, "%m-%d %H:%M"),
            "pick": final_recommendation_cn(m),
            "confidence": (m.get("predict_row") or {}).get("置信度") or m.get("confidence_cn") or "—",
            "score_hint": (m.get("predict_row") or {}).get("推荐比分") or "",
            "level": level,
            "level_cn": level_cn,
            "consistency": consistency,
            "consistency_cn": _consistency_label(consistency),
            "pattern_names": pattern_names[:3],
            "conversion_summary": (
                m.get("market_pattern_summary")
                or (getattr(mp, "conversion_summary", "") if mp else "")
            ),
            "routine_notes": (getattr(mp, "routine_notes", []) if mp else [])[:3],
            "open_ah": f"{snap.get('ah_open_line') or '—'} {snap.get('ah_open_home_water') or '—'}/{snap.get('ah_open_away_water') or '—'}",
            "live_ah": f"{snap.get('ah_line') or '—'} {snap.get('ah_home_water') or '—'}/{snap.get('ah_away_water') or '—'}",
            "open_eu": _fmt_triplet(snap.get("eu_open_home"), snap.get("eu_open_draw"), snap.get("eu_open_away")),
            "live_eu": _fmt_triplet(snap.get("eu_home"), snap.get("eu_draw"), snap.get("eu_away")),
            "similar_open": _summary_rate(sim, "open"),
            "similar_live": _summary_rate(sim, "live"),
        })

    rows.sort(key=lambda r: ({"warn": 0, "ok": 1, "neutral": 2}.get(r["level"], 9), r["kickoff"]))
    headline = "未来24小时暂无可分析开盘样本"
    if rows:
        headline = (
            f"未来{hours}小时 {len(rows)} 场："
            f"{counts.get('warn', 0)} 场需防套路，"
            f"{counts.get('ok', 0)} 场欧亚相对清晰"
        )
    notes: list[str] = []
    if counts.get("ah_shallow"):
        notes.append(f"亚盘偏浅 {counts['ah_shallow']} 场：热门方向需防小胜/不穿或诱上。")
    if counts.get("aligned"):
        notes.append(f"欧亚一致 {counts['aligned']} 场：可优先结合 SP 与置信度筛选。")
    if counts.get("ah_deep"):
        notes.append(f"亚盘偏深 {counts['ah_deep']} 场：注意是否为阻上或真实支撑。")
    if not notes:
        notes.append("样本以实时盘口为准，未调用 AI；建议结合单场详情的历史相似 Top10 复核。")

    return {
        "hours": hours,
        "count": len(rows),
        "headline": headline,
        "notes": notes,
        "counts": dict(counts),
        "matches": rows[:16],
    }


def _ai_watch_cache_path(output_root: str | Path) -> Path:
    return Path(output_root) / "worldcup" / "upcoming_ai_watch.json"


def _load_ai_watch_cache(output_root: str | Path, *, ttl_sec: int = 3600) -> dict[str, Any] | None:
    path = _ai_watch_cache_path(output_root)
    if not path.is_file():
        return None
    if time.time() - path.stat().st_mtime > ttl_sec:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _compact_finished_for_ai(records: list[dict], limit: int = 20) -> list[dict]:
    out = []
    for r in records[-limit:]:
        out.append({
            "match": r.get("match_name"),
            "group": r.get("group"),
            "score": r.get("score_text"),
            "result": r.get("result_1x2_cn"),
            "opening_favorite": r.get("opening_favorite_cn"),
            "opening_consistency": _consistency_label(r.get("opening_consistency")),
            "line_move": r.get("line_move"),
            "takeaway": r.get("takeaway"),
        })
    return out


def _save_ai_watch_cache(output_root: str | Path, data: dict[str, Any]) -> None:
    path = _ai_watch_cache_path(output_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _ai_match_watch_cache_path(output_root: str | Path, fixture_id: str) -> Path:
    safe = "".join(ch for ch in str(fixture_id) if ch.isdigit() or ch in ("_", "-")) or "unknown"
    return Path(output_root) / "worldcup" / "match_ai_watch" / f"{safe}.json"


def _load_ai_match_watch_cache(
    output_root: str | Path,
    fixture_id: str,
    *,
    ttl_sec: int = 3600,
) -> dict[str, Any] | None:
    path = _ai_match_watch_cache_path(output_root, fixture_id)
    if not path.is_file():
        return None
    if time.time() - path.stat().st_mtime > ttl_sec:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _save_ai_match_watch_cache(output_root: str | Path, fixture_id: str, data: dict[str, Any]) -> None:
    path = _ai_match_watch_cache_path(output_root, fixture_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def build_upcoming_match_ai_watch(
    output_root: str | Path,
    fixture_id: str,
    *,
    opening_watch: dict | None = None,
    opening_patterns: dict | None = None,
    records: list[dict] | None = None,
    ai_model: str | None = None,
    ai_base_url: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Manual AI analysis for one upcoming-watch match card."""
    fid = str(fixture_id)
    if not force:
        cached = _load_ai_match_watch_cache(output_root, fid)
        if cached:
            return cached

    root = Path(output_root)
    records = records if records is not None else load_tournament_records(root)
    opening_patterns = opening_patterns or compute_opening_characteristics(records)
    opening_watch = opening_watch or build_upcoming_opening_watch(root, hours=24, records=records)
    match = next((m for m in (opening_watch.get("matches") or []) if str(m.get("fixture_id")) == fid), None)
    if not match:
        raise ValueError(f"未来24小时重点场次中未找到 {fid}")

    try:
        from ai_profiles import get_primary_profile
        from ai_prompt import _extract_json_text
        from deepseek_client import chat

        prof = get_primary_profile(ai_model, ai_base_url)
        api_key = prof.resolve_api_key()
        if not api_key:
            raise ValueError(f"未配置 {prof.api_key_env}")

        system = """你是世界杯单场开盘套路复核员。只基于用户提供的数据分析，不编造伤停、阵容、新闻。

任务：针对一场未来24小时比赛，综合本届世界杯赛果/小组强弱、本届开盘套路统计、该场初盘→实时盘、欧亚互转、历史相似样本和当前推荐，给出人工可读的单场盘路分析。

赛制重点：2026为48队12组，每组前二直接晋级，12个小组第三中成绩最好的8队也晋级。分析时必须考虑：弱队/中游队拿1分的战略价值更高，强队领先后可能更保守，同组实力接近时平局与小比分权重上升，低赔热门穿盘风险可能高于胜负风险。

小组博弈重点：用户会提供 group_archetype/group_strategy_hint，例如“1超2强1弱”“2强2弱”。这类田忌赛马结构会影响净胜球、平局价值和轮换/保守倾向。单场判断必须说明：本场是否是强队抢净胜球、两强互相保平、弱队守1分、还是热门赢球但不穿盘的场景。

动态战意重点：如果 match.group_state_context.played_matches > 0，必须结合本组已赛结果、当前积分/净胜球、上一轮输赢和48队最佳小组第三规则判断战意。不要只按赛前强弱档位分析；已拿3分的球队、0分球队、净胜球落后的球队，策略完全不同。

次要因素（权重低）：tournament_format_context.secondary_strategy_notes 与 group_state_context.secondary_signals 涉及挑对手、默契球/控节奏。仅在末轮同分对话、提前出线或盘口异常降热时顺带提及，不可压过盘口套路、真实战意和历史相似样本。

输出 JSON：
{
  "headline": "一句话结论",
  "verdict": "重点/防范/观望",
  "action": "可执行建议，例如主胜可看但不追让球",
  "reason": "主要理由",
  "risk": "最大风险",
  "watch_points": ["赛前继续观察点"],
  "stake_advice": "仓位建议"
}"""
        payload = {
            "generated_at": now_beijing_str(),
            "tournament_format_context": _load_tournament_format_context(),
            "match": match,
            "tournament_opening": {
                "sample_size": opening_patterns.get("sample_size"),
                "summary": opening_patterns.get("summary"),
                "traits": opening_patterns.get("traits") or [],
                "stats": opening_patterns.get("stats") or {},
            },
            "finished_matches_recent": _compact_finished_for_ai(records, limit=12),
            "instruction": "请只分析这一场，必须先检查match.group_state_context：若本组已有赛果，要结合当前积分、净胜球和上一轮结果判断战意；再结合48队赛制和group_archetype田忌赛马博弈，判断是否属于强队抢净胜球、两强保平、弱队守1分、热门赢球不穿、诱盘/不追让球或观望。secondary_signals（挑对手/默契球）仅作低权重补充，有则一句带过，不可作为主结论。",
        }
        text = chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
            ],
            api_key=api_key,
            model=prof.model,
            base_url=prof.base_url,
            temperature=0.2,
            max_tokens=1800,
            timeout=180,
        )
        data = json.loads(_extract_json_text(text))
        data["ok"] = True
        data["fixture_id"] = fid
        data["match"] = match.get("match")
        data["generated_at"] = now_beijing_str()
        data["ai_provider"] = prof.provider_id
        data["ai_provider_label"] = prof.label
        _save_ai_match_watch_cache(root, fid, data)
        return data
    except Exception as exc:
        log.exception("世界杯单场AI盘路分析失败")
        data = {
            "ok": False,
            "fixture_id": fid,
            "match": match.get("match"),
            "generated_at": now_beijing_str(),
            "error": str(exc),
        }
        _save_ai_match_watch_cache(root, fid, data)
        return data


def build_upcoming_ai_watch(
    output_root: str | Path,
    *,
    opening_watch: dict,
    opening_patterns: dict,
    records: list[dict],
    ai_model: str | None = None,
    ai_base_url: str | None = None,
    force: bool = False,
) -> dict[str, Any] | None:
    """AI summary for the upcoming 24h opening-routine module, cached hourly."""
    if not opening_watch.get("matches"):
        return None
    if not force:
        cached = _load_ai_watch_cache(output_root)
        if cached:
            return cached

    try:
        from ai_profiles import get_primary_profile
        from ai_prompt import _extract_json_text
        from deepseek_client import chat

        prof = get_primary_profile(ai_model, ai_base_url)
        api_key = prof.resolve_api_key()
        if not api_key:
            return {
                "ok": False,
                "generated_at": now_beijing_str(),
                "error": f"未配置 {prof.api_key_env}",
            }

        system = """你是世界杯开盘套路复核员。你只根据用户给出的结构化数据分析，不编造伤停、新闻、阵容。

任务：针对未来24小时重点场次，综合：
1. 本届世界杯已完场赛果与小组强弱表现；
2. 本届开盘套路统计（热门、平局、亚盘偏浅/偏深、盘赔一致）；
3. 未来24小时每场的初盘→实时盘、欧亚互转、历史相似样本和当前推荐。

赛制重点：2026为48队12组，每组前二直接晋级，12个小组第三中成绩最好的8队也晋级。分析时必须考虑：弱队/中游队拿1分的战略价值更高，强队领先后可能更保守，同组实力接近时平局与小比分权重上升，低赔热门穿盘风险可能高于胜负风险。

小组博弈重点：用户会提供每组 group_archetype/group_strategy_hint，例如“1超2强1弱”“2强2弱”。这类田忌赛马结构会影响净胜球、平局价值和轮换/保守倾向。总结时要指出哪些比赛像强队抢净胜球，哪些像两强互相保平，哪些像弱队守1分，哪些是热门赢球但不穿盘风险。

动态战意重点：每场 match 可能包含 group_state_context。如果 played_matches > 0，必须结合本组已赛结果、当前积分/净胜球、上一轮输赢和48队最佳小组第三规则判断战意。不要只按赛前强弱档位分析；已拿3分的球队、0分球队、净胜球落后的球队，策略完全不同。

次要因素（权重低）：secondary_strategy_notes 与 secondary_signals 涉及挑对手、默契球/控节奏。仅在末轮同分对话、提前出线或盘口异常降热时顺带提及，不可压过盘口套路与真实战意。

输出目标：给页面模块一段更像人工盘手的总结，指出哪些场次可重点看、哪些需防平/防诱盘、哪些不宜重仓。

只返回 JSON：
{
  "headline": "一句话总判断",
  "overview": "100字内总览",
  "group_notes": ["小组/强弱相关观察"],
  "betting_notes": ["投注/风控建议"],
  "match_notes": [
    {"fixture_id":"123","match":"A vs B","verdict":"重点/防范/观望","action":"可看主胜但不追让球","reason":"原因","risk":"主要风险"}
  ]
}"""
        payload = {
            "generated_at": now_beijing_str(),
            "tournament_format_context": _load_tournament_format_context(),
            "tournament_opening": {
                "sample_size": opening_patterns.get("sample_size"),
                "summary": opening_patterns.get("summary"),
                "traits": opening_patterns.get("traits") or [],
                "stats": opening_patterns.get("stats") or {},
                "insights": opening_patterns.get("insights") or [],
            },
            "finished_matches_recent": _compact_finished_for_ai(records),
            "upcoming_24h": opening_watch,
            "instruction": "请重点解释未来24小时重点场次模块。每场先检查group_state_context：若本组已有赛果，要结合当前积分、净胜球和上一轮结果判断战意；再给出小组强弱+赔率套路综合判断，并显式考虑48队赛制、最佳小组第三晋级规则、group_archetype田忌赛马结构对平局、保守策略、净胜球和穿盘风险的影响。secondary_signals（挑对手/默契球）仅作低权重补充，有则一句带过。",
        }
        text = chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
            ],
            api_key=api_key,
            model=prof.model,
            base_url=prof.base_url,
            temperature=0.2,
            max_tokens=2600,
            timeout=180,
        )
        data = json.loads(_extract_json_text(text))
        data["ok"] = True
        data["generated_at"] = now_beijing_str()
        data["ai_provider"] = prof.provider_id
        data["ai_provider_label"] = prof.label
        _save_ai_watch_cache(output_root, data)
        return data
    except Exception as exc:
        log.exception("世界杯未来24h AI总结失败")
        data = {
            "ok": False,
            "generated_at": now_beijing_str(),
            "error": str(exc),
        }
        _save_ai_watch_cache(output_root, data)
        return data


def _record_from_row(row: dict) -> dict[str, Any]:
    payload = row.get("payload") or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = {}

    pred = payload.get("prediction") or {}
    opening = payload.get("opening_odds") or {}
    closing = payload.get("closing_odds") or {}
    open_tags = payload.get("opening_pattern_tags") or []
    close_tags = payload.get("closing_pattern_tags") or []

    return {
        "fixture_id": str(row.get("external_id") or ""),
        "match_name": row.get("match_name") or "",
        "kickoff_at": format_beijing(row.get("kickoff_at")) if row.get("kickoff_at") else None,
        "score_text": row.get("score_text"),
        "result_1x2": row.get("result_1x2"),
        "result_1x2_cn": row.get("result_1x2_cn"),
        "pick_jingcai_cn": row.get("pick_jingcai_cn") or pred.get("pick_jingcai_cn"),
        "recommended_scores": row.get("recommended_scores") or pred.get("recommended_scores"),
        "hit_1x2": row.get("hit_1x2"),
        "hit_score": row.get("hit_score"),
        "recommendation_source": pred.get("recommendation_source") or payload.get("recommendation_source"),
        "confidence_cn": pred.get("confidence_cn"),
        "asian_handicap_cn": pred.get("asian_handicap_cn"),
        "asian_handicap_pick": pred.get("asian_handicap_pick"),
        "asian_handicap_reason": pred.get("asian_handicap_reason"),
        "pick_ah": row.get("pick_ah"),
        "pick_ah_cn": row.get("pick_ah_cn"),
        "hit_ah": row.get("hit_ah"),
        "ah_settlement": row.get("ah_settlement"),
        "opening_odds": opening,
        "closing_odds": closing,
        "opening_favorite": payload.get("opening_favorite"),
        "opening_favorite_cn": RESULT_CN.get(payload.get("opening_favorite"), "—"),
        "opening_pattern_tags": open_tags,
        "closing_pattern_tags": close_tags,
        "opening_consistency": payload.get("opening_consistency"),
        "line_move": payload.get("line_move"),
        "settled_at": format_beijing(row.get("settled_at")) if row.get("settled_at") else None,
    }


def load_tournament_records(output_root: str | Path) -> list[dict]:
    records: list[dict] = []
    seen: set[str] = set()

    if ping():
        try:
            for row in list_tournament_results(source=SOURCE):
                rec = _record_from_row(row)
                fid = rec.get("fixture_id") or ""
                if fid:
                    seen.add(fid)
                records.append(rec)
        except Exception as exc:
            log.debug("DB 赛果读取失败: %s", exc)

    settled_dir = Path(output_root) / "settled"
    if settled_dir.is_dir():
        for p in sorted(settled_dir.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                fid = str(data.get("fixture_id") or p.stem)
                if fid in seen:
                    continue
                payload = data.get("payload") or {}
                records.append(_record_from_row({
                    "external_id": fid,
                    "match_name": data.get("match_name"),
                    "kickoff_at": data.get("kickoff_at"),
                    "score_text": data.get("score_text"),
                    "result_1x2": data.get("result_1x2"),
                    "result_1x2_cn": data.get("result_1x2_cn"),
                    "pick_jingcai_cn": data.get("pick_jingcai_cn"),
                    "recommended_scores": data.get("recommended_scores"),
                    "hit_1x2": data.get("hit_1x2"),
                    "hit_score": data.get("hit_score"),
                    "settled_at": data.get("settled_at"),
                    "payload": payload,
                }))
                seen.add(fid)
            except json.JSONDecodeError:
                continue

    # 500 完场 + DB/API 初终盘：无本地 settlement 时仍可总结开盘特征
    try:
        for rec in _backfill_from_500_finished(seen, output_root):
            records.append(rec)
    except Exception as exc:
        log.debug("500 完场回填失败: %s", exc)

    records.sort(key=lambda r: r.get("kickoff_at") or "")
    for r in records:
        if not r.get("takeaway"):
            r["takeaway"] = match_takeaway(r)
    return records


def _attach_prediction(rec: dict, output_root: str | Path) -> None:
    """Fill pick/hit from archived prediction when backfilling."""
    fid = rec.get("fixture_id")
    if not fid:
        return
    pred = load_best_prediction(output_root, fid)
    if not pred:
        return
    pick = pred.get("pick_jingcai_cn")
    if pick and pick not in ("—", "观望", ""):
        rec["pick_jingcai_cn"] = pick
        rec["recommended_scores"] = pred.get("likely_scores") or pred.get("recommended_scores")
        rec["recommendation_source"] = pred.get("recommendation_source") or pred.get("source")
        rec["confidence_cn"] = pred.get("confidence_cn")
        actual = rec.get("result_1x2")
        pick_key = pred.get("result_1x2") or pred.get("pick_1x2")
        if actual and pick_key:
            rec["hit_1x2"] = pick_key == actual
        pick_ah = pred.get("asian_handicap_pick")
        if pick_ah in ("home", "away"):
            rec["asian_handicap_pick"] = pick_ah
            rec["asian_handicap_cn"] = pred.get("asian_handicap_cn")
            rec["asian_handicap_reason"] = pred.get("asian_handicap_reason")


def _record_from_finished_fixture(
    fx,
    *,
    opening_tick: dict | None,
    closing_tick: dict | None,
    source: str = "500+db",
    output_root: str | Path | None = None,
) -> dict[str, Any] | None:
    """Build ledger record from 500 finished match + DB/API odds."""
    hs, gs = fx.home_score, fx.away_score
    if hs is None or gs is None:
        return None
    result = goals_to_result_1x2(hs, gs)

    opening = odds_from_tick(opening_tick, opening=True) if opening_tick else {}
    closing = odds_from_tick(closing_tick, opening=False) if closing_tick else {}

    if not opening.get("odds_valid"):
        opening = {**opening, **opening_eu_from_fixture(fx)}

    if not opening.get("eu_home"):
        return None

    open_cur = {k: opening.get(k) for k in (
        "eu_home", "eu_draw", "eu_away", "ah_line", "ah_home_water", "ah_away_water",
    )}
    fav = eu_favorite(opening.get("eu_home"), opening.get("eu_draw"), opening.get("eu_away"))
    open_mp = analyze_market_patterns(open_cur)
    open_tags = [open_mp.consistency] if open_mp.consistency != "unknown" else []
    open_tags.extend(p.get("id") for p in open_mp.patterns if p.get("id"))

    line_move = None
    if opening.get("ah_line") is not None and closing.get("ah_line") is not None:
        line_move = round(float(closing["ah_line"]) - float(opening["ah_line"]), 2)

    eu_imp = compute_eu_implied(opening.get("eu_home"), opening.get("eu_draw"), opening.get("eu_away"))

    rec = {
        "fixture_id": fx.fixture_id,
        "match_name": fx.match_name,
        "kickoff_at": fx.kickoff,
        "group": fx.group,
        "round": fx.round,
        "score_text": fx.score_text,
        "result_1x2": result,
        "result_1x2_cn": RESULT_CN[result],
        "pick_jingcai_cn": None,
        "hit_1x2": None,
        "hit_score": None,
        "recommendation_source": "wc500_backfill",
        "opening_odds": opening,
        "closing_odds": closing,
        "opening_favorite": fav,
        "opening_favorite_cn": RESULT_CN.get(fav) if fav else "—",
        "opening_pattern_tags": open_tags,
        "opening_consistency": open_mp.consistency,
        "line_move": line_move,
        "eu_implied_sum": eu_imp.raw_sum_pct if eu_imp else None,
        "source": source,
        "takeaway": "",
    }
    if output_root:
        _attach_prediction(rec, output_root)
    rec["takeaway"] = match_takeaway(rec)
    return rec


def _backfill_from_500_finished(seen: set[str], output_root: str | Path) -> list[dict]:
    from wc_standings_fetch import fetch_finished_fixtures

    from db.repository import get_closing_tick, get_fixture_by_external, get_opening_tick

    out: list[dict] = []
    for fx in fetch_finished_fixtures():
        if fx.fixture_id in seen:
            continue
        opening_tick = closing_tick = None
        source = "500_api"
        if ping():
            row = get_fixture_by_external(SOURCE, fx.fixture_id)
            if row:
                db_id = int(row["id"])
                opening_tick = get_opening_tick(db_id)
                if opening_tick and not opening_eu_from_tick(opening_tick):
                    opening_tick = None
                closing_tick = get_closing_tick(db_id, row.get("kickoff_at"))
                source = "500+db" if opening_tick else "500_api"

        rec = _record_from_finished_fixture(
            fx,
            opening_tick=opening_tick,
            closing_tick=closing_tick,
            source=source,
            output_root=output_root,
        )
        if rec:
            out.append(rec)
            seen.add(fx.fixture_id)
    return out


def _rate(hits: int, total: int) -> float | None:
    return round(hits / total * 100, 1) if total else None


def compute_accuracy_report(records: list[dict]) -> dict[str, Any]:
    total = len(records)
    with_pick = [r for r in records if r.get("pick_jingcai_cn") and r["pick_jingcai_cn"] not in ("—", "观望", "")]
    judged_1x2 = [r for r in with_pick if r.get("hit_1x2") is not None]
    judged_sc = [r for r in with_pick if r.get("hit_score") is not None]

    hit_1x2 = sum(1 for r in judged_1x2 if r.get("hit_1x2"))
    hit_sc = sum(1 for r in judged_sc if r.get("hit_score"))

    by_source: dict[str, dict] = defaultdict(lambda: {"total": 0, "hit": 0})
    by_conf: dict[str, dict] = defaultdict(lambda: {"total": 0, "hit": 0})

    for r in judged_1x2:
        src = r.get("recommendation_source") or "unknown"
        by_source[src]["total"] += 1
        if r.get("hit_1x2"):
            by_source[src]["hit"] += 1
        conf = r.get("confidence_cn") or "未知"
        by_conf[conf]["total"] += 1
        if r.get("hit_1x2"):
            by_conf[conf]["hit"] += 1

    def _summarize(groups: dict) -> dict:
        out = {}
        for k, v in sorted(groups.items(), key=lambda x: -x[1]["total"]):
            out[k] = {**v, "rate_pct": _rate(v["hit"], v["total"])}
        return out

    return {
        "total_settled": total,
        "with_recommendation": len(with_pick),
        "judged_1x2": len(judged_1x2),
        "judged_score": len(judged_sc),
        "hit_1x2": hit_1x2,
        "hit_score": hit_sc,
        "rate_1x2_pct": _rate(hit_1x2, len(judged_1x2)),
        "rate_score_pct": _rate(hit_sc, len(judged_sc)),
        "by_source": _summarize(by_source),
        "by_confidence": _summarize(by_conf),
    }


def compute_opening_patterns(records: list[dict]) -> dict[str, Any]:
    """Analyze opening odds routines vs actual outcomes."""
    fav_total = Counter()
    fav_hit = Counter()
    consistency_outcomes: dict[str, Counter] = defaultdict(Counter)
    pattern_outcomes: dict[str, Counter] = defaultdict(Counter)
    line_moves: list[dict] = []

    for r in records:
        actual = r.get("result_1x2")
        if not actual:
            continue
        fav = r.get("opening_favorite")
        if fav:
            fav_total[fav] += 1
            if fav == actual:
                fav_hit[fav] += 1

        cons = r.get("opening_consistency")
        if cons:
            consistency_outcomes[cons][actual] += 1

        for tag in r.get("opening_pattern_tags") or []:
            if tag in ("aligned", "ah_shallow", "ah_deep", "unknown"):
                continue
            pattern_outcomes[tag][actual] += 1

        op = r.get("opening_odds") or {}
        cl = r.get("closing_odds") or {}
        ol, ll = op.get("ah_line"), cl.get("ah_line")
        if ol is not None and ll is not None and ol != ll:
            line_moves.append({
                "match": r.get("match_name"),
                "open_line": ol,
                "close_line": ll,
                "move": round(ll - ol, 2),
                "result": actual,
                "result_cn": r.get("result_1x2_cn"),
            })

    fav_summary = {}
    for k in ("home", "draw", "away"):
        t = fav_total[k]
        if t:
            fav_summary[RESULT_CN[k]] = {
                "count": t,
                "win_rate_pct": _rate(fav_hit[k], t),
                "label": f"初盘欧赔最低项（{RESULT_CN[k]}）实际打出",
            }

    cons_summary = {}
    cons_labels = {
        "aligned": "盘赔一致",
        "ah_shallow": "亚盘偏浅（诱上风险）",
        "ah_deep": "亚盘偏深（阻上/看低主）",
    }
    for key, counter in consistency_outcomes.items():
        n = sum(counter.values())
        if not n:
            continue
        top = counter.most_common(1)[0]
        cons_summary[cons_labels.get(key, key)] = {
            "matches": n,
            "top_outcome_cn": RESULT_CN.get(top[0], top[0]),
            "top_rate_pct": _rate(top[1], n),
            "distribution": {RESULT_CN.get(k, k): v for k, v in counter.items()},
        }

    pat_summary = {}
    for pid, counter in pattern_outcomes.items():
        n = sum(counter.values())
        if n < 2:
            continue
        top = counter.most_common(1)[0]
        pat_summary[pid] = {
            "matches": n,
            "top_outcome_cn": RESULT_CN.get(top[0], top[0]),
            "top_rate_pct": _rate(top[1], n),
        }

    shallow = consistency_outcomes.get("ah_shallow", Counter())
    shallow_n = sum(shallow.values())
    deep = consistency_outcomes.get("ah_deep", Counter())
    deep_n = sum(deep.values())

    insights: list[str] = []
    if shallow_n >= 3:
        home_w = shallow.get("home", 0)
        insights.append(
            f"初盘亚盘偏浅 {shallow_n} 场，主胜打出 {home_w} 场（{_rate(home_w, shallow_n)}%）"
            " — 偏浅时主队未必稳，需防诱上"
        )
    if deep_n >= 3:
        home_w = deep.get("home", 0)
        insights.append(
            f"初盘亚盘偏深 {deep_n} 场，主胜打出 {home_w} 场（{_rate(home_w, deep_n)}%）"
        )
    if fav_summary:
        best = max(fav_summary.items(), key=lambda x: x[1]["count"])
        insights.append(
            f"初盘欧赔最低项共 {best[1]['count']} 场，实际打出率 {best[1]['win_rate_pct']}%"
        )

    return {
        "opening_favorite": fav_summary,
        "by_consistency": cons_summary,
        "named_patterns": pat_summary,
        "line_moves_sample": line_moves[-15:],
        "insights": insights,
    }


def compute_opening_characteristics(records: list[dict]) -> dict[str, Any]:
    """
    本届世界杯完场样本 → 开盘特征总结（初盘欧赔/亚盘 vs 实际赛果）。
    """
    finished = [r for r in records if r.get("result_1x2")]
    n = len(finished)
    if not n:
        return {
            "sample_size": 0,
            "summary": "暂无完场比赛样本，无法总结开盘特征。",
            "traits": [],
            "stats": {},
            "conclusions": build_opening_conclusions(
                sample_size=0, stats={}, upset_matches=[], by_consistency={},
            ),
        }

    patterns = compute_opening_patterns(finished)

    fav_hit = fav_miss = 0
    upsets: list[str] = []
    draw_n = 0
    implied_draw_sum = 0.0
    implied_draw_cnt = 0
    shallow_home = shallow_n = 0
    deep_home = deep_n = 0
    aligned_fav_hit = aligned_n = 0
    line_up_home = line_up_n = 0
    line_down_home = line_down_n = 0
    eu_sums: list[float] = []

    for r in finished:
        actual = r["result_1x2"]
        if actual == "draw":
            draw_n += 1

        fav = r.get("opening_favorite")
        if fav:
            if fav == actual:
                fav_hit += 1
            else:
                fav_miss += 1
                op = r.get("opening_odds") or {}
                fav_odds = {"home": op.get("eu_home"), "draw": op.get("eu_draw"), "away": op.get("eu_away")}.get(fav)
                if fav_odds and fav_odds < 2.0 and actual in ("home", "away"):
                    dog = "away" if fav == "home" else "home"
                    if actual == dog:
                        upsets.append(r.get("match_name") or "")

        op = r.get("opening_odds") or {}
        imp = compute_eu_implied(op.get("eu_home"), op.get("eu_draw"), op.get("eu_away"))
        if imp:
            eu_sums.append(imp.raw_sum_pct)
            implied_draw_sum += imp.fair_draw_pct
            implied_draw_cnt += 1

        cons = r.get("opening_consistency")
        if cons == "ah_shallow":
            shallow_n += 1
            if actual == "home":
                shallow_home += 1
        elif cons == "ah_deep":
            deep_n += 1
            if actual == "home":
                deep_home += 1
        elif cons == "aligned" and fav:
            aligned_n += 1
            if fav == actual:
                aligned_fav_hit += 1

        mv = r.get("line_move")
        if mv is not None:
            if mv < 0:
                line_up_n += 1
                if actual == "home":
                    line_up_home += 1
            elif mv > 0:
                line_down_n += 1
                if actual == "home":
                    line_down_home += 1

    fav_total = fav_hit + fav_miss
    draw_rate = _rate(draw_n, n)
    avg_implied_draw = round(implied_draw_sum / implied_draw_cnt, 1) if implied_draw_cnt else None
    avg_eu_sum = round(sum(eu_sums) / len(eu_sums), 2) if eu_sums else None

    stats = {
        "finished_matches": n,
        "favorite_hit_rate_pct": _rate(fav_hit, fav_total),
        "favorite_samples": fav_total,
        "upset_count": len(upsets),
        "draw_rate_pct": draw_rate,
        "avg_implied_draw_pct": avg_implied_draw,
        "avg_eu_implied_sum": avg_eu_sum,
        "shallow_home_win_pct": _rate(shallow_home, shallow_n) if shallow_n else None,
        "shallow_samples": shallow_n,
        "deep_home_win_pct": _rate(deep_home, deep_n) if deep_n else None,
        "deep_samples": deep_n,
        "aligned_fav_hit_pct": _rate(aligned_fav_hit, aligned_n) if aligned_n else None,
        "aligned_samples": aligned_n,
        "line_up_home_pct": _rate(line_up_home, line_up_n) if line_up_n else None,
        "line_up_samples": line_up_n,
        "line_down_home_pct": _rate(line_down_home, line_down_n) if line_down_n else None,
        "line_down_samples": line_down_n,
    }

    traits: list[str] = []
    if fav_total >= 3:
        hr = stats["favorite_hit_rate_pct"]
        traits.append(
            f"初盘欧赔最低项（热门）{fav_total} 场中打出 {fav_hit} 场，命中率 {hr}%"
            + ("，热门相对可靠" if hr and hr >= 55 else "，冷门比例偏高，需防诱盘")
        )
    if len(upsets) >= 1:
        traits.append(f"低赔热门被爆冷 {len(upsets)} 场" + (f"（如 {'、'.join(upsets[:3])}）" if upsets else ""))
    if draw_rate is not None and avg_implied_draw is not None:
        gap = draw_rate - avg_implied_draw
        if abs(gap) >= 5:
            traits.append(
                f"实际平局率 {draw_rate}% vs 初盘隐含 {avg_implied_draw}%"
                + ("，平局偏多" if gap > 0 else "，平局偏少")
            )
        elif draw_rate is not None:
            traits.append(f"平局率 {draw_rate}%，与初盘隐含 {avg_implied_draw}% 接近")
    if shallow_n >= 2:
        traits.append(
            f"亚盘偏浅 {shallow_n} 场，主胜打出 {shallow_home} 场（{stats['shallow_home_win_pct']}%）"
            " — 偏浅不等于稳胆，警惕诱上"
        )
    if deep_n >= 2:
        traits.append(
            f"亚盘偏深 {deep_n} 场，主胜打出 {deep_home} 场（{stats['deep_home_win_pct']}%）"
        )
    if aligned_n >= 2:
        traits.append(
            f"盘赔一致 {aligned_n} 场，低赔项打出 {aligned_fav_hit} 场（{stats['aligned_fav_hit_pct']}%）"
        )
    if line_up_n >= 2:
        traits.append(
            f"临盘升盘 {line_up_n} 场，主胜 {line_up_home} 场（{stats['line_up_home_pct']}%）"
        )
    if line_down_n >= 2:
        traits.append(
            f"临盘降盘 {line_down_n} 场，主胜 {line_down_home} 场（{stats['line_down_home_pct']}%）"
        )
    if avg_eu_sum:
        traits.append(f"初盘欧赔隐含概率和均值 {avg_eu_sum}%（正常约 102–110）")

    traits = _dedupe_traits(traits)

    summary_parts = [f"基于本届 {n} 场完赛样本："]
    if stats.get("favorite_hit_rate_pct") is not None:
        summary_parts.append(f"初盘热门打出率 {stats['favorite_hit_rate_pct']}%。")
    if stats.get("draw_rate_pct") is not None:
        summary_parts.append(f"平局占比 {stats['draw_rate_pct']}%。")
    if stats.get("upset_count"):
        summary_parts.append(f"共 {stats['upset_count']} 场低赔热门未打出。")
    if shallow_n:
        summary_parts.append(f"亚盘偏浅场次主胜率 {stats['shallow_home_win_pct']}%。")

    conclusions = build_opening_conclusions(
        sample_size=n,
        stats=stats,
        upset_matches=upsets,
        by_consistency=patterns.get("by_consistency") or {},
    )

    return {
        "sample_size": n,
        "summary": conclusions.get("headline") or "".join(summary_parts),
        "traits": traits[:8],
        "stats": stats,
        "upset_matches": upsets[:10],
        "conclusions": conclusions,
        **patterns,
    }


def _dedupe_traits(traits: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for t in traits:
        key = t.split("（")[0].split("，")[0][:20]
        if key not in seen:
            seen.add(key)
            out.append(t)
    return out


def build_tournament_ledger(
    output_root: str | Path,
    *,
    include_ai_watch: bool = False,
    ai_model: str | None = None,
    ai_base_url: str | None = None,
    force_ai_watch: bool = False,
) -> dict[str, Any]:
    root = Path(output_root)
    records = load_tournament_records(root)
    opening_patterns = compute_opening_characteristics(records)
    upcoming_watch = build_upcoming_opening_watch(root, hours=24, records=records)
    ai_watch = None
    if include_ai_watch:
        ai_watch = build_upcoming_ai_watch(
            root,
            opening_watch=upcoming_watch,
            opening_patterns=opening_patterns,
            records=records,
            ai_model=ai_model,
            ai_base_url=ai_base_url,
            force=force_ai_watch,
        )
    return {
        "tournament": TOURNAMENT,
        "leagues": list(DEFAULT_LEAGUES),
        "updated_at": now_beijing_str(),
        "accuracy": compute_accuracy_report(records),
        "opening_patterns": opening_patterns,
        "upcoming_opening_watch": upcoming_watch,
        "upcoming_ai_watch": ai_watch,
        "records": records,
    }


def save_tournament_ledger(
    output_root: str | Path,
    *,
    include_ai_watch: bool = False,
    ai_model: str | None = None,
    ai_base_url: str | None = None,
    force_ai_watch: bool = False,
) -> Path:
    root = Path(output_root)
    out_dir = root / "worldcup"
    out_dir.mkdir(parents=True, exist_ok=True)
    ledger = build_tournament_ledger(
        root,
        include_ai_watch=include_ai_watch,
        ai_model=ai_model,
        ai_base_url=ai_base_url,
        force_ai_watch=force_ai_watch,
    )
    path = out_dir / "ledger.json"
    path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def refresh_tournament_ledger(
    output_root: str | Path,
    *,
    include_ai_watch: bool = False,
    ai_model: str | None = None,
    ai_base_url: str | None = None,
    force_ai_watch: bool = False,
) -> dict[str, Any]:
    path = save_tournament_ledger(
        output_root,
        include_ai_watch=include_ai_watch,
        ai_model=ai_model,
        ai_base_url=ai_base_url,
        force_ai_watch=force_ai_watch,
    )
    log.info("世界杯账本已更新 → %s（%d 场）", path, len(load_tournament_records(output_root)))
    return build_tournament_ledger(
        output_root,
        include_ai_watch=include_ai_watch,
        ai_model=ai_model,
        ai_base_url=ai_base_url,
    )
