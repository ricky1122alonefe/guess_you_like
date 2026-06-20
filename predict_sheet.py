#!/usr/bin/env python3
"""Batch predict + export sheet for next-day result verification."""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from pathlib import Path

from history import load_all_history
from parser import pair_match_files, parse_match_pair
from predict import build_payload
from recommend import build_recommendation


def discover_xls(directory: Path) -> list[str]:
    files = sorted(directory.glob("*.xls"))
    if not files:
        raise FileNotFoundError(f"目录下没有 xls: {directory}")
    return [str(p) for p in files]


def rec_to_row(rec, *, cur=None, predict_date: str = "") -> dict:
    ah = rec.asian_handicap_cn if rec.asian_handicap_pick != "skip" else "观望"
    scores = "、".join(rec.likely_scores_detail or rec.likely_scores or [])
    row = {
        "预测日期": predict_date,
        "比赛": rec.match,
        "赛果预测": rec.reference_result_1x2_cn or rec.result_1x2_cn,
        "胜平负": rec.result_1x2_cn,
        "推荐比分": scores,
        "亚盘": ah,
        "大小球": rec.over_under_cn,
        "置信度": rec.confidence_cn,
        "置信原因": rec.confidence_reason or "",
        "诱盘解读": rec.funds_interpretation or "",
        "初盘倾向": rec.open_result_1x2_cn or "",
        "初盘概率": rec.open_probability_summary or "",
        "规律参考": rec.pattern_reference_cn or "",
        "控盘": rec.control_level_cn or "",
        "风险": rec.risk_level_cn or "",
        "初盘样本": f"{rec.open_sample_count}/{rec.open_eu_sample_count}",
        "临盘样本": f"{rec.sample_count}/{rec.eu_sample_count}",
        "实际赛果": "",
        "实际比分": "",
        "1X2命中": "",
        "比分命中": "",
        "备注": "",
    }
    if rec.odds_blend_summary:
        row["赔率权重"] = rec.odds_blend_summary
    if rec.alert_tags:
        row["特殊标注"] = "、".join(rec.alert_tags)
    if rec.eu_ah_divergence_score is not None:
        row["欧亚分歧"] = rec.eu_ah_divergence_score
    if rec.qualification_divergence:
        qd = rec.qualification_divergence
        row["出线欧亚提示"] = qd.get("advice") or ""
    if cur is not None:
        row["临盘盘口"] = cur.ah_line
        row["临盘欧赔"] = f"{cur.eu_home}/{cur.eu_draw}/{cur.eu_away}"
        row["初盘盘口"] = cur.ah_open_line
    return row


# 竞彩字段由 jingcai_pick.attach 后追加；各场可能不全，导出 CSV 须合并列
_CSV_COLUMN_ORDER = [
    "预测日期", "比赛", "赛果预测", "胜平负", "推荐比分", "亚盘", "大小球", "置信度", "置信原因",
    "诱盘解读", "初盘倾向", "初盘概率", "规律参考", "控盘", "风险",
    "初盘样本", "临盘样本", "实际赛果", "实际比分", "1X2命中", "比分命中", "备注",
    "临盘盘口", "临盘欧赔", "初盘盘口",
    "赔率权重", "特殊标注", "欧亚分歧", "出线欧亚提示",
    "赛果预测", "竞彩玩法", "竞彩推荐", "竞彩SP",
]


def _csv_fieldnames(rows: list[dict]) -> list[str]:
    all_keys = {k for row in rows for k in row}
    ordered = [c for c in _CSV_COLUMN_ORDER if c in all_keys]
    extras = sorted(k for k in all_keys if k not in _CSV_COLUMN_ORDER)
    return ordered + extras


def save_csv(rows: list[dict], path: Path) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = _csv_fieldnames(rows)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def print_sheet_table(rows: list[dict]) -> None:
    print()
    print("=" * 100)
    print(f"  预测对照表 · 共 {len(rows)} 场 · 赛后填写「实际赛果/实际比分」列")
    print("=" * 100)
    hdr = f"{'比赛':<22} {'胜平负':<8} {'推荐比分':<28} {'亚盘':<16} {'置信':<4}"
    print(hdr)
    print("-" * 100)
    for r in rows:
        print(
            f"{r['比赛']:<22} {r['胜平负']:<8} {r['推荐比分']:<28} "
            f"{r['亚盘']:<16} {r['置信度']:<4}"
        )
    print("=" * 100)
    print()


