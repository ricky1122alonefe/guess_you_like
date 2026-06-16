"""Multi-bookmaker European odds chart data + outlier / spike markers."""

from __future__ import annotations

import hashlib
from typing import Any

from eu_implied_metrics import detect_implied_sum_anomalies
from time_utils import chart_time_label, format_ts

OUTCOMES = ("home", "draw", "away")
OUTCOME_CN = {"home": "主胜", "draw": "平局", "away": "客胜"}

# vs peer median at same timestamp
PEER_DEVIATION_PCT = 8.0
# vs previous tick for same book, while peers stable
DIVERGENT_MOVE_PCT = 5.0
PEER_STABLE_PCT = 2.0

PALETTE = (
    "#2563eb", "#dc2626", "#16a34a", "#9333ea", "#ea580c", "#0891b2",
    "#be123c", "#4f46e5", "#0d9488", "#ca8a04", "#7c3aed", "#db2777",
    "#0284c7", "#65a30d", "#c026d3", "#e11d48",
)


def _num(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2


def _pct_change(new: float, old: float) -> float:
    if not old:
        return 0.0
    return abs(new - old) / old * 100.0


def parse_eu_book_row(cells: list[str]) -> dict[str, Any] | None:
    """Parse one 500.com 欧赔 table row."""
    name = (cells[0] if cells else "").strip()
    skip_names = frozenset({
        "", "欧赔公司", "公司", "最大值", "最小值", "平均值", "离散值",
    })
    if not name or name in skip_names:
        return None
    home = _num(cells[1]) if len(cells) > 1 else None
    if home is None:
        return None
    return {
        "name": name,
        "home": home,
        "draw": _num(cells[2]) if len(cells) > 2 else None,
        "away": _num(cells[3]) if len(cells) > 3 else None,
        "open_home": _num(cells[8]) if len(cells) > 10 else None,
        "open_draw": _num(cells[9]) if len(cells) > 10 else None,
        "open_away": _num(cells[10]) if len(cells) > 10 else None,
    }


def parse_eu_bookmakers(eu_rows: list[str]) -> list[dict[str, Any]]:
    books: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in eu_rows:
        cells = row.split("|")
        book = parse_eu_book_row(cells)
        if not book or book["name"] in seen:
            continue
        seen.add(book["name"])
        books.append(book)
    return books


def eu_books_fingerprint(books: list[dict[str, Any]]) -> str:
    """Compact fingerprint so poll detects any bookmaker move."""
    parts: list[str] = []
    for b in sorted(books, key=lambda x: str(x.get("name", ""))):
        name = b.get("name", "")
        bits = []
        for k in ("home", "draw", "away"):
            v = _num(b.get(k))
            if v is not None:
                bits.append(f"{k[0]}{v:.3f}")
        if bits:
            parts.append(f"{name}:{'/'.join(bits)}")
    raw = "|".join(parts[:24])
    return hashlib.sha256(raw.encode()).hexdigest()[:16] if raw else ""


def _books_at_point(odds: dict) -> list[dict[str, Any]]:
    books = odds.get("eu_books") or []
    if books:
        return books
    # fallback: single primary line as one pseudo-bookmaker
    if odds.get("eu_home") is not None:
        return [{
            "name": odds.get("bookmaker") or "主盘",
            "home": odds.get("eu_home"),
            "draw": odds.get("eu_draw"),
            "away": odds.get("eu_away"),
        }]
    return []


def detect_eu_anomalies(
    timeline: list[dict],
    *,
    peer_deviation_pct: float = PEER_DEVIATION_PCT,
    divergent_move_pct: float = DIVERGENT_MOVE_PCT,
    peer_stable_pct: float = PEER_STABLE_PCT,
) -> list[dict[str, Any]]:
    """Mark book/outcome points that deviate from peers or move sharply alone."""
    anomalies: list[dict[str, Any]] = []
    if len(timeline) < 1:
        return anomalies

    prev_by_book: dict[str, dict[str, float]] = {}

    for idx, point in enumerate(timeline):
        odds = point.get("odds") or {}
        books = _books_at_point(odds)
        if not books:
            continue

        for outcome in OUTCOMES:
            peer_vals: list[float] = []
            book_vals: dict[str, float] = {}
            for b in books:
                v = _num(b.get(outcome))
                if v is not None:
                    peer_vals.append(v)
                    book_vals[b["name"]] = v
            med = _median(peer_vals)
            if med is None:
                continue

            peer_prev_vals: list[float] = []
            if idx > 0:
                prev_odds = timeline[idx - 1].get("odds") or {}
                for b in _books_at_point(prev_odds):
                    pv = _num(b.get(outcome))
                    if pv is not None:
                        peer_prev_vals.append(pv)
            peer_prev_med = _median(peer_prev_vals)
            peer_med_move = (
                _pct_change(med, peer_prev_med)
                if peer_prev_med is not None and idx > 0 else 0.0
            )

            for name, val in book_vals.items():
                reasons: list[str] = []
                direction = "up" if val > med else "down"

                dev = _pct_change(val, med)
                if dev >= peer_deviation_pct:
                    reasons.append(f"偏离中位数{dev:.1f}%")

                prev = (prev_by_book.get(name) or {}).get(outcome)
                if prev is not None:
                    move = _pct_change(val, prev)
                    if move >= divergent_move_pct and peer_med_move <= peer_stable_pct:
                        arrow = "急升" if val > prev else "急跌"
                        reasons.append(f"独{arrow}{move:.1f}%（同业≈{peer_med_move:.1f}%）")

                if reasons:
                    anomalies.append({
                        "idx": idx,
                        "ts": format_ts(point.get("ts")),
                        "book": name,
                        "outcome": outcome,
                        "outcome_cn": OUTCOME_CN[outcome],
                        "value": round(val, 3),
                        "median": round(med, 3),
                        "direction": direction,
                        "reason": "；".join(reasons),
                    })

        for b in books:
            name = b["name"]
            slot = prev_by_book.setdefault(name, {})
            for outcome in OUTCOMES:
                v = _num(b.get(outcome))
                if v is not None:
                    slot[outcome] = v

        ts_label = format_ts(point.get("ts"))
        anomalies.extend(
            detect_implied_sum_anomalies(books, idx=idx, ts=ts_label)
        )

    return anomalies


def build_eu_multi_chart_data(timeline: list[dict]) -> dict[str, Any]:
    """Build Chart.js payloads for multi-book EU line charts + anomaly markers."""
    labels: list[str] = []
    book_names: set[str] = set()

    for p in timeline:
        labels.append(chart_time_label(p.get("ts") or p.get("hour")))
        for b in _books_at_point(p.get("odds") or {}):
            book_names.add(b["name"])

    books = sorted(book_names)
    n = len(timeline)
    series: dict[str, dict[str, list[float | None]]] = {
        o: {b: [None] * n for b in books} for o in OUTCOMES
    }

    for i, p in enumerate(timeline):
        for b in _books_at_point(p.get("odds") or {}):
            name = b["name"]
            if name not in series["home"]:
                continue
            for o in OUTCOMES:
                series[o][name][i] = _num(b.get(o))

    colors = {b: PALETTE[i % len(PALETTE)] for i, b in enumerate(books)}
    anomalies = detect_eu_anomalies(timeline)

    anomaly_points: dict[str, list[dict[str, Any]]] = {o: [] for o in OUTCOMES}
    sum_points: list[dict[str, Any]] = []
    for a in anomalies:
        if a.get("kind") == "implied_sum":
            sum_points.append(a)
        else:
            anomaly_points[a["outcome"]].append(a)

    latest_implied = None
    if timeline:
        from eu_implied_metrics import metrics_from_odds_dict
        latest_implied = metrics_from_odds_dict(timeline[-1].get("odds") or {})
        if latest_implied:
            latest_implied = latest_implied.to_dict()

    return {
        "labels": labels,
        "books": books,
        "book_colors": colors,
        "series": series,
        "anomalies": anomalies,
        "anomaly_points": anomaly_points,
        "implied_sum_points": sum_points,
        "latest_implied": latest_implied,
        "has_multi_books": len(books) > 1,
    }
