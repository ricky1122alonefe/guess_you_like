#!/usr/bin/env python3
"""Resettle recently settled 0-0 matches whose real score differs."""
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
from match_settlement import _resolve_score, settle_fixture

# 已知可疑场：强制重新 settle 以刷新比分 + closing OU + 0-0 可信度盖章
TARGETS: list[str] = ["1420010", "1453755"]


def _probe_500_network(timeout: float = 10) -> tuple[bool, str]:
    """轻探 500 网络可达性；被封/403/连接失败返回 (False, reason)。"""
    try:
        session = make_session()
        resp = session.get(BASE, timeout=timeout, allow_redirects=True)
        if resp.status_code in (403, 429):
            return False, f"HTTP {resp.status_code}"
        if resp.status_code >= 500:
            return False, f"HTTP {resp.status_code}"
        return True, ""
    except requests.RequestException as exc:
        return False, str(exc)


def _resettle_one(ext: str, scoreboard: dict, *, force: bool = False):
    fx = get_fixture_by_external("500", ext)
    if not fx:
        return None, f"{ext}: fixture not found"
    fresh = _resolve_score(fx, scoreboard)
    if fresh is None:
        return None, f"{ext}: cannot resolve score"
    # 对任何确认的 0-0 也重新 settle，用于 payload 盖章 verified_0_0 / 刷新 closing_ou
    is_genuine_0_0 = fresh.home_score == 0 and fresh.away_score == 0
    if not force and not is_genuine_0_0:
        return (ext, fx.get("match_name"), f"{fresh.home_score}-{fresh.away_score}", "no change"), None
    settle_fixture(fx, fresh, output_root="output/service")
    action = "genuine 0-0" if is_genuine_0_0 else "resettled"
    return (ext, fx.get("match_name"), f"{fresh.home_score}-{fresh.away_score}", action), None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="重新结算可疑 0-0 场次或核验指定场")
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
    scoreboard: dict = {}
    fixed = []
    genuine = []
    errors = []

    specified = [str(x).strip() for x in args.fixture_id if str(x).strip()]

    # 强制核对已知目标场（也用于刷新 closing OU / 0-0 盖章）
    targets = specified if specified else TARGETS
    for ext in targets:
        result, err = _resettle_one(ext, scoreboard, force=True)
        if err:
            errors.append(err)
        elif result and result[3] == "genuine 0-0":
            genuine.append(result)
        elif result:
            fixed.append(result)

    # 扫描近 N 天其它 0-0：只修真正错误的
    if not specified:
        rows = list_match_results_map(source="500", limit=500)
        for r in rows.values():
            if r.get("home_score") != 0 or r.get("away_score") != 0:
                continue
            settled_at = r.get("settled_at")
            if not settled_at or settled_at < cutoff:
                continue
            ext = str(r.get("external_id"))
            if ext in targets:
                continue  # 已处理
            fx = get_fixture_by_external("500", ext)
            if not fx:
                continue
            fresh = _resolve_score(fx, scoreboard)
            if fresh is None:
                continue
            try:
                settle_fixture(fx, fresh, output_root="output/service")
                if fresh.home_score == 0 and fresh.away_score == 0:
                    genuine.append((ext, fx.get("match_name"), "0-0", "genuine 0-0"))
                else:
                    fixed.append((ext, fx.get("match_name"), f"{fresh.home_score}-{fresh.away_score}", "resettled"))
            except Exception as exc:
                errors.append((ext, str(exc)))

    print("resettled", len(fixed))
    for f in fixed:
        print(" ", f)
    print("genuine 0-0", len(genuine))
    for g in genuine:
        print(" ", g)
    if errors:
        print("errors", len(errors))
        for e in errors:
            print(" ", e)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
