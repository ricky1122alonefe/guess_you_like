"""竞彩 SP / 让球胜平负 — 所有最终推荐以国内竞彩可售玩法为准."""

from __future__ import annotations

import re
from typing import Any

RQ_CN = {"home": "胜", "draw": "平", "away": "负", "skip": "观望"}
SP_CN = {"home": "主胜", "draw": "平局", "away": "客胜", "skip": "观望"}
KEY_FROM_RQ_CN = {"胜": "home", "平": "draw", "负": "away", "观望": "skip"}
KEY_FROM_SP_CN = {"主胜": "home", "平局": "draw", "客胜": "away", "观望": "skip"}
NO_JINGCAI = "暂无竞彩"


def jingcai_market_mode(jc: dict | None) -> str:
    """Return sp | rqsp | none — which Jingcai product is buyable."""
    if not jc:
        return "none"
    if jc.get("has_sp"):
        return "sp"
    if jc.get("has_rqsp"):
        return "rqsp"
    return "none"


def handicap_label(jc: dict) -> str:
    label = jc.get("handicap_label")
    if label not in (None, ""):
        return str(label)
    h = jc.get("handicap")
    if h is None:
        return "—"
    if int(h) > 0:
        return f"+{int(h)}"
    return str(int(h))


def market_label(jc: dict, mode: str) -> str:
    if mode == "sp":
        return "胜平负"
    if mode == "rqsp":
        hcap = handicap_label(jc)
        return f"让球({hcap})" if hcap != "—" else "让球胜平负"
    return "—"


def settle_handicap(home_goals: int, away_goals: int, handicap: int) -> str:
    """Handicap applied to home side (竞彩规则：+2 表示主队加 2 球后比较)."""
    adj = home_goals + handicap
    if adj > away_goals:
        return "home"
    if adj == away_goals:
        return "draw"
    return "away"


def parse_score_text(text: str) -> tuple[int, int, float] | None:
    if not text:
        return None
    m = re.search(r"(\d+)\s*[-:：]\s*(\d+)", str(text))
    if not m:
        return None
    w = 1.0
    pm = re.search(r"([\d.]+)\s*%", str(text))
    if pm:
        try:
            w = float(pm.group(1))
        except ValueError:
            w = 1.0
    return int(m.group(1)), int(m.group(2)), w


def _collect_scores(pred: dict) -> list[str]:
    scores = pred.get("likely_scores_detail") or pred.get("likely_scores") or []
    if isinstance(scores, str):
        scores = re.split(r"[、,，/]", scores)
    row = pred.get("predict_row") or {}
    extra = row.get("推荐比分") or ""
    if extra and isinstance(extra, str):
        scores = list(scores) + re.split(r"[、,，/]", extra)
    out: list[str] = []
    for s in scores:
        s = str(s).strip()
        if s and s not in out:
            out.append(s)
    return out[:6]


def infer_rq_pick_from_scores(scores: list[str], handicap: int) -> tuple[str, str]:
    """Return (pick_key, reason) from likely scores under handicap line."""
    counts = {"home": 0.0, "draw": 0.0, "away": 0.0}
    used = 0
    for s in scores:
        parsed = parse_score_text(s)
        if not parsed:
            continue
        h, a, w = parsed
        outcome = settle_handicap(h, a, handicap)
        counts[outcome] += w
        used += 1
    if used == 0:
        return "skip", "无可用比分推演让球结果"
    best = max(counts, key=counts.get)
    total = sum(counts.values()) or 1.0
    pct = counts[best] / total * 100
    hcap = handicap
    sign = f"+{hcap}" if hcap > 0 else str(hcap)
    reason = (
        f"按推荐比分在让球({sign})下推演，{RQ_CN[best]}概率约 {pct:.0f}%"
        f"（{used} 个比分样本）"
    )
    return best, reason


def _sp_for_pick(jc: dict, mode: str, pick_key: str) -> float | None:
    if pick_key in ("skip", ""):
        return None
    if mode == "sp":
        mapping = {"home": "sp_home", "draw": "sp_draw", "away": "sp_away"}
    else:
        mapping = {"home": "rqsp_home", "draw": "rqsp_draw", "away": "rqsp_away"}
    val = jc.get(mapping.get(pick_key, ""))
    try:
        return round(float(val), 2) if val is not None else None
    except (TypeError, ValueError):
        return None


def _analytical_result_cn(pred: dict) -> str:
    row = pred.get("predict_row") or {}
    if row.get("赛果预测"):
        return str(row["赛果预测"])
    if pred.get("match_result_1x2_cn"):
        return str(pred["match_result_1x2_cn"])
    return str(row.get("胜平负") or pred.get("result_1x2_cn") or "—")


