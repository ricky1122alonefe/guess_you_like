#!/usr/bin/env python3
"""Verify recent 0-0 settled scores against 500 data pages."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import requests

from db.repository import list_match_results_map, get_fixture_by_external
from download_500 import _session, BASE
from http_client import make_session
from match_settlement import _resolve_score


def _probe_500_network(timeout: float = 10) -> tuple[bool, str]:
    """轻探 500 网络可达性；被封/403/连接失败返回 (False, reason)。"""
    try:
        session = make_session()
        resp = session.get(BASE, timeout=timeout, allow_redirects=True)
        if resp.status_code in (403, 429):
            return False, f"HTTP {resp.status_code}"
        if resp.status_code >= 500:
            return False, f"HTTP {resp.status_code}"
        # 200 也未必能爬到数据页，但起码网络层未封
        return True, ""
    except requests.RequestException as exc:
        return False, str(exc)


def _verify_one(fx: dict, scoreboard: dict, *, mismatches: list, verified: list) -> None:
    ext = str(fx.get("external_id"))
    fresh = _resolve_score(fx, scoreboard)
    if fresh is None:
        mismatches.append((ext, fx.get("match_name"), "no fresh score"))
        return
    if fresh.home_score != 0 or fresh.away_score != 0:
        mismatches.append((ext, fx.get("match_name"), f"fresh {fresh.home_score}-{fresh.away_score}"))
    else:
        verified.append((ext, fx.get("match_name"), fresh.score_source))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="核验近 14 天 0-0 比分与 500 数据页是否一致")
    parser.add_argument("--days", type=int, default=14, help="扫描最近 N 天（默认 14）")
    parser.add_argument(
        "--fixture-id", action="append", default=[],
        help="指定单个/多个 fixture_id 单查（可多次使用）",
    )
    args = parser.parse_args(argv)

    ok, reason = _probe_500_network()
    if not ok:
        print(f"网络不可用，跳过 fresh 核验: {reason}")
        return 2

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    session = _session()
    mismatches = []
    verified = []

    specified = [str(x).strip() for x in args.fixture_id if str(x).strip()]
    if specified:
        for ext in specified:
            fx = get_fixture_by_external("500", ext)
            if not fx:
                print(f"fixture {ext} not found")
                return 1
            _verify_one(fx, {}, mismatches=mismatches, verified=verified)
    else:
        rows = list_match_results_map(source="500", limit=500)
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
            _verify_one(fx, {}, mismatches=mismatches, verified=verified)

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
