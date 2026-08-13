#!/usr/bin/env python3
"""第 0 关：检查近 N 天 settle 场的 closing 字段覆盖，并可选从 odds_ticks 回填。

原则：无亚盘线则不伪造；只补 closing_eu / closing_ah / SP 等库内已有字段。
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db.connection import cursor

_SQL = """
SELECT
  COUNT(*) AS settled,
  COUNT(*) FILTER (WHERE closing_eu_home IS NOT NULL) AS with_eu,
  COUNT(*) FILTER (WHERE closing_ah_line IS NOT NULL) AS with_ah,
  COUNT(*) FILTER (
    WHERE home_score IS NOT NULL
      AND away_score IS NOT NULL
      AND result_1x2 IS NOT NULL
  ) AS with_score_result
FROM match_results
WHERE settled_at > %s
"""


def report(days: int) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    with cursor() as cur:
        cur.execute(_SQL, (cutoff,))
        row = cur.fetchone()
    return {
        "settled": row["settled"],
        "with_eu": row["with_eu"],
        "with_ah": row["with_ah"],
        "with_score_result": row["with_score_result"],
    }


def _pct(num: int, den: int) -> float:
    return round(100.0 * num / den, 1) if den else 0.0


def print_report(days: int) -> None:
    stats = report(days)
    settled = stats["settled"]
    print(f"DB calibration coverage (last {days} days)")
    print(f"  settled          = {settled}")
    print(f"  with_eu          = {stats['with_eu']} ({_pct(stats['with_eu'], settled)}%)")
    print(f"  with_ah          = {stats['with_ah']} ({_pct(stats['with_ah'], settled)}%)")
    print(
        f"  with_score/result= {stats['with_score_result']} "
        f"({_pct(stats['with_score_result'], settled)}%)"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检查并回填 settle 场 closing 字段")
    parser.add_argument("--days", type=int, default=90, help="近 N 天")
    parser.add_argument("--backfill", action="store_true", help="先回填再报告")
    args = parser.parse_args(argv)

    if args.backfill:
        print("=== before backfill ===")
        print_report(args.days)
        print("\n=== backfill closing odds / SP ===")
        from scripts.backfill_closing_odds import main as backfill
        backfill(["--days", str(args.days)])
        print("\n=== after backfill ===")

    print_report(args.days)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
