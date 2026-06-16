#!/usr/bin/env python3
"""Refresh WC ledger and print opening-characteristics summary."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from worldcup_analytics import (
    compute_opening_characteristics,
    load_tournament_records,
    refresh_tournament_ledger,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="本届世界杯开盘特征总结")
    parser.add_argument("--output-root", default="output/service")
    parser.add_argument("--no-save", action="store_true", help="仅打印，不写 ledger.json")
    args = parser.parse_args(argv)
    root = Path(args.output_root)

    if not args.no_save:
        refresh_tournament_ledger(root)

    records = load_tournament_records(root)
    chars = compute_opening_characteristics(records)
    print(json.dumps({
        "sample_size": chars.get("sample_size"),
        "summary": chars.get("summary"),
        "traits": chars.get("traits"),
        "stats": chars.get("stats"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
