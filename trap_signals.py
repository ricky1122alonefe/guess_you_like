"""Detect bookmaker trap / contradiction patterns and apply directional penalties."""

from __future__ import annotations

from dataclasses import dataclass, field

import config as cfg
from market_patterns import analyze_market_patterns, pattern_penalties


@dataclass
class TrapAnalysis:
    """Multiplicative penalties per 1X2 direction (1.0 = no change)."""
    penalties: dict[str, float] = field(default_factory=lambda: {"home": 1.0, "draw": 1.0, "away": 1.0})
    flagged_direction: str | None = None
    notes: list[str] = field(default_factory=list)
    draw_steam: bool = False
    severe: bool = False
    market_patterns: object | None = None


def _safe(v) -> float | None:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _implied(h, d, a) -> dict[str, float] | None:
    try:
        ih, id_, ia = 1 / float(h), 1 / float(d), 1 / float(a)
        t = ih + id_ + ia
        return {"home": ih / t, "draw": id_ / t, "away": ia / t}
    except (TypeError, ZeroDivisionError, ValueError):
        return None


def analyze_traps(cur: dict, *, intensity: float, level: str) -> TrapAnalysis:
    """
    Reference patterns (industry-style heuristics, not insider formulas):
    - Line up + upper water down → lure upper/home
    - Line down + lower water down → lure lower/away
    - AH direction vs EU implied direction conflict
    - EU moves sharply while AH stable → funds on 1X2, AH lagging
    - Draw odds steam while favorite line hardens
    """
    out = TrapAnalysis()
    notes = out.notes
    p = out.penalties

    ol, ll = _safe(cur.get("ah_open_line")), _safe(cur.get("ah_line"))
    oh, lh = _safe(cur.get("ah_open_home_water")), _safe(cur.get("ah_home_water"))
    oa, la = _safe(cur.get("ah_open_away_water")), _safe(cur.get("ah_away_water"))

    eu_oh, eu_od, eu_oa = _safe(cur.get("eu_open_home")), _safe(cur.get("eu_open_draw")), _safe(cur.get("eu_open_away"))
    eu_lh, eu_ld, eu_la = _safe(cur.get("eu_home")), _safe(cur.get("eu_draw")), _safe(cur.get("eu_away"))

    line_up = ol is not None and ll is not None and ll - ol < -cfg.LINE_MOVE_EPS
    line_down = ol is not None and ll is not None and ll - ol > cfg.LINE_MOVE_EPS
    line_flat = ol is not None and ll is not None and abs(ll - ol) <= cfg.LINE_MOVE_EPS

    upper_water_down = oh is not None and lh is not None and lh - oh <= -cfg.WATER_MOVE_EPS
    lower_water_down = oa is not None and la is not None and la - oa <= -cfg.WATER_MOVE_EPS
    upper_water_up = oh is not None and lh is not None and lh - oh >= cfg.WATER_MOVE_EPS
    lower_water_up = oa is not None and la is not None and la - oa >= cfg.WATER_MOVE_EPS

    # ① 升盘 + 上盘降水 → 诱上盘
    if line_up and upper_water_down:
        p["home"] *= cfg.TRAP_PENALTY_LINE_UP_WATER_DOWN
        notes.append("【诱盘】升盘+上盘降水：常见诱上盘/主胜，慎追")
        out.flagged_direction = "home"

    # ② 降盘 + 下盘降水 → 诱下盘
    if line_down and lower_water_down:
        p["away"] *= cfg.TRAP_PENALTY_LINE_DOWN_WATER_DOWN
        notes.append("【诱盘】降盘+下盘降水：常见诱下盘/客胜，慎追")
        out.flagged_direction = out.flagged_direction or "away"

    # ③ 盘口 vs 欧赔矛盾
    if line_up and eu_oh and eu_lh and eu_lh > eu_oh + cfg.EU_ODDS_MOVE_EPS:
        p["home"] *= cfg.TRAP_PENALTY_LINE_EU_CONFLICT
        notes.append("【矛盾】亚盘升盘但欧赔主胜上调：盘赔背离，主胜慎信")
        out.flagged_direction = out.flagged_direction or "home"

    if line_down and eu_oa and eu_la and eu_la > eu_oa + cfg.EU_ODDS_MOVE_EPS:
        p["away"] *= cfg.TRAP_PENALTY_LINE_EU_CONFLICT
        notes.append("【矛盾】亚盘降盘但欧赔客胜上调：盘赔背离，客胜慎信")
        out.flagged_direction = out.flagged_direction or "away"

    # ④ 欧赔隐含概率大变、亚盘几乎不动 → 资金在 1X2，亚盘参考性降
    imp_o = _implied(eu_oh, eu_od, eu_oa)
    imp_l = _implied(eu_lh, eu_ld, eu_la)
    if imp_o and imp_l and line_flat and intensity >= cfg.EU_DIVERGE_INTENSITY:
        moved = any(abs(imp_l[k] - imp_o[k]) >= cfg.EU_IMPLIED_MOVE_EPS for k in imp_o)
        if moved:
            for k in p:
                p[k] *= cfg.TRAP_PENALTY_EU_AH_DIVERGE
            notes.append("【异动】欧赔隐含概率明显变动、亚盘不动：资金在胜平负通道，规律易失真")

    # ⑤ 平赔资金（draw steam）— 仅提示，用于解读/联动
    if eu_od and eu_ld and eu_ld < eu_od - cfg.DRAW_STEAM_DROP:
        out.draw_steam = True
        notes.append("【资金】平赔下调：临场有平局资金介入，主/客方向需防平")

    # ⑥ 升盘 + 下盘升水（不鼓励下盘）— 轻度利好上盘但若同时上盘降水要警惕（已在①）
    if line_up and lower_water_up and not upper_water_down:
        notes.append("【风控】升盘+下盘升水：机构 discouraging 下盘，偏向上盘赔付管理")

    # ⑦ 高震荡全方向轻扣
    if intensity >= cfg.CONTROL_INTENSITY_HIGH:
        out.severe = True
        for k in p:
            p[k] *= cfg.TRAP_PENALTY_SEVERE_FLUCTUATION
        notes.append("【震荡】临盘剧烈震荡：各方向有效概率统一下调")

    # ⑧ 高控盘 + 已标记诱盘方向 → 再打5折
    if level == "high" and out.flagged_direction:
        fd = out.flagged_direction
        p[fd] *= cfg.TRAP_EXTRA_ON_FLAGGED_HIGH_CONTROL
        notes.append(f"【高控盘】{fd} 方向诱盘信号叠加，有效概率再减半")

    # ⑨ 欧转亚/亚转欧 套路识别
    mp = analyze_market_patterns(cur)
    pp, pnotes = pattern_penalties(mp)
    for k in p:
        p[k] *= pp.get(k, 1.0)
    if mp.conversion_summary:
        notes.insert(0, mp.conversion_summary)
    notes.extend(mp.routine_notes)
    for pn in pnotes:
        if pn not in notes:
            notes.append(pn)
    if mp.patterns:
        trap_ids = {pat.get("bias") for pat in mp.patterns if pat.get("bias", "").startswith("trap_")}
        if "trap_home" in str(trap_ids) and not out.flagged_direction:
            out.flagged_direction = "home"
        if "trap_away" in str(trap_ids) and not out.flagged_direction:
            out.flagged_direction = out.flagged_direction or "away"
    out.market_patterns = mp

    return out


def apply_penalties(rates: dict[str, float], trap: TrapAnalysis) -> dict[str, float]:
    return {k: rates.get(k, 0) * trap.penalties.get(k, 1.0) for k in ("home", "draw", "away")}
