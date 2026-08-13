"""Build EU↔AH divergence from DB odds_latest / ticks (no new crawler)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from analysis.signals import eu_ah_divergence as ead
from db.connection import cursor
from db.repository import get_fixture_by_external, get_closing_tick, list_ticks

logger = logging.getLogger(__name__)


def _to_float(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _odds_from_latest(fixture_db_id: int) -> dict[str, Any] | None:
    """Read odds_latest row for a fixture."""
    with cursor() as cur:
        cur.execute(
            """
            SELECT
                ah_line, ah_home_water, ah_away_water,
                ah_open_line, ah_open_home, ah_open_away,
                eu_home, eu_draw, eu_away,
                eu_open_home, eu_open_draw, eu_open_away
            FROM odds_latest
            WHERE fixture_id = %s
            """,
            (fixture_db_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {k: _to_float(v) for k, v in dict(row).items()}


def _latest_valid_tick(fixture_db_id: int) -> dict[str, Any] | None:
    """Fallback: last tick with at least one EU/AH field."""
    ticks = list_ticks(fixture_db_id, limit=20)
    keys = (
        "eu_home", "eu_draw", "eu_away",
        "eu_open_home", "eu_open_draw", "eu_open_away",
        "ah_line", "ah_home_water", "ah_away_water",
        "ah_open_line", "ah_open_home", "ah_open_away",
    )
    for tick in reversed(ticks):
        if any(tick.get(k) is not None for k in keys):
            return {k: _to_float(tick.get(k)) for k in keys}
    return None


def _build_snapshot(
    fixture_db_id: int,
    fixture: dict[str, Any],
) -> dict[str, Any] | None:
    """Compose cur dict compatible with analyze_eu_ah_divergence."""
    source = "postgres_latest_tick"
    snap = _odds_from_latest(fixture_db_id)
    if snap is None:
        source = "postgres_tick_fallback"
        snap = _latest_valid_tick(fixture_db_id)
    if snap is None:
        source = "postgres_closing_tick"
        closing = get_closing_tick(fixture_db_id, fixture.get("kickoff_at"))
        if closing:
            snap = {k: _to_float(closing.get(k)) for k in (
                "eu_home", "eu_draw", "eu_away",
                "eu_open_home", "eu_open_draw", "eu_open_away",
                "ah_line", "ah_home_water", "ah_away_water",
                "ah_open_line", "ah_open_home", "ah_open_away",
            )}
    if not snap:
        return None
    # odds_latest uses ah_open_home/away; analyzer expects ah_open_home_water/away_water
    return {
        "source": source,
        "eu_home": snap.get("eu_home"),
        "eu_draw": snap.get("eu_draw"),
        "eu_away": snap.get("eu_away"),
        "eu_open_home": snap.get("eu_open_home"),
        "eu_open_draw": snap.get("eu_open_draw"),
        "eu_open_away": snap.get("eu_open_away"),
        "ah_line": snap.get("ah_line"),
        "ah_home_water": snap.get("ah_home_water"),
        "ah_away_water": snap.get("ah_away_water"),
        "ah_open_line": snap.get("ah_open_line"),
        "ah_open_home_water": snap.get("ah_open_home"),
        "ah_open_away_water": snap.get("ah_open_away"),
    }


def _build_snapshot_from_cur(
    cur: dict[str, Any],
    fixture_id: str,
    match_name: str,
) -> dict[str, Any] | None:
    """Build a divergence dict from an odds snapshot dict (test/DB helper)."""
    if not cur or not any(cur.get(k) is not None for k in ("eu_home", "ah_line")):
        return None
    div = ead.analyze_eu_ah_divergence(
        cur,
        fixture_id=str(fixture_id),
        match=match_name,
    )
    if not div:
        return None
    return {
        "fixture_id": div.fixture_id,
        "match": div.match,
        "source": cur.get("source", "unknown"),
        "divergence_score": div.divergence_score,
        "severity": div.severity,
        "severity_cn": div.severity_cn,
        "consistency": div.consistency,
        "consistency_cn": div.consistency_cn,
        "line_gap": div.line_gap,
        "eu_to_ah_line": div.eu_to_ah_line,
        "ah_line": div.ah_line,
        "eu_home": div.eu_home,
        "ah_sketch_home": div.ah_sketch_home,
        "eu_odds_gap": div.eu_odds_gap,
        "open_line_gap": div.open_line_gap,
        "live_line_gap": div.live_line_gap,
        "gap_shift": div.gap_shift,
        "signals": div.signals,
        "pattern_names": div.pattern_names,
        "conversion_summary": div.conversion_summary,
        "open_eu": div.open_eu,
        "live_eu": div.live_eu,
        "open_ah": div.open_ah,
        "live_ah": div.live_ah,
        "advice": div.advice,
    }


def build_eu_ah_divergence(
    fixture_id: str,
    *,
    fixture: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return structured EU/AH divergence for a fixture, or missing dict."""
    if fixture is None:
        fixture = get_fixture_by_external("500", str(fixture_id))
    if not fixture:
        return {"missing": ["fixture_not_found"], "fixture_id": str(fixture_id)}

    snap = _build_snapshot(fixture["id"], fixture)
    if not snap or not any(snap.get(k) is not None for k in ("eu_home", "ah_line")):
        return {"missing": ["no_eu_ah_odds"], "fixture_id": str(fixture_id)}

    div = _build_snapshot_from_cur(snap, str(fixture_id), fixture.get("match_name") or "")
    if not div:
        return {"missing": ["analyzer_returned_none"], "fixture_id": str(fixture_id)}

    return div
