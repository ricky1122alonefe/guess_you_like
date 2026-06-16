#!/usr/bin/env python3
"""Fill 1X2/比分命中 after matches finish. Updates CSV in place."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

RESULT_MAP = {
    "主胜": "home", "主": "home", "home": "home", "h": "home", "3": "home",
    "平": "draw", "平局": "draw", "draw": "draw", "d": "draw", "1": "draw",
    "客胜": "away", "客": "away", "away": "away", "a": "away", "0": "away",
}


def _norm_result(s: str) -> str | None:
    s = (s or "").strip()
    return RESULT_MAP.get(s) or RESULT_MAP.get(s.lower())


def _score_outcome(score: str) -> str | None:
    try:
        h, a = map(int, str(score).strip().split("-"))
    except (TypeError, ValueError):
        return None
    if h > a:
        return "home"
    if h == a:
        return "draw"
    return "away"


def _pick_cn(result: str) -> str:
    return {"home": "主胜", "draw": "平", "away": "客胜"}.get(result, "")


def evaluate_row(row: dict) -> dict:
    actual_result = _norm_result(row.get("实际赛果", ""))
    actual_score = (row.get("实际比分") or "").strip()
    pick_cn = row.get("胜平负", "")
    pick = _norm_result(pick_cn)

    if actual_result and pick:
        row["1X2命中"] = "✓" if actual_result == pick else "✗"
    if actual_score:
        scores_raw = row.get("推荐比分") or ""
        recommended = [s.split("(")[0].strip() for s in scores_raw.split("、") if s.strip()]
        row["比分命中"] = "✓" if actual_score in recommended else "✗"
        if not row.get("实际赛果") and actual_result is None:
            oc = _score_outcome(actual_score)
            if oc:
                row["实际赛果"] = _pick_cn(oc)
                if pick:
                    row["1X2命中"] = "✓" if oc == pick else "✗"
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="根据填写的实际赛果/比分计算命中")
    parser.add_argument("csv", help="predict_sheet 导出的 CSV")
    args = parser.parse_args(argv)

    path = Path(args.csv)
    if not path.exists():
        print(f"文件不存在: {path}", file=sys.stderr)
        return 1

    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print("CSV 为空", file=sys.stderr)
        return 1

    for row in rows:
        evaluate_row(row)

    fields = list(rows[0].keys())
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    done = [r for r in rows if r.get("实际比分") or r.get("实际赛果")]
    hit_1x2 = sum(1 for r in done if r.get("1X2命中") == "✓")
    hit_sc = sum(1 for r in done if r.get("比分命中") == "✓")
    print(f"已更新: {path}")
    print(f"已填 {len(done)}/{len(rows)} 场 | 1X2 命中 {hit_1x2}/{len(done)} | 比分命中 {hit_sc}/{len(done)}")
    for r in rows:
        if r.get("实际赛果") or r.get("实际比分"):
            print(
                f"  {r['比赛']}: 预测{r['胜平负']} 实际{r.get('实际赛果','?')} "
                f"{r.get('实际比分','')} | 1X2{r.get('1X2命中','-')} 比分{r.get('比分命中','-')}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
