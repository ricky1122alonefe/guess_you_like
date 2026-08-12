#!/usr/bin/env python3
"""Resettle recently settled 0-0 matches whose real score differs."""
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db.repository import list_match_results_map, get_fixture_by_external
from match_settlement import _resolve_score, settle_fixture

# 已知可疑场：强制重新 settle 以刷新比分 + closing OU
TARGETS: list[str] = ["1420010", "1453755"]


def _resettle_one(ext: str, scoreboard: dict, *, force: bool = False):
    fx = get_fixture_by_external("500", ext)
    if not fx:
        return None, f"{ext}: fixture not found"
    fresh = _resolve_score(fx, scoreboard)
    if fresh is None:
        return None, f"{ext}: cannot resolve score"
    if not force and fresh.home_score == 0 and fresh.away_score == 0:
        return (ext, fx.get("match_name"), f"{fresh.home_score}-{fresh.away_score}", "genuine 0-0"), None
    settle_fixture(fx, fresh, output_root="output/service")
    return (ext, fx.get("match_name"), f"{fresh.home_score}-{fresh.away_score}", "resettled"), None


def main():
    rows = list_match_results_map(source="500", limit=500)
    cutoff = datetime.now(timezone.utc) - timedelta(days=14)
    scoreboard: dict = {}
    fixed = []
    genuine = []
    errors = []

    # 强制核对已知目标场（也用于刷新 closing OU）
    for ext in TARGETS:
        result, err = _resettle_one(ext, scoreboard, force=True)
        if err:
            errors.append(err)
        elif result and result[3] == "genuine 0-0":
            genuine.append(result)
        elif result:
            fixed.append(result)

    # 扫描近 14 天其它 0-0：只修真正错误的
    for r in rows.values():
        if r.get("home_score") != 0 or r.get("away_score") != 0:
            continue
        settled_at = r.get("settled_at")
        if not settled_at or settled_at < cutoff:
            continue
        ext = str(r.get("external_id"))
        if ext in TARGETS:
            continue  # 已处理
        fx = get_fixture_by_external("500", ext)
        if not fx:
            continue
        fresh = _resolve_score(fx, scoreboard)
        if fresh is None:
            continue
        if fresh.home_score == 0 and fresh.away_score == 0:
            genuine.append((ext, fx.get("match_name"), "0-0", "genuine 0-0"))
            continue
        try:
            settle_fixture(fx, fresh, output_root="output/service")
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
