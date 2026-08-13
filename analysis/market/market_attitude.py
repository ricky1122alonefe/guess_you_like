"""market_attitude: 赔率变动 = 市场态度。

产品语义（两类解读可并存，勿二选一硬判）：
A. 庄家调盘：亚盘升/降盘（line 变）、欧赔显著漂移、盘口结构重开。
B. 资金平衡：同盘降水/升水、竞彩 SP 单边压低、必发成交量/占比倾斜。

态度标签（中文，给 UI/reasons）：
- 资金追热 / 资金追冷
- 升盘加压 / 降盘减压
- 水位对倒（同线主客水对调）
- 欧粘亚动（欧赔不动但亚/SP 动——常见，不算爬虫坏）
- 信号不足（开收几乎无有效差）

本模块只读/汇总已有 odds_ticks + match_results；禁止重训模型；禁止把页内
book_open（庄家初盘）当观测初盘，开盘只用本站 first valid tick。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR = ROOT / "data" / "cache"
CACHE_FILE = CACHE_DIR / "market_attitude_calib.json"

DEFAULT_MIN_N = 20
DEFAULT_CALIB_DAYS = 90

_LABEL_ORDER = [
    "升盘加压",
    "降盘减压",
    "资金追热",
    "资金追冷",
    "水位对倒",
    "欧粘亚动",
    "信号不足",
]


def _safe_float(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _side_cn(side: str) -> str:
    return {"home": "主", "draw": "平", "away": "客"}.get(side, side)


def _delta(opening: dict, closing: dict, key: str) -> float | None:
    o = _safe_float(opening.get(key))
    c = _safe_float(closing.get(key))
    if o is None or c is None:
        return None
    return round(c - o, 3)


def _delta_line(opening: dict, closing: dict, key: str) -> float | None:
    o = opening.get(key)
    c = closing.get(key)
    if o is None or c is None:
        return None
    try:
        return round(float(c) - float(o), 2)
    except (TypeError, ValueError):
        return None


def _delta_sp(opening: dict, closing: dict) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for side in ("home", "draw", "away"):
        o = (opening.get("jingcai_sp") or {}).get(f"sp_{side}")
        c = (closing.get("jingcai_sp") or {}).get(f"sp_{side}")
        out[side] = _safe_float(c) - _safe_float(o) if _safe_float(c) and _safe_float(o) else None
        if out[side] is not None:
            out[side] = round(out[side], 3)
    return out


def _delta_betfair(opening: dict, closing: dict) -> dict[str, float | None]:
    o_bf = opening.get("betfair") or {}
    c_bf = closing.get("betfair") or {}
    out: dict[str, float | None] = {}
    o_vol = o_bf.get("volume_total") or 0
    c_vol = c_bf.get("volume_total") or 0
    out["volume"] = (c_vol - o_vol) if (o_vol or c_vol) else None
    if out["volume"] is not None:
        out["volume"] = round(out["volume"], 1)

    o_pct = o_bf.get("volume_pct") or {}
    c_pct = c_bf.get("volume_pct") or {}
    oh = _safe_float(o_pct.get("home")) or _safe_float(o_pct.get("home_pct"))
    ch = _safe_float(c_pct.get("home")) or _safe_float(c_pct.get("home_pct"))
    if oh is not None and ch is not None:
        out["home_pct"] = round(ch - oh, 3)
    else:
        out["home_pct"] = None
    return out


def _count_valid_ticks(external_id: str) -> int:
    try:
        from db.connection import cursor

        with cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS n
                FROM odds_ticks t
                JOIN fixtures f ON f.id = t.fixture_id
                WHERE f.external_id = %s
                  AND (t.eu_home IS NOT NULL OR t.ah_line IS NOT NULL)
                """,
                (external_id,),
            )
            return cur.fetchone()["n"] or 0
    except Exception as exc:
        log.debug("count_valid_ticks failed %s: %s", external_id, exc)
        return 0


def _hours_span(opening: dict, closing: dict) -> float | None:
    o_ts = opening.get("captured_at")
    c_ts = closing.get("captured_at")
    if not o_ts or not c_ts:
        return None
    try:
        if isinstance(o_ts, str):
            o_ts = datetime.fromisoformat(o_ts.replace("Z", "+00:00"))
        if isinstance(c_ts, str):
            c_ts = datetime.fromisoformat(c_ts.replace("Z", "+00:00"))
        span = (c_ts - o_ts).total_seconds() / 3600.0
        return round(span, 1)
    except Exception:
        return None


