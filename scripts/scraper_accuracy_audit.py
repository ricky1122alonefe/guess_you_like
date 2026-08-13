#!/usr/bin/env python3
"""爬虫准确性门禁审计。

覆盖范围：poll_500 / jingcai_500 / betfair_500 / download_500 / poll_service /
db/repository 写入路径。输出 JSON + 人读摘要，exit 1 当存在 P0 error。
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db.connection import cursor
from poll_500 import is_dirty_team_label
from analysis.market.tick_quality import validate_tick

log = logging.getLogger(__name__)

DEFAULT_HOURS = 48


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _dirty_team_count(cutoff: datetime) -> int:
    with cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS n
            FROM fixtures
            WHERE source = '500'
              AND updated_at > %s
              AND (
                home_team = '' OR away_team = ''
                OR home_team IS NULL OR away_team IS NULL
              )
            """,
            (cutoff,),
        )
        empty = cur.fetchone()["n"] or 0

        cur.execute(
            """
            SELECT home_team, away_team
            FROM fixtures
            WHERE source = '500' AND updated_at > %s
            """,
            (cutoff,),
        )
        dirty = 0
        for row in cur.fetchall():
            if is_dirty_team_label(row["home_team"]) or is_dirty_team_label(row["away_team"]):
                dirty += 1
        return empty + dirty


def _latest_tick_consistency(cutoff: datetime) -> dict[str, Any]:
    """检查 odds_latest 与最新 odds_ticks 关键字段是否一致。"""
    mismatches = 0
    with cursor() as cur:
        cur.execute(
            """
            SELECT
              l.fixture_id,
              f.external_id,
              l.tick_hash AS latest_hash,
              t.tick_hash AS tick_hash,
              l.eu_home AS l_eu_home, t.eu_home AS t_eu_home,
              l.eu_away AS l_eu_away, t.eu_away AS t_eu_away,
              l.ah_line AS l_ah_line, t.ah_line AS t_ah_line,
              l.ah_home_water AS l_ah_home_water, t.ah_home_water AS t_ah_home_water,
              l.ah_away_water AS l_ah_away_water, t.ah_away_water AS t_ah_away_water
            FROM odds_latest l
            JOIN fixtures f ON f.id = l.fixture_id
            JOIN odds_ticks t ON t.fixture_id = l.fixture_id
            WHERE l.captured_at > %s
              AND t.captured_at = (
                SELECT MAX(captured_at) FROM odds_ticks
                WHERE fixture_id = l.fixture_id
              )
            """,
            (cutoff,),
        )
        rows = cur.fetchall()
        bad_fids = []
        for r in rows:
            if r["latest_hash"] != r["tick_hash"]:
                mismatches += 1
                bad_fids.append(str(r["external_id"]))
                continue
            for col in ("eu_home", "eu_away", "ah_line", "ah_home_water", "ah_away_water"):
                if r[f"l_{col}"] != r[f"t_{col}"]:
                    mismatches += 1
                    bad_fids.append(f"{r['external_id']}:{col}")
                    break
    return {"mismatches": mismatches, "bad_fids": bad_fids[:20], "checked": len(rows)}


def _raw_meta_missing_rate(cutoff: datetime) -> dict[str, Any]:
    with cursor() as cur:
        cur.execute(
            """
            SELECT
              COUNT(*) AS total,
              COUNT(*) FILTER (WHERE raw_meta->>'jingcai' IS NULL OR raw_meta->'jingcai'->>'match_num' IS NULL) AS no_jingcai,
              COUNT(*) FILTER (WHERE raw_meta->>'betfair' IS NULL) AS no_betfair,
              COUNT(*) FILTER (WHERE raw_meta->'ou'->>'has_data' IS NULL OR (raw_meta->'ou'->>'has_data')::bool = false) AS no_ou
            FROM odds_ticks t
            JOIN fixtures f ON f.id = t.fixture_id
            WHERE f.source = '500' AND t.captured_at > %s
            """,
            (cutoff,),
        )
        row = cur.fetchone()
    total = row["total"] or 0
    return {
        "total": total,
        "jingcai_missing": row["no_jingcai"],
        "betfair_missing": row["no_betfair"],
        "ou_missing": row["no_ou"],
        "jingcai_missing_rate": round(row["no_jingcai"] / total, 3) if total else 0,
        "betfair_missing_rate": round(row["no_betfair"] / total, 3) if total else 0,
        "ou_missing_rate": round(row["no_ou"] / total, 3) if total else 0,
    }


