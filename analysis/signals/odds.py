"""Interpret Asian handicap line/water and European odds movement."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MarketSignals:
    """Structured market read; bias keys are home/draw/away small adjustments (~±0.05)."""
    bias_1x2: dict[str, float] = field(default_factory=lambda: {"home": 0.0, "draw": 0.0, "away": 0.0})
    ah_side_bias: float = 0.0  # >0 upper/home, <0 lower/away
    notes: list[str] = field(default_factory=list)
    line_summary: str = ""
    water_summary: str = ""
    eu_summary: str = ""


def _safe_float(v) -> float | None:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _line_desc(line: float | None) -> str:
    if line is None:
        return "n/a"
    if line == 0:
        return "平手"
    if line < 0:
        return f"主让 {abs(line)}"
    return f"主受 {line}"


def _analyze_ah_line(cur: dict, sig: MarketSignals) -> None:
    open_line = _safe_float(cur.get("ah_open_line"))
    live_line = _safe_float(cur.get("ah_line"))
    if open_line is None or live_line is None:
        sig.line_summary = f"当前盘口 {_line_desc(live_line)}（无初盘对比）"
        return

    delta = live_line - open_line
    if delta < -0.01:
        sig.bias_1x2["home"] += 0.04
        sig.ah_side_bias += 0.06
        direction = f"升盘：{_line_desc(open_line)} → {_line_desc(live_line)}，主队让球加深"
        note = "升盘通常表示机构对主队/上盘信心增强"
    elif delta > 0.01:
        sig.bias_1x2["home"] -= 0.04
        sig.bias_1x2["away"] += 0.03
        sig.ah_side_bias -= 0.06
        direction = f"降盘：{_line_desc(open_line)} → {_line_desc(live_line)}，主队让球变浅"
        note = "降盘通常表示对上盘/主队信心减弱或下盘资金介入"
    else:
        direction = f"盘口未变 {_line_desc(live_line)}"
        note = "盘口稳定，重点看水位与欧赔变化"

    sig.line_summary = direction
    sig.notes.append(f"【盘口】{direction}。{note}")


def _analyze_ah_water(cur: dict, sig: MarketSignals) -> None:
    oh = _safe_float(cur.get("ah_open_home_water"))
    oa = _safe_float(cur.get("ah_open_away_water"))
    lh = _safe_float(cur.get("ah_home_water"))
    la = _safe_float(cur.get("ah_away_water"))
    live_line = _safe_float(cur.get("ah_line"))

    parts: list[str] = []
    if lh is not None:
        parts.append(f"上水 {oh or '?'} → {lh}")

    if oh is not None and lh is not None:
        dh = lh - oh
        if dh <= -0.03:
            sig.bias_1x2["home"] += 0.03
            sig.ah_side_bias += 0.05
            parts.append("上盘降水→机构降赔防上盘")
        elif dh >= 0.03:
            sig.bias_1x2["home"] -= 0.02
            sig.ah_side_bias -= 0.04
            parts.append("上盘升水→对上盘信心减弱")

    if oa is not None and la is not None:
        da = la - oa
        if la is not None:
            parts.append(f"下水 {oa} → {la}")
        if da >= 0.03:
            sig.bias_1x2["away"] -= 0.02
            sig.ah_side_bias += 0.04
            parts.append("下盘升水→不鼓励下盘，利好上盘")
        elif da <= -0.03:
            sig.bias_1x2["away"] += 0.03
            sig.ah_side_bias -= 0.05
            parts.append("下盘降水→资金支持下盘")

    if live_line is not None and lh is not None:
        if lh <= 0.85:
            parts.append(f"临盘上水 {lh} 偏低水，上盘赔付压力小")
            sig.ah_side_bias += 0.02
        elif lh >= 1.0:
            parts.append(f"临盘上水 {lh} 偏高水，上盘打出赔付高")
            sig.ah_side_bias -= 0.02

    sig.water_summary = "；".join(parts) if parts else "水位数据不足"
    if parts:
        sig.notes.append(f"【水位】{sig.water_summary}")


def _implied(h, d, a) -> dict[str, float] | None:
    try:
        ih, id_, ia = 1 / float(h), 1 / float(d), 1 / float(a)
        t = ih + id_ + ia
        return {"home": ih / t, "draw": id_ / t, "away": ia / t}
    except (TypeError, ZeroDivisionError, ValueError):
        return None


def _analyze_eu_move(cur: dict, sig: MarketSignals) -> None:
    open_h = _safe_float(cur.get("eu_open_home"))
    open_d = _safe_float(cur.get("eu_open_draw"))
    open_a = _safe_float(cur.get("eu_open_away"))
    live_h = _safe_float(cur.get("eu_home"))
    live_d = _safe_float(cur.get("eu_draw"))
    live_a = _safe_float(cur.get("eu_away"))

    if not any([open_h, open_d, open_a]):
        sig.eu_summary = (
            f"当前欧赔 主{live_h}/平{live_d}/客{live_a}（无初赔对比）"
            if live_h else "欧赔数据不足"
        )
        return

    imp_open = _implied(open_h, open_d, open_a)
    imp_live = _implied(live_h, live_d, live_a)
    from eu_implied_metrics import compute_eu_implied
    eu_metrics = compute_eu_implied(live_h, live_d, live_a)
    if not imp_open or not imp_live:
        return

    labels = {"home": "主胜", "draw": "平局", "away": "客胜"}
    moves: list[str] = []
    for key, oh, lh in [("home", open_h, live_h), ("draw", open_d, live_d), ("away", open_a, live_a)]:
        if oh is None or lh is None:
            continue
        delta_imp = imp_live[key] - imp_open[key]
        if lh < oh - 0.02:
            sig.bias_1x2[key] += 0.04
            moves.append(f"{labels[key]}赔率 {oh}→{lh} 下调，资金倾向{labels[key]}")
        elif lh > oh + 0.02:
            sig.bias_1x2[key] -= 0.03
            moves.append(f"{labels[key]}赔率 {oh}→{lh} 上调，{labels[key]}被降温")
        elif abs(delta_imp) >= 0.008:
            if delta_imp > 0:
                sig.bias_1x2[key] += 0.02
                moves.append(f"{labels[key]}隐含概率升至 {imp_live[key]*100:.1f}%")
            else:
                sig.bias_1x2[key] -= 0.02
                moves.append(f"{labels[key]}隐含概率降至 {imp_live[key]*100:.1f}%")

    sig.eu_summary = "；".join(moves) if moves else (
        f"欧赔变化不大（主 {open_h}→{live_h}，平 {open_d}→{live_d}，客 {open_a}→{live_a}）"
    )
    if eu_metrics:
        sig.eu_summary += (
            f"；隐含和 {eu_metrics.raw_sum_pct:.1f}%"
            f"（去水 主{eu_metrics.fair_home_pct:.1f}/"
            f"平{eu_metrics.fair_draw_pct:.1f}/"
            f"客{eu_metrics.fair_away_pct:.1f}%）"
        )
        if eu_metrics.is_anomaly:
            sig.notes.append(f"【欧赔隐含】{eu_metrics.reason}（参考权重低，注意数据质量）")
    sig.notes.append(f"【欧赔】{sig.eu_summary}")


def build_market_signals(cur: dict) -> MarketSignals:
    sig = MarketSignals()
    _analyze_ah_line(cur, sig)
    _analyze_ah_water(cur, sig)
    _analyze_eu_move(cur, sig)
    return sig
