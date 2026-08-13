#!/usr/bin/env python3
"""Backfill closing_eu_* / closing_ah_* for settled matches from latest odds tick.

策略：
- 优先 odds_latest（最新盘口）
- 无 odds_latest 时取该 fixture 最后一条有效 odds_ticks
- 回填对象：已 settle 但 closing_eu_home IS NULL 的场
- 同时刷新 payload.closing_odds 与 jingcai SP
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db.connection import cursor
from match_settlement import _closing_fields, _build_payload, _extract_jingcai_sp
from db.repository import get_fixture_by_external

log = logging.getLogger(__name__)


def _latest_tick_from_ticks(fixture_db_id: int) -> dict | None:
    with cursor() as cur:
        cur.execute(
            """
            SELECT * FROM odds_ticks
            WHERE fixture_id = %s
              AND (eu_home IS NOT NULL OR ah_line IS NOT NULL)
            ORDER BY captured_at DESC
            LIMIT 1
            """,
            (fixture_db_id,),
        )
        return cur.fetchone()


def _latest_tick(fixture_db_id: int) -> dict | None:
    with cursor() as cur:
        cur.execute("SELECT * FROM odds_latest WHERE fixture_id = %s", (fixture_db_id,))
        row = cur.fetchone()
    if row and row.get("eu_home") is not None:
        return dict(row)
    return _latest_tick_from_ticks(fixture_db_id)


def _tick_with_jingcai(fixture_db_id: int) -> dict | None:
    with cursor() as cur:
        cur.execute(
            """
            SELECT * FROM odds_ticks
            WHERE fixture_id = %s
              AND raw_meta->'jingcai' IS NOT NULL
              AND (raw_meta->'jingcai'->>'sp_home' IS NOT NULL)
            ORDER BY captured_at DESC
            LIMIT 1
            """,
            (fixture_db_id,),
        )
        return cur.fetchone()


def _update_one(fixture_db_id: int, tick: dict) -> dict:
    closing = _closing_fields(tick, fixture_db_id)
    # payload 同步：保留现有预测/命中等字段，仅刷新 closing_odds + jingcai_sp
    with cursor() as cur:
        cur.execute("SELECT payload FROM match_results WHERE fixture_id = %s", (fixture_db_id,))
        row = cur.fetchone()
        payload = row["payload"] or {} if row else {}
    payload["closing_odds"] = payload.get("closing_odds") or {}
    payload["closing_odds"].update({
        "eu_home": closing.get("closing_eu_home"),
        "eu_draw": closing.get("closing_eu_draw"),
        "eu_away": closing.get("closing_eu_away"),
        "ah_line": closing.get("closing_ah_line"),
        "ah_home_water": closing.get("closing_ah_home_water"),
        "ah_away_water": closing.get("closing_ah_away_water"),
        "ou": {
            "line": closing.get("closing_ou_line"),
            "over": closing.get("closing_ou_over"),
            "under": closing.get("closing_ou_under"),
        },
    })
    sp = _extract_jingcai_sp(tick)
    if sp:
        payload["jingcai_sp"] = sp

    cols = [
        "closing_captured_at", "closing_ah_line", "closing_ah_home_water", "closing_ah_away_water",
        "closing_eu_home", "closing_eu_draw", "closing_eu_away",
        "closing_eu_open_home", "closing_eu_open_draw", "closing_eu_open_away",
        "closing_ou_line", "closing_ou_over", "closing_ou_under",
        "closing_ou_open_line", "closing_ou_open_over", "closing_ou_open_under",
        "payload",
    ]
    updates = ", ".join(f"{c} = %s" for c in cols)
    vals = [closing.get(c) for c in cols[:-1]] + [json.dumps(payload, ensure_ascii=False, default=str)]
    with cursor() as cur:
        cur.execute(
            f"UPDATE match_results SET {updates} WHERE fixture_id = %s",
            vals + [fixture_db_id],
        )
    return {"updated": True, "fixture_db_id": fixture_db_id}


def _backfill_sp_only(days: int, limit: int, dry_run: bool) -> tuple[int, int]:
    """为已有 closing_eu 但缺 SP 的场补竞彩 SP。"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    with cursor() as cur:
        cur.execute(
            """
            SELECT mr.fixture_id
            FROM match_results mr
            WHERE mr.settled_at > %s
              AND mr.payload->'jingcai_sp' IS NULL
            ORDER BY mr.settled_at DESC
            LIMIT %s
            """,
            (cutoff, limit),
        )
        rows = cur.fetchall()

    updated = 0
    missing = 0
    for row in rows:
        fid = row["fixture_id"]
        tick = _tick_with_jingcai(fid) or _latest_tick(fid)
        sp = _extract_jingcai_sp(tick)
        if not sp:
            missing += 1
            continue
        if dry_run:
            print("dry-run sp", fid, sp)
            updated += 1
            continue
        with cursor() as cur:
            cur.execute(
                "SELECT payload FROM match_results WHERE fixture_id = %s",
                (fid,),
            )
            db_row = cur.fetchone()
            payload = (db_row["payload"] or {}) if db_row else {}
        payload["jingcai_sp"] = sp
        with cursor() as cur:
            cur.execute(
                "UPDATE match_results SET payload = %s WHERE fixture_id = %s",
                (json.dumps(payload, ensure_ascii=False, default=str), fid),
            )
        updated += 1
    return updated, missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="回填已 settle 场的 closing odds 与竞彩 SP")
    parser.add_argument("--days", type=int, default=90, help="扫描最近 N 天（默认 90）")
    parser.add_argument("--dry-run", action="store_true", help="只打印不写入")
    parser.add_argument("--limit", type=int, default=10000, help="最大处理数")
    parser.add_argument("--sp-only", action="store_true", help="仅补 SP")
    args = parser.parse_args(argv)

    if args.sp_only:
        u, m = _backfill_sp_only(args.days, args.limit, args.dry_run)
        print(f"sp_only total={u+m} updated={u} missing={m}")
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    with cursor() as cur:
        cur.execute(
            """
            SELECT mr.fixture_id, f.external_id
            FROM match_results mr
            JOIN fixtures f ON f.id = mr.fixture_id
            WHERE mr.settled_at > %s
              AND mr.closing_eu_home IS NULL
            ORDER BY mr.settled_at DESC
            LIMIT %s
            """,
            (cutoff, args.limit),
        )
        rows = cur.fetchall()

    updated = 0
    missing = 0
    for row in rows:
        fid = row["fixture_id"]
        tick = _latest_tick(fid)
        if not tick or (tick.get("eu_home") is None and tick.get("ah_line") is None):
            missing += 1
            continue
        if args.dry_run:
            print("dry-run", fid, tick.get("eu_home"), tick.get("ah_line"))
            updated += 1
            continue
        try:
            _update_one(fid, tick)
            updated += 1
        except Exception as exc:
            log.error("backfill fixture %s failed: %s", fid, exc)
            missing += 1

    # 同时补 SP
    sp_u, sp_m = _backfill_sp_only(args.days, args.limit, args.dry_run)

    total = len(rows)
    print(f"odds total={total} updated={updated} missing={missing}; sp updated={sp_u} missing={sp_m}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
