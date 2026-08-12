#!/usr/bin/env python3
"""导出近 N 天比分区间预测命中复盘。

Usage:
    python3 scripts/export_score_range_review.py --days 14 --output output/score_range_review.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db.connection import cursor


def _load_payload(row: dict) -> dict:
    payload = row.get("payload") or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = {}
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--output", type=str, default="output/score_range_review.csv")
    args = parser.parse_args()

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    rows: list[dict] = []
    with cursor() as cur:
        cur.execute(
            """
            SELECT
              f.external_id,
              f.home_team,
              f.away_team,
              f.kickoff_at,
              mr.home_score,
              mr.away_score,
              mr.payload
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

    # band id -> {samples, hits, details}
    band_stats: dict[str, dict] = defaultdict(lambda: {"samples": 0, "hits": 0, "details": []})
    fixture_count = 0
    with_score_bands = 0

    for r in rows:
        fixture_count += 1
        payload = _load_payload(r)
        score_bands = (payload.get("hits") or {}).get("score_bands")
        if not score_bands:
            continue
        with_score_bands += 1
        for band in score_bands:
            bid = band.get("id")
            if not bid:
                continue
            band_stats[bid]["samples"] += 1
            if band.get("hit"):
                band_stats[bid]["hits"] += 1
            band_stats[bid]["details"].append(
                {
                    "external_id": r.get("external_id"),
                    "match": f"{r.get('home_team')} vs {r.get('away_team')}",
                    "score": f"{r.get('home_score')}-{r.get('away_score')}",
                    "hit": band.get("hit"),
                }
            )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["band_id", "label_cn", "samples", "hits", "hit_rate", "reliable"]
        )
        for bid, st in sorted(
            band_stats.items(), key=lambda kv: -kv[1]["samples"]
        ):
            label = bid
            samples = st["samples"]
            hits = st["hits"]
            rate = hits / samples if samples else 0.0
            reliable = samples >= 30
            writer.writerow(
                [bid, label, samples, hits, f"{rate:.2%}", "yes" if reliable else "no"]
            )

    print(f"fixtures: {fixture_count}, with_score_bands: {with_score_bands}")
    print(f"bands: {len(band_stats)}, output: {output_path}")
    for bid, st in sorted(band_stats.items(), key=lambda kv: -kv[1]["samples"])[:10]:
        rate = st["hits"] / st["samples"] if st["samples"] else 0.0
        note = "OK" if st["samples"] >= 30 else "小样本"
        print(f"  {bid}: n={st['samples']}, hit={st['hits']}, rate={rate:.1%} ({note})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
