#!/usr/bin/env python3
"""Predict from current 球探 xls by matching free football-data history."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import config as app_cfg
from history import load_all_history
from match import MatchConfig, find_similar, find_similar_eu_only, summarize
from parser import MatchOdds, odds_snapshot, pair_match_files, parse_match_pair
from recommend import MIN_SAMPLES_FOR_PICK, build_recommendation, print_batch_summary, print_recommendation

RESULT_CN = {"home": "主胜", "draw": "平", "away": "客胜"}


def _pct(v):
    return "n/a" if v is None else f"{v * 100:.1f}%"


def _print_samples(title: str, stats: dict) -> None:
    samples = stats.get("samples") or []
    total = stats.get("count", 0)
    print(f"{title} (最相似 Top {len(samples)}/{total} 场):")
    if not samples:
        print("  (无)")
        return
    for i, row in enumerate(samples, 1):
        result = RESULT_CN.get(row.get("result_1x2"), row.get("result_1x2"))
        ah = row.get("ah_line")
        ah_txt = f"盘 {ah}" if ah is not None and str(ah) != "nan" else "盘 n/a"
        eu = row.get("eu_home")
        comp = row.get("competition", "")
        dist = row.get("similarity_dist")
        dist_txt = f" | 相似差 {dist}" if dist is not None else ""
        print(
            f"  {i:02d}. {row.get('date')} | {row.get('home')} {row.get('score_h')}-{row.get('score_a')} "
            f"{row.get('away')} | {result} | {ah_txt} | 欧主 {eu}{dist_txt} | {comp}/{row.get('source')}"
        )


def _print_stats_block(title: str, stats: dict) -> None:
    print(f"{title}: {stats['count']} 场")
    if stats["count"] == 0:
        print(f"  (无样本，推荐至少需要 {MIN_SAMPLES_FOR_PICK} 场)")
        return
    if stats["count"] < MIN_SAMPLES_FOR_PICK:
        print(f"  注意: 样本 {stats['count']} 场，低于推荐门槛 {MIN_SAMPLES_FOR_PICK} 场")
    print(
        f"  联赛 {stats.get('league_count', 0)} | "
        f"世界杯 {stats.get('worldcup_count', 0)} | "
        f"预选 {stats.get('qualifier_count', 0)} | "
        f"美洲 {stats.get('americas_count', 0)}"
    )
    print(
        f"  1X2: 主胜 {_pct(stats['home_win_rate'])} | "
        f"平 {_pct(stats['draw_rate'])} | 客胜 {_pct(stats['away_win_rate'])}"
    )
    if stats.get("ah_home_net") is not None:
        print(
            f"  亚盘上盘净胜率: {_pct((stats['ah_home_net'] + 1) / 2)} | "
            f"下盘净胜率: {_pct((stats['ah_away_net'] + 1) / 2)}"
        )
    if stats.get("avg_total_goals") is not None:
        print(f"  场均总进球: {stats['avg_total_goals']:.2f}")


def print_report(current, stats, eu_stats, open_stats=None, open_eu_stats=None):
    print("=" * 60)
    print(f"比赛: {current.match_name}")
    print(f"来源: {current.bookmaker}")
    print("-" * 60)
    print(
        f"当前亚盘: 上水 {current.ah_home_water}({current.ah_home_decimal}) / "
        f"盘口 {current.ah_line} / 下水 {current.ah_away_water}({current.ah_away_decimal})"
    )
    if current.ah_open_line is not None:
        print(
            f"初盘亚盘: 上水 {current.ah_open_home_water} / 盘口 {current.ah_open_line} / 下水 {current.ah_open_away_water}"
        )
    print(
        f"当前欧赔: 主 {current.eu_home} / 平 {current.eu_draw} / 客 {current.eu_away}"
    )
    print("-" * 60)
    print("【初盘相似匹配 — 赛事本身概率（主依据）】")
    if open_stats is not None:
        _print_stats_block("  初盘亚盘", open_stats)
        _print_samples("  初盘亚盘 Top 样本", open_stats)
    if open_eu_stats is not None:
        print("-" * 60)
        _print_stats_block("  初盘欧赔扩展", open_eu_stats)
        _print_samples("  初盘欧赔 Top 样本", open_eu_stats)
    print("-" * 60)
    print("【临盘相似匹配 — 含机构控盘后】")
    _print_stats_block("  临盘亚盘", stats)
    _print_samples("  临盘亚盘 Top 样本", stats)
    print("-" * 60)
    _print_stats_block("  临盘欧赔扩展", eu_stats)
    _print_samples("  临盘欧赔 Top 样本", eu_stats)
    print("=" * 60)


def build_payload(
    ah_xls: str,
    eu_xls: str,
    *,
    sample_limit: int = 5,
    line_tol: float = app_cfg.DEFAULT_LINE_TOL,
    water_tol: float = app_cfg.DEFAULT_WATER_TOL,
    eu_tol: float = app_cfg.DEFAULT_EU_HOME_TOL,
    relaxed: bool = False,
    history=None,
) -> dict:
    if relaxed:
        line_tol = max(line_tol, app_cfg.RELAXED_LINE_TOL)
        water_tol = max(water_tol, app_cfg.RELAXED_WATER_TOL)
        eu_tol = max(eu_tol, app_cfg.RELAXED_EU_TOL)

    current = parse_match_pair(ah_xls, eu_xls)
    current_open = odds_snapshot(current, "open")
    if history is None:
        history = load_all_history()
    cfg = MatchConfig(line_tol=line_tol, water_tol=water_tol, eu_home_tol=eu_tol)
    similar = find_similar(history, current, cfg, phase="close")
    eu_similar = find_similar_eu_only(history, current, cfg, phase="close")
    open_similar = find_similar(history, current_open, cfg, phase="open")
    open_eu_similar = find_similar_eu_only(history, current_open, cfg, phase="open")
    auto_relaxed = False

    if (
        len(similar) == 0 and len(eu_similar) == 0
        and len(open_similar) == 0 and len(open_eu_similar) == 0
        and not relaxed
    ):
        cfg = MatchConfig(
            line_tol=app_cfg.RELAXED_LINE_TOL,
            water_tol=app_cfg.RELAXED_WATER_TOL,
            eu_home_tol=app_cfg.RELAXED_EU_TOL,
        )
        similar = find_similar(history, current, cfg, phase="close")
        eu_similar = find_similar_eu_only(history, current, cfg, phase="close")
        open_similar = find_similar(history, current_open, cfg, phase="open")
        open_eu_similar = find_similar_eu_only(history, current_open, cfg, phase="open")
        if any(len(x) > 0 for x in (similar, eu_similar, open_similar, open_eu_similar)):
            auto_relaxed = True

    stats = summarize(similar, sample_limit=sample_limit, current=current, cfg=cfg, include_ah=True)
    eu_stats = summarize(eu_similar, sample_limit=sample_limit, current=current, cfg=cfg, include_ah=False)
    open_stats = summarize(
        open_similar, sample_limit=sample_limit, current=current_open, cfg=cfg, include_ah=True,
    )
    open_eu_stats = summarize(
        open_eu_similar, sample_limit=sample_limit, current=current_open, cfg=cfg, include_ah=False,
    )

    return {
        "current": current.__dict__,
        "stats": stats,
        "eu_stats": eu_stats,
        "open_stats": open_stats,
        "open_eu_stats": open_eu_stats,
        "history_total": len(history),
        "match_config": cfg.__dict__,
        "auto_relaxed": auto_relaxed,
        "ah_xls": ah_xls,
        "eu_xls": eu_xls,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Match current odds xls against free historical data. "
        "Supports 2 files (one match) or 4+ files (auto-pair by match name).",
    )
    parser.add_argument(
        "xls_files",
        nargs="+",
        help="xls paths: 2 files (one match) or 4+ files (multiple matches, auto-pair 亚盘+欧赔)",
    )
    parser.add_argument("--json", action="store_true", help="output full json payload")
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="show detailed stats and sample list",
    )
    parser.add_argument("--samples", type=int, default=5, help="show top-N most similar samples (default 5)")
    parser.add_argument("--line-tol", type=float, default=0.25)
    parser.add_argument("--water-tol", type=float, default=0.18)
    parser.add_argument("--eu-tol", type=float, default=0.30)
    parser.add_argument(
        "--relaxed",
        action="store_true",
        help="wider match: line 0.5, water 0.25, eu 0.45",
    )
    args = parser.parse_args(argv)

    try:
        pairs = pair_match_files(args.xls_files)
    except (ValueError, FileNotFoundError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    history = load_all_history()
    json_out = []
    recs = []

    for i, (ah_xls, eu_xls) in enumerate(pairs):
        if len(pairs) > 1:
            print(f"\n{'#' * 60}\n  第 {i + 1}/{len(pairs)} 场\n{'#' * 60}\n", file=sys.stderr)
        payload = build_payload(
            ah_xls,
            eu_xls,
            sample_limit=args.samples,
            line_tol=args.line_tol,
            water_tol=args.water_tol,
            eu_tol=args.eu_tol,
            relaxed=args.relaxed,
            history=history,
        )
        if payload.get("auto_relaxed"):
            print("提示: 严格匹配无样本，已自动放宽条件重试", file=sys.stderr)
        if args.json:
            json_out.append(payload)
            continue

        current = parse_match_pair(ah_xls, eu_xls)
        if args.verbose:
            print_report(
                current,
                payload["stats"],
                payload["eu_stats"],
                payload.get("open_stats"),
                payload.get("open_eu_stats"),
            )
            print(f"历史库总量: {payload['history_total']} 场")
        rec = build_recommendation(payload)
        print_recommendation(rec)
        recs.append(rec)

    if args.json:
        out = json_out[0] if len(json_out) == 1 else json_out
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    elif len(recs) > 1:
        print_batch_summary(recs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
