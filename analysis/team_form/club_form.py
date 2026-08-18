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


def _row_is_home(row: dict, aliases: set[str]) -> bool | None:
    """用别名集判断本场该队是主还是客；对不上返回 None。"""
    home = str(row.get("home_team") or "").strip()
    away = str(row.get("away_team") or "").strip()
    in_home = home in aliases
    in_away = away in aliases
    if in_home and not in_away:
        return True
    if in_away and not in_home:
        return False
    return None


def _summary_row(
    team: str,
    matches: list[dict],
    perspective: str,
    aliases: set[str] | None = None,
) -> dict:
    """汇总单队战绩。

    Args:
        team: 展示用队名
        matches: 该队参与的赛果列表（含 home_team/away_team/home_score/away_score/result_1x2 + 赔率）
        perspective: "home" | "away" | "all"
        aliases: 该队在库里可能出现的名字（中英文别名）；缺省只用展示名
    """
    alias_set = {str(x).strip() for x in (aliases or {team}) if str(x).strip()}
    alias_set.add(team)
    usable: list[tuple[bool, dict]] = []
    for m in matches:
        is_home = _row_is_home(m, alias_set)
        if is_home is None:
            continue
        usable.append((is_home, m))

    played = len(usable)
    if played == 0:
        return {"team": team, "played": 0, "w": 0, "d": 0, "l": 0,
                "goals_for": 0, "goals_against": 0, "win_rate": 0, "form_str": "",
                "summary_cn": f"{team}：近0场无数据"}

    w = d = l = 0
    gf = ga = 0
    form_chars: list[str] = []
    for is_home, m in usable:
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


def _sample_rows(
    team: str,
    matches: list[dict],
    perspective: str,
    max_n: int = 10,
    aliases: set[str] | None = None,
) -> list[dict]:
    """取该队近 N 场带 closing/opening 赔率的样本摘要（用于 UI 列表）。"""
    alias_set = {str(x).strip() for x in (aliases or {team}) if str(x).strip()}
    alias_set.add(team)
    samples: list[dict] = []
    for m in matches:
        if len(samples) >= max_n:
            break
        is_home = _row_is_home(m, alias_set)
        if is_home is None:
            continue
        my_score = m["home_score"] if is_home else m["away_score"]
        opp_score = m["away_score"] if is_home else m["home_score"]
        result = "W" if my_score > opp_score else ("D" if my_score == opp_score else "L")
        hs, aws = m.get("home_score"), m.get("away_score")
        samples.append({
            "date": str(m.get("kickoff_at", "") or "")[:10],
            "match": f"{m['home_team']} {hs}-{aws} {m['away_team']}",
            "is_home": is_home,
            "result": result,
            "home_score": hs,
            "away_score": aws,
            "closing_eu_home": _safe_float(m.get("closing_eu_home")),
            "closing_eu_draw": _safe_float(m.get("closing_eu_draw")),
            "closing_eu_away": _safe_float(m.get("closing_eu_away")),
            "opening_eu_home": _safe_float(m.get("closing_eu_open_home")),
            "opening_eu_draw": _safe_float(m.get("closing_eu_open_draw")),
            "opening_eu_away": _safe_float(m.get("closing_eu_open_away")),
            "closing_ah_line": m.get("closing_ah_line"),
            "closing_ah_home_water": _safe_float(m.get("closing_ah_home_water")),
            "closing_ah_away_water": _safe_float(m.get("closing_ah_away_water")),
        })
    return samples


_LEAGUE_MAP_CACHE: dict | None = None

# ESPN / football-data 常见写法，yaml 里没有的补丁
_EXTRA_ALIASES: dict[str, tuple[str, ...]] = {
    "东京绿茵": ("Tokyo Verdy 1969", "Tokyo Verdy"),
    "Tokyo Verdy 1969": ("东京绿茵", "Tokyo Verdy"),
    "Tokyo Verdy": ("东京绿茵", "Tokyo Verdy 1969"),
    "横滨水手": ("Yokohama F Marinos", "Yokohama F. Marinos"),
    "Yokohama F Marinos": ("Yokohama F. Marinos", "横滨水手"),
    "Yokohama F. Marinos": ("Yokohama F Marinos", "横滨水手"),
    "东京FC": ("FC Tokyo", "Tokyo FC"),
    "FC Tokyo": ("东京FC", "Tokyo FC"),
}


def _load_league_map() -> dict:
    """加载 jingcai_league_map.yaml（带缓存）。"""
    global _LEAGUE_MAP_CACHE
    if _LEAGUE_MAP_CACHE is not None:
        return _LEAGUE_MAP_CACHE
    try:
        import yaml
        from pathlib import Path
        here = Path(__file__).resolve()
        candidates = (
            Path("config/jingcai_league_map.yaml"),
            here.parents[2] / "config" / "jingcai_league_map.yaml",
        )
        p = next((c for c in candidates if c.exists()), None)
        if p is None:
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


