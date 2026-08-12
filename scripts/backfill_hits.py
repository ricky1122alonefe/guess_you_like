#!/usr/bin/env python3
"""Backfill payload.hits / hit_1x2 / ah / ou for recently settled matches."""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db.connection import cursor
from db.repository import (
    get_closing_tick,
    get_opening_tick,
    upsert_match_result,
)
from live_scores_500 import LiveScore
from match_settlement import _result_row
from prediction_archive import load_best_prediction


def main():
    output_root = Path("output/service")
    days = 30
    since = datetime.now(timezone.utc) - timedelta(days=days)
    with cursor() as cur:
        cur.execute(
            """
            SELECT r.*, f.external_id, f.kickoff_at
            FROM match_results r
            JOIN fixtures f ON f.id = r.fixture_id
            WHERE r.settled_at > %s
            ORDER BY r.settled_at DESC
            """,
            (since,),
        )
        rows = cur.fetchall()

    fixed = 0
    skipped_no_score = 0
    no_prediction = 0
    errors = []
    for r in rows:
        fixture_db_id = r["fixture_id"]
        hs, aws = r.get("home_score"), r.get("away_score")
        if hs is None or aws is None:
            skipped_no_score += 1
            continue
        ext = str(r.get("external_id") or "")
        score = LiveScore(
            fixture_id=ext,
            home_score=int(hs),
            away_score=int(aws),
            score_text=r.get("score_text") or f"{hs}-{aws}",
            status="finished",
            source=r.get("source") or "db",
            is_finished=True,
            score_source=r.get("score_source") or r.get("source") or "db",
        )
        pred = None
        if ext:
            pred = load_best_prediction(output_root, ext, kickoff_at=r.get("kickoff_at"))
        if not pred:
            no_prediction += 1
        try:
            opening_tick = get_opening_tick(fixture_db_id)
            closing_tick = get_closing_tick(fixture_db_id, r.get("kickoff_at"))
            new_row = _result_row(
                fixture_db_id, score, pred=pred, opening_tick=opening_tick, closing_tick=closing_tick
            )
            upsert_match_result(fixture_db_id, new_row)
            fixed += 1
        except Exception as exc:
            errors.append((ext or fixture_db_id, str(exc)))
    print(f"backfill: fixed={fixed}, skipped_no_score={skipped_no_score}, "
          f"no_prediction={no_prediction}, errors={len(errors)}")
    for fid, msg in errors[:10]:
        print(f"  error {fid}: {msg}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
