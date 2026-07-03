"""Team recent match records — settled 2026 WC + openfootball + local DB + web search."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

VIEWING_FORM_LIMIT = 10
_DEFAULT_OUTPUT = Path(__file__).resolve().parent / "output" / "service"

_RESULT_CN = {"胜": "胜", "W": "胜", "win": "胜", "平": "平", "D": "平", "draw": "平", "负": "负", "L": "负", "loss": "负"}

_SCORE_IN_TEXT = re.compile(
    r"(?:(\d{4})[/-](\d{1,2})[/-](\d{1,2}))?\s*"
    r"(?:[^0-9]{0,12})?"
    r"(\d{1,2})\s*[-:：]\s*(\d{1,2})"
    r"(?:\s*(胜|平|负|战胜|战平|不敌|小胜|闷平|失利))?",
    re.I,
)

_SOURCE_RANK = {
    "settled": 0,
    "openfootball/2026": 1,
    "web_search": 2,
    "web_parse": 3,
    "国际赛/预选赛": 4,
}


def _short_date(date_str: str) -> str:
    s = str(date_str or "").strip()
    if len(s) >= 10 and s[4] == "-":
        return s[2:10]
    return s or "—"


def _parse_dt(raw: str) -> datetime | None:
    s = str(raw or "").strip()[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _infer_result(gf: int, ga: int, hint: str = "") -> str:
    h = str(hint or "").strip()
    if h in _RESULT_CN:
        return _RESULT_CN[h]
    if "平" in h or "draw" in h.lower():
        return "平"
    if "负" in h or "不敌" in h or "loss" in h.lower():
        return "负"
    if "胜" in h or "击败" in h or "win" in h.lower():
        return "胜"
    if gf > ga:
        return "胜"
    if gf == ga:
        return "平"
    return "负"


def _is_near_duplicate(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if _canonical_opponent(str(a.get("opponent") or "")) != _canonical_opponent(str(b.get("opponent") or "")):
        return False
    if str(a.get("score") or "") != str(b.get("score") or ""):
        return False
    da, db = _parse_dt(str(a.get("date") or "")), _parse_dt(str(b.get("date") or ""))
    if not da or not db:
        return False
    return abs((da - db).days) <= 1


def _canonical_opponent(name: str) -> str:
    from team_recent_form import canonical_team

    return canonical_team(str(name or "")) or str(name or "").strip()


def _match_key(m: dict[str, Any]) -> str:
    return f"{m.get('date')}|{m.get('score')}|{_canonical_opponent(str(m.get('opponent') or ''))}"


def _row_from_perspective(row: dict[str, Any], team_cn: str) -> dict[str, Any]:
    """Normalize openfootball/settled row to perspective match dict."""
    from team_recent_form import canonical_team

    team = canonical_team(team_cn)
    home_cn = canonical_team(str(row.get("home_cn") or row.get("home_raw") or ""))
    away_cn = canonical_team(str(row.get("away_cn") or row.get("away_raw") or ""))
    sh = int(row.get("score_h") or row.get("home_score") or 0)
    sa = int(row.get("score_a") or row.get("away_score") or 0)

    if row.get("opponent") and row.get("score") and row.get("result"):
        return {
            "date": row.get("date") or "—",
            "opponent": str(row.get("opponent")),
            "venue": str(row.get("venue") or "—"),
            "score": str(row.get("score")),
            "result": str(row.get("result")),
            "goals_for": int(row.get("goals_for") or 0),
            "goals_against": int(row.get("goals_against") or 0),
            "competition": row.get("competition") or row.get("source") or "",
            "source_rank": _SOURCE_RANK.get(str(row.get("competition") or row.get("source") or ""), 5),
        }

    is_home = team == home_cn
    if not is_home and team != away_cn:
        return {}
    if is_home:
        gf, ga, opp = sh, sa, row.get("away_raw") or row.get("away_cn") or away_cn
        venue = "主"
    else:
        gf, ga, opp = sa, sh, row.get("home_raw") or row.get("home_cn") or home_cn
        venue = "客"
    res = _infer_result(gf, ga)
    comp = str(row.get("competition") or row.get("source") or "")
    return {
        "date": str(row.get("date") or row.get("kickoff_at") or "—")[:10],
        "opponent": str(opp)[:20],
        "venue": venue,
        "score": f"{gf}-{ga}",
        "result": res,
        "goals_for": gf,
        "goals_against": ga,
        "competition": comp,
        "source_rank": _SOURCE_RANK.get(comp, 5),
    }


def _matches_from_settled(team_cn: str, *, output_root: Path | None = None) -> list[dict[str, Any]]:
    from share_card import split_teams
    from team_recent_form import canonical_team

    team = canonical_team(team_cn)
    root = output_root or _DEFAULT_OUTPUT
    if not root.is_dir():
        return []
    try:
        from match_settlement import load_settled_map
    except ImportError:
        return []

    out: list[dict[str, Any]] = []
    for settled in load_settled_map(root).values():
        name = str(settled.get("match_name") or "")
        home, away = split_teams(name)
        if team not in (canonical_team(home), canonical_team(away)):
            continue
        score_text = str(settled.get("score_text") or "")
        m = re.search(r"(\d+)\s*[-:：]\s*(\d+)", score_text)
        if not m:
            continue
        sh, sa = int(m.group(1)), int(m.group(2))
        is_home = team == canonical_team(home)
        row = _row_from_perspective({
            "date": str(settled.get("kickoff_at") or settled.get("settled_at") or "")[:10],
            "home_cn": canonical_team(home),
            "away_cn": canonical_team(away),
            "home_raw": home,
            "away_raw": away,
            "score_h": sh,
            "score_a": sa,
            "competition": "settled",
            "source": "settled",
        }, team)
        if row:
            row["source_rank"] = _SOURCE_RANK["settled"]
            out.append(row)
    return out


def _matches_from_openfootball(team_cn: str) -> list[dict[str, Any]]:
    from openfootball_intl import load_openfootball_matches
    from team_recent_form import canonical_team

    team = canonical_team(team_cn)
    out: list[dict[str, Any]] = []
    for raw in load_openfootball_matches():
        if team not in (canonical_team(raw.get("home_cn") or ""), canonical_team(raw.get("away_cn") or "")):
            continue
        if str(raw.get("date") or "—") == "—":
            continue
        row = _row_from_perspective({**raw, "competition": "openfootball/2026"}, team)
        if row:
            row["source_rank"] = _SOURCE_RANK["openfootball/2026"]
            out.append(row)
    return out


def _matches_from_local_db(
    team_cn: str,
    *,
    limit: int,
    reference_date: datetime | None,
) -> list[dict[str, Any]]:
    from datetime import timedelta

    from team_recent_form import (
        _load_international_matches,
        _perspective_row,
        _team_mask,
        canonical_team,
    )

    team = canonical_team(team_cn)
    df = _load_international_matches()
    if df.empty or not team:
        return []
    ref = reference_date or datetime.now()
    if hasattr(ref, "tzinfo") and ref.tzinfo is not None:
        ref = ref.replace(tzinfo=None)
    cutoff = ref - timedelta(days=900)
    recent = df[df["date"] >= cutoff]
    sub = recent[_team_mask(recent, team)].head(limit * 3)
    out: list[dict[str, Any]] = []
    for _, row in sub.iterrows():
        m = _perspective_row(row, team)
        row_dict = _row_from_perspective({**m, "competition": "国际赛/预选赛"}, team)
        if row_dict:
            row_dict["source_rank"] = _SOURCE_RANK["国际赛/预选赛"]
            out.append(row_dict)
        if len(out) >= limit:
            break
    return out


def parse_matches_from_text(text: str, *, team_cn: str = "") -> list[dict[str, Any]]:
    if not text:
        return []
    out: list[dict[str, Any]] = []
    for m in _SCORE_IN_TEXT.finditer(str(text)):
        y, mo, d, gf_s, ga_s = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
        hint = m.group(6) or ""
        try:
            gf, ga = int(gf_s), int(ga_s)
        except (TypeError, ValueError):
            continue
        if gf > 9 or ga > 9:
            continue
        date = "—"
        if y and mo and d:
            try:
                date = f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
            except ValueError:
                date = f"{y}-{mo}-{d}"
        res = _infer_result(gf, ga, hint)
        out.append({
            "date": date,
            "opponent": "—",
            "venue": "—",
            "score": f"{gf}-{ga}",
            "result": res,
            "goals_for": gf,
            "goals_against": ga,
            "competition": "web_parse",
            "source_rank": _SOURCE_RANK["web_parse"],
        })
    return out


@lru_cache(maxsize=96)
def search_team_recent_matches(team_cn: str, *, limit: int = VIEWING_FORM_LIMIT) -> tuple[tuple, ...]:
    team = (team_cn or "").strip()
    if not team:
        return tuple()
    try:
        from match_agents.web_lookup import search_web
    except ImportError:
        return tuple()

    queries = [
        f"{team} 2026 世界杯 小组赛 赛果",
        f"{team} 国家队 2026 最近比赛 战绩",
        f"{team} national team 2026 World Cup results",
    ]
    found: list[dict[str, Any]] = []
    for q in queries:
        hits, _logs = search_web(q, max_results=5)
        for hit in hits:
            blob = f"{hit.get('title') or ''} {hit.get('snippet') or ''}"
            for row in parse_matches_from_text(blob, team_cn=team):
                if _match_key(row) not in {_match_key(x) for x in found}:
                    found.append(row)
                if len(found) >= limit:
                    return tuple(found)
    return tuple(found)


def _merge_team_matches(
    team_cn: str,
    *,
    limit: int,
    output_root: Path | None,
    reference_date: datetime | None,
    use_search: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    buckets: list[dict[str, Any]] = []
    sources: list[str] = []

    settled = _matches_from_settled(team_cn, output_root=output_root)
    if settled:
        buckets.extend(settled)
        sources.append("已结算赛果")

    of_rows = _matches_from_openfootball(team_cn)
    if of_rows:
        buckets.extend(of_rows)
        sources.append("openfootball 2026")

    local = _matches_from_local_db(team_cn, limit=limit, reference_date=reference_date)
    if local:
        buckets.extend(local)
        if "预选赛/国际赛库" not in sources:
            sources.append("预选赛/国际赛库")

    if use_search:
        web = list(search_team_recent_matches(team_cn, limit=limit))
        if web:
            buckets.extend(web)
            sources.append("网页搜索")

    ref = reference_date
    filtered: list[dict[str, Any]] = []
    for m in buckets:
        dt = _parse_dt(str(m.get("date") or ""))
        if ref and dt and dt.date() > ref.date():
            continue
        filtered.append(m)

    def sort_key(m: dict[str, Any]) -> tuple:
        dt = _parse_dt(str(m.get("date") or "")) or datetime.min
        rank = int(m.get("source_rank") or 9)
        return (-dt.timestamp(), rank)

    filtered.sort(key=sort_key)

    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for m in filtered:
        key = _match_key(m)
        if key in seen:
            continue
        if any(_is_near_duplicate(m, x) for x in merged):
            continue
        seen.add(key)
        merged.append(m)
        if len(merged) >= limit:
            break

    return merged, sources


def build_viewing_notes_team_form(
    home_cn: str,
    away_cn: str,
    *,
    limit: int = VIEWING_FORM_LIMIT,
    use_search: bool = True,
    output_root: Path | str | None = None,
    reference_date: str | datetime | None = None,
) -> dict[str, Any]:
    """Merge settled 2026 WC + openfootball + local qualifiers + web search."""
    from team_recent_form import build_team_recent_form, canonical_team

    home = canonical_team(home_cn) or home_cn
    away = canonical_team(away_cn) or away_cn
    root = Path(output_root) if output_root else _DEFAULT_OUTPUT
    ref = _parse_dt(reference_date) if isinstance(reference_date, str) else reference_date

    home_matches, home_src = _merge_team_matches(
        home, limit=limit, output_root=root, reference_date=ref, use_search=use_search,
    )
    away_matches, away_src = _merge_team_matches(
        away, limit=limit, output_root=root, reference_date=ref, use_search=use_search,
    )
    all_sources = sorted(set(home_src + away_src))

    local = build_team_recent_form(home, away, max_matches=3, days=900, reference_date=ref)

    def _pack(team: str, matches: list[dict]) -> dict[str, Any]:
        wins = sum(1 for m in matches if m.get("result") == "胜")
        draws = sum(1 for m in matches if m.get("result") == "平")
        losses = sum(1 for m in matches if m.get("result") == "负")
        gf = sum(int(m.get("goals_for") or 0) for m in matches)
        ga = sum(int(m.get("goals_against") or 0) for m in matches)
        n = len(matches)
        wc_n = sum(1 for m in matches if str(m.get("date") or "").startswith("2026-06"))
        summary = (
            f"{wins}胜{draws}平{losses}负 · 进{gf}失{ga}"
            + (f" · 含{wc_n}场2026世界杯" if wc_n else "")
            if n else f"{team}：暂无近{limit}场记录"
        )
        rows = [{
            "date": _short_date(m.get("date")),
            "opponent": _canonical_opponent(str(m.get("opponent") or ""))[:12] or str(m.get("opponent") or "—")[:12],
            "venue": str(m.get("venue") or "—"),
            "score": str(m.get("score") or "—"),
            "result": str(m.get("result") or "—"),
        } for m in matches[:limit]]
        return {"team": team, "summary": summary, "matches": rows, "count": n}

    return {
        "home": _pack(home, home_matches),
        "away": _pack(away, away_matches),
        "head_to_head": local.get("head_to_head") or [],
        "available": bool(home_matches or away_matches),
        "data_source": " · ".join(all_sources) if all_sources else "暂无数据",
        "limit": limit,
    }
