#!/usr/bin/env python3
"""Rebuild Asian handicap win-rate ledger and recommendation backtest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ah_analytics import refresh_ah_ledger


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh AH win-rate ledger")
    parser.add_argument(
        "--output-root",
        default=str(ROOT / "output" / "service"),
        help="Service output directory",
    )
    args = parser.parse_args()
    root = Path(args.output_root)
    ledger = refresh_ah_ledger(root)
    acc = ledger.get("accuracy") or {}
    print(json.dumps({
        "ok": True,
        "path": str(root / "handicap" / "ledger.json"),
        "total_settled": acc.get("total_settled"),
        "with_ah_pick": acc.get("with_ah_pick"),
        "rate_ah_pct": acc.get("rate_ah_pct"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
