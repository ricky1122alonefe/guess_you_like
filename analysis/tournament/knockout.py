"""Knockout bracket paths and opponent-picking incentive analysis for WC 2026."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

BRACKET_PATH = _PROJECT_ROOT / "data" / "wc2026_knockout_bracket.json"
GROUPS_PATH = _PROJECT_ROOT / "data" / "wc2026_groups.json"

TIER_SCORE = {"elite": 5, "strong": 4, "mid": 2, "weak": 1}


def _load_bracket() -> dict:
    return json.loads(BRACKET_PATH.read_text(encoding="utf-8"))


def _load_groups_config() -> dict:
    return json.loads(GROUPS_PATH.read_text(encoding="utf-8"))


def slot_label(group: str, rank: int) -> str:
    if rank == 1:
        return f"1{group}"
    if rank == 2:
        return f"2{group}"
    return f"3rd-{group}"


def _matches_for_slot(slot: str, bracket: dict | None = None) -> list[dict]:
    """Find R32 matches where a team with this slot appears."""
    bracket = bracket or _load_bracket()
    out: list[dict] = []

    if slot.startswith("3rd-"):
        g = slot[4:]
        for m in bracket.get("r32") or []:
            pool = m.get("third_pool") or []
            if "3rd" in (m.get("home"), m.get("away")) and g in pool:
                out.append(m)
        return out

    for m in bracket.get("r32") or []:
        if m.get("home") == slot or m.get("away") == slot:
            out.append(m)
    return out


def _opponent_slot_for_fixed_match(slot: str, match: dict) -> str:
    home, away = match.get("home"), match.get("away")
    if home == slot:
        return away if away != "3rd" else f"最佳第三({''.join(match.get('third_pool') or [])})"
    if away == slot:
        return home
    if slot.startswith("3rd-"):
        g = slot[4:]
        if match.get("away") == "3rd" and g in (match.get("third_pool") or []):
            return match.get("home") or "?"
        if match.get("home") == "3rd" and g in (match.get("third_pool") or []):
            return match.get("away") or "?"
    return "?"


def _estimate_slot_difficulty(opponent_slot: str, tiers: dict[str, str], groups: dict) -> float:
    if opponent_slot.startswith("最佳第三"):
        return 3.0
    if opponent_slot.startswith("3rd"):
        return 2.8
    if len(opponent_slot) >= 2 and opponent_slot[0] in "12":
        rank = int(opponent_slot[0])
        grp = opponent_slot[1:]
        teams = groups.get(grp) or []
        if not teams:
            return 3.0
        if rank == 1:
            t = teams[0] if teams else ""
        else:
            t = teams[1] if len(teams) > 1 else teams[0]
        tier = tiers.get(t, "mid")
        return float(TIER_SCORE.get(tier, 2))
    return 3.0


def path_for_rank(
    group: str,
    rank: int,
    *,
    bracket: dict | None = None,
    tiers: dict | None = None,
    groups: dict | None = None,
) -> dict[str, Any]:
    """Describe R32 path if team finishes rank (1/2/3) in group."""
    bracket = bracket or _load_bracket()
    cfg = _load_groups_config()
    tiers = tiers or cfg.get("team_strength_tiers") or {}
    groups = groups or cfg.get("groups") or {}

    slot = slot_label(group, rank)
    if rank == 3:
        matches = _matches_for_slot(f"3rd-{group}", bracket)
    else:
        matches = _matches_for_slot(slot, bracket)

    if rank == 3:
        pools = []
        for m in matches:
            pools.append({
                "match": m.get("match"),
                "label": m.get("label"),
                "opponent": m.get("home") if m.get("away") == "3rd" else m.get("away"),
                "pool": m.get("third_pool"),
            })
        narrow = group in ("K", "L")
        return {
            "rank": rank,
            "rank_cn": "小组第三(若进最佳8)",
            "slot": slot,
            "r32_matches": pools,
            "r32_summary": (
                f"若晋级最佳8第三：可能进入 {len(pools)} 个签位池之一（赛后按FIFA表锁定）"
            ),
            "difficulty_score": 3.0,
            "narrow_path": narrow,
            "narrow_note": (
                f"{'K组第三仅可能对1K(M88)' if group == 'K' else 'L组第三仅可能对1L(M80)' if group == 'L' else ''}"
            ) if narrow else "",
        }

    if not matches:
        return {"rank": rank, "slot": slot, "r32_summary": "—", "difficulty_score": 3.0}

    m = matches[0]
    fixed = f"{rank}{group}"
    opp_slot = _opponent_slot_for_fixed_match(fixed, m)
    diff = _estimate_slot_difficulty(opp_slot, tiers, groups)
    r16_hint = _r16_path_hint(m.get("match"))

    return {
        "rank": rank,
        "rank_cn": "小组第一" if rank == 1 else "小组第二",
        "slot": slot,
        "r32_match": m.get("match"),
        "r32_label": m.get("label"),
        "r32_opponent_slot": opp_slot,
        "r32_summary": f"M{m.get('match')} {m.get('label')}",
        "r16_hint": r16_hint,
        "difficulty_score": diff,
        "bracket_half": _bracket_half(group, bracket),
    }


def _bracket_half(group: str, bracket: dict) -> str:
    halves = bracket.get("bracket_halves") or {}
    if group in (halves.get("upper") or []):
        return "upper"
    if group in (halves.get("lower") or []):
        return "lower"
    return "unknown"


def _r16_path_hint(r32_match: int | None) -> str:
    if not r32_match:
        return "—"
    bracket = _load_bracket()
    for r16 in bracket.get("r16") or []:
        h, a = r16.get("home", ""), r16.get("away", "")
        if f"W{r32_match}" in (h, a):
            other = a if h == f"W{r32_match}" else h
            return f"若晋级16强 → M{r16.get('match')} 对阵 {other} 的胜者"
    return "—"


def bracket_flow_steps(path: dict) -> list[dict[str, str]]:
    """Turn a rank path into display steps for the mini bracket UI."""
    rank_cn = path.get("rank_cn") or ""
    if path.get("r32_matches"):
        pools = path.get("r32_matches") or []
        labels = " / ".join(f"M{p.get('match')}" for p in pools[:3])
        suffix = "…" if len(pools) > 3 else ""
        return [
            {"stage": "group", "label": rank_cn},
            {"stage": "r32", "label": f"32强 · {len(pools)}个可能签位 {labels}{suffix}"},
            {"stage": "note", "label": path.get("narrow_note") or "赛后按FIFA表锁定"},
        ]

    steps = [{"stage": "group", "label": rank_cn}]
    r32 = path.get("r32_summary") or path.get("r32_label") or "—"
    steps.append({"stage": "r32", "label": f"32强 · {r32}"})
    r16 = path.get("r16_hint") or ""
    if r16 and r16 != "—":
        steps.append({"stage": "r16", "label": r16.replace("若晋级16强 → ", "16强 · ")})
    half = path.get("bracket_half")
    if half in ("upper", "lower"):
        steps.append({"stage": "half", "label": "上半区" if half == "upper" else "下半区"})
    return steps


def build_group_bracket_overview(group: str) -> dict[str, Any]:
    """Fixed R32 slots for a group (detail page bracket strip)."""
    bracket = _load_bracket()
    return {
        "group": group,
        "first": path_for_rank(group, 1, bracket=bracket),
        "second": path_for_rank(group, 2, bracket=bracket),
        "third_pools": path_for_rank(group, 3, bracket=bracket).get("r32_matches") or [],
    }


def analyze_opponent_picking(
    team: str,
    group: str,
    *,
    standings_row: dict | None = None,
    remaining_rounds: int = 2,
) -> dict[str, Any]:
    """Compare incentives for finishing 1st vs 2nd vs 3rd."""
    cfg = _load_groups_config()
    tiers = cfg.get("team_strength_tiers") or {}
    tier = tiers.get(team, "mid")

    p1 = path_for_rank(group, 1)
    p2 = path_for_rank(group, 2)
    p3 = path_for_rank(group, 3)

    scores = {1: p1["difficulty_score"], 2: p2["difficulty_score"], 3: p3["difficulty_score"]}
    easiest = min(scores, key=scores.get)
    hardest = max(scores, key=scores.get)

    notes: list[str] = []
    picking_level = "low"

    if scores[1] > scores[2] + 0.8:
        notes.append(
            f"小组第二路径(M{p2.get('r32_match')})对手强度低于第一(M{p1.get('r32_match')})，"
            "存在控分争第二/避免强敌的动机（挑对手嫌疑）。"
        )
        picking_level = "medium"
    elif scores[2] > scores[1] + 0.8:
        notes.append("小组第一路径相对更优，领先时会倾向拿满分数确保头名。")

    if p3.get("narrow_path"):
        notes.append(p3.get("narrow_note") or "")
        if remaining_rounds <= 1:
            picking_level = "medium"

    pts = (standings_row or {}).get("points", 0)
    played = (standings_row or {}).get("played", 0)
    if pts >= 3 and played >= 1 and remaining_rounds >= 1:
        notes.append(
            "已胜一场且仍有2轮：若头名路径碰更强2档对手，末轮可能接受小胜/平局保住出线而非强攻穿盘。"
        )
        if picking_level == "low":
            picking_level = "watch"

    if tier in ("elite", "strong") and pts >= 3:
        notes.append("强队领先后的控节奏与穿盘风险需同步考虑，不等于放水。")

    preferred_rank_cn = {1: "小组第一", 2: "小组第二", 3: "小组第三(若进最佳8)"}[easiest]

    return {
        "team": team,
        "group": group,
        "picking_level": picking_level,
        "picking_level_cn": {"low": "低", "watch": "观察", "medium": "中等", "high": "较高"}.get(picking_level, "低"),
        "paths": {"first": p1, "second": p2, "third": p3},
        "easiest_path_rank": easiest,
        "preferred_path_cn": preferred_rank_cn,
        "notes": notes or ["当前路径差异不大，战意仍以抢分/守平为主。"],
    }


def project_scenarios(
    home: str,
    away: str,
    group: str,
    *,
    home_pts: int,
    away_pts: int,
    home_played: int,
    away_played: int,
) -> list[dict[str, Any]]:
    """Win/draw/loss effect on points and rough rank goal."""
    scenarios = []
    for label, hp, ap in (("主胜", 3, 0), ("平局", 1, 1), ("客胜", 0, 3)):
        nh, na = home_pts + hp, away_pts + ap
        scenarios.append({
            "label": label,
            "score_effect": f"{home} {nh}分 · {away} {na}分",
            "home_after": nh,
            "away_after": na,
            "note": _scenario_note(home, away, nh, na, home_played + 1),
        })
    return scenarios


def _scenario_note(home: str, away: str, hp: int, ap: int, played: int) -> str:
    rem = max(0, 3 - played)
    if hp >= 6:
        return f"{home} 接近锁定出线，后程可能控节奏"
    if ap >= 6:
        return f"{away} 接近锁定出线"
    if hp == 0 and rem <= 1:
        return f"{home} 出线告急，必须抢分"
    if ap == 0 and rem <= 1:
        return f"{away} 出线告急"
    if hp == ap and hp >= 4:
        return "双方同分高位，平局可能同时满意"
    return "积分争夺继续"


def build_match_knockout_context(match_name: str) -> dict[str, Any] | None:
    """Knockout stage context for match analysis (no group-stage dependencies)."""
    from share_card import split_teams
    from wc_standings_fetch import normalize_team

    home_raw, away_raw = split_teams(match_name or "")
    if not home_raw:
        return None

    home = normalize_team(home_raw)
    away = normalize_team(away_raw)

    bracket = _load_bracket()
    
    # 识别淘汰赛轮次
    knockout_round = _detect_knockout_round(match_name, bracket)
    if not knockout_round:
        return None

    # 获取两队的淘汰赛路径信息
    home_path = _team_knockout_path(home, bracket)
    away_path = _team_knockout_path(away, bracket)

    # 分析对阵双方的路径差异和挑对手动机
    picking_level = "low"
    picking_notes: list[str] = []
    
    if home_path and away_path:
        home_diff = home_path.get("difficulty_score", 3.0)
        away_diff = away_path.get("difficulty_score", 3.0)
        diff_gap = abs(home_diff - away_diff)
        
        if diff_gap >= 1.5:
            picking_level = "high"
            easier_team = home if home_diff < away_diff else away
            picking_notes.append(f"{easier_team}的淘汰赛路径明显更容易，存在控分/挑对手动机")
        elif diff_gap >= 0.8:
            picking_level = "medium"
            picking_notes.append("双方路径难度有差异，需关注战术选择")

    # 生成预测提示
    prediction_hint = _knockout_prediction_hint(
        home_path, away_path, picking_level, knockout_round
    )

    # 构建情景分析（淘汰赛版本）
    scenarios = _knockout_scenarios(home, away, knockout_round)

    return {
        "knockout_round": knockout_round,
        "knockout_round_cn": {
            "r32": "32强", "r16": "16强", "qf": "8强", 
            "sf": "4强", "final": "决赛", "third": "季军赛"
        }.get(knockout_round, knockout_round),
        "home_knockout": home_path,
        "away_knockout": away_path,
        "picking_level": picking_level,
        "picking_level_cn": {
            "low": "低", "watch": "观察", "medium": "中等", "high": "较高"
        }.get(picking_level, "低"),
        "picking_notes": picking_notes,
        "prediction_hint": prediction_hint,
        "scenarios": scenarios,
        "bracket_notes": bracket.get("notes") or [],
    }


def _detect_knockout_round(match_name: str, bracket: dict) -> str | None:
    """Detect which knockout round this match belongs to.
    
    match_name is like "巴西 VS 阿根廷" (team names).
    bracket uses slot labels like "2A", "1C", "W73" etc.
    We match by finding teams' group slots in R32, or by
    checking if both teams exist in the tournament config.
    """
    from share_card import split_teams
    from wc_standings_fetch import normalize_team

    home_raw, away_raw = split_teams(match_name or "")
    if not home_raw:
        return None

    home = normalize_team(home_raw)
    away = normalize_team(away_raw)

    cfg = _load_groups_config()
    team_to_group: dict[str, str] = {}
    for g, teams in (cfg.get("groups") or {}).items():
        for t in teams:
            team_to_group[t] = g

    home_group = team_to_group.get(home)
    away_group = team_to_group.get(away)

    # 如果两队都不在小组赛配置中，不是世界杯比赛
    if not home_group and not away_group:
        return None

    # 尝试通过小组签位匹配 R32
    for m in bracket.get("r32") or []:
        h_slot = m.get("home") or ""
        a_slot = m.get("away") or ""
        # 检查主队签位是否匹配
        home_match = False
        away_match = False
        if home_group:
            for rank in (1, 2, 3):
                sl = slot_label(home_group, rank)
                if sl == h_slot or (rank == 3 and home_group in (m.get("third_pool") or []) and "3rd" in h_slot):
                    home_match = True
                if sl == a_slot or (rank == 3 and home_group in (m.get("third_pool") or []) and "3rd" in a_slot):
                    home_match = True
        if away_group:
            for rank in (1, 2, 3):
                sl = slot_label(away_group, rank)
                if sl == h_slot or (rank == 3 and away_group in (m.get("third_pool") or []) and "3rd" in h_slot):
                    away_match = True
                if sl == a_slot or (rank == 3 and away_group in (m.get("third_pool") or []) and "3rd" in a_slot):
                    away_match = True
        if home_match and away_match:
            return "r32"

    # 两队都在锦标赛中但不在 R32 直接匹配 → 可能是 R16 及以后的轮次
    # 尝试通过 fixture 数据或 match_name 中的轮次关键词推断
    name_lower = (match_name or "").lower()
    if any(kw in name_lower for kw in ("决赛", "final")):
        return "final"
    if any(kw in name_lower for kw in ("季军", "third")):
        return "third"
    if any(kw in name_lower for kw in ("半决赛", "semi")):
        return "sf"
    if any(kw in name_lower for kw in ("1/4", "四分之一", "quarter")):
        return "qf"
    if any(kw in name_lower for kw in ("1/8", "八分之一", "round of 16")):
        return "r16"

    # 两队都是参赛队伍但无法精确匹配轮次 → 默认 R16（最常见的淘汰赛分析场景）
    if home_group and away_group:
        return "r16"

    return None


def _team_knockout_path(team: str, bracket: dict) -> dict[str, Any] | None:
    """Get knockout path info for a team (simplified for knockout phase)."""
    cfg = _load_groups_config()
    tiers = cfg.get("team_strength_tiers") or {}
    tier = tiers.get(team, "mid")
    
    # 查找队伍所在小组
    team_group = None
    for g, teams in (cfg.get("groups") or {}).items():
        if team in teams:
            team_group = g
            break
    
    if not team_group:
        return None
    
    # 获取该小组各排名的路径
    p1 = path_for_rank(team_group, 1, bracket=bracket)
    p2 = path_for_rank(team_group, 2, bracket=bracket)
    p3 = path_for_rank(team_group, 3, bracket=bracket)
    
    # 判断最可能路径
    scores = {1: p1["difficulty_score"], 2: p2["difficulty_score"], 3: p3["difficulty_score"]}
    easiest = min(scores, key=scores.get)
    
    notes = []
    if scores[1] > scores[2] + 0.8:
        notes.append("小组第二路径优于第一，可能存在控分动机")
    elif scores[2] > scores[1] + 0.8:
        notes.append("小组第一路径更优，确保头名是优先策略")
    
    return {
        "team": team,
        "group": team_group,
        "tier": tier,
        "paths": {"first": p1, "second": p2, "third": p3},
        "easiest_path_rank": easiest,
        "preferred_path_cn": {1: "小组第一", 2: "小组第二", 3: "小组第三(若进最佳8)"}.get(easiest),
        "difficulty_score": scores[easiest],
        "notes": notes or ["路径差异不大，按正常节奏比赛"],
    }


def _knockout_prediction_hint(
    home_path: dict | None,
    away_path: dict | None,
    picking_level: str,
    knockout_round: str,
) -> dict[str, Any]:
    """Generate prediction hints for knockout matches."""
    notes = []
    
    if picking_level in ("medium", "high"):
        notes.append("淘汰赛路径差异可能影响战术选择，关注保守/激进策略")
    
    if knockout_round in ("r16", "qf"):
        notes.append("淘汰赛早期轮次，加时/点球概率较高")
    elif knockout_round in ("sf", "final"):
        notes.append("淘汰赛关键轮次，双方都会全力以赴")
    
    draw_bias = 0.0
    if picking_level in ("medium", "high"):
        draw_bias = 0.06 if picking_level == "medium" else 0.08
    
    return {
        "model_1x2_hint": "draw" if draw_bias > 0.05 else "none",
        "draw_bias": draw_bias,
        "picking_note": "存在挑对手/控分可能，优先防平局与小比分" if picking_level in ("medium", "high") else "",
        "notes": notes[:3],
    }


def _knockout_scenarios(home: str, away: str, knockout_round: str) -> list[dict[str, Any]]:
    """Generate knockout-specific scenarios."""
    scenarios = []
    
    round_cn = {
        "r32": "32强", "r16": "16强", "qf": "8强", 
        "sf": "4强", "final": "决赛"
    }.get(knockout_round, knockout_round)
    
    scenarios.append({
        "label": "常规时间",
        "note": f"淘汰赛{round_cn}，90分钟内解决战斗是首选",
    })
    
    scenarios.append({
        "label": "加时赛",
        "note": "淘汰赛加时概率约30-35%，需关注体能和替补深度",
    })
    
    scenarios.append({
        "label": "点球大战",
        "note": "若进入点球，心理素质和门将表现成为关键",
    })
    
    return scenarios


def _combined_prediction_hint(
    motivation: dict | None,
    home_pick: dict,
    away_pick: dict,
    picking_level: str,
) -> dict[str, Any]:
    mt = (motivation or {}).get("match_type_cn") or "常规"
    likely = (motivation or {}).get("likely_direction_cn") or "按盘口"
    ah = (motivation or {}).get("ah_hint") or ""

    draw_up = (motivation or {}).get("match_type") in (
        "collusion_watch", "draw_friendly", "open_race",
    )
    pick_1x2 = "draw" if draw_up else (motivation or {}).get("model_pick_hint") or "none"

    notes = list((motivation or {}).get("reasoning") or [])[:2]
    if picking_level in ("medium", "watch"):
        notes.extend((home_pick.get("notes") or [])[:1])
        notes.extend((away_pick.get("notes") or [])[:1])

    return {
        "match_type_cn": mt,
        "likely_direction_cn": likely,
        "model_1x2_hint": pick_1x2,
        "draw_bias": 0.08 if picking_level in ("medium", "high", "watch") and draw_up else (
            0.06 if picking_level in ("medium", "watch") else 0.0
        ),
        "ah_hint": ah or "热门谨慎追让" if picking_level != "low" else ah,
        "picking_note": "存在挑对手/控分可能，优先防平局与小比分" if picking_level in ("medium", "high", "watch") else "",
        "summary": f"{mt} · {likely}" + (f" · {ah}" if ah else ""),
        "notes": notes[:4],
    }
