#!/usr/bin/env python3
"""Resettle recently settled 0-0 matches whose real score differs."""
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db.repository import list_match_results_map, get_fixture_by_external
from download_500 import _session
from match_settlement import _resolve_score, settle_fixture


def main():
    rows = list_match_results_map(source="500", limit=500)
    cutoff = datetime.now(timezone.utc) - timedelta(days=14)
    session = _session()
    fixed = []
    errors = []
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
            continue
        if fresh.home_score == 0 and fresh.away_score == 0:
            continue  # genuine 0-0
        try:
            settle_fixture(fx, fresh, output_root="output/service")
            fixed.append((ext, fx.get("match_name"), f"{fresh.home_score}-{fresh.away_score}"))
        except Exception as exc:
            errors.append((ext, str(exc)))
    print("fixed", len(fixed))
    for f in fixed:
        print(" ", f)
    if errors:
        print("errors", len(errors))
        for e in errors:
            print(" ", e)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
