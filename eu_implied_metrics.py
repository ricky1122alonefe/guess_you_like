"""European 1X2 implied probability metrics (1/odds) and overround sanity checks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import config as app_cfg

OUTCOME_CN = {"home": "主胜", "draw": "平局", "away": "客胜"}
OUTCOMES = ("home", "draw", "away")


@dataclass
class EuImpliedMetrics:
    """Raw 1/odds percentages sum to ~102–110% (book overround); fair sum = 100%."""

    raw_home_pct: float
    raw_draw_pct: float
    raw_away_pct: float
    raw_sum_pct: float
    fair_home_pct: float
    fair_draw_pct: float
    fair_away_pct: float
    overround_pct: float
    is_anomaly: bool = False
    anomaly_level: str = "ok"  # ok | warn | severe
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def fair_cn(self) -> dict[str, str]:
        return {
            "主胜": f"{self.fair_home_pct:.1f}%",
            "平": f"{self.fair_draw_pct:.1f}%",
            "客胜": f"{self.fair_away_pct:.1f}%",
        }

    def raw_cn(self) -> dict[str, str]:
        return {
            "主胜": f"{self.raw_home_pct:.1f}%",
            "平": f"{self.raw_draw_pct:.1f}%",
            "客胜": f"{self.raw_away_pct:.1f}%",
        }


def _num(v) -> float | None:
    try:
        if v is None:
            return None
        x = float(v)
        return x if x > 1.0 else None
    except (TypeError, ValueError):
        return None


def compute_eu_implied(h, d, a) -> EuImpliedMetrics | None:
    """
    Compute implied win % from EU odds.

    - raw_* = 100/odds (未归一，三者之和通常 >100%，为机构抽水)
    - fair_* = 去水后概率，三者之和 = 100%
    """
    oh, od, oa = _num(h), _num(d), _num(a)
    if oh is None or od is None or oa is None:
        return None

    ih, id_, ia = 100.0 / oh, 100.0 / od, 100.0 / oa
    raw_sum = ih + id_ + ia
    if raw_sum <= 0:
        return None

    fair_h = ih / raw_sum * 100.0
    fair_d = id_ / raw_sum * 100.0
    fair_a = ia / raw_sum * 100.0
    overround = raw_sum - 100.0

    level, is_anom, reason = _classify_sum(raw_sum)
    return EuImpliedMetrics(
        raw_home_pct=round(ih, 2),
        raw_draw_pct=round(id_, 2),
        raw_away_pct=round(ia, 2),
        raw_sum_pct=round(raw_sum, 2),
        fair_home_pct=round(fair_h, 2),
        fair_draw_pct=round(fair_d, 2),
        fair_away_pct=round(fair_a, 2),
        overround_pct=round(overround, 2),
        is_anomaly=is_anom,
        anomaly_level=level,
        reason=reason,
    )


def _classify_sum(raw_sum: float) -> tuple[str, bool, str]:
    lo = app_cfg.EU_IMPLIED_SUM_OK_MIN
    hi = app_cfg.EU_IMPLIED_SUM_OK_MAX
    warn_hi = app_cfg.EU_IMPLIED_SUM_WARN_MAX

    if raw_sum < lo:
        return "severe", True, f"隐含概率和 {raw_sum:.1f}% 低于 {lo}%（赔率异常或数据错误）"
    if raw_sum > warn_hi:
        return "severe", True, f"隐含概率和 {raw_sum:.1f}% 高于 {warn_hi}%（抽水异常偏高）"
    if raw_sum > hi:
        return "warn", True, f"隐含概率和 {raw_sum:.1f}% 略高于常见区间 {lo}–{hi}%"
    return "ok", False, f"隐含概率和 {raw_sum:.1f}% 在正常范围（去水后=100%）"


def detect_implied_sum_anomalies(
    books: list[dict],
    *,
    idx: int,
    ts: str,
) -> list[dict[str, Any]]:
    """Flag books whose raw implied sum deviates from normal range or peer median."""
    if not books:
        return []

    metrics_by_book: dict[str, EuImpliedMetrics] = {}
    sums: list[float] = []
    for b in books:
        m = compute_eu_implied(b.get("home"), b.get("draw"), b.get("away"))
        if not m:
            continue
        name = str(b.get("name") or "—")
        metrics_by_book[name] = m
        sums.append(m.raw_sum_pct)

    if not metrics_by_book:
        return []

    peer_med = _median(sums)
    dev_pp = app_cfg.EU_IMPLIED_PEER_SUM_DEV_PP
    out: list[dict[str, Any]] = []

    for name, m in metrics_by_book.items():
        reasons: list[str] = []
        if m.is_anomaly and m.reason:
            reasons.append(m.reason)
        if peer_med is not None and len(sums) > 1:
            gap = abs(m.raw_sum_pct - peer_med)
            if gap >= dev_pp:
                reasons.append(
                    f"隐含和偏离同业中位 {peer_med:.1f}% 达 {gap:.1f}pp"
                )
        if not reasons:
            continue
        out.append({
            "idx": idx,
            "ts": ts,
            "book": name,
            "outcome": "sum",
            "outcome_cn": "隐含和",
            "value": m.raw_sum_pct,
            "median": round(peer_med, 2) if peer_med is not None else None,
            "direction": "high" if m.raw_sum_pct > (peer_med or 100) else "low",
            "reason": "；".join(reasons),
            "kind": "implied_sum",
            "raw_sum_pct": m.raw_sum_pct,
            "fair_home_pct": m.fair_home_pct,
            "fair_draw_pct": m.fair_draw_pct,
            "fair_away_pct": m.fair_away_pct,
            "overround_pct": m.overround_pct,
            "anomaly_level": m.anomaly_level,
        })
    return out


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2


def metrics_from_odds_dict(odds: dict) -> EuImpliedMetrics | None:
    return compute_eu_implied(
        odds.get("eu_home"), odds.get("eu_draw"), odds.get("eu_away"),
    )
