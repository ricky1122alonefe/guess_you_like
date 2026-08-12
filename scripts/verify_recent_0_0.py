#!/usr/bin/env python3
"""Verify recent 0-0 settled scores against 500 data pages."""
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db.repository import list_match_results_map, get_fixture_by_external
from download_500 import _session
from match_settlement import _resolve_score


def main():
    rows = list_match_results_map(source="500", limit=500)
    cutoff = datetime.now(timezone.utc) - timedelta(days=14)
    session = _session()
    mismatches = []
    verified = []
    for r in rows.values():
        if r.get("home_score") != 0 or r.get("away_score") != 0:
            continue
        settled_at = r.get("settled_at")
        if not settled_at or settled_at < cutoff:
            continue
        ext = str(r.get("external_id"))
        fx = get_fixture_by_external("500", ext)
        if not fx:
            continue
        fresh = _resolve_score(fx, {})
        if fresh is None:
            mismatches.append((ext, r.get("match_name"), "no fresh score"))
            continue
        if fresh.home_score != 0 or fresh.away_score != 0:
            mismatches.append((ext, r.get("match_name"), f"fresh {fresh.home_score}-{fresh.away_score}"))
        else:
            verified.append((ext, r.get("match_name"), fresh.score_source))
    print("verified", len(verified))
    for v in verified:
        print(" ", v)
    if mismatches:
        print("MISMATCHES")
        for m in mismatches:
            print(" ", m)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
