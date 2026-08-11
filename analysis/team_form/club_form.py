"""P2: 俱乐部战绩引擎。

数据源：match_results JOIN fixtures（PG）→ 带赔率的历史赛果。
窗口：20|30|50（默认 30）。
维度：
  - overall: 两队近 N 场（全部）
  - split: 主队近 20 主场 + 客队近 20 客场

无数据 → missing，不崩；不假造。
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def _safe_float(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _summary_row(team: str, matches: list[dict], perspective: str) -> dict:
    """汇总单队战绩。

    Args:
        team: 队名
        matches: 该队参与的赛果列表（含 home_team/away_team/home_score/away_score/result_1x2 + 赔率）
        perspective: "home" | "away" | "all"
    """
    played = len(matches)
    if played == 0:
        return {"team": team, "played": 0, "w": 0, "d": 0, "l": 0,
                "goals_for": 0, "goals_against": 0, "win_rate": 0, "form_str": "",
                "summary_cn": f"{team}：近0场无数据"}

    w = d = l = 0
    gf = ga = 0
    form_chars: list[str] = []
    for m in matches:
        is_home = m["home_team"] == team
        my_score = m["home_score"] if is_home else m["away_score"]
        opp_score = m["away_score"] if is_home else m["home_score"]
        gf += my_score
        ga += opp_score
        if my_score > opp_score:
            w += 1
            form_chars.append("胜")
        elif my_score == opp_score:
            d += 1
            form_chars.append("平")
        else:
            l += 1
            form_chars.append("负")

    form_str = "".join(form_chars[:10])  # 最近10场
    win_rate = w / played if played > 0 else 0
    venue_cn = {"home": "主场", "away": "客场", "all": "全部"}[perspective]
    return {
        "team": team,
        "played": played,
        "w": w, "d": d, "l": l,
        "goals_for": gf, "goals_against": ga,
        "win_rate": round(win_rate, 3),
        "form_str": form_str,
        "summary_cn": f"{team}：近{played}场{venue_cn} {w}胜{d}平{l}负（胜率{win_rate:.0%}）",
    }


_LEAGUE_MAP_CACHE: dict | None = None


def _load_league_map() -> dict:
    """加载 jingcai_league_map.yaml（带缓存）。"""
    global _LEAGUE_MAP_CACHE
    if _LEAGUE_MAP_CACHE is not None:
        return _LEAGUE_MAP_CACHE
    try:
        import yaml
        from pathlib import Path
        p = Path("config/jingcai_league_map.yaml")
        if not p.exists():
            _LEAGUE_MAP_CACHE = {}
            return _LEAGUE_MAP_CACHE
        data = yaml.safe_load(p.read_text())
        _LEAGUE_MAP_CACHE = data.get("leagues") or {}
        return _LEAGUE_MAP_CACHE
    except Exception:
        _LEAGUE_MAP_CACHE = {}
        return _LEAGUE_MAP_CACHE


def _resolve_team_name(team: str, league_name: str = "") -> str:
    """通过 jingcai_league_map 映射中文别名 → 历史库名。

    优先在 league_name 对应联赛的 teams 子表查找；
    找不到则全局搜索所有联赛的 teams 子表。
    """
    leagues = _load_league_map()

    # 1. 优先在指定联赛的 teams 里查
    if league_name and league_name in leagues:
        teams = leagues[league_name].get("teams") or {}
        if team in teams:
            return teams[team]

    # 2. 全局搜索所有联赛的 teams
    for league_info in leagues.values():
        teams = league_info.get("teams") or {}
        if team in teams:
            return teams[team]

    # 3. 原样返回（可能是英文名或未映射）
    return team


def _query_team_matches(team: str, perspective: str, limit: int) -> list[dict]:
    """从 PG 查某队近 N 场赛果（带赔率）。"""
    try:
        from db.connection import cursor
    except ImportError:
        return []

    if perspective == "home":
        where = "f.home_team = %s"
        order_field = "f.kickoff_at"
    elif perspective == "away":
        where = "f.away_team = %s"
        order_field = "f.kickoff_at"
    else:
        where = "(f.home_team = %s OR f.away_team = %s)"
        order_field = "f.kickoff_at"

    params: list = [team] if perspective != "all" else [team, team]

    try:
        with cursor() as cur:
            cur.execute(
                f"""SELECT f.home_team, f.away_team, f.kickoff_at,
                           mr.home_score, mr.away_score, mr.result_1x2,
                           mr.closing_eu_home, mr.closing_eu_draw, mr.closing_eu_away,
                           mr.closing_ah_line, mr.closing_ah_home_water, mr.closing_ah_away_water
                    FROM match_results mr
                    JOIN fixtures f ON f.id = mr.fixture_id
                    WHERE {where}
                      AND mr.home_score IS NOT NULL
                    ORDER BY {order_field} DESC
                    LIMIT %s""",
                (*params, limit),
            )
            rows = cur.fetchall()
            return [dict(r) for r in rows]
    except Exception as exc:
        log.warning("club_form query failed for %s: %s", team, exc)
        return []


def build_club_form(
    home_team: str,
    away_team: str,
    *,
    window: int = 30,
    split_n: int = 20,
    league_name: str = "",
) -> dict[str, Any]:
    """构建两队战绩上下文。

    Args:
        home_team: 主队名
        away_team: 客队名
        window: overall 窗口（20|30|50，默认 30）
        split_n: 主队主场/客队客场各取 N 场（默认 20）
        league_name: 联赛名（用于 jingcai_league_map 映射）

    Returns:
        {overall: {home_team, away_team}, split: {home_at_home_last_N, away_at_away_last_N}, missing}
    """
    missing: list[str] = []

    # FIX-3: 通过联赛映射表解析中文别名
    home_resolved = _resolve_team_name(home_team, league_name)
    away_resolved = _resolve_team_name(away_team, league_name)

    # Overall
    home_all = _query_team_matches(home_resolved, "all", window)
    away_all = _query_team_matches(away_resolved, "all", window)
    home_overall = _summary_row(home_team, home_all, "all") if home_all else None
    away_overall = _summary_row(away_team, away_all, "all") if away_all else None

    if not home_overall:
        missing.append(f"home_overall({home_team})")
    if not away_overall:
        missing.append(f"away_overall({away_team})")

    # Split: 主队主场 / 客队客场
    home_home = _query_team_matches(home_resolved, "home", split_n)
    away_away = _query_team_matches(away_resolved, "away", split_n)
    home_at_home = _summary_row(home_team, home_home, "home") if home_home else None
    away_at_away = _summary_row(away_team, away_away, "away") if away_away else None

    if not home_at_home:
        missing.append(f"home_at_home({home_team})")
    if not away_at_away:
        missing.append(f"away_at_away({away_team})")

    # 样本带赔率比例
    def _eu_ratio(matches: list[dict]) -> float:
        if not matches:
            return 0
        with_eu = sum(1 for m in matches if _safe_float(m.get("closing_eu_home")))
        return with_eu / len(matches)

    return {
        "overall": {
            "home_team": home_overall,
            "away_team": away_overall,
            "window": window,
        },
        "split": {
            "home_at_home_last_20": home_at_home,
            "away_at_away_last_20": away_away,
            "split_n": split_n,
        },
        "eu_coverage": {
            "home_all": _eu_ratio(home_all),
            "away_all": _eu_ratio(away_all),
        },
        "missing": missing,
    }