def build_move_features(external_id: str) -> dict[str, Any]:
    """取单场 lifecycle，计算开盘→临盘漂移特征。

    返回字段：
      eu_home/draw/away_delta, ah_line_delta, ah_home/away_water_delta,
      sp_home/draw/away_delta, bf_volume_delta, bf_home_pct_delta,
      ticks_n, hours_span, provisional, settled, result_1x2, scores.
    """
    from analysis.market.odds_lifecycle import get_match_odds_lifecycle

    lc = get_match_odds_lifecycle(str(external_id))
    if lc.get("error"):
        return {"missing": ["lifecycle_error"], "external_id": str(external_id)}

    opening = lc.get("opening") or {}
    closing = lc.get("closing") or {}
    if not opening or not closing:
        return {"missing": ["no_open_close"], "external_id": str(external_id)}

    sp_d = _delta_sp(opening, closing)
    bf_d = _delta_betfair(opening, closing)

    eu_deltas = {
        "home": _delta(opening, closing, "eu_home"),
        "draw": _delta(opening, closing, "eu_draw"),
        "away": _delta(opening, closing, "eu_away"),
    }
    eu_sticky = all(
        abs(v) < 0.02 for v in eu_deltas.values() if v is not None
    ) and any(v is not None for v in eu_deltas.values())

    ah_line_delta = _delta_line(opening, closing, "ah_line")
    ah_home_wd = _delta(opening, closing, "ah_home_water")
    ah_away_wd = _delta(opening, closing, "ah_away_water")

    has_valid_signal = bool(
        (ah_line_delta is not None and abs(ah_line_delta) >= 0.25)
        or (ah_home_wd is not None and abs(ah_home_wd) >= 0.05)
        or (ah_away_wd is not None and abs(ah_away_wd) >= 0.05)
        or any(abs(sp_d.get(k) or 0) >= 0.03 for k in ("home", "draw", "away"))
        or (not eu_sticky and any(v is not None for v in eu_deltas.values()))
        or (bf_d.get("volume") is not None and bf_d.get("volume", 0) > 0)
    )

    features = {
        "external_id": str(external_id),
        "opening": opening,
        "closing": closing,
        "eu_home_delta": eu_deltas["home"],
        "eu_draw_delta": eu_deltas["draw"],
        "eu_away_delta": eu_deltas["away"],
        "ah_line_delta": ah_line_delta,
        "ah_home_water_delta": ah_home_wd,
        "ah_away_water_delta": ah_away_wd,
        "sp_home_delta": sp_d["home"],
        "sp_draw_delta": sp_d["draw"],
        "sp_away_delta": sp_d["away"],
        "bf_volume_delta": bf_d.get("volume"),
        "bf_home_pct_delta": bf_d.get("home_pct"),
        "ticks_n": _count_valid_ticks(external_id),
        "hours_span": _hours_span(opening, closing),
        "provisional": bool(lc.get("provisional", True)),
        "settled": bool(lc.get("settled", False)),
        "result_1x2": lc.get("result_1x2"),
        "scores": lc.get("scores"),
        "kickoff_at": lc.get("kickoff_at"),
        "eu_sticky": eu_sticky,
        "has_valid_signal": has_valid_signal,
    }
    return features


