#!/usr/bin/env python3
"""Settle finished matches: fetch FT scores and persist closing odds."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db.connection import ensure_schema, ping
from match_settlement import run_settlement


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="抓取已完场赛果并写入数据库")
    parser.add_argument(
        "--output-root",
        default="output/service",
        help="服务输出目录（用于读取 latest.json 预测）",
    )
    parser.add_argument(
        "--resettle",
        action="store_true",
        help="重新结算已有赛果（用官方终场比分覆盖错误记录）",
    )
    args = parser.parse_args(argv)
    root = Path(args.output_root)

    if ping():
        ensure_schema()
    else:
        print("警告：数据库未连接，无法写入 match_results", file=sys.stderr)

    summary = run_settlement(root, resettle=args.resettle)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
