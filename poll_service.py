#!/usr/bin/env python3
"""Poll 500.com odds every N seconds and store ticks in PostgreSQL."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from time_utils import now_beijing_str

from analysis.market.tick_quality import validate_tick
from db.connection import ensure_schema, ping
from db.repository import (
    db_stats,
    insert_tick_if_changed,
    set_scraper_state,
    upsert_fixture,
)
from download_500 import DEFAULT_LEAGUES, WORLD_CUP_LEAGUES, fetch_live_fixtures
from focus_watch import focus_fids
from http_client import ScraperGuard, make_session
from poll_500 import fetch_jingcai_context, poll_fixture
from poll_interval import poll_interval_seconds

log = logging.getLogger("poll_service")
SOURCE = "500"


def run_once(
    *,
    within_days: float,
    guard: ScraperGuard,
    leagues=DEFAULT_LEAGUES,
    focus_fids: set[str] | None = None,
) -> dict:
    """``leagues=None``（默认）= live.500 时间窗内全部联赛。focus_fids 优先轮询并更新心跳。"""
    session = make_session()
    fixtures = fetch_live_fixtures(session, within_days=within_days, leagues=leagues)
    live_odds, jczq_meta = fetch_jingcai_context(session)
    focus_fids = focus_fids or set()
    summary = {
        "started_at": now_beijing_str(),
        "fixtures": len(fixtures),
        "inserted": 0,
        "unchanged": 0,
        "errors": [],
        "changed_ids": [],
        "focus_polled": 0,
        "focus_heartbeat_at": None,
    }
    if not fixtures:
        label = "全部联赛" if leagues is None else "、".join(leagues)
        log.info("无 %s 天内 %s 比赛", within_days, label)
        return summary

    # focus 场置顶轮询
    fixtures = sorted(
        fixtures,
        key=lambda fx: str(fx.fixture_id) not in focus_fids,
    )

    for fx in fixtures:
        fid = str(fx.fixture_id)
        is_focus = fid in focus_fids
        try:
            # 队名修正：统一调 ensure_fixture_identity
            from poll_500 import ensure_fixture_identity
            fx = ensure_fixture_identity(session, fx)
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
            quality = validate_tick(tick, fixture_id=fx.fixture_id)
            if quality["errors"]:
                msg = f"{fx.base_name}({fx.fixture_id}): tick 质量校验失败: {';'.join(quality['errors'])}"
                summary["errors"].append(msg)
                log.warning("%s", msg)
                continue
            if quality["warnings"]:
                raw_meta = tick.get("raw_meta") or {}
                raw_meta["quality_warnings"] = quality["warnings"]
                tick["raw_meta"] = raw_meta
            if insert_tick_if_changed(db_id, tick, source=SOURCE):
                summary["inserted"] += 1
                summary["changed_ids"].append(fx.fixture_id)
                log.info("变动 %s (%s)", fx.base_name, fx.fixture_id)
            else:
                summary["unchanged"] += 1
            # focus 场无论是否变化都计数并更新心跳
            if is_focus:
                summary["focus_polled"] += 1
                summary["focus_heartbeat_at"] = now_beijing_str()
        except Exception as exc:
            msg = f"{fx.base_name}({fx.fixture_id}): {exc}"
            summary["errors"].append(msg)
            log.warning("%s", msg)

    if summary.get("focus_heartbeat_at"):
        set_scraper_state("focus_poll_heartbeat", {"at": summary["focus_heartbeat_at"], "focus_count": summary["focus_polled"]})
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
    parser.add_argument("--interval", type=int, default=300, help="轮询间隔秒，默认 300=5分钟（北京时间 11 点后）")
    parser.add_argument("--interval-pre-jingcai", type=int, default=120, help="竞彩开售前台轮询间隔秒，默认 120")
    parser.add_argument("--days", type=float, default=7, help="只抓 N 天内比赛")
    parser.add_argument(
        "--all-leagues",
        action="store_true",
        help="包含全部联赛（默认已是全部，保留兼容）",
    )
    parser.add_argument(
        "--worldcup-only",
        action="store_true",
        help="仅抓世界杯（旧默认行为）",
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
    if args.worldcup_only:
        leagues = WORLD_CUP_LEAGUES
    else:
        leagues = None  # 全部联赛（含 --all-leagues）

    if args.once:
        run_once(within_days=args.days, guard=guard, leagues=leagues, focus_fids=set(focus_fids()))
        return 0

    log.info(
        "开始轮询 interval=%ds pre-jingcai=%ds days=%s leagues=%s focus=%d",
        args.interval,
        args.interval_pre_jingcai,
        args.days,
        "全部" if leagues is None else "、".join(leagues),
        len(focus_fids()),
    )
    while True:
        started = time.time()
        try:
            run_once(within_days=args.days, guard=guard, leagues=leagues, focus_fids=set(focus_fids()))
        except Exception:
            log.exception("轮询异常")
        elapsed = time.time() - started
        interval = poll_interval_seconds(
            default=args.interval,
            pre_jingcai=args.interval_pre_jingcai,
        )
        sleep_for = max(5.0, interval - elapsed)
        log.info(
            "下次轮询 %.0f 秒后（%s, interval=%ds）",
            sleep_for,
            "pre-jingcai" if interval == args.interval_pre_jingcai else "jingcai-hours",
            interval,
        )
        time.sleep(sleep_for)


if __name__ == "__main__":
    raise SystemExit(main())
