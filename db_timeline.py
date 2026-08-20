"""Build match timeline view from PostgreSQL odds_ticks."""

from __future__ import annotations

import json
from decimal import Decimal

from db.connection import ping
from db.repository import get_fixture_by_external, list_ticks
from match_timeline import _compute_changes
from time_utils import beijing_hour_key, format_beijing


def _num(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _raw_meta_from_tick(t: dict) -> dict:
    raw = t.get("raw_meta")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {}
    return raw if isinstance(raw, dict) else {}


def _jingcai_from_tick(t: dict) -> dict:
    return _raw_meta_from_tick(t).get("jingcai") or {}


def _betfair_from_tick(t: dict) -> dict:
    return _raw_meta_from_tick(t).get("betfair") or {}


def _eu_books_from_tick(t: dict) -> list:
    raw = _raw_meta_from_tick(t)
    books = raw.get("eu_books")
    if isinstance(books, list) and books:
        return books
    return []


def _ou_from_tick(t: dict) -> dict:
    raw = _raw_meta_from_tick(t)
    ou = raw.get("ou") or {}
    return {
        "ou_line": _num(t.get("ou_line") or ou.get("ou_line")),
        "ou_over": _num(t.get("ou_over") or ou.get("ou_over")),
        "ou_under": _num(t.get("ou_under") or ou.get("ou_under")),
        "ou_open_line": _num(t.get("ou_open_line") or ou.get("ou_open_line")),
        "ou_open_over": _num(t.get("ou_open_over") or ou.get("ou_open_over")),
        "ou_open_under": _num(t.get("ou_open_under") or ou.get("ou_open_under")),
    }


def _odds_from_tick(t: dict) -> dict:
    return {
        "ah_line": _num(t.get("ah_line")),
        "ah_open_line": _num(t.get("ah_open_line")),
        "ah_home_water": _num(t.get("ah_home_water")),
        "ah_away_water": _num(t.get("ah_away_water")),
        "ah_open_home_water": _num(t.get("ah_open_home")),
        "ah_open_away_water": _num(t.get("ah_open_away")),
        "eu_home": _num(t.get("eu_home")),
        "eu_draw": _num(t.get("eu_draw")),
        "eu_away": _num(t.get("eu_away")),
        "eu_open_home": _num(t.get("eu_open_home")),
        "eu_open_draw": _num(t.get("eu_open_draw")),
        "eu_open_away": _num(t.get("eu_open_away")),
        **_ou_from_tick(t),
        "bookmaker": t.get("bookmaker") or "pinnacle",
        "jingcai": _jingcai_from_tick(t),
        "betfair": _betfair_from_tick(t),
        "eu_books": _eu_books_from_tick(t),
    }


def _pick_from_tick(tick: dict) -> dict:
    return {
        "result_1x2": None,
        "result_1x2_cn": None,
        "likely_scores": "",
        "asian_handicap_cn": None,
        "over_under_cn": None,
        "confidence_cn": None,
        "recommendation_source": "odds_poll",
    }


def load_match_index_from_db(external_id: str, *, source: str = "500") -> dict | None:
    if not ping():
        return None
    fx = get_fixture_by_external(source, external_id)
    if not fx:
        return None
    ticks = list_ticks(fx["id"])
    if not ticks:
        return None

    timeline = []
    for t in ticks:
        captured = t["captured_at"]
        ts = format_beijing(captured)
        timeline.append({
            "run_id": f"db_{t['id']}",
            "ts": ts,
            "hour": beijing_hour_key(captured),
            "odds": _odds_from_tick(t),
            "pick": _pick_from_tick(t),
        })

    home_team = fx.get("home_team") or ""
    away_team = fx.get("away_team") or ""
    kickoff_at = fx.get("kickoff_at")
    return {
        "fixture_id": str(external_id),
        "match_name": f"{home_team}VS{away_team}" if home_team and away_team else (fx.get("match_name") or str(external_id)),
        "home_team": home_team,
        "away_team": away_team,
        "league_name": fx.get("competition") or "",
        "kickoff_at": kickoff_at.isoformat() if hasattr(kickoff_at, "isoformat") else str(kickoff_at or ""),
        "updated_at": timeline[-1]["ts"],
        "point_count": len(timeline),
        "timeline": timeline,
        "changes": _compute_changes(timeline),
        "source": "postgresql",
    }
