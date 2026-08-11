"""Lightweight 500.com HTML odds polling (no xls download)."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any

from bs4 import BeautifulSoup
from download_500 import BASE, MatchFixture, _serialize_xls_table, fetch_live_fixtures
from http_client import ScraperGuard, get_text, make_session
from betfair_500 import fetch_betfair_snapshot
from eu_odds_chart import eu_books_fingerprint, parse_eu_bookmakers
from jingcai_500 import build_jingcai_snapshot, fetch_jczq_meta_by_order, fetch_live_odds_list
from parser import parse_handicap

log = logging.getLogger(__name__)


def _to_float(text: str) -> float | None:
    text = str(text or "").strip().replace("↑", "").replace("↓", "")
    if not text or text in {"-", "—"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _pick_row(rows: list[str], *patterns: str) -> list[str] | None:
    for row in rows:
        head = row.split("|", 1)[0]
        for pat in patterns:
            if re.search(pat, head, re.I):
                return row.split("|")
    return None


def _parse_ah_row(cells: list[str]) -> dict[str, Any]:
    # name|home|line|away|time|open_home|open_line|open_away|open_time
    line = parse_handicap(cells[2]) if len(cells) > 2 else None
    open_line = parse_handicap(cells[6]) if len(cells) > 6 else None
    return {
        "ah_line": line,
        "ah_home_water": _to_float(cells[1]) if len(cells) > 1 else None,
        "ah_away_water": _to_float(cells[3]) if len(cells) > 3 else None,
        "ah_open_line": open_line or line,
        "ah_open_home": _to_float(cells[5]) if len(cells) > 5 else None,
        "ah_open_away": _to_float(cells[7]) if len(cells) > 7 else None,
    }


def _parse_eu_row(cells: list[str]) -> dict[str, Any]:
    return {
        "eu_home": _to_float(cells[1]) if len(cells) > 1 else None,
        "eu_draw": _to_float(cells[2]) if len(cells) > 2 else None,
        "eu_away": _to_float(cells[3]) if len(cells) > 3 else None,
        "eu_open_home": _to_float(cells[8]) if len(cells) > 10 else None,
        "eu_open_draw": _to_float(cells[9]) if len(cells) > 10 else None,
        "eu_open_away": _to_float(cells[10]) if len(cells) > 10 else None,
    }


def fetch_odds_html(
    session,
    fixture_id: str,
    *,
    guard: ScraperGuard,
) -> tuple[dict[str, Any], dict[str, Any]]:
    fid = str(fixture_id)
    ah_url = f"{BASE}/fenxi/yazhi-{fid}.shtml"
    eu_url = f"{BASE}/fenxi/ouzhi-{fid}.shtml"

    ah_html = get_text(session, ah_url, source="500", guard=guard)
    eu_html = get_text(session, eu_url, source="500", guard=guard)

    ah_soup = BeautifulSoup(ah_html, "html.parser")
    eu_soup = BeautifulSoup(eu_html, "html.parser")
    ah_rows = _serialize_xls_table(ah_soup)["row"]
    eu_rows = _serialize_xls_table(eu_soup)["row"]
    if not ah_rows or not eu_rows:
        raise RuntimeError(f"页面无赔率表格 fid={fid}")

    ah_cells = _pick_row(ah_rows, r"Pi|平博|Pinnacle") or _pick_row(ah_rows, "平均值")
    eu_cells = _pick_row(eu_rows, r"Pi|平博|Pinnacle") or _pick_row(eu_rows, "平均值")
    if not ah_cells or not eu_cells:
        raise RuntimeError(f"未找到平博/平均值行 fid={fid}")

    bookmaker = "pinnacle" if re.search(r"Pi|平博", ah_cells[0], re.I) else "average"
    ah = _parse_ah_row(ah_cells)
    eu = _parse_eu_row(eu_cells)
    eu_books = parse_eu_bookmakers(eu_rows)
    ah["bookmaker"] = bookmaker
    eu["bookmaker"] = bookmaker
    eu["eu_books"] = eu_books
    ah["eu_books"] = eu_books
    return ah, eu


def build_tick(
    fixture: MatchFixture,
    ah: dict[str, Any],
    eu: dict[str, Any],
    *,
    jingcai: dict[str, Any] | None = None,
    betfair: dict[str, Any] | None = None,
) -> dict[str, Any]:
    jc = jingcai or {}
    bf = betfair or {}
    merged = {
        "bookmaker": ah.get("bookmaker") or eu.get("bookmaker") or "pinnacle",
        **ah,
        **eu,
        "raw_meta": {
            "external_id": fixture.fixture_id,
            "match_name": fixture.base_name,
            "match_num": fixture.match_num or jc.get("match_num"),
            "jingcai": jc,
            "betfair": bf,
            "eu_books": eu.get("eu_books") or [],
        },
    }
    key = {
        k: merged.get(k)
        for k in (
            "bookmaker",
            "ah_line", "ah_home_water", "ah_away_water",
            "ah_open_line", "ah_open_home", "ah_open_away",
            "eu_home", "eu_draw", "eu_away",
            "eu_open_home", "eu_open_draw", "eu_open_away",
        )
    }
    key["eu_books_fp"] = eu_books_fingerprint(eu.get("eu_books") or [])
    key["jingcai"] = jc
    key["betfair"] = {
        "volume_home": bf.get("volume_home"),
        "volume_draw": bf.get("volume_draw"),
        "volume_away": bf.get("volume_away"),
        "volume_pct": bf.get("volume_pct"),
    }
    merged["tick_hash"] = hashlib.sha256(
        json.dumps(key, sort_keys=True, default=str).encode()
    ).hexdigest()[:32]
    return merged


def poll_fixture(
    session,
    fixture: MatchFixture,
    *,
    guard: ScraperGuard,
    live_odds: dict[str, dict] | None = None,
    jczq_meta: dict[str, dict] | None = None,
) -> dict[str, Any]:
    ah, eu = fetch_odds_html(session, fixture.fixture_id, guard=guard)
    jc = build_jingcai_snapshot(
        fixture.fixture_id,
        live_odds or {},
        order_id=fixture.order_id,
        jczq_meta=jczq_meta,
    )
    bf = fetch_betfair_snapshot(session, fixture.fixture_id)
    return build_tick(fixture, ah, eu, jingcai=jc, betfair=bf)


def list_upcoming_fixtures(*, within_days: float = 2) -> list[MatchFixture]:
    session = make_session()
    return fetch_live_fixtures(session, within_days=within_days)


def fetch_jingcai_context(session) -> tuple[dict[str, dict], dict[str, dict]]:
    """One live page + one trade page per poll round."""
    live_odds = fetch_live_odds_list(session)
    try:
        jczq_meta = fetch_jczq_meta_by_order(session)
    except Exception as exc:
        log.warning("竞彩元数据抓取失败: %s", exc)
        jczq_meta = {}
    return live_odds, jczq_meta


def poll_single_fixture(
    fixture_id: str,
    *,
    output_root=None,
    within_days: float = 14,
) -> dict[str, Any]:
    """补抓单场：写 Postgres odds_ticks，返回 DB 时间线 match index。

    serve ``POST /api/match/{fid}/poll`` 调用此入口。``output_root`` 仅兼容占位。
    """
    from db.connection import ensure_schema, ping
    from db.repository import insert_tick_if_changed, upsert_fixture
    from db_timeline import load_match_index_from_db
    from download_500 import MatchFixture, extract_fixture_id, fetch_match_info

    del output_root  # 当前只写 DB 时间线
    fid = extract_fixture_id(str(fixture_id))
    if not ping():
        raise RuntimeError("数据库未连接，无法补抓（请先 docker compose up -d db）")
    ensure_schema()

    session = make_session()
    guard = ScraperGuard(min_delay=1.0, max_delay=2.0)

    # 1) 尽量从 live 列表拿到对阵 / order_id；失败则只靠分析页队名
    fx: MatchFixture | None = None
    try:
        live = fetch_live_fixtures(session, within_days=within_days, leagues=None)
        for cand in live:
            if str(cand.fixture_id) == fid:
                fx = cand
                break
    except Exception as exc:
        log.warning("live 列表查找 fid=%s 失败: %s", fid, exc)

    if fx is None:
        try:
            fx = fetch_match_info(session, fid)
        except Exception as exc:
            log.warning("fetch_match_info fid=%s 失败: %s", fid, exc)
            fx = MatchFixture(fixture_id=fid)

    # 2) 竞彩上下文（失败不阻断欧亚）
    live_odds: dict[str, dict] = {}
    jczq_meta: dict[str, dict] = {}
    try:
        live_odds, jczq_meta = fetch_jingcai_context(session)
    except Exception as exc:
        log.warning("jingcai context fid=%s: %s", fid, exc)

    # 3) 抓亚欧 + 必发，强制要求有有效欧或亚
    tick = poll_fixture(
        session, fx, guard=guard, live_odds=live_odds, jczq_meta=jczq_meta,
    )
    has_eu = tick.get("eu_home") is not None and tick.get("eu_away") is not None
    has_ah = tick.get("ah_line") is not None
    if not has_eu and not has_ah:
        raise RuntimeError(
            f"补抓后欧亚均为空 fid={fid}（页面解析失败或 500 暂无盘）"
        )

    db_id = upsert_fixture(
        source="500",
        external_id=fid,
        home_team=fx.home or "",
        away_team=fx.away or "",
        match_name=fx.base_name,
        kickoff_at=fx.kickoff,
    )
    inserted = insert_tick_if_changed(db_id, tick, source="500")
    log.info(
        "单场补抓 fid=%s inserted=%s eu=%s ah_line=%s",
        fid, inserted, tick.get("eu_home"), tick.get("ah_line"),
    )

    idx = load_match_index_from_db(fid)
    if not idx:
        # 最小返回，避免 serve 再炸
        idx = {
            "fixture_id": fid,
            "match_name": fx.base_name,
            "timeline": [{"odds": {
                k: tick.get(k) for k in (
                    "eu_home", "eu_draw", "eu_away",
                    "ah_line", "ah_home_water", "ah_away_water",
                )
            }}],
            "point_count": 1,
            "source": "postgresql",
        }
    return idx