def classify_attitude(features: dict[str, Any]) -> dict[str, Any]:
    """基于 drift 特征输出态度标签、偏向、强度与中文叙事。

    规则（写死可测）：
    - 亚盘主让加深 + 主水下降 → 升盘加压 + 资金追热(主)
    - 同线主水升客水降 → 水位对倒，偏客
    - 仅 SP 主降、欧/亚不动 → 资金追热(主) weak
    - 仅 bf 量涨无方向 → 信号不足或弱
    - 全无有效差 → 信号不足
    - 欧赔粘滞但亚/SP 有动 → 追加「欧粘亚动」
    """
    ah_line_delta = features.get("ah_line_delta")
    ah_home_wd = features.get("ah_home_water_delta")
    ah_away_wd = features.get("ah_away_water_delta")
    sp_home_d = features.get("sp_home_delta")
    sp_draw_d = features.get("sp_draw_delta")
    sp_away_d = features.get("sp_away_delta")
    bf_vol_d = features.get("bf_volume_delta")
    bf_home_pct_d = features.get("bf_home_pct_delta")
    eu_home_d = features.get("eu_home_delta")
    eu_draw_d = features.get("eu_draw_delta")
    eu_away_d = features.get("eu_away_delta")
    eu_sticky = features.get("eu_sticky", True)
    has_signal = features.get("has_valid_signal", False)

    labels: list[str] = []
    side = "none"
    strength = "weak"
    parts: list[str] = []

    # 1. 亚盘线变化（主队视角：更负 = 主队让更深）
    if ah_line_delta is not None and abs(ah_line_delta) >= 0.25:
        if ah_line_delta < 0:
            labels.append("升盘加压")
            side = "home"
            strength = "mid"
            parts.append(f"亚盘主让升{abs(ah_line_delta):.1f}级")
        else:
            labels.append("降盘减压")
            side = "away"
            strength = "mid"
            parts.append(f"亚盘主让降{abs(ah_line_delta):.1f}级")

    # 2. 亚盘水位变化 / 对倒
    home_water_hot = ah_home_wd is not None and ah_home_wd <= -0.05
    away_water_hot = ah_away_wd is not None and ah_away_wd <= -0.05
    home_water_cold = ah_home_wd is not None and ah_home_wd >= 0.05
    away_water_cold = ah_away_wd is not None and ah_away_wd >= 0.05
    same_line = ah_line_delta is None or abs(ah_line_delta) < 0.05

    if same_line and home_water_hot and away_water_cold:
        labels.append("水位对倒")
        if side == "none":
            side = "home"
            strength = "mid"
            parts.append("同线主水降客水升")
        else:
            parts.append("同线主水降客水升")
    elif same_line and away_water_hot and home_water_cold:
        labels.append("水位对倒")
        if side == "none":
            side = "away"
            strength = "mid"
            parts.append("同线主水升客水降")
        else:
            parts.append("同线主水升客水降")
    elif home_water_hot:
        if side == "none":
            side = "home"
            labels.append("资金追热")
            parts.append("主水明显下降")
        elif side == "home":
            labels.append("资金追热")
            parts.append("主水下降配合升盘")
            strength = "strong" if strength == "mid" else "mid"
        else:
            parts.append("主水下降，与降盘方向对冲")
    elif away_water_hot:
        if side == "none":
            side = "away"
            labels.append("资金追热")
            parts.append("客水明显下降")
        elif side == "away":
            labels.append("资金追热")
            parts.append("客水下降配合降盘")
            strength = "strong" if strength == "mid" else "mid"
        else:
            parts.append("客水下降，与升盘方向对冲")
    elif home_water_cold and side == "home":
        parts.append("主水上升，升盘承压")
        strength = "weak"
    elif away_water_cold and side == "away":
        parts.append("客水上升，降盘承压")
        strength = "weak"

    # 3. 竞彩 SP（压低 = 资金涌入）
    sp_signals: list[tuple[str, float]] = []
    if sp_home_d is not None and sp_home_d <= -0.03:
        sp_signals.append(("home", sp_home_d))
    if sp_draw_d is not None and sp_draw_d <= -0.03:
        sp_signals.append(("draw", sp_draw_d))
    if sp_away_d is not None and sp_away_d <= -0.03:
        sp_signals.append(("away", sp_away_d))

    if sp_signals:
        sp_side, sp_val = sp_signals[0]
        if side == "none":
            side = sp_side
            labels.append("资金追热")
            parts.append(f"竞彩{_side_cn(sp_side)}SP降{abs(sp_val):.2f}")
        elif side == sp_side:
            parts.append(f"竞彩{_side_cn(sp_side)}SP同向降{abs(sp_val):.2f}")
            if strength == "mid":
                strength = "strong"
        else:
            parts.append(f"竞彩{_side_cn(sp_side)}SP反向降{abs(sp_val):.2f}")

    # 4. 必发量/占比
    if bf_vol_d is not None and bf_vol_d > 0:
        if bf_home_pct_d is not None and abs(bf_home_pct_d) >= 0.05:
            bf_side = "home" if bf_home_pct_d > 0 else "away"
            if side == "none":
                side = bf_side
                labels.append("资金追热")
                parts.append(f"必发主胜占比变化{bf_home_pct_d:+.0%}")
            elif side == bf_side:
                parts.append(f"必发主胜占比同向变化{bf_home_pct_d:+.0%}")
                if strength == "mid":
                    strength = "strong"
            else:
                parts.append(f"必发主胜占比反向变化{bf_home_pct_d:+.0%}")
        else:
            parts.append("必发量涨但方向不明")

    # 5. 欧赔显著漂移（>=0.05）
    eu_signals: list[tuple[str, float]] = []
    if eu_home_d is not None and eu_home_d <= -0.05:
        eu_signals.append(("home", eu_home_d))
    if eu_draw_d is not None and eu_draw_d <= -0.05:
        eu_signals.append(("draw", eu_draw_d))
    if eu_away_d is not None and eu_away_d <= -0.05:
        eu_signals.append(("away", eu_away_d))

    if eu_signals:
        eu_side, eu_val = eu_signals[0]
        if side == "none":
            side = eu_side
            parts.append(f"欧赔{_side_cn(eu_side)}降{abs(eu_val):.2f}")
        elif side == eu_side:
            parts.append(f"欧赔{_side_cn(eu_side)}同向降{abs(eu_val):.2f}")
            if strength == "mid":
                strength = "strong"
        else:
            parts.append(f"欧赔{_side_cn(eu_side)}反向降{abs(eu_val):.2f}")

    # 6. 欧粘亚动
    if eu_sticky and labels and labels != ["信号不足"]:
        labels.append("欧粘亚动")
        if not any("欧赔粘滞" in p for p in parts):
            parts.append("欧赔粘滞，信号来自亚盘/SP")

    # 7. 信号不足兜底
    if not has_signal or not labels or labels == ["欧粘亚动"]:
        labels = ["信号不足"]
        side = "none"
        strength = "weak"
        narrative = "开盘至临盘有效信号不足，市场态度中性"
    else:
        narrative = "；".join(parts) if parts else "市场存在有效信号但方向不明确"

    return {
        "labels": labels,
        "supported_side": side,
        "strength": strength,
        "narrative": narrative,
        "evidence": {
            "eu_home_delta": eu_home_d,
            "eu_draw_delta": eu_draw_d,
            "eu_away_delta": eu_away_d,
            "ah_line_delta": ah_line_delta,
            "ah_home_water_delta": ah_home_wd,
            "ah_away_water_delta": ah_away_wd,
            "sp_home_delta": sp_home_d,
            "sp_draw_delta": sp_draw_d,
            "sp_away_delta": sp_away_d,
            "bf_volume_delta": bf_vol_d,
            "bf_home_pct_delta": bf_home_pct_d,
            "ticks_n": features.get("ticks_n"),
            "hours_span": features.get("hours_span"),
            "eu_sticky": eu_sticky,
        },
    }