def _scraper_state() -> dict[str, Any]:
    from db.repository import get_scraper_state

    state = get_scraper_state("poll_500_last_run")
    return {
        "last_run": state.get("started_at"),
        "inserted": state.get("inserted", 0),
        "unchanged": state.get("unchanged", 0),
        "errors": state.get("errors", []),
        "fixtures": state.get("fixtures", 0),
    }


def _eu_sticky_diagnosis(cutoff: datetime) -> dict[str, Any]:
    """统计近 N 小时 ticks>=5 的场中，欧赔粘滞但亚/SP/必发有动的占比。"""
    with cursor() as cur:
        cur.execute(
            """
            SELECT f.external_id, t.fixture_id
            FROM odds_ticks t
            JOIN fixtures f ON f.id = t.fixture_id
            WHERE f.source = '500' AND t.captured_at > %s
            GROUP BY f.external_id, t.fixture_id
            HAVING COUNT(*) >= 5
            LIMIT 500
            """,
            (cutoff,),
        )
        rows = cur.fetchall()
    total = len(rows)
    if not total:
        return {"total": 0, "eu_sticky_but_moved": 0, "rate": 0.0}

    eu_sticky_but_moved = 0
    for r in rows:
        fid = r["fixture_id"]
        with cursor() as cur:
            cur.execute(
                """
                SELECT eu_home, eu_draw, eu_away, ah_line, ah_home_water, ah_away_water, raw_meta
                FROM odds_ticks
                WHERE fixture_id = %s AND captured_at > %s
                ORDER BY captured_at ASC
                """,
                (fid, cutoff),
            )
            ticks = cur.fetchall()
        if len(ticks) < 2:
            continue
        first = ticks[0]
        last = ticks[-1]
        eu_home_d = abs((_to_float(last["eu_home"]) or 0) - (_to_float(first["eu_home"]) or 0))
        eu_draw_d = abs((_to_float(last["eu_draw"]) or 0) - (_to_float(first["eu_draw"]) or 0))
        eu_away_d = abs((_to_float(last["eu_away"]) or 0) - (_to_float(first["eu_away"]) or 0))
        eu_sticky = max(eu_home_d, eu_draw_d, eu_away_d) < 0.02

        ah_line_d = abs((_to_float(last["ah_line"]) or 0) - (_to_float(first["ah_line"]) or 0))
        ah_hw_d = abs((_to_float(last["ah_home_water"]) or 0) - (_to_float(first["ah_home_water"]) or 0))
        ah_aw_d = abs((_to_float(last["ah_away_water"]) or 0) - (_to_float(first["ah_away_water"]) or 0))
        ah_moved = ah_line_d >= 0.25 or max(ah_hw_d, ah_aw_d) >= 0.05

        raw0 = first["raw_meta"] or {}
        raw1 = last["raw_meta"] or {}
        if isinstance(raw0, str):
            raw0 = json.loads(raw0)
        if isinstance(raw1, str):
            raw1 = json.loads(raw1)
        jc0 = raw0.get("jingcai") or {}
        jc1 = raw1.get("jingcai") or {}
        sp_moved = any(
            abs((_to_float(jc1.get(k)) or 0) - (_to_float(jc0.get(k)) or 0)) >= 0.03
            for k in ("sp_home", "sp_draw", "sp_away")
        )
        bf0 = raw0.get("betfair") or {}
        bf1 = raw1.get("betfair") or {}
        bf_moved = (bf1.get("volume_total") or 0) != (bf0.get("volume_total") or 0) and (bf1.get("volume_total") or 0) > 0

        if eu_sticky and (ah_moved or sp_moved or bf_moved):
            eu_sticky_but_moved += 1

    return {
        "total": total,
        "eu_sticky_but_moved": eu_sticky_but_moved,
        "rate": round(eu_sticky_but_moved / total, 3),
    }