def _aliases_for(team: str, league_name: str = "") -> list[str]:
    """该队在历史库里可能出现的全部名字（中文、英文、ESPN 变体）。"""
    raw = (team or "").strip()
    if not raw:
        return []
    resolved = _resolve_team_name(raw, league_name)
    names: set[str] = {raw, resolved}
    for info in _load_league_map().values():
        for cn, en in (info.get("teams") or {}).items():
            cn_s, en_s = str(cn).strip(), str(en).strip()
            if not cn_s or not en_s:
                continue
            if raw in (cn_s, en_s) or resolved in (cn_s, en_s):
                names.add(cn_s)
                names.add(en_s)
    for key in list(names):
        for alt in _EXTRA_ALIASES.get(key, ()):
            names.add(alt)
    return [n for n in names if n]


def _query_team_matches(team_names: list[str] | str, perspective: str, limit: int) -> list[dict]:
    """从 PG 查某队近 N 场赛果（带赔率）。team_names 为别名列表。"""
    try:
        from db.connection import cursor
    except ImportError:
        return []

    if isinstance(team_names, str):
        names = [team_names] if team_names.strip() else []
    else:
        names = [str(n).strip() for n in team_names if str(n).strip()]
    # 去重保序
    seen: set[str] = set()
    uniq: list[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            uniq.append(n)
    names = uniq
    if not names:
        return []

    if perspective == "home":
        where = "f.home_team = ANY(%s)"
        params: list = [names]
    elif perspective == "away":
        where = "f.away_team = ANY(%s)"
        params = [names]
    else:
        where = "(f.home_team = ANY(%s) OR f.away_team = ANY(%s))"
        params = [names, names]
    order_field = "f.kickoff_at"

    try:
        with cursor() as cur:
            cur.execute(
                f"""SELECT f.home_team, f.away_team, f.kickoff_at,
                           mr.home_score, mr.away_score, mr.result_1x2,
                           mr.closing_eu_home, mr.closing_eu_draw, mr.closing_eu_away,
                           mr.closing_eu_open_home, mr.closing_eu_open_draw, mr.closing_eu_open_away,
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
        log.warning("club_form query failed for %s: %s", names, exc)
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

    home_aliases = _aliases_for(home_team, league_name)
    away_aliases = _aliases_for(away_team, league_name)
    home_alias_set = set(home_aliases)
    away_alias_set = set(away_aliases)
    home_name_mapped = len(home_aliases) > 1
    away_name_mapped = len(away_aliases) > 1

    home_all = _query_team_matches(home_aliases, "all", window)
    away_all = _query_team_matches(away_aliases, "all", window)
    home_overall = _summary_row(home_team, home_all, "all", home_alias_set)
    away_overall = _summary_row(away_team, away_all, "all", away_alias_set)

    if not home_overall or home_overall.get("played", 0) == 0:
        reason = "队名未映射" if not home_name_mapped else "库无赛果"
        missing.append(f"home_overall({home_team}): {reason}")
    if not away_overall or away_overall.get("played", 0) == 0:
        reason = "队名未映射" if not away_name_mapped else "库无赛果"
        missing.append(f"away_overall({away_team}): {reason}")

    home_home = _query_team_matches(home_aliases, "home", split_n)
    away_away = _query_team_matches(away_aliases, "away", split_n)
    home_at_home = _summary_row(home_team, home_home, "home", home_alias_set)
    away_at_away = _summary_row(away_team, away_away, "away", away_alias_set)

    if not home_at_home or home_at_home.get("played", 0) == 0:
        reason = "队名未映射" if not home_name_mapped else "库无赛果/样本不足"
        missing.append(f"home_at_home({home_team}): {reason}")
    if not away_at_away or away_at_away.get("played", 0) == 0:
        reason = "队名未映射" if not away_name_mapped else "库无赛果/样本不足"
        missing.append(f"away_at_away({away_team}): {reason}")

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
            "away_at_away_last_20": away_at_away,
            "split_n": split_n,
        },
        "samples": {
            "home_all": _sample_rows(home_team, home_all, "all", aliases=home_alias_set),
            "away_all": _sample_rows(away_team, away_all, "all", aliases=away_alias_set),
            "home_at_home": _sample_rows(home_team, home_home, "home", aliases=home_alias_set),
            "away_at_away": _sample_rows(away_team, away_away, "away", aliases=away_alias_set),
        },
        "eu_coverage": {
            "home_all": _eu_ratio(home_all),
            "away_all": _eu_ratio(away_all),
        },
        "missing": missing,
    }