def _primary_bucket_label(labels: list[str]) -> str:
    """把标签序列归到一个主要统计桶。"""
    for cand in _LABEL_ORDER:
        if cand in labels:
            return cand
    return "信号不足"


def summarize_attitude_vs_results(min_n: int = DEFAULT_MIN_N, days: int = DEFAULT_CALIB_DAYS) -> dict[str, Any]:
    """扫描已 settle 场，按态度桶统计历史命中率。

    返回并缓存到 data/cache/market_attitude_calib.json：
      buckets: [{label, supported_side, n, hit, draw, hit_rate, draw_rate, reliable}]
      totals, eu_sticky_rate, generated_at.
    """
    from db.connection import cursor

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    with cursor() as cur:
        cur.execute(
            """
            SELECT f.external_id, mr.result_1x2
            FROM match_results mr
            JOIN fixtures f ON f.id = mr.fixture_id
            WHERE mr.settled_at > %s
              AND f.source = '500'
              AND mr.result_1x2 IS NOT NULL
            ORDER BY mr.settled_at DESC
            """,
            (cutoff,),
        )
        rows = cur.fetchall()

    buckets: dict[str, dict[str, Any]] = {}
    processed = 0
    eu_sticky_n = 0
    no_open_close = 0

    for row in rows:
        external_id = str(row["external_id"])
        result = row["result_1x2"]
        features = build_move_features(external_id)
        if "missing" in features:
            no_open_close += 1
            continue
        if features.get("eu_sticky"):
            eu_sticky_n += 1
        attitude = classify_attitude(features)
        label = _primary_bucket_label(attitude["labels"])
        side = attitude["supported_side"]
        key = f"{label}|{side}"
        b = buckets.setdefault(
            key,
            {
                "label": label,
                "supported_side": side,
                "n": 0,
                "hit": 0,
                "draw": 0,
                "hit_rate": 0.0,
                "draw_rate": 0.0,
                "reliable": False,
            },
        )
        b["n"] += 1
        if side != "none" and result == side:
            b["hit"] += 1
        if result == "draw":
            b["draw"] += 1
        processed += 1

    for b in buckets.values():
        n = b["n"]
        b["hit_rate"] = round(b["hit"] / n, 3) if n else 0.0
        b["draw_rate"] = round(b["draw"] / n, 3) if n else 0.0
        b["reliable"] = n >= min_n

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "days": days,
        "min_n": min_n,
        "total_settled": len(rows),
        "processed": processed,
        "no_open_close": no_open_close,
        "eu_sticky_rate": round(eu_sticky_n / processed, 3) if processed else 0.0,
        "buckets": sorted(buckets.values(), key=lambda x: (-x["n"], x["label"], x["supported_side"])),
    }

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def load_calibration() -> dict[str, Any]:
    """读取缓存的 attitude 校准统计。"""
    if not CACHE_FILE.exists():
        return {"buckets": [], "generated_at": None}
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("load calib failed: %s", exc)
        return {"buckets": [], "generated_at": None}


