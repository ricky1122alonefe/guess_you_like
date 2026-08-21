"""赔率区间 ↔ 胜平负命中率校准（固化「有规律的赔率桶」）。

只使用自有 settle 数据 + opening/closing 盘口；去水后再算 edge；
小样本标灰；不引入 ML。
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Iterable

from analysis.market.devig import devig_1x2
from config import (
    DEVIG_METHOD,
    ODDS_BUCKET_AH_RANGES,
    ODDS_BUCKET_EDGES,
    ODDS_BUCKET_MIN_N,
    ODDS_BUCKET_RISK_NOTES,
)
from db.connection import cursor


@dataclass
class _Bucket:
    key: tuple[float, float | None]
    label: str
    n: int = 0
    home: int = 0
    draw: int = 0
    away: int = 0
    fav_hit: int = 0
    implied_sum: float = 0.0

    def as_dict(self, *, fav: bool = False) -> dict[str, Any]:
        n = self.n
        if n == 0:
            rates = {"rate_home": None, "rate_draw": None, "rate_away": None}
            if fav:
                rates["fav_hit_rate"] = None
            rates.update({"mkt_implied_avg": None, "edge_vs_mkt": None, "reliable": False})
            return {"bucket": self.label, "n": 0, **rates}
        rates = {
            "rate_home": round(self.home / n, 3),
            "rate_draw": round(self.draw / n, 3),
            "rate_away": round(self.away / n, 3),
        }
        if fav:
            rates["fav_hit_rate"] = round(self.fav_hit / n, 3)
        mkt = self.implied_sum / n if self.implied_sum > 0 else None
        edge = None
        if fav and mkt is not None:
            # 热门桶：用 fav_hit_rate - 去水隐含 p(热门方向)
            edge = round(self.fav_hit / n - mkt, 3)
        elif mkt is not None:
            # 主胜桶：用 rate_home - mkt
            edge = round(self.home / n - mkt, 3)
        rates.update({
            "mkt_implied_avg": round(mkt, 3) if mkt is not None else None,
            "edge_vs_mkt": edge,
            "reliable": n >= ODDS_BUCKET_MIN_N,
        })
        return {"bucket": self.label, "n": n, **rates}


def _to_float(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _bucket_for_value(value: float, edges: list[float]) -> tuple[int, int]:
    """Return (low_index, high_index_exclusive) for value in edges list."""
    for i in range(len(edges) - 1):
        low, high = edges[i], edges[i + 1]
        if low <= value < high:
            return i, i + 1
    # last bucket [last_edge, +inf)
    return len(edges) - 1, len(edges)


def _bucket_label(edges: list[float], low_i: int, high_i: int) -> str:
    low = edges[low_i]
    if high_i >= len(edges):
        return f"{low:.2f}+"
    high = edges[high_i]
    return f"{low:.2f}–{high:.2f}"


def _ah_bucket_label(ah_line: float) -> tuple[str, float]:
    """Return (label, bucket_center) for an AH line."""
    for label, low, high in ODDS_BUCKET_AH_RANGES:
        ok_low = low is None or (low <= ah_line < high if high is not None else low <= ah_line)
        ok_high = high is None or ah_line < high
        if ok_low and ok_high:
            center = 0.0
            if low is not None and high is not None:
                center = (low + high) / 2
            elif low is not None:
                center = low + 0.5
            else:
                center = high - 0.5
            return label, center
    return "其它", 0.0


def _resolve_eu_odds(row: dict) -> tuple[float | None, float | None, float | None, str]:
    """赔率优先级：竞彩 SP（有）→ closing_eu → opening_eu → None。"""
    sp = (row.get("payload") or {}).get("jingcai_sp") or {}
    if sp:
        h, d, a = _to_float(sp.get("sp_home")), _to_float(sp.get("sp_draw")), _to_float(sp.get("sp_away"))
        if h and d and a:
            return h, d, a, "sp"
    if row.get("closing_eu_home") is not None:
        return (
            _to_float(row["closing_eu_home"]),
            _to_float(row["closing_eu_draw"]),
            _to_float(row["closing_eu_away"]),
            "closing",
        )
    opening = (row.get("payload") or {}).get("opening_odds") or {}
    h, d, a = _to_float(opening.get("eu_home")), _to_float(opening.get("eu_draw")), _to_float(opening.get("eu_away"))
    if h and d and a:
        return h, d, a, "opening"
    return None, None, None, "missing"


def _resolve_ah_line(row: dict) -> float | None:
    if row.get("closing_ah_line") is not None:
        return _to_float(row["closing_ah_line"])
    closing = (row.get("payload") or {}).get("closing_odds") or {}
    if closing.get("ah_line") is not None:
        return _to_float(closing["ah_line"])
    opening = (row.get("payload") or {}).get("opening_odds") or {}
    if opening.get("ah_line") is not None:
        return _to_float(opening["ah_line"])
    return None


def _resolve_draw_odds(row: dict) -> float | None:
    h, d, a, src = _resolve_eu_odds(row)
    return d


def _resolve_home_odds(row: dict) -> float | None:
    h, d, a, src = _resolve_eu_odds(row)
    return h


def _resolve_favorite_odds(row: dict) -> tuple[float | None, str]:
    """Return (min odds, favorite direction) for favorite bucket."""
    h, d, a, src = _resolve_eu_odds(row)
    if h is None or d is None or a is None:
        return None, ""
    m = min(h, d, a)
    if m == h:
        return m, "home"
    if m == d:
        return m, "draw"
    return m, "away"


def _devig_implied_for_key(probs: dict, key: str) -> float | None:
    if key == "home":
        return probs.get("p_home")
    if key == "draw":
        return probs.get("p_draw")
    if key == "away":
        return probs.get("p_away")
    return None


@lru_cache(maxsize=1)
def build_bucket_stats(days: int = 90) -> dict[str, Any]:
    """Build home / draw / fav / ah bucket stats from settled matches.

    90 天桶统计按天缓存（每场 context 构建都会查，避免反复全表聚合）；
    settle 数据随抓取变化，TLL 1 天内的旧桶可接受。
    """
    from db.repository import list_tournament_results

    rows = list_tournament_results(source="500", limit=5000)
    import datetime

    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)

    home_edges = ODDS_BUCKET_EDGES["home"]
    draw_edges = ODDS_BUCKET_EDGES["draw"]

    home_buckets: dict[tuple[float, float | None], _Bucket] = {}
    draw_buckets: dict[tuple[float, float | None], _Bucket] = {}
    fav_buckets: dict[tuple[float, float | None], _Bucket] = {}
    ah_buckets: dict[str, _Bucket] = {}

    def ensure_home(low_i: int, high_i: int):
        key = (home_edges[low_i], home_edges[high_i] if high_i < len(home_edges) else None)
        if key not in home_buckets:
            home_buckets[key] = _Bucket(key=key, label=_bucket_label(home_edges, low_i, high_i))
        return home_buckets[key]

    def ensure_draw(low_i: int, high_i: int):
        key = (draw_edges[low_i], draw_edges[high_i] if high_i < len(draw_edges) else None)
        if key not in draw_buckets:
            draw_buckets[key] = _Bucket(key=key, label=_bucket_label(draw_edges, low_i, high_i))
        return draw_buckets[key]

    def ensure_fav(low_i: int, high_i: int):
        key = (home_edges[low_i], home_edges[high_i] if high_i < len(home_edges) else None)
        if key not in fav_buckets:
            fav_buckets[key] = _Bucket(key=key, label=_bucket_label(home_edges, low_i, high_i))
        return fav_buckets[key]

    def ensure_ah(label: str, center: float):
        if label not in ah_buckets:
            ah_buckets[label] = _Bucket(key=(center, None), label=label)
        return ah_buckets[label]

    for row in rows:
        settled_at = row.get("settled_at")
        if settled_at and settled_at < cutoff:
            continue
        result = row.get("result_1x2")
        if not result:
            continue

        # home odds bucket
        home_odds = _resolve_home_odds(row)
        if home_odds is not None:
            low_i, high_i = _bucket_for_value(home_odds, home_edges)
            b = ensure_home(low_i, high_i)
            b.n += 1
            if result == "home":
                b.home += 1
            elif result == "draw":
                b.draw += 1
            elif result == "away":
                b.away += 1
            # implied home probability from devig
            h, d, a, src = _resolve_eu_odds(row)
            if h and d and a:
                try:
                    probs = devig_1x2(h, d, a, method=DEVIG_METHOD)
                    b.implied_sum += _devig_implied_for_key(probs, "home") or 0.0
                except Exception:
                    pass

        # draw odds bucket
        draw_odds = _resolve_draw_odds(row)
        if draw_odds is not None:
            low_i, high_i = _bucket_for_value(draw_odds, draw_edges)
            b = ensure_draw(low_i, high_i)
            b.n += 1
            if result == "home":
                b.home += 1
            elif result == "draw":
                b.draw += 1
            elif result == "away":
                b.away += 1
            h, d, a, src = _resolve_eu_odds(row)
            if h and d and a:
                try:
                    probs = devig_1x2(h, d, a, method=DEVIG_METHOD)
                    b.implied_sum += _devig_implied_for_key(probs, "draw") or 0.0
                except Exception:
                    pass

        # favorite bucket
        fav_odds, fav_dir = _resolve_favorite_odds(row)
        if fav_odds is not None:
            low_i, high_i = _bucket_for_value(fav_odds, home_edges)
            b = ensure_fav(low_i, high_i)
            b.n += 1
            if result == "home":
                b.home += 1
            elif result == "draw":
                b.draw += 1
            elif result == "away":
                b.away += 1
            if result == fav_dir:
                b.fav_hit += 1
            h, d, a, src = _resolve_eu_odds(row)
            if h and d and a:
                try:
                    probs = devig_1x2(h, d, a, method=DEVIG_METHOD)
                    p = _devig_implied_for_key(probs, fav_dir) or 0.0
                    b.implied_sum += p
                except Exception:
                    pass

        # ah bucket
        ah_line = _resolve_ah_line(row)
        if ah_line is not None:
            label, center = _ah_bucket_label(ah_line)
            b = ensure_ah(label, center)
            b.n += 1
            if result == "home":
                b.home += 1
            elif result == "draw":
                b.draw += 1
            elif result == "away":
                b.away += 1

    def sort_key(b: _Bucket):
        return b.key[0] if b.key[0] is not None else 0

    return {
        "meta": {"days": days, "min_n": ODDS_BUCKET_MIN_N, "total_settled": len(rows)},
        "home": [b.as_dict() for b in sorted(home_buckets.values(), key=sort_key)],
        "draw": [b.as_dict() for b in sorted(draw_buckets.values(), key=sort_key)],
        "fav": [b.as_dict(fav=True) for b in sorted(fav_buckets.values(), key=sort_key)],
        "ah": [b.as_dict() for b in sorted(ah_buckets.values(), key=lambda x: x.key[0])],
    }


def _lookup_bucket(buckets: list[dict], value: float, edges: list[float]) -> dict | None:
    for b in buckets:
        label = b["bucket"]
        if label.endswith("+"):
            low = float(label[:-1])
            if value >= low:
                return b
        else:
            parts = label.split("–")
            if len(parts) == 2:
                low, high = float(parts[0]), float(parts[1])
                if low <= value < high:
                    return b
    return None


def build_odds_bucket_context(fixture_id: str) -> dict[str, Any]:
    """单场落在哪一桶 + 风险提示。"""
    from db.repository import get_match_result_by_external

    row = get_match_result_by_external("500", fixture_id)
    if not row:
        # 未 settle 的赛事：用 odds_latest 算实时桶
        from db.repository import get_fixture_by_external

        fx = get_fixture_by_external("500", fixture_id)
        if not fx:
            return {"notes": ["无此赛事"], "home_odds": None, "source": "missing"}
        from db.repository import get_latest_hash, get_opening_tick

        tick = get_opening_tick(fx["id"])  # 临时取初盘，可替换为最新
        if not tick:
            return {"notes": ["无盘口"], "home_odds": None, "source": "missing"}
        h = _to_float(tick.get("eu_home"))
        d = _to_float(tick.get("eu_draw"))
        a = _to_float(tick.get("eu_away"))
        row = {
            "closing_eu_home": h,
            "closing_eu_draw": d,
            "closing_eu_away": a,
            "closing_ah_line": _to_float(tick.get("ah_line")),
            "payload": {"jingcai_sp": _extract_jingcai_sp(tick)},
            "result_1x2": None,
        }

    stats = build_bucket_stats(days=90)
    h, d, a, src = _resolve_eu_odds(row)
    ah_line = _resolve_ah_line(row)

    notes: list[str] = []

    home_bucket = None
    fav_bucket = None
    ah_bucket = None

    if h is not None:
        home_bucket = _lookup_bucket(stats["home"], h, ODDS_BUCKET_EDGES["home"])
        for (low, high), note in ODDS_BUCKET_RISK_NOTES.get("home", {}).items():
            if low <= h < high:
                notes.append(note)
        if h >= 4.0:
            notes.append("深冷门，客胜历史主导")

    if h is not None and d is not None and a is not None:
        fav_odds = min(h, d, a)
        fav_bucket = _lookup_bucket(stats["fav"], fav_odds, ODDS_BUCKET_EDGES["home"])
        for (low, high), note in ODDS_BUCKET_RISK_NOTES.get("fav", {}).items():
            if low <= fav_odds < high:
                notes.append(note)

    if ah_line is not None:
        label, _ = _ah_bucket_label(ah_line)
        for b in stats["ah"]:
            if b["bucket"] == label:
                ah_bucket = b
                break
        for (low, high), note in ODDS_BUCKET_RISK_NOTES.get("ah", {}).items():
            if low <= ah_line < high or (low <= -ah_line < high and ah_line < 0):
                notes.append(note)

    return {
        "home_odds": h,
        "source": src,
        "home_bucket": home_bucket,
        "fav_bucket": fav_bucket,
        "ah_bucket": ah_bucket,
        "notes": list(dict.fromkeys(notes)),
    }


def _extract_jingcai_sp(tick: dict | None) -> dict[str, Any]:
    """从 tick.raw_meta.jingcai 提取竞彩 SP。"""
    if not tick:
        return {}
    raw = tick.get("raw_meta") or {}
    jc = raw.get("jingcai") or {}
    sp = {}
    for k in ("sp_home", "sp_draw", "sp_away", "rqsp_home", "rqsp_draw", "rqsp_away"):
        v = jc.get(k)
        if v not in (None, "", "-"):
            sp[k] = v
    return sp
