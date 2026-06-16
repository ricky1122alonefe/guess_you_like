"""Fetch finished-match scores from live.500.com."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Collection

import requests
from bs4 import BeautifulSoup

from download_500 import (
    DEFAULT_LEAGUES,
    Download500Error,
    _decode,
    _parse_league_from_tr,
    _session,
)

log = logging.getLogger(__name__)
DEFAULT_TIMEOUT = 60


@dataclass
class LiveScore:
    fixture_id: str
    home_score: int
    away_score: int
    score_text: str
    status: str = "finished"
    league: str = ""


def _parse_score_from_tr(tr) -> tuple[int, int, str] | None:
    if tr is None:
        return None
    for td in tr.find_all("td"):
        cls = " ".join(td.get("class") or []).lower()
        if "score" not in cls and "bf" not in cls:
            continue
        txt = td.get_text(strip=True)
        m = re.match(r"^(\d+)\s*[-:：]\s*(\d+)$", txt)
        if m:
            return int(m.group(1)), int(m.group(2)), f"{m.group(1)}-{m.group(2)}"

    parts = [p.strip() for p in tr.get_text("|", strip=True).split("|") if p.strip()]
    for i, p in enumerate(parts):
        if p not in ("完", "完场", "结束"):
            continue
        for j in (i + 1, i - 1, i + 2):
            if 0 <= j < len(parts):
                m = re.match(r"^(\d+)\s*[-:：]\s*(\d+)$", parts[j])
                if m:
                    return int(m.group(1)), int(m.group(2)), f"{m.group(1)}-{m.group(2)}"
        if i + 2 < len(parts) and parts[i + 1].isdigit() and parts[i + 2].isdigit():
            h, a = int(parts[i + 1]), int(parts[i + 2])
            return h, a, f"{h}-{a}"

    for p in parts:
        m = re.match(r"^(\d+)\s*[-:：]\s*(\d+)$", p)
        if m and p not in ("0-0",):
            return int(m.group(1)), int(m.group(2)), f"{m.group(1)}-{m.group(2)}"
    return None


def fetch_live_scoreboard(
    session: requests.Session | None = None,
    *,
    leagues: Collection[str] | None = DEFAULT_LEAGUES,
) -> dict[str, LiveScore]:
    """Map fixture_id -> score for finished rows on live.500.com."""
    sess = session or _session()
    resp = sess.get("https://live.500.com/", timeout=DEFAULT_TIMEOUT)
    resp.raise_for_status()
    soup = BeautifulSoup(_decode(resp.content), "html.parser")
    league_filter = set(leagues) if leagues is not None else None
    out: dict[str, LiveScore] = {}

    for a in soup.find_all("a", href=re.compile(r"youliao-\d+\.shtml")):
        m = re.search(r"youliao-(\d+)\.shtml", a.get("href", ""))
        if not m:
            continue
        fid = m.group(1)
        tr = a.find_parent("tr")
        if league_filter is not None:
            league = _parse_league_from_tr(tr)
            if league not in league_filter:
                continue
        row_text = tr.get_text("|", strip=True) if tr else ""
        if "完" not in row_text and "完场" not in row_text:
            continue
        parsed = _parse_score_from_tr(tr)
        if not parsed:
            continue
        h, a_g, txt = parsed
        out[fid] = LiveScore(
            fixture_id=fid,
            home_score=h,
            away_score=a_g,
            score_text=txt,
            status="finished",
            league=_parse_league_from_tr(tr),
        )
    log.info("live.500 已完场比分 %d 场", len(out))
    return out


def fetch_fixture_score(
    fixture_id: str,
    session: requests.Session | None = None,
    *,
    leagues: Collection[str] | None = DEFAULT_LEAGUES,
) -> LiveScore | None:
    board = fetch_live_scoreboard(session, leagues=leagues)
    return board.get(str(fixture_id))
