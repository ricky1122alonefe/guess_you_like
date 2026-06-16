#!/usr/bin/env python3
"""Rebuild World Cup prediction vs result ledger (accuracy + opening patterns)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from worldcup_analytics import refresh_tournament_ledger


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="刷新世界杯预测账本")
    parser.add_argument("--output-root", default="output/service")
    args = parser.parse_args(argv)
    root = Path(args.output_root)
    ledger = refresh_tournament_ledger(root)
    acc = ledger.get("accuracy") or {}
    print(json.dumps({
        "ok": True,
        "total_settled": acc.get("total_settled"),
        "rate_1x2_pct": acc.get("rate_1x2_pct"),
        "path": str(root / "worldcup" / "ledger.json"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
