"""批量修正 DB 中近 N 天的脏队名。

用法：
    python -m scripts.fix_dirty_team_names --days 7 [--limit 50]
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import timedelta

from db.connection import cursor
from match_settlement import ensure_fixture_identity
from poll_500 import is_dirty_team_label
from time_utils import now_beijing

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _fetch_dirty_fixtures(days: int, limit: int | None = None) -> list[dict]:
    """扫描近 days 天（按开球时间）主客含脏名的记录，并用 poll_500.is_dirty_team_label 二次确认。"""
    sql = """
    SELECT id, external_id, source, home_team, away_team, match_name, kickoff_at
    FROM fixtures
    WHERE kickoff_at >= NOW() - INTERVAL '%s days'
    ORDER BY kickoff_at ASC, id ASC
    """
    params = [days]
    if limit:
        sql += " LIMIT %s"
        params.append(limit)
    with cursor() as cur:
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
    return [
        r for r in rows
        if is_dirty_team_label(r.get("home_team") or "")
        or is_dirty_team_label(r.get("away_team") or "")
    ]


def _report(row: dict, after_home: str, after_away: str, match_name: str) -> None:
    before = f"{row['home_team']} VS {row['away_team']}"
    after = f"{after_home} VS {after_away}"
    if before != after:
        log.info("fid=%s fixed: %s -> %s", row["external_id"], before, after)
    else:
        log.info("fid=%s unchanged: %s", row["external_id"], before)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fix dirty team names in DB")
    parser.add_argument("--days", type=int, default=7, help="Scan kickoff within last N days")
    parser.add_argument("--limit", type=int, default=None, help="Max fixtures to process")
    args = parser.parse_args()

    rows = _fetch_dirty_fixtures(args.days, args.limit)
    if not rows:
        print(f"近 {args.days} 天无脏队名记录。")
        return 0

    fixed = unchanged = failed = 0
    before_after: list[tuple[str, str, str]] = []

    for row in rows:
        external_id = str(row["external_id"])
        before_home = row["home_team"] or ""
        before_away = row["away_team"] or ""
        before = f"{before_home} VS {before_away}"
        try:
            ensure_fixture_identity(fixture_id=external_id, source=row["source"] or "500")
        except Exception as exc:
            log.warning("fid=%s 修正失败: %s", external_id, exc)
            failed += 1
            before_after.append((external_id, before, before))
            continue

        # 回读确认
        with cursor() as cur:
            cur.execute(
                "SELECT home_team, away_team, match_name FROM fixtures WHERE external_id=%s AND source=%s",
                (external_id, row["source"] or "500"),
            )
            updated = cur.fetchone()
        after_home = updated["home_team"] if updated else before_home
        after_away = updated["away_team"] if updated else before_away
        after_match = updated["match_name"] if updated else (row["match_name"] or "")
        after = f"{after_home} VS {after_away}"

        _report(row, after_home, after_away, after_match)
        before_after.append((external_id, before, after))
        if after != before or not (is_dirty_team_label(after_home) or is_dirty_team_label(after_away)):
            fixed += 1
        else:
            unchanged += 1

    print("\n===== 脏队名修正报告 =====")
    print(f"扫描天数: {args.days} | 共 {len(rows)} 条 | 修正/成功 {fixed} | 仍脏 {unchanged} | 失败 {failed}")
    print("\nfid | 修正前 -> 修正后")
    print("-" * 60)
    for fid, before, after in before_after:
        print(f"{fid} | {before} -> {after}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
