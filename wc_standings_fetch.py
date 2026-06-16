"""Fetch World Cup 2026 group standings & fixtures from liansai.500.com."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from download_500 import _decode, _session

log = logging.getLogger(__name__)

WC_STAGE_ID = 26226
WC_STANDINGS_URL = f"https://liansai.500.com/zuqiu-19476/jifen-{WC_STAGE_ID}/"
WC_MATCH_API = "https://liansai.500.com/index.php"
GROUPS = tuple("ABCDEFGHIJKL")
# 500 API: 5=完场, 1=未赛, 3=进行中(推测)
STATUS_FINISHED = {5, 4}


@dataclass
class GroupStanding:
    group: str
    rank: int
    team: str
    played: int
    won: int
    drawn: int
    lost: int
    gf: int
    ga: int
    gd: int
    points: int
    form: str = ""


@dataclass
class GroupFixture:
    fixture_id: str
    group: str
    round: int
    kickoff: str
    home: str
    away: str
    home_score: int | None
    away_score: int | None
    status: int
    eu_home: float | None = None
    eu_draw: float | None = None
    eu_away: float | None = None

    @property
    def match_name(self) -> str:
        return f"{self.home}VS{self.away}"

    @property
    def is_finished(self) -> bool:
        return self.status in STATUS_FINISHED and self.home_score is not None

    @property
    def score_text(self) -> str | None:
        if self.home_score is None or self.away_score is None:
            return None
        return f"{self.home_score}-{self.away_score}"


def _load_aliases() -> dict[str, str]:
    """Map variant team names → canonical name from data/wc2026_groups.json."""
    path = Path(__file__).resolve().parent / "data" / "wc2026_groups.json"
    canon: dict[str, str] = {}
    if not path.is_file():
        return canon
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return canon
    for team in data.get("groups", {}).values():
        for t in team:
            canon[t] = t
    for canonical, aliases in (data.get("aliases") or {}).items():
        canon[canonical] = canonical
        for a in aliases:
            canon[a] = canonical
    extra = {
        "民主刚果": "刚果(金)",
        "乌兹别克斯坦": "乌兹别克",
        "沙特": "沙特",
        "沙特阿拉伯": "沙特",
        "库拉索": "库拉索",
        "Curaçao": "库拉索",
    }
    canon.update(extra)
    return canon


_ALIASES = _load_aliases()


def normalize_team(name: str) -> str:
    s = (name or "").strip()
    return _ALIASES.get(s, s)


def fetch_group_standings(session=None) -> dict[str, list[GroupStanding]]:
    """Parse 12 group tables from 500 standings page."""
    sess = session or _session()
    html = _decode(sess.get(WC_STANDINGS_URL, timeout=60).content)
    soup = BeautifulSoup(html, "html.parser")
    out: dict[str, list[GroupStanding]] = {}
    group_idx = 0
    for table in soup.find_all("table", class_=lambda c: c and "ljifen_list" in c):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        if group_idx >= len(GROUPS):
            break
        grp = GROUPS[group_idx]
        group_idx += 1
        standings: list[GroupStanding] = []
        for row in rows[1:]:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) < 14:
                continue
            try:
                standings.append(GroupStanding(
                    group=grp,
                    rank=int(cells[1]),
                    team=normalize_team(cells[2]),
                    played=int(cells[3]),
                    won=int(cells[4]),
                    drawn=int(cells[5]),
                    lost=int(cells[6]),
                    gf=int(cells[7]),
                    ga=int(cells[8]),
                    gd=int(cells[9]),
                    points=int(cells[13]),
                    form=cells[14] if len(cells) > 14 else "",
                ))
            except (ValueError, IndexError):
                continue
        if standings:
            out[grp] = standings
    return out


def fetch_group_fixtures(group: str, *, session=None, stage_id: int = WC_STAGE_ID) -> list[GroupFixture]:
    sess = session or _session()
    r = sess.get(
        WC_MATCH_API,
        params={"c": "score", "a": "getmatch", "stid": stage_id, "round": group.upper()},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    fixtures: list[GroupFixture] = []
    for m in data:
        fixtures.append(GroupFixture(
            fixture_id=str(m.get("fid") or ""),
            group=group.upper(),
            round=int(m.get("round") or 0),
            kickoff=str(m.get("stime") or ""),
            home=normalize_team(m.get("hname") or m.get("hsxname") or ""),
            away=normalize_team(m.get("gname") or m.get("gsxname") or ""),
            home_score=_int(m.get("hscore")),
            away_score=_int(m.get("gscore")),
            status=int(m.get("status") or 0),
            eu_home=_float(m.get("win")),
            eu_draw=_float(m.get("draw")),
            eu_away=_float(m.get("lost")),
        ))
    return fixtures


def fetch_all_group_fixtures(*, session=None) -> list[GroupFixture]:
    sess = session or _session()
    all_fx: list[GroupFixture] = []
    for g in GROUPS:
        try:
            all_fx.extend(fetch_group_fixtures(g, session=sess))
        except Exception as exc:
            log.warning("拉取 %s 组赛程失败: %s", g, exc)
    return all_fx


def fetch_finished_fixtures(*, session=None) -> list[GroupFixture]:
    return [f for f in fetch_all_group_fixtures(session=session) if f.is_finished]


def _int(v) -> int | None:
    try:
        return int(v) if v is not None and str(v).strip() != "" else None
    except (TypeError, ValueError):
        return None


def _float(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