def compute_jingcai_pick(pred: dict, jc: dict | None) -> dict[str, Any]:
    """Derive buyable 竞彩 recommendation from prediction + poll jingcai snapshot."""
    mode = jingcai_market_mode(jc)
    empty = {
        "jingcai_market": "none",
        "jingcai_market_label": "—",
        "jingcai_pick": "skip",
        "jingcai_pick_cn": "观望",
        "jingcai_pick_display": NO_JINGCAI,
        "jingcai_sp": None,
        "jingcai_reason": "暂无竞彩开售数据",
    }
    if mode == "none" or not jc:
        return empty

    mkt_label = market_label(jc, mode)
    pick_key = "skip"
    reason = ""

    ai_rq = pred.get("jingcai_rq_pick") or pred.get("jingcai_pick")
    ai_rq_cn = pred.get("jingcai_rq_pick_cn") or pred.get("jingcai_pick_cn")
    if mode == "rqsp" and ai_rq in ("home", "draw", "away"):
        pick_key = ai_rq
        reason = pred.get("jingcai_rq_reason") or pred.get("jingcai_reason") or "AI 让球推荐"
    elif mode == "rqsp":
        handicap = jc.get("handicap")
        if handicap is None:
            pick_key = "skip"
            reason = "缺少让球数，无法计算让球推荐"
        else:
            pick_key, reason = infer_rq_pick_from_scores(
                _collect_scores(pred), int(handicap),
            )
    else:
        pick_key = pred.get("result_1x2") or "skip"
        cn = pred.get("result_1x2_cn") or ""
        if pick_key == "skip" and cn in KEY_FROM_SP_CN:
            pick_key = KEY_FROM_SP_CN[cn]
        if pick_key == "skip":
            reason = "赛果分析为观望"
        else:
            reason = "竞彩胜平负与赛果分析一致"

    if mode == "rqsp" and ai_rq_cn in KEY_FROM_RQ_CN and pick_key == "skip":
        pick_key = KEY_FROM_RQ_CN[ai_rq_cn]

    if pick_key == "skip":
        pick_cn = "观望"
        display = f"{mkt_label} 观望"
    elif mode == "rqsp":
        pick_cn = RQ_CN[pick_key]
        display = f"{mkt_label} {pick_cn}"
    else:
        pick_cn = SP_CN[pick_key]
        display = pick_cn

    return {
        "jingcai_market": mode,
        "jingcai_market_label": mkt_label,
        "jingcai_pick": pick_key,
        "jingcai_pick_cn": pick_cn,
        "jingcai_pick_display": display,
        "jingcai_sp": _sp_for_pick(jc, mode, pick_key),
        "jingcai_reason": reason,
    }


def final_recommendation_cn(pred: dict) -> str:
    """Primary user-facing recommendation — always 竞彩 when available."""
    row = pred.get("predict_row") or {}
    for key in ("竞彩推荐", "胜平负", "final_pick_cn"):
        val = row.get(key) if key != "final_pick_cn" else pred.get(key)
        if val and str(val) not in ("—", ""):
            return str(val)
    info = pred.get("jingcai_pick_info") or {}
    display = info.get("jingcai_pick_display")
    if display and display not in ("—", ""):
        return str(display)
    return NO_JINGCAI


def final_pick_key(pred: dict) -> str:
    info = pred.get("jingcai_pick_info") or {}
    key = info.get("jingcai_pick")
    if key and key != "skip":
        return str(key)
    cn = final_recommendation_cn(pred)
    if cn in KEY_FROM_SP_CN:
        return KEY_FROM_SP_CN[cn]
    if cn.endswith(" 胜") or cn == "胜":
        return "home"
    if cn.endswith(" 平") or cn == "平":
        return "draw"
    if cn.endswith(" 负") or cn == "负":
        return "away"
    return "skip"


def attach_jingcai_recommendation(pred: dict, jingcai: dict | None) -> dict:
    """Attach 竞彩 fields and sync as the sole final recommendation."""
    info = compute_jingcai_pick(pred, jingcai)
    pred["jingcai_pick_info"] = info
    if jingcai:
        pred["jingcai_snapshot"] = jingcai

    row = dict(pred.get("predict_row") or {})
    analytical = _analytical_result_cn(pred)
    if analytical not in ("—", NO_JINGCAI, ""):
        row["赛果预测"] = analytical
        pred["match_result_1x2_cn"] = analytical

    mode = info.get("jingcai_market") or "none"
    if mode == "none":
        row["竞彩玩法"] = "—"
        row["竞彩推荐"] = NO_JINGCAI
        row["胜平负"] = NO_JINGCAI
        pred["final_pick_cn"] = NO_JINGCAI
    else:
        row["竞彩玩法"] = info["jingcai_market_label"]
        row["竞彩推荐"] = info["jingcai_pick_display"]
        if info.get("jingcai_sp") is not None:
            row["竞彩SP"] = info["jingcai_sp"]
        if info.get("jingcai_pick") == "skip":
            row["胜平负"] = info["jingcai_pick_display"]
            pred["final_pick_cn"] = info["jingcai_pick_display"]
        else:
            row["胜平负"] = info["jingcai_pick_display"]
            pred["final_pick_cn"] = info["jingcai_pick_display"]

    pred["predict_row"] = row
    return pred


def actionable_jingcai_pick(pred: dict) -> dict[str, Any] | None:
    """Actionable pick for parlays — must have 竞彩开售且非观望."""
    info = pred.get("jingcai_pick_info") or {}
    mode = info.get("jingcai_market") or jingcai_market_mode(pred.get("jingcai_snapshot"))
    if mode == "none":
        return None
    pick_key = info.get("jingcai_pick") or "skip"
    pick_display = final_recommendation_cn(pred)
    if pick_key == "skip" or pick_display in (NO_JINGCAI, "—", "观望", "") or "观望" in pick_display:
        return None
    return {
        "pick_key": pick_key,
        "pick_cn": pick_display,
        "pick_short": info.get("jingcai_pick_cn") or "—",
        "market": mode,
        "market_label": info.get("jingcai_market_label") or "—",
        "sp": info.get("jingcai_sp"),
        "reason": info.get("jingcai_reason") or "",
    }
