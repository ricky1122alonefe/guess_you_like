#!/usr/bin/env python3
"""Export odds bucket stats for calibration review."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.market.odds_bucket_stats import build_bucket_stats


def _print_table(title: str, buckets: list[dict], fav: bool = False) -> None:
    print(f"\n{title}")
    header = ["bucket", "n", "主%", "平%", "客%"]
    if fav:
        header += ["热门命中%"]
    header += ["去水隐含%", "edge", "可靠"]
    print("\t".join(header))
    for b in buckets:
        n = b["n"]
        reliable = "是" if b.get("reliable") else "小样本"
        row = [
            b["bucket"],
            str(n),
            f"{b['rate_home']:.1%}" if b["rate_home"] is not None else "—",
            f"{b['rate_draw']:.1%}" if b["rate_draw"] is not None else "—",
            f"{b['rate_away']:.1%}" if b["rate_away"] is not None else "—",
        ]
        if fav:
            row.append(f"{b['fav_hit_rate']:.1%}" if b.get("fav_hit_rate") is not None else "—")
        row.append(f"{b['mkt_implied_avg']:.1%}" if b.get("mkt_implied_avg") is not None else "—")
        row.append(f"{b['edge_vs_mkt']:+.1%}" if b.get("edge_vs_mkt") is not None else "—")
        row.append(reliable)
        print("\t".join(row))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导出赔率桶命中率统计")
    parser.add_argument("--days", type=int, default=90, help="统计最近 N 天 settle（默认 90）")
    parser.add_argument("--json", dest="out_json", help="输出 JSON 文件路径")
    args = parser.parse_args(argv)

    stats = build_bucket_stats(days=args.days)
    _print_table("主胜赔桶", stats["home"])
    _print_table("平赔桶", stats["draw"])
    _print_table("热门最短赔桶", stats["fav"], fav=True)
    _print_table("亚盘桶", stats["ah"])

    if args.out_json:
        Path(args.out_json).write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n已写入 {args.out_json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
