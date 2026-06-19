#!/usr/bin/env python3
"""Poll 500.com odds every N seconds and store ticks in PostgreSQL."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from time_utils import now_beijing_str

from db.connection import ensure_schema, ping
from db.repository import (
    db_stats,
    insert_tick_if_changed,
    set_scraper_state,
    upsert_fixture,
)
from download_500 import DEFAULT_LEAGUES, fetch_live_fixtures
from http_client import ScraperGuard, make_session
from poll_500 import fetch_jingcai_context, poll_fixture

log = logging.getLogger("poll_service")
SOURCE = "500"


def run_once(*, within_days: float, guard: ScraperGuard, leagues=DEFAULT_LEAGUES) -> dict:
    session = make_session()
    fixtures = fetch_live_fixtures(session, within_days=within_days, leagues=leagues)
    live_odds, jczq_meta = fetch_jingcai_context(session)
    summary = {
        "started_at": now_beijing_str(),
        "fixtures": len(fixtures),
        "inserted": 0,
        "unchanged": 0,
        "errors": [],
        "changed_ids": [],
    }
    if not fixtures:
        label = "全部联赛" if leagues is None else "、".join(leagues)
        log.info("无 %s 天内 %s 比赛", within_days, label)
        return summary

    for fx in fixtures:
        try:
            db_id = upsert_fixture(
                source=SOURCE,
                external_id=fx.fixture_id,
                home_team=fx.home,
                away_team=fx.away,
                match_name=fx.base_name,
                kickoff_at=fx.kickoff,
            )
            tick = poll_fixture(
                session, fx, guard=guard,
                live_odds=live_odds, jczq_meta=jczq_meta,
            )
            if insert_tick_if_changed(db_id, tick, source=SOURCE):
                summary["inserted"] += 1
                summary["changed_ids"].append(fx.fixture_id)
                log.info("变动 %s (%s)", fx.base_name, fx.fixture_id)
            else:
                summary["unchanged"] += 1
        except Exception as exc:
            msg = f"{fx.base_name}({fx.fixture_id}): {exc}"
            summary["errors"].append(msg)
            log.warning("%s", msg)

    stats = db_stats()
    summary.update(stats)
    set_scraper_state("poll_500_last_run", summary)
    log.info(
        "轮询完成 fixtures=%d inserted=%d unchanged=%d errors=%d ticks_total=%d",
        summary["fixtures"], summary["inserted"], summary["unchanged"],
        len(summary["errors"]), stats.get("ticks", 0),
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    from __version__ import __version__

    parser = argparse.ArgumentParser(description="每 N 秒轻量抓取 500.com 赔率写入 Postgres")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--interval", type=int, default=300, help="轮询间隔秒，默认 300=5分钟")
    parser.add_argument("--days", type=float, default=7, help="只抓 N 天内比赛")
    parser.add_argument(
        "--all-leagues",
        action="store_true",
        help="包含全部联赛（默认仅世界杯）",
    )
    parser.add_argument("--once", action="store_true", help="只跑一轮")
    parser.add_argument("--init-db", action="store_true", help="初始化 schema 后退出")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    if not ping():
        log.error("无法连接 PostgreSQL，请先 docker compose up -d db")
        return 1

    ensure_schema()

    if args.init_db:
        log.info("schema OK: %s", db_stats())
        return 0

    guard = ScraperGuard(min_delay=1.5, max_delay=3.0)
    leagues = None if args.all_leagues else DEFAULT_LEAGUES

    if args.once:
        run_once(within_days=args.days, guard=guard, leagues=leagues)
        return 0

    log.info("开始轮询 interval=%ds days=%s leagues=%s",
             args.interval, args.days,
             "全部" if leagues is None else "、".join(leagues))
    while True:
        started = time.time()
        try:
            run_once(within_days=args.days, guard=guard, leagues=leagues)
        except Exception:
            log.exception("轮询异常")
        elapsed = time.time() - started
        sleep_for = max(5.0, args.interval - elapsed)
        log.info("下次轮询 %.0f 秒后", sleep_for)
        time.sleep(sleep_for)


if __name__ == "__main__":
    raise SystemExit(main())
