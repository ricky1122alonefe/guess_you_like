"""Bookmaker risk-control analysis: opening vs live movement, pattern weight."""

from __future__ import annotations

from dataclasses import dataclass, field

import config as cfg
from analysis.signals.odds import MarketSignals, build_market_signals


PATTERN_WEIGHT = cfg.PATTERN_WEIGHT
LEVEL_CN = {"low": "低", "medium": "中", "high": "高"}
RISK_CN = {"low": "常规", "medium": "升高", "high": "显著升高"}


@dataclass
class ControlAnalysis:
    intensity: float  # 0~1
    level: str  # low | medium | high
    pattern_weight: float
    trajectory_tag: str
    risk_level: str
    payout_pressure_note: str
    live_signal_scale: float  # how much to trust live movement vs open pattern
    notes: list[str] = field(default_factory=list)
    signals: MarketSignals | None = None


def _safe(v) -> float | None:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _move_score(cur: dict) -> tuple[float, str]:
    """Estimate control intensity from open→live changes."""
    score = 0.0
    moves = 0

    ol, ll = _safe(cur.get("ah_open_line")), _safe(cur.get("ah_line"))
    if ol is not None and ll is not None:
        ld = abs(ll - ol)
        if ld >= cfg.LINE_MOVE_EPS:
            score += min(ld / cfg.MOVE_NORM_LINE, 1.0) * cfg.MOVE_WEIGHT_LINE
            moves += 1

    oh, lh = _safe(cur.get("ah_open_home_water")), _safe(cur.get("ah_home_water"))
    oa, la = _safe(cur.get("ah_open_away_water")), _safe(cur.get("ah_away_water"))
    if oh is not None and lh is not None:
        score += min(abs(lh - oh) / cfg.MOVE_NORM_WATER, 1.0) * cfg.MOVE_WEIGHT_WATER
        moves += 1
    if oa is not None and la is not None:
        score += min(abs(la - oa) / cfg.MOVE_NORM_WATER, 1.0) * cfg.MOVE_WEIGHT_WATER
        moves += 1

    for ok, lk in [
        ("eu_open_home", "eu_home"),
        ("eu_open_draw", "eu_draw"),
        ("eu_open_away", "eu_away"),
    ]:
        o, l = _safe(cur.get(ok)), _safe(cur.get(lk))
        if o and l:
            score += min(abs(l - o) / max(o * cfg.MOVE_NORM_EU_RATIO, cfg.MOVE_NORM_EU_FLOOR), 1.0) * cfg.MOVE_WEIGHT_EU
            moves += 1

    intensity = min(score, 1.0)
    return intensity, f"{moves}项变动"


def _trajectory_tag(cur: dict, intensity: float) -> str:
    ol, ll = _safe(cur.get("ah_open_line")), _safe(cur.get("ah_line"))
    oh, lh = _safe(cur.get("ah_open_home_water")), _safe(cur.get("ah_home_water"))
    oa, la = _safe(cur.get("ah_open_away_water")), _safe(cur.get("ah_away_water"))

    tags: list[str] = []
    if ol is not None and ll is not None:
        d = ll - ol
        if d < -cfg.LINE_MOVE_EPS:
            tags.append("升盘")
        elif d > cfg.LINE_MOVE_EPS:
            tags.append("降盘")
        else:
            tags.append("盘口稳定")

    water_moves = 0
    if oh is not None and lh is not None and abs(lh - oh) >= cfg.WATER_MOVE_EPS:
        water_moves += 1
    if oa is not None and la is not None and abs(la - oa) >= cfg.WATER_MOVE_EPS:
        water_moves += 1
    if water_moves:
        tags.append("水位调整")
    if intensity >= cfg.CONTROL_INTENSITY_HIGH:
        tags.append("临盘剧烈震荡")
    elif intensity < cfg.CONTROL_INTENSITY_LOW:
        tags.append("走势平稳")

    return " / ".join(tags) if tags else "数据不足"


def analyze_control(cur: dict) -> ControlAnalysis:
    """Interpret line/water/EU movement as payout hedging, not pure form change."""
    signals = build_market_signals(cur)
    intensity, move_cnt = _move_score(cur)
    trajectory = _trajectory_tag(cur, intensity)

    if intensity < cfg.CONTROL_INTENSITY_LOW:
        level = "low"
    elif intensity < cfg.CONTROL_INTENSITY_HIGH:
        level = "medium"
    else:
        level = "high"

    pattern_weight = PATTERN_WEIGHT[level]
    live_scale = 1.0 - intensity * cfg.LIVE_SIGNAL_DAMPING

    if level == "high":
        payout = (
            "临盘异动显著，走势更反映资金对冲与控赔付，"
            "历史同初盘规律参考价值降低，赛果不确定性上升。"
        )
    elif level == "medium":
        payout = "存在明显调盘/调水，部分走势为平衡资金，初盘规律需打折参考。"
    else:
        payout = "走势相对平稳，初盘→临盘变化小，历史同初盘区间规律参考价值较高。"

    notes = [
        "【风控逻辑】后续调盘/调水多数为控赔付、引导资金，不等于机构对赛果判断改变。",
        f"【控盘强度】{LEVEL_CN[level]}（指数 {intensity:.2f}，{move_cnt}）| 轨迹：{trajectory}",
        f"【规律权重】初盘历史规律按 {int(pattern_weight * 100)}% 计入综合结论",
        f"【赔付压力】{payout}",
    ]
    for n in signals.notes:
        notes.append(n.replace("→", "→").replace("信心增强", "可能为引导资金").replace("被降温", "或为控赔付"))

    return ControlAnalysis(
        intensity=intensity,
        level=level,
        pattern_weight=pattern_weight,
        trajectory_tag=trajectory,
        risk_level=level,
        payout_pressure_note=payout,
        live_signal_scale=live_scale,
        notes=notes,
        signals=signals,
    )
