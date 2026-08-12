#!/usr/bin/env python3
"""Backfill payload.hits for recently settled rows without Python per-row overhead."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db.connection import cursor

SQL = """
    WITH updated AS (
        UPDATE match_results
        SET payload = jsonb_set(
            COALESCE(payload, '{}'::jsonb),
            '{hits}',
            jsonb_build_object(
                '1x2', COALESCE(payload->'hits'->'1x2', 'null'::jsonb),
                'ah', COALESCE(payload->'hits'->'ah', 'null'::jsonb),
                'ou', COALESCE(
                    payload->'hits'->'ou',
                    CASE
                        WHEN closing_ou_line IS NULL THEN 'null'::jsonb
                        WHEN (home_score + away_score) > closing_ou_line THEN '"over"'::jsonb
                        WHEN (home_score + away_score) < closing_ou_line THEN '"under"'::jsonb
                        ELSE '"push"'::jsonb
                    END
                ),
                'jingcai', COALESCE(payload->'hits'->'jingcai', 'null'::jsonb)
            )
        )
        WHERE settled_at > NOW() - INTERVAL '14 days'
        RETURNING fixture_id
    )
    SELECT COUNT(*) FROM updated;
"""


def main():
    with cursor() as cur:
        cur.execute(SQL)
        n = cur.fetchone()["count"]
    print(f"backfill payload.hits rows: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
