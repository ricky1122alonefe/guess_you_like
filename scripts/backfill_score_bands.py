#!/usr/bin/env python3
"""Backfill score_bands for settled matches without recomputing scores.

Usage:
    python3 scripts/backfill_score_bands.py --days 14
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.market.score_range import build_score_range_forecast, evaluate_score_bands
from db.connection import cursor


def _load_payload(raw):
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return raw or {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    rows: list[dict] = []
    with cursor() as cur:
        cur.execute(
            """
            SELECT mr.fixture_id, f.external_id, mr.home_score, mr.away_score, mr.payload
            FROM match_results mr
            JOIN fixtures f ON f.id = mr.fixture_id
            WHERE mr.settled_at >= %s
              AND mr.home_score IS NOT NULL
              AND mr.away_score IS NOT NULL
            ORDER BY mr.settled_at DESC
            """,
            (cutoff,),
        )
        rows = [dict(r) for r in cur.fetchall()]

    updated = 0
    skipped = 0
    errors = 0
    for r in rows:
        payload = _load_payload(r.get("payload"))
        hits = payload.get("hits") or {}
        if hits.get("score_bands"):
            skipped += 1
            continue
        ext = str(r.get("external_id"))
        try:
            score_range = build_score_range_forecast(ext)
        except Exception as exc:
            print(f"score_range failed {ext}: {exc}")
            errors += 1
            continue
        score_bands = evaluate_score_bands(
            score_range, int(r["home_score"]), int(r["away_score"])
        )
        hits["score_bands"] = score_bands
        payload["score_range"] = score_range
        if args.dry_run:
            print(f"DRY {ext}: bands={len(score_bands)}")
            updated += 1
            continue
        with cursor() as cur:
            cur.execute(
                """
                UPDATE match_results
                SET payload = %s
                WHERE fixture_id = %s
                """,
                (json.dumps(payload, ensure_ascii=False, default=str), r["fixture_id"]),
            )
        updated += 1

    print(f"total={len(rows)}, updated={updated}, skipped={skipped}, errors={errors}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
