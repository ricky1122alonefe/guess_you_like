"""EU↔AH conversion heuristics and bookmaker routine (套路) pattern detection."""

from __future__ import annotations

from dataclasses import dataclass, field

import config as cfg


@dataclass
class MarketPatternAnalysis:
    """Cross-market consistency and named routines."""
    eu_implied: dict[str, float] | None = None
    eu_to_ah_line: float | None = None          # 欧转亚：欧赔隐含大致盘口
    ah_to_eu_sketch: dict[str, float] | None = None  # 亚转欧：盘口反推欧赔区间
    ah_line_live: float | None = None
    line_gap: float | None = None               # 实际盘口 - 欧赔隐含盘口
    consistency: str = "unknown"                # aligned | ah_shallow | ah_deep
    patterns: list[dict] = field(default_factory=list)
    routine_notes: list[str] = field(default_factory=list)
    conversion_summary: str = ""


def _safe(v) -> float | None:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def eu_implied_probs(h, d, a) -> dict[str, float] | None:
    try:
        ih, id_, ia = 1 / float(h), 1 / float(d), 1 / float(a)
        t = ih + id_ + ia
        return {"home": ih / t, "draw": id_ / t, "away": ia / t}
    except (TypeError, ZeroDivisionError, ValueError):
        return None


def _p_home_win_conditional(imp: dict[str, float]) -> float:
    """P(home win | not draw) ≈ 用于欧转亚."""
    h, a = imp.get("home", 0), imp.get("away", 0)
    t = h + a
    return h / t if t > 0 else 0.5


def eu_to_ah_line(h, d, a) -> float | None:
    """
    欧转亚：由欧赔隐含概率粗算「合理亚盘」(主队视角，负=让球)。
    行业常用近似，非精确公式。
    """
    imp = eu_implied_probs(h, d, a)
    if not imp:
        return None
    ph = _p_home_win_conditional(imp)
    pd = imp.get("draw", 0)

    # 平局率高 → 实际让球通常比纯胜负概率浅一点
    if pd >= 0.30:
        ph -= 0.02
    elif pd >= 0.27:
        ph -= 0.01

    if ph >= 0.74:
        return -1.25
    if ph >= 0.68:
        return -1.0
    if ph >= 0.62:
        return -0.75
    if ph >= 0.56:
        return -0.5
    if ph >= 0.53:
        return -0.25
    if ph >= 0.47:
        return 0.0
    if ph >= 0.44:
        return 0.25
    if ph >= 0.38:
        return 0.5
    if ph >= 0.32:
        return 0.75
    return 1.0


def ah_to_eu_sketch(line: float | None) -> dict[str, float] | None:
    """
    亚转欧：由亚盘粗推欧赔主/客区间（中值，不含精确返还率）。
    仅用于「盘赔是否同向」对照，非投注换算。
    """
    if line is None:
        return None
    ln = float(line)
    table = {
        -1.25: (1.45, 6.5),
        -1.0: (1.55, 5.5),
        -0.75: (1.65, 4.8),
        -0.5: (1.85, 4.0),
        -0.25: (2.05, 3.5),
        0.0: (2.35, 3.0),
        0.25: (2.70, 2.55),
        0.5: (3.10, 2.25),
        0.75: (3.60, 1.95),
        1.0: (4.20, 1.75),
    }
    keys = sorted(table.keys())
    best = min(keys, key=lambda k: abs(k - ln))
    home, away = table[best]
    draw = round((home + away) / 2.8, 2)
    return {"home": home, "draw": draw, "away": away, "ref_line": best}


def _line_desc(line: float | None) -> str:
    if line is None:
        return "n/a"
    if line == 0:
        return "平手"
    if line < 0:
        return f"主让{abs(line)}"
    return f"主受{line}"


def _add_pattern(out: MarketPatternAnalysis, pid: str, name: str, detail: str, *, bias: str = "neutral") -> None:
    out.patterns.append({"id": pid, "name": name, "routine": detail, "bias": bias})
    out.routine_notes.append(f"【{name}】{detail}")


