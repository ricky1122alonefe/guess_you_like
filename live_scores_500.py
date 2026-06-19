"""Fetch finished-match scores — prefer 500 league API (full time), HTML as fallback."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, replace
from typing import Collection

import requests
from bs4 import BeautifulSoup

from download_500 import (
    DEFAULT_LEAGUES,
    _decode,
    _parse_league_from_tr,
    _parse_teams_from_row,
    _session,
)

log = logging.getLogger(__name__)
DEFAULT_TIMEOUT = 60
_SCORE_RE = re.compile(r"^(\d+)\s*[-:：]\s*(\d+)$")


@dataclass
class LiveScore:
    fixture_id: str
    home_score: int
    away_score: int
    score_text: str
    status: str = "finished"
    league: str = ""
    home_name: str = ""
    away_name: str = ""
    source: str = "live_html"


def _score_tuple(h: int, a: int) -> tuple[int, int, str]:
    return h, a, f"{h}-{a}"


def _parse_score_text(text: str) -> tuple[int, int, str] | None:
    txt = (text or "").strip()
    if not txt or "半场" in txt:
        return None
    m = _SCORE_RE.search(txt.replace(" ", ""))
    if not m:
        m = _SCORE_RE.match(txt)
    if not m:
        return None
    return _score_tuple(int(m.group(1)), int(m.group(2)))


def _parse_score_from_tr(tr) -> tuple[int, int, str] | None:
    """Parse full-time score from a live.500.com table row (ignore half-time)."""
    if tr is None:
        return None

    # Detail/list rows: <span class="score">2 - 0</span> vs <span class="score2">半场：1-0</span>
    for sp in tr.select("span.score"):
        classes = " ".join(sp.get("class") or []).lower()
        if "score2" in classes:
            continue
        parsed = _parse_score_text(sp.get_text(strip=True))
        if parsed:
            return parsed

    candidates: list[tuple[int, int, str]] = []
    for td in tr.find_all("td"):
        cls = " ".join(td.get("class") or []).lower()
        txt = td.get_text(strip=True)
        if "半场" in txt:
            continue
        if "score" in cls and "score2" in cls:
            continue
        if "score" not in cls and "bf" not in cls:
            continue
        parsed = _parse_score_text(txt)
        if parsed:
            candidates.append(parsed)

    if candidates:
        return candidates[-1]

    parts = [p.strip() for p in tr.get_text("|", strip=True).split("|") if p.strip()]
    for i, p in enumerate(parts):
        if p not in ("完", "完场", "结束"):
            continue
        for j in (i + 1, i - 1, i + 2):
            if 0 <= j < len(parts) and "半场" not in parts[j]:
                parsed = _parse_score_text(parts[j])
                if parsed:
                    return parsed

    for p in parts:
        if "半场" in p:
            continue
        parsed = _parse_score_text(p)
        if parsed:
            candidates.append(parsed)

    return candidates[-1] if candidates else None


def fetch_wc_api_scoreboard(session: requests.Session | None = None) -> dict[str, LiveScore]:
    """Full-time scores from liansai.500.com getmatch API (hscore/gscore)."""
    from wc_standings_fetch import fetch_all_group_fixtures

    sess = session or _session()
    out: dict[str, LiveScore] = {}
    for fx in fetch_all_group_fixtures(session=sess):
        if not fx.is_finished or fx.home_score is None or fx.away_score is None:
            continue
        fid = str(fx.fixture_id)
        out[fid] = LiveScore(
            fixture_id=fid,
            home_score=int(fx.home_score),
            away_score=int(fx.away_score),
            score_text=f"{fx.home_score}-{fx.away_score}",
            status="finished",
            league="世界杯",
            home_name=fx.home,
            away_name=fx.away,
            source="wc_api",
        )
    log.info("500 联赛 API 已完场比分 %d 场", len(out))
    return out


def fetch_live_html_scoreboard(
    session: requests.Session | None = None,
    *,
    leagues: Collection[str] | None = DEFAULT_LEAGUES,
) -> dict[str, LiveScore]:
    """Map fixture_id -> score for finished rows on live.500.com (HTML fallback)."""
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
        home, away = _parse_teams_from_row(row_text)
        out[fid] = LiveScore(
            fixture_id=fid,
            home_score=h,
            away_score=a_g,
            score_text=txt,
            status="finished",
            league=_parse_league_from_tr(tr),
            home_name=home,
            away_name=away,
            source="live_html",
        )
    log.info("live.500 HTML 已完场比分 %d 场", len(out))
    return out


def fetch_live_scoreboard(
    session: requests.Session | None = None,
    *,
    leagues: Collection[str] | None = DEFAULT_LEAGUES,
) -> dict[str, LiveScore]:
    """Prefer WC API full-time scores; fill gaps from live.500 HTML."""
    sess = session or _session()
    board: dict[str, LiveScore] = {}

    if leagues is None or "世界杯" in set(leagues):
        try:
            board.update(fetch_wc_api_scoreboard(sess))
        except Exception as exc:
            log.warning("拉取 500 联赛 API 比分失败: %s", exc)

    try:
        html_board = fetch_live_html_scoreboard(sess, leagues=leagues)
    except Exception as exc:
        log.warning("拉取 live.500 HTML 比分失败: %s", exc)
        html_board = {}

    for fid, score in html_board.items():
        if fid not in board:
            board[fid] = score

    log.info("合并比分板 %d 场 (API %d, HTML-only %d)",
             len(board),
             sum(1 for s in board.values() if s.source == "wc_api"),
             sum(1 for s in board.values() if s.source == "live_html"))
    return board


def align_score_to_fixture(score: LiveScore, fixture: dict) -> LiveScore:
    """Swap home/away goals if parsed row order differs from fixture metadata."""
    from share_card import split_teams
    from wc_standings_fetch import normalize_team

    fx_home = normalize_team(str(fixture.get("home_team") or ""))
    fx_away = normalize_team(str(fixture.get("away_team") or ""))
    if not fx_home or not fx_away:
        mh, ma = split_teams(str(fixture.get("match_name") or ""))
        fx_home = normalize_team(mh)
        fx_away = normalize_team(ma)
    if not fx_home or not fx_away:
        return score

    sc_home = normalize_team(score.home_name)
    sc_away = normalize_team(score.away_name)
    if not sc_home or not sc_away:
        return score

    if sc_home == fx_home and sc_away == fx_away:
        return score
    if sc_home == fx_away and sc_away == fx_home:
        return replace(
            score,
            home_score=score.away_score,
            away_score=score.home_score,
            score_text=f"{score.away_score}-{score.home_score}",
            home_name=fx_home,
            away_name=fx_away,
        )
    log.warning(
        "比分主客与赛程不一致 fid=%s fixture=%sVS%s score=%s row=%sVS%s",
        score.fixture_id, fx_home, fx_away, score.score_text, sc_home, sc_away,
    )
    return score


def fetch_fixture_score(
    fixture_id: str,
    session: requests.Session | None = None,
    *,
    leagues: Collection[str] | None = DEFAULT_LEAGUES,
) -> LiveScore | None:
    board = fetch_live_scoreboard(session, leagues=leagues)
    return board.get(str(fixture_id))