def save_markdown(rows: list[dict], path: Path, *, predict_date: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# 世界杯预测对照表 · {predict_date}",
        "",
        "赛后填写最后几列，用于复盘命中率。",
        "",
        "| 比赛 | 胜平负 | 推荐比分 | 亚盘 | 大小球 | 置信 | 初盘倾向 | 实际赛果 | 实际比分 | 1X2命中 | 比分命中 |",
        "|------|--------|----------|------|--------|------|----------|----------|----------|---------|----------|",
    ]
    for r in rows:
        lines.append(
            f"| {r['比赛']} | {r['胜平负']} | {r['推荐比分']} | {r['亚盘']} | "
            f"{r['大小球']} | {r['置信度']} | {r['初盘倾向']} | | | | |"
        )
    lines.extend(["", "## 明细", ""])
    for r in rows:
        lines.append(f"### {r['比赛']}")
        lines.append(f"- 胜平负：**{r['胜平负']}** | 比分：{r['推荐比分']}")
        lines.append(f"- 亚盘：{r['亚盘']} | 大小球：{r['大小球']} | 置信：{r['置信度']}")
        lines.append(f"- {r['初盘概率']}")
        lines.append(f"- 规律 {r['规律参考']} | 控盘 {r['控盘']} | 风险 {r['风险']}")
        lines.append(f"- 样本 初盘 {r['初盘样本']} / 临盘 {r['临盘样本']}")
        if r.get("临盘盘口") is not None:
            lines.append(
                f"- 盘口 初 {r.get('初盘盘口')} → 临 {r.get('临盘盘口')} | 欧赔 {r.get('临盘欧赔')}"
            )
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def run_batch(
    pairs: list[tuple[str, str]],
    *,
    history,
    relaxed: bool,
    predict_date: str,
    detail: bool,
) -> list[dict]:
    rows: list[dict] = []
    for i, (ah_xls, eu_xls) in enumerate(pairs, 1):
        payload = build_payload(ah_xls, eu_xls, relaxed=relaxed, history=history)
        rec = build_recommendation(payload)
        cur = parse_match_pair(ah_xls, eu_xls)
        row = rec_to_row(rec, cur=cur, predict_date=predict_date)
        rows.append(row)
        if detail:
            from recommend import print_recommendation
            print(f"\n{'#' * 60}\n  [{i}/{len(pairs)}] {rec.match}\n{'#' * 60}")
            print_recommendation(rec, title_suffix="预测")
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="批量预测并导出对照表（方便赛后填实际赛果复盘）",
    )
    parser.add_argument(
        "xls_files",
        nargs="*",
        help="xls 路径；不传则扫描 --dir 下全部 xls 自动配对",
    )
    parser.add_argument(
        "--dir", "-d",
        default=str(Path.home() / "Downloads"),
        help="自动扫描目录（默认 ~/Downloads）",
    )
    parser.add_argument(
        "--out", "-o",
        help="输出 CSV 路径（默认 output/predictions_YYYYMMDD.csv）",
    )
    parser.add_argument("--relaxed", action="store_true")
    parser.add_argument("--detail", action="store_true", help="每场打印完整推荐")
    parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="预测日期标记（默认今天）",
    )
    args = parser.parse_args(argv)

    try:
        if args.xls_files:
            paths = args.xls_files
        else:
            print(f"扫描目录: {args.dir}", file=sys.stderr)
            paths = discover_xls(Path(args.dir))
        pairs = pair_match_files(paths)
    except (ValueError, FileNotFoundError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    print(f"共 {len(pairs)} 场比赛，正在匹配历史样本...", file=sys.stderr)
    history = load_all_history()
    rows = run_batch(pairs, history=history, relaxed=args.relaxed, predict_date=args.date, detail=args.detail)

    print_sheet_table(rows)

    out_dir = Path(__file__).resolve().parent / "output"
    csv_path = Path(args.out) if args.out else out_dir / f"predictions_{args.date}.csv"
    md_path = csv_path.with_suffix(".md")
    save_csv(rows, csv_path)
    save_markdown(rows, md_path, predict_date=args.date)

    print(f"已保存 CSV: {csv_path}")
    print(f"已保存 Markdown: {md_path}")
    print("赛后把实际赛果/比分填进 CSV，或用 Excel 打开对照。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
