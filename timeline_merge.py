"""Merge PostgreSQL poll timeline with file-based AI picks."""

from __future__ import annotations

import copy
from typing import Any

from match_timeline import _compute_changes, compact_ai_analyses
from time_utils import format_beijing


def _pick_ts(p: dict) -> str:
    return str(p.get("ts") or "")


def _has_meaningful_pick(pick: dict) -> bool:
    if not pick:
        return False
    src = pick.get("recommendation_source") or ""
    if pick.get("ai_analyses"):
        return True
    if "ai" in src or src in ("rule_engine", "ai_dual", "ai_multi"):
        return bool(pick.get("result_1x2_cn"))
    return bool(pick.get("result_1x2_cn"))


def _merge_pick(base: dict, overlay: dict) -> dict:
    """Overlay AI/rule pick onto poll odds pick, keep poll source if no overlay."""
    if not overlay:
        return base
    out = copy.deepcopy(base)
    for key, val in overlay.items():
        if val is None:
            continue
        if key == "recommendation_source" and val == "odds_poll":
            continue
        out[key] = val
    return out


def merge_timelines(db_timeline: list[dict], file_timeline: list[dict]) -> list[dict]:
    """Forward-fill file picks onto DB odds points; append file-only AI snapshots."""
    file_sorted = sorted(
        [p for p in file_timeline if _has_meaningful_pick(p.get("pick") or {})],
        key=_pick_ts,
    )
    pick_by_hour: dict[str, dict] = {}
    for fp in file_sorted:
        hour = fp.get("hour")
        if hour:
            pick_by_hour[hour] = fp.get("pick") or {}

    if not db_timeline:
        return copy.deepcopy(file_timeline)

    merged: list[dict] = []
    pick_i = 0
    current_pick: dict = {}
    db_sorted = sorted(db_timeline, key=_pick_ts)

    for db_p in db_sorted:
        ts = _pick_ts(db_p)
        hour = db_p.get("hour")
        while pick_i < len(file_sorted) and _pick_ts(file_sorted[pick_i]) <= ts:
            current_pick = file_sorted[pick_i].get("pick") or {}
            pick_i += 1
        overlay = current_pick or pick_by_hour.get(hour) or {}
        point = copy.deepcopy(db_p)
        base_pick = point.get("pick") or {"recommendation_source": "odds_poll"}
        point["pick"] = _merge_pick(base_pick, overlay)
        merged.append(point)

    last_db_ts = _pick_ts(db_sorted[-1])
    for fp in file_sorted:
        if _pick_ts(fp) <= last_db_ts:
            continue
        point = copy.deepcopy(fp)
        if merged:
            point["odds"] = copy.deepcopy(merged[-1].get("odds") or {})
        merged.append(point)

    merged.sort(key=_pick_ts)
    return merged


def merge_match_indexes(
    db_idx: dict | None,
    file_idx: dict | None,
) -> dict | None:
    """Combine poll odds (DB) with AI recommendations (files)."""
    if not db_idx and not file_idx:
        return None
    if not db_idx:
        return file_idx
    if not file_idx:
        return db_idx

    db_tl = db_idx.get("timeline") or []
    file_tl = file_idx.get("timeline") or []
    timeline = merge_timelines(db_tl, file_tl)

    match_name = (
        file_idx.get("match_name")
        or db_idx.get("match_name")
        or ""
    )
    return {
        "fixture_id": db_idx.get("fixture_id") or file_idx.get("fixture_id"),
        "match_name": match_name,
        "updated_at": timeline[-1]["ts"] if timeline else "",
        "point_count": len(timeline),
        "timeline": timeline,
        "changes": _compute_changes(timeline),
        "source": "merged",
        "db_points": len(db_tl),
        "file_points": len(file_tl),
    }


def load_latest_poll_meta(external_id: str, *, source: str = "500") -> dict[str, Any]:
    """Latest jingcai + betfair from poll ticks (for AI context)."""
    from db.connection import ping
    from db.repository import get_fixture_by_external, list_ticks

    if not ping():
        return {}
    fx = get_fixture_by_external(source, str(external_id))
    if not fx:
        return {}
    ticks = list_ticks(fx["id"], limit=500)
    if not ticks:
        return {}
    t = ticks[-1]
    raw = t.get("raw_meta")
    if isinstance(raw, str):
        import json
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {}
    if not isinstance(raw, dict):
        raw = {}
    return {
        "captured_at": format_beijing(t["captured_at"]),
        "jingcai": raw.get("jingcai") or {},
        "betfair": raw.get("betfair") or {},
    }