def analyze_market_patterns(cur: dict) -> MarketPatternAnalysis:
    """Detect EU↔AH consistency and common bookmaker routines."""
    out = MarketPatternAnalysis()

    eu_h = _safe(cur.get("eu_home"))
    eu_d = _safe(cur.get("eu_draw"))
    eu_a = _safe(cur.get("eu_away"))
    eu_oh = _safe(cur.get("eu_open_home"))
    eu_od = _safe(cur.get("eu_open_draw"))
    eu_oa = _safe(cur.get("eu_open_away"))

    ll = _safe(cur.get("ah_line"))
    ol = _safe(cur.get("ah_open_line"))
    lh = _safe(cur.get("ah_home_water"))
    oh = _safe(cur.get("ah_open_home_water"))
    la = _safe(cur.get("ah_away_water"))
    oa = _safe(cur.get("ah_open_away_water"))

    out.ah_line_live = ll
    out.eu_implied = eu_implied_probs(eu_h, eu_d, eu_a) if all(x for x in (eu_h, eu_d, eu_a)) else None

    if out.eu_implied and eu_h and eu_d and eu_a:
        out.eu_to_ah_line = eu_to_ah_line(eu_h, eu_d, eu_a)
    if ll is not None:
        out.ah_to_eu_sketch = ah_to_eu_sketch(ll)

    # ── 欧转亚 / 亚转欧 对照 ──
    if out.eu_to_ah_line is not None and ll is not None:
        out.line_gap = round(ll - out.eu_to_ah_line, 2)
        gap = out.line_gap
        tol = cfg.EU_AH_LINE_GAP_TOL

        if abs(gap) <= tol:
            out.consistency = "aligned"
            out.conversion_summary = (
                f"欧转亚：欧赔隐含约 {_line_desc(out.eu_to_ah_line)}，"
                f"实际亚盘 {_line_desc(ll)}，盘赔基本一致（差 {gap:+.2f}），参考性较高"
            )
        elif gap > tol:
            out.consistency = "ah_shallow"
            out.conversion_summary = (
                f"欧转亚：欧赔隐含约 {_line_desc(out.eu_to_ah_line)}，"
                f"实际亚盘 {_line_desc(ll)} 更浅（差 {gap:+.2f}）→ 亚盘比欧赔「少让」，"
                f"常见主队过热/诱上套路"
            )
            _add_pattern(
                out, "shallow_ah_vs_eu", "亚盘偏浅",
                f"欧赔支持 {_line_desc(out.eu_to_ah_line)}，实际仅 {_line_desc(ll)}，主队门槛偏低，需防诱主",
                bias="trap_home",
            )
        else:
            out.consistency = "ah_deep"
            out.conversion_summary = (
                f"欧转亚：欧赔隐含约 {_line_desc(out.eu_to_ah_line)}，"
                f"实际亚盘 {_line_desc(ll)} 更深（差 {gap:+.2f}）→ 亚盘比欧赔更看低主队或阻上"
            )
            _add_pattern(
                out, "deep_ah_vs_eu", "亚盘偏深",
                f"实际盘口比欧赔隐含更深，上盘门槛高，可能是真看主或阻上",
                bias="caution_upper",
            )

    if out.ah_to_eu_sketch and eu_h:
        sketch_h = out.ah_to_eu_sketch["home"]
        diff = eu_h - sketch_h
        if abs(diff) >= cfg.EU_AH_ODDS_GAP:
            direction = "主胜欧赔低于亚转欧预期（更热）" if diff < 0 else "主胜欧赔高于亚转欧预期（更冷）"
            out.routine_notes.append(
                f"【亚转欧】盘口 {_line_desc(ll)} 粗推主胜约 {sketch_h}，实际 {eu_h}，{direction}"
            )

    # ── 经典套路组合 ──
    line_up = ol is not None and ll is not None and ll - ol < -cfg.LINE_MOVE_EPS
    line_down = ol is not None and ll is not None and ll - ol > cfg.LINE_MOVE_EPS
    upper_water_down = oh is not None and lh is not None and lh - oh <= -cfg.WATER_MOVE_EPS
    lower_water_down = oa is not None and la is not None and la - oa <= -cfg.WATER_MOVE_EPS
    eu_home_down = eu_oh and eu_h and eu_h < eu_oh - cfg.EU_ODDS_MOVE_EPS
    eu_home_up = eu_oh and eu_h and eu_h > eu_oh + cfg.EU_ODDS_MOVE_EPS
    eu_draw_down = eu_od and eu_d and eu_d < eu_od - cfg.DRAW_STEAM_DROP

    if line_up and upper_water_down:
        _add_pattern(
            out, "lure_upper_combo", "诱上三部曲",
            "升盘+上盘降水：一边加深门槛一边降上盘赔付，典型诱上/引导资金打上盘",
            bias="trap_home",
        )

    if line_up and eu_home_up:
        _add_pattern(
            out, "ah_eu_split_home", "盘赔分裂·阻主",
            "亚盘升盘示强，欧赔主胜却上调 → 亚盘诱多、欧赔阻投，主胜慎追",
            bias="trap_home",
        )

    if line_down and lower_water_down:
        _add_pattern(
            out, "lure_lower_combo", "诱下三部曲",
            "降盘+下盘降水：诱下盘/客胜套路",
            bias="trap_away",
        )

    if line_down and eu_home_down:
        _add_pattern(
            out, "sync_weak_home", "盘赔同向看衰主",
            "降盘且欧赔主胜下调 → 亚盘欧赔同向不看好主队，非单纯诱盘",
            bias="bear_home",
        )

    if eu_draw_down and not line_up:
        _add_pattern(
            out, "draw_split", "平局分流",
            "平赔下调、亚盘未明显升盘 → 资金分流至平局，胜负方向需防平",
            bias="draw_live",
        )

    if out.consistency == "aligned" and eu_home_down and line_up:
        _add_pattern(
            out, "aligned_strengthen", "盘赔共振加强",
            "盘赔一致且欧赔主胜降、亚盘升 → 主胜方向共振（仍看水位是否诱盘）",
            bias="support_home",
        )

    if out.consistency == "ah_shallow" and eu_home_down:
        _add_pattern(
            out, "shallow_plus_eu_hot", "浅盘+欧热",
            "欧赔主胜降（更热）但亚盘偏浅 → 高概率诱主：欧赔引流、亚盘不设防",
            bias="trap_home",
        )

    # 初盘→临盘 套路
    if ol is not None and out.eu_to_ah_line is not None:
        open_eu_line = eu_to_ah_line(eu_oh, eu_od, eu_oa) if all(x for x in (eu_oh, eu_od, eu_oa)) else None
        if open_eu_line is not None and ll is not None:
            open_gap = ol - open_eu_line
            live_gap = ll - out.eu_to_ah_line
            if open_gap <= cfg.EU_AH_LINE_GAP_TOL and live_gap > cfg.EU_AH_LINE_GAP_TOL + 0.1:
                _add_pattern(
                    out, "open_aligned_live_shallow", "初盘正路→临盘变浅",
                    "初盘欧亚大致吻合，临盘亚盘变浅的幅度大于欧赔变化 → 临场诱上嫌疑上升",
                    bias="trap_home",
                )

    return out


def pattern_penalties(patterns: MarketPatternAnalysis) -> tuple[dict[str, float], list[str]]:
    """Map detected routines to 1X2 penalty multipliers."""
    p = {"home": 1.0, "draw": 1.0, "away": 1.0}
    notes: list[str] = []
    for pat in patterns.patterns:
        bias = pat.get("bias", "neutral")
        if bias == "trap_home":
            p["home"] *= cfg.PATTERN_PENALTY_TRAP_HOME
            notes.append(pat.get("routine", pat.get("name", "")))
        elif bias == "trap_away":
            p["away"] *= cfg.PATTERN_PENALTY_TRAP_AWAY
            notes.append(pat.get("routine", pat.get("name", "")))
    return p, notes
