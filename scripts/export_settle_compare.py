#!/usr/bin/env python3
"""导出近 N 天已结算场次的预测 vs 赛果对比。"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db.connection import cursor, ping


SQL = """
SELECT
    f.external_id AS fid,
    f.home_team AS home,
    f.away_team AS away,
    mr.score_text,
    mr.pick_1x2_cn,
    mr.pick_jingcai_cn,
    mr.hit_1x2,
    mr.hit_jingcai,
    mr.payload->'hits'->>'ah' AS hit_ah,
    mr.hit_ou,
    mr.closing_ah_line,
    mr.payload->'closing_odds'->'ou'->'line' AS closing_ou_line,
    mr.payload->'opening_odds'->'eu_home' AS eu_open_home,
    mr.payload->'opening_odds'->'eu_draw' AS eu_open_draw,
    mr.payload->'opening_odds'->'eu_away' AS eu_open_away,
    mr.payload->'closing_odds'->'eu_home' AS eu_close_home,
    mr.payload->'closing_odds'->'eu_draw' AS eu_close_draw,
    mr.payload->'closing_odds'->'eu_away' AS eu_close_away,
    mr.payload->'closing_odds'->'ou'->'line' AS ou_line,
    mr.payload->'hits' AS hits,
    mr.payload->>'score_source' AS score_source,
    mr.settled_at
FROM match_results mr
JOIN fixtures f ON f.id = mr.fixture_id
WHERE f.source = '500'
  AND mr.settled_at > NOW() - (%s || ' days')::interval
ORDER BY mr.settled_at DESC
"""


def _hit_label(val):
    if val is None:
        return ""
    return "Y" if val is True else ("N" if val is False else str(val))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导出已结算场次的预测命中对比")
    parser.add_argument("--days", type=int, default=14, help="近 N 天")
    parser.add_argument("--output", "-o", default="-", help="输出文件（默认 stdout）")
    args = parser.parse_args(argv)

    if not ping():
        print("数据库未连接", file=sys.stderr)
        return 1

    rows: list[dict] = []
    with cursor() as cur:
        cur.execute(SQL, (str(args.days),))
        rows = [dict(r) for r in cur.fetchall()]

    header = [
        "fid", "home", "away", "score", "预测1x2", "预测竞彩",
        "hit_1x2", "hit_竞彩", "hit_亚盘", "hit_ou",
        "亚盘线", "OU线",
        "欧赔初(主/平/客)", "欧赔收(主/平/客)",
        "score_source", "settled_at",
    ]

    def fmt_eu(h, d, a):
        if h is None:
            return ""
        return f"{h}/{d}/{a}"

    def fmt_ou_line(v):
        if isinstance(v, dict):
            v = v.get("line")
        if v is None:
            return ""
        return str(v)

    lines = []
    for r in rows:
        hits = r.get("hits") or {}
        lines.append([
            r["fid"],
            r["home"],
            r["away"],
            r["score_text"],
            r["pick_1x2_cn"] or "",
            r["pick_jingcai_cn"] or "",
            _hit_label(r["hit_1x2"]),
            _hit_label(r["hit_jingcai"]),
            _hit_label(r["hit_ah"]),
            r["hit_ou"] or "",
            r["closing_ah_line"] if r["closing_ah_line"] is not None else "",
            fmt_ou_line(r["closing_ou_line"]),
            fmt_eu(r["eu_open_home"], r["eu_open_draw"], r["eu_open_away"]),
            fmt_eu(r["eu_close_home"], r["eu_close_draw"], r["eu_close_away"]),
            r["score_source"] or "",
            r["settled_at"],
        ])

    out = sys.stdout if args.output == "-" else open(args.output, "w", newline="", encoding="utf-8")
    try:
        writer = csv.writer(out)
        writer.writerow(header)
        writer.writerows(lines)
    finally:
        if out is not sys.stdout:
            out.close()

    stats = {
        "total": len(rows),
        "with_prediction": sum(1 for r in rows if r["pick_1x2_cn"] or r["pick_jingcai_cn"]),
        "with_hit_1x2": sum(1 for r in rows if r["hit_1x2"] is not None),
        "with_hit_ou": sum(1 for r in rows if r["hit_ou"]),
        "with_hits_obj": sum(1 for r in rows if isinstance(r.get("hits"), dict)),
        "zero_zero": sum(1 for r in rows if r["score_text"] == "0-0"),
    }
    print(json.dumps(stats, ensure_ascii=False), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
