"""Scan matches where European odds and Asian handicap strongly disagree."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import config as cfg
from market_patterns import (
    MarketPatternAnalysis,
    _line_desc,
    analyze_market_patterns,
    eu_to_ah_line,
)
from time_utils import format_beijing, now_beijing, to_beijing


SPLIT_PATTERN_IDS = frozenset({
    "ah_eu_split_home",
    "open_aligned_live_shallow",
    "shallow_plus_eu_hot",
    "lure_upper_combo",
    "lure_lower_combo",
})

CONSISTENCY_CN = {
    "aligned": "欧亚一致",
    "ah_shallow": "亚盘偏浅",
    "ah_deep": "亚盘偏深",
    "unknown": "数据不足",
}


@dataclass
class EuAhDivergence:
    fixture_id: str
    match: str
    kickoff: str
    divergence_score: int
    severity: str
    severity_cn: str
    consistency: str
    consistency_cn: str
    line_gap: float | None
    eu_to_ah_line: float | None
    ah_line: float | None
    eu_home: float | None
    ah_sketch_home: float | None
    eu_odds_gap: float | None
    open_line_gap: float | None
    live_line_gap: float | None
    gap_shift: float | None
    signals: list[str] = field(default_factory=list)
    pattern_names: list[str] = field(default_factory=list)
    conversion_summary: str = ""
    open_eu: str = "—"
    live_eu: str = "—"
    open_ah: str = "—"
    live_ah: str = "—"
    advice: str = ""


def _fmt_triplet(a, b, c) -> str:
    if a is None and b is None and c is None:
        return "—"
    return f"{a or '—'}/{b or '—'}/{c or '—'}"


def _severity(score: int) -> tuple[str, str]:
    if score >= cfg.EU_AH_DIVERGENCE_HUGE_SCORE:
        return "extreme", "巨大分歧"
    if score >= cfg.EU_AH_DIVERGENCE_MIN_SCORE:
        return "major", "明显分歧"
    if score >= cfg.EU_AH_DIVERGENCE_NOTICE_SCORE:
        return "moderate", "轻度分歧"
    return "low", "基本一致"


def _advice_for(mp: MarketPatternAnalysis, *, score: int) -> str:
    if mp.consistency == "ah_shallow":
        base = "欧赔支持更深盘口，实际亚盘偏浅：热门方向需防诱上、小胜或不穿。"
    elif mp.consistency == "ah_deep":
        base = "实际亚盘比欧赔隐含更深：可能是真看低主队/阻上，不宜单凭欧赔追热门。"
    elif any(p.get("id") in SPLIT_PATTERN_IDS for p in mp.patterns):
        base = "盘赔走势分裂：欧亚不同通道在讲不同故事，优先观望或降档。"
    else:
        base = "欧亚换算存在偏差，建议对照单场历史相似样本与水位变化复核。"
    if score >= cfg.EU_AH_DIVERGENCE_HUGE_SCORE:
        return base + " 分歧幅度大，不建议重仓。"
    return base


def analyze_eu_ah_divergence(cur: dict, *, fixture_id: str = "", match: str = "") -> EuAhDivergence | None:
    """Score EU↔AH disagreement for one odds snapshot."""
    mp = analyze_market_patterns(cur)
    if mp.eu_to_ah_line is None or mp.ah_line_live is None:
        return None

    score = 0
    signals: list[str] = []

    gap = mp.line_gap or 0.0
    gap_abs = abs(gap)
    score += min(55, int(gap_abs / 0.75 * 55))
    if gap_abs > cfg.EU_AH_LINE_GAP_TOL:
        direction = "亚盘偏浅" if gap > 0 else "亚盘偏深"
        signals.append(f"盘口差 {gap:+.2f}（{direction}）")

    eu_h = cur.get("eu_home")
    sketch_h = (mp.ah_to_eu_sketch or {}).get("home") if mp.ah_to_eu_sketch else None
    eu_odds_gap = None
    if eu_h is not None and sketch_h is not None:
        eu_odds_gap = round(float(eu_h) - float(sketch_h), 2)
        if abs(eu_odds_gap) >= cfg.EU_AH_ODDS_GAP:
            score += min(20, int(abs(eu_odds_gap) / 0.35 * 20))
            hot = "欧赔主胜更热" if eu_odds_gap < 0 else "欧赔主胜更冷"
            signals.append(f"亚转欧偏差 {eu_odds_gap:+.2f}（{hot}）")

    open_gap = live_gap = gap_shift = None
    eu_oh, eu_od, eu_oa = cur.get("eu_open_home"), cur.get("eu_open_draw"), cur.get("eu_open_away")
    ol, ll = cur.get("ah_open_line"), cur.get("ah_line")
    if all(x is not None for x in (eu_oh, eu_od, eu_oa, ol, ll)):
        open_eu_line = eu_to_ah_line(eu_oh, eu_od, eu_oa)
        if open_eu_line is not None:
            open_gap = round(float(ol) - open_eu_line, 2)
            live_gap = gap
            gap_shift = round(live_gap - open_gap, 2)
            if abs(gap_shift) >= 0.2:
                score += min(15, int(abs(gap_shift) / 0.4 * 15))
                signals.append(f"临盘分歧扩大 {gap_shift:+.2f}")

    for pat in mp.patterns:
        pid = pat.get("id") or ""
        if pid in SPLIT_PATTERN_IDS:
            score += 12
            name = pat.get("name") or pid
            if name not in signals:
                signals.append(name)

    score = min(100, score)
    severity, severity_cn = _severity(score)
    pattern_names = [p.get("name") or p.get("id") for p in mp.patterns if p.get("name") or p.get("id")]

    snap = cur
    return EuAhDivergence(
        fixture_id=str(fixture_id),
        match=match,
        kickoff="",
        divergence_score=score,
        severity=severity,
        severity_cn=severity_cn,
        consistency=mp.consistency,
        consistency_cn=CONSISTENCY_CN.get(mp.consistency, mp.consistency),
        line_gap=mp.line_gap,
        eu_to_ah_line=mp.eu_to_ah_line,
        ah_line=mp.ah_line_live,
        eu_home=float(eu_h) if eu_h is not None else None,
        ah_sketch_home=float(sketch_h) if sketch_h is not None else None,
        eu_odds_gap=eu_odds_gap,
        open_line_gap=open_gap,
        live_line_gap=live_gap,
        gap_shift=gap_shift,
        signals=signals[:6],
        pattern_names=pattern_names[:4],
        conversion_summary=mp.conversion_summary,
        open_eu=_fmt_triplet(snap.get("eu_open_home"), snap.get("eu_open_draw"), snap.get("eu_open_away")),
        live_eu=_fmt_triplet(snap.get("eu_home"), snap.get("eu_draw"), snap.get("eu_away")),
        open_ah=f"{snap.get('ah_open_line') or '—'} {snap.get('ah_open_home_water') or '—'}/{snap.get('ah_open_away_water') or '—'}",
        live_ah=f"{snap.get('ah_line') or '—'} {snap.get('ah_home_water') or '—'}/{snap.get('ah_away_water') or '—'}",
        advice=_advice_for(mp, score=score),
    )


def _odds_snapshot(m: dict) -> dict[str, Any]:
    snap = m.get("odds_snapshot") or {}
    return {
        "ah_open_line": snap.get("ah_open_line"),
        "ah_open_home_water": snap.get("ah_open_home_water"),
        "ah_open_away_water": snap.get("ah_open_away_water"),
        "ah_line": snap.get("ah_line"),
        "ah_home_water": snap.get("ah_home_water"),
        "ah_away_water": snap.get("ah_away_water"),
        "eu_open_home": snap.get("eu_open_home"),
        "eu_open_draw": snap.get("eu_open_draw"),
        "eu_open_away": snap.get("eu_open_away"),
        "eu_home": snap.get("eu_home"),
        "eu_draw": snap.get("eu_draw"),
        "eu_away": snap.get("eu_away"),
    }


def scan_eu_ah_divergence(
    matches: list[dict],
    kickoff_map: dict[str, datetime],
    *,
    within_hours: float | None = None,
    min_score: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Rank upcoming matches by EU↔AH divergence score."""
    now = now or now_beijing()
    min_score = cfg.EU_AH_DIVERGENCE_MIN_SCORE if min_score is None else min_score
    cutoff = now + timedelta(hours=within_hours) if within_hours is not None else None

    rows: list[dict[str, Any]] = []
    counts = {"extreme": 0, "major": 0, "moderate": 0, "low": 0, "skipped": 0}

    for m in matches:
        fid = str(m.get("fixture_id") or "")
        if not fid:
            continue
        ko = kickoff_map.get(fid)
        if ko:
            ko_bj = to_beijing(ko)
            if ko_bj < now - timedelta(minutes=30):
                continue
            if cutoff and ko_bj > cutoff:
                continue

        cur = _odds_snapshot(m)
        if not any(cur.get(k) is not None for k in ("eu_home", "ah_line", "eu_open_home", "ah_open_line")):
            counts["skipped"] += 1
            continue

        match_name = m.get("match") or (m.get("predict_row") or {}).get("比赛") or fid
        div = analyze_eu_ah_divergence(cur, fixture_id=fid, match=match_name)
        if not div:
            counts["skipped"] += 1
            continue

        counts[div.severity] = counts.get(div.severity, 0) + 1
        if div.divergence_score < min_score:
            continue

        row = {
            "fixture_id": fid,
            "match": match_name,
            "kickoff": format_beijing(ko_bj, "%m-%d %H:%M") if ko else "—",
            "divergence_score": div.divergence_score,
            "severity": div.severity,
            "severity_cn": div.severity_cn,
            "consistency": div.consistency,
            "consistency_cn": div.consistency_cn,
            "line_gap": div.line_gap,
            "eu_to_ah_line": div.eu_to_ah_line,
            "eu_to_ah_line_cn": _line_desc(div.eu_to_ah_line),
            "ah_line": div.ah_line,
            "ah_line_cn": _line_desc(div.ah_line),
            "eu_odds_gap": div.eu_odds_gap,
            "open_line_gap": div.open_line_gap,
            "gap_shift": div.gap_shift,
            "signals": div.signals,
            "pattern_names": div.pattern_names,
            "conversion_summary": div.conversion_summary,
            "open_eu": div.open_eu,
            "live_eu": div.live_eu,
            "open_ah": div.open_ah,
            "live_ah": div.live_ah,
            "advice": div.advice,
        }
        rows.append(row)

    rows.sort(key=lambda r: (-r["divergence_score"], r["kickoff"]))
    huge = sum(1 for r in rows if r["severity"] == "extreme")
    major = sum(1 for r in rows if r["severity"] == "major")

    headline = "暂无可分析的欧亚盘口样本"
    if rows:
        headline = (
            f"共 {len(rows)} 场达到筛选阈值（≥{min_score} 分）："
            f"{huge} 场巨大分歧，{major} 场明显分歧"
        )

    notes = [
        "欧转亚：由临盘欧赔去水概率粗算「合理亚盘」，与实际亚盘对比得 line_gap。",
        f"|line_gap| > {cfg.EU_AH_LINE_GAP_TOL} 视为不一致；≥0.5 通常跨一整档盘口，记为巨大分歧。",
        "亚转欧：由实际亚盘粗推主胜欧赔，与临盘主胜对比，可发现欧热/欧冷。",
        "盘赔分裂套路（升盘欧升、浅盘+欧热等）会额外加分；仅供风控，非投注建议。",
    ]

    return {
        "min_score": min_score,
        "within_hours": within_hours,
        "headline": headline,
        "notes": notes,
        "counts": counts,
        "matches": rows,
    }


def build_divergence_report(
    output_root: str | Path,
    *,
    within_hours: float | None = None,
    min_score: int | None = None,
    within_days: float | None = None,
) -> dict[str, Any]:
    from daily_picks import load_dashboard_matches, load_kickoff_map

    root = Path(output_root)
    days = within_days if within_days is not None else cfg.SERVICE_WITHIN_DAYS
    matches = load_dashboard_matches(root, within_days=days)
    kickoff_map = load_kickoff_map(within_days=days)
    report = scan_eu_ah_divergence(
        matches,
        kickoff_map,
        within_hours=within_hours,
        min_score=min_score,
    )
    report["updated_at"] = format_beijing(now_beijing())
    report["scanned"] = len(matches)
    return report