def apply_calibration(attitude: dict[str, Any], min_n: int = DEFAULT_MIN_N) -> dict[str, Any]:
    """按 attitude 的 label+side 查历史命中；样本不足时不调分，只写说明。"""
    label = _primary_bucket_label(attitude.get("labels", []))
    side = attitude.get("supported_side", "none")
    calib = load_calibration()
    buckets = calib.get("buckets") or []
    for b in buckets:
        if b.get("label") == label and b.get("supported_side") == side:
            return {
                "label": label,
                "supported_side": side,
                "n": b["n"],
                "hit_rate": b["hit_rate"],
                "draw_rate": b["draw_rate"],
                "reliable": b["n"] >= min_n,
                "note": (
                    f"历史同类命中 {b['hit_rate']:.0%}（n={b['n']}）"
                    if b["n"] >= min_n
                    else f"历史样本不足（n={b['n']}）"
                ),
            }
    return {
        "label": label,
        "supported_side": side,
        "n": 0,
        "hit_rate": None,
        "draw_rate": None,
        "reliable": False,
        "note": "尚未生成市场态度校准缓存",
    }


def _print_summary(summary: dict[str, Any]) -> None:
    print(f"市场态度校准（近 {summary['days']} 天）")
    print(f"  settled 总数: {summary['total_settled']}")
    print(f"  可算 move:    {summary['processed']}")
    print(f"  缺 open/close:{summary['no_open_close']}")
    print(f"  欧粘亚动占比: {summary['eu_sticky_rate']:.1%}")
    print()
    print("桶统计（label | supported_side | n | hit_rate | draw_rate | reliable）")
    for b in summary["buckets"]:
        reliable = "✓" if b["reliable"] else "×"
        print(
            f"  {b['label']:8s} {b['supported_side']:6s} "
            f"n={b['n']:3d} hit={b['hit_rate']:.1%} draw={b['draw_rate']:.1%} {reliable}"
        )


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="市场态度校准")
    parser.add_argument("--rebuild", action="store_true", help="重建校准缓存")
    parser.add_argument("--days", type=int, default=DEFAULT_CALIB_DAYS)
    parser.add_argument("--min-n", type=int, default=DEFAULT_MIN_N)
    parser.add_argument("--external-id", help="打印单场 attitude")
    args = parser.parse_args(argv)

    if args.external_id:
        features = build_move_features(args.external_id)
        if "missing" in features:
            print(f"{args.external_id}: {features['missing']}")
            return 1
        attitude = classify_attitude(features)
        print(json.dumps({"features": features, "attitude": attitude}, ensure_ascii=False, indent=2, default=str))
        return 0

    summary = summarize_attitude_vs_results(min_n=args.min_n, days=args.days)
    _print_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