def run_audit(*, hours: int, live_sample: int = 0) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    # 1) tick 质量
    with cursor() as cur:
        cur.execute(
            """
            SELECT f.external_id, t.*
            FROM odds_ticks t
            JOIN fixtures f ON f.id = t.fixture_id
            WHERE f.source = '500' AND t.captured_at > %s
            ORDER BY t.captured_at DESC
            LIMIT 2000
            """,
            (cutoff,),
        )
        ticks = cur.fetchall()

    tick_errors = 0
    tick_warnings = 0
    error_fids: set[str] = set()
    warn_fids: set[str] = set()
    for row in ticks:
        # reconstruct tick shape expected by _validate_tick
        tick = dict(row)
        tick["raw_meta"] = row["raw_meta"] if isinstance(row["raw_meta"], dict) else json.loads(row["raw_meta"] or "{}")
        v = validate_tick(tick, fixture_id=str(row["external_id"]))
        if v["errors"]:
            tick_errors += 1
            error_fids.add(str(row["external_id"]))
        if v["warnings"]:
            tick_warnings += 1
            warn_fids.add(str(row["external_id"]))

    dirty_teams = _dirty_team_count(cutoff)
    consistency = _latest_tick_consistency(cutoff)
    meta_missing = _raw_meta_missing_rate(cutoff)
    sticky = _eu_sticky_diagnosis(cutoff)
    state = _scraper_state()

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "hours": hours,
        "ticks_checked": len(ticks),
        "tick_errors": tick_errors,
        "tick_warnings": tick_warnings,
        "error_fixture_count": len(error_fids),
        "warn_fixture_count": len(warn_fids),
        "dirty_team_count": dirty_teams,
        "latest_tick_mismatches": consistency["mismatches"],
        "latest_tick_checked": consistency["checked"],
        "raw_meta_missing": meta_missing,
        "eu_sticky_but_moved": sticky,
        "scraper_state": state,
        "error_fixture_ids": sorted(error_fids)[:20],
        "warn_fixture_ids": sorted(warn_fids)[:20],
        "latest_mismatch_fids": consistency["bad_fids"],
    }
    return report


def _print_summary(report: dict[str, Any]) -> None:
    print("=" * 60)
    print("爬虫准确性审计摘要")
    print("=" * 60)
    print(f"检查窗口: 近 {report['hours']} 小时")
    print(f"检查 ticks: {report['ticks_checked']}")
    print(f"  P0 error 数: {report['tick_errors']} (涉及 {report['error_fixture_count']} 场)")
    print(f"  warning 数: {report['tick_warnings']} (涉及 {report['warn_fixture_count']} 场)")
    print(f"脏队名/空队名场数: {report['dirty_team_count']}")
    print(f"odds_latest 与最新 tick 不一致: {report['latest_tick_mismatches']} / {report['latest_tick_checked']}")
    mm = report["raw_meta_missing"]
    print(f"raw_meta 缺失率: 竞彩={mm['jingcai_missing_rate']:.1%} 必发={mm['betfair_missing_rate']:.1%} OU={mm['ou_missing_rate']:.1%}")
    st = report["eu_sticky_but_moved"]
    print(f"欧粘亚动占比: {st['eu_sticky_but_moved']}/{st['total']} = {st['rate']:.1%}")
    state = report["scraper_state"]
    print(f"poll_500_last_run: {state['last_run']} | inserted={state['inserted']} unchanged={state['unchanged']} errors={len(state['errors'])}")
    print("=" * 60)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="爬虫准确性审计")
    parser.add_argument("--hours", type=int, default=DEFAULT_HOURS)
    parser.add_argument("--live-sample", type=int, default=0, help="现场重抓样本数（需网络）")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)

    report = run_audit(hours=args.hours, live_sample=args.live_sample)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    else:
        _print_summary(report)

    p0 = report["tick_errors"] + report["latest_tick_mismatches"] + report["dirty_team_count"]
    return 1 if p0 > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
