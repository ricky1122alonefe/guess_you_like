"""Accuracy-first pick profile — prioritize hit rate; SP sweet spot 1.30–1.60."""

from __future__ import annotations

from typing import Any

import config as app_cfg
from jingcai_pick import actionable_jingcai_pick, final_recommendation_cn, resolve_jingcai_sp
from product_focus import score_prediction_enabled

SKIP_PICKS = frozenset({"观望", "—", "", None, "暂无竞彩"})
DIVERGENCE_TAGS = frozenset({"出线·欧亚分歧", "竞彩·参考分歧"})


def sp_in_sweet_spot(sp: float | None) -> bool:
    if sp is None:
        return False
    lo = getattr(app_cfg, "ACCURACY_SP_MIN", 1.30)
    hi = getattr(app_cfg, "ACCURACY_SP_MAX", 1.60)
    return lo <= sp <= hi


def evaluate_accuracy_pick(pred: dict) -> dict[str, Any]:
    """
    Grade picks for accuracy-first betting.

    稳胆甜区: 高置信 + 参考/初盘一致 + 无重大分歧 + SP∈[1.3,1.6]
    稳胆:     同上但 SP 不在甜区（仍重正确率，赔率略偏离）
    可跟:     中置信或轻微风险，可小注单关
    慎跟:     低置信 / 分歧 / SP 过高
    """
    row = pred.get("predict_row") or {}
    pick_cn = final_recommendation_cn(pred)
    jc = actionable_jingcai_pick(pred)
    conf = (row.get("置信度") or pred.get("confidence_cn") or "").strip()
    ref_cn = (
        pred.get("reference_result_1x2_cn")
        or row.get("赛果预测")
        or pred.get("match_result_1x2_cn")
        or ""
    )
    open_cn = pred.get("open_result_1x2_cn") or row.get("初盘倾向") or ""
    tags = set(pred.get("alert_tags") or [])
    buy_tier = pred.get("buy_tier") or ""
    sp = resolve_jingcai_sp(pred)
    sweet = sp_in_sweet_spot(sp)
    lo = getattr(app_cfg, "ACCURACY_SP_MIN", 1.30)
    hi = getattr(app_cfg, "ACCURACY_SP_MAX", 1.60)

    reasons: list[str] = []
    score = 0.0

    if pick_cn in SKIP_PICKS or not jc:
        return _out("跳过", 0, sp, sweet, ["不可购或观望"], parlay_ok=False)

    pick_key = jc.get("pick_key") or "skip"
    from jingcai_pick import KEY_FROM_SP_CN

    ref_key = KEY_FROM_SP_CN.get(ref_cn.strip(), "")
    open_key = KEY_FROM_SP_CN.get(open_cn.strip(), "")
    aligned = (not ref_key or ref_key == pick_key) and (not open_key or open_key == pick_key)

    if conf == "高":
        score += 4
    elif conf == "中":
        score += 2
        reasons.append("置信为中")
    else:
        score += 0.5
        reasons.append("置信偏低")

    if aligned:
        score += 3
    else:
        reasons.append("与参考/初盘不完全一致")

    if tags & DIVERGENCE_TAGS:
        score -= 3
        reasons.append("存在欧亚/竞彩分歧标签")

    div = pred.get("jingcai_divergence")
    if isinstance(div, dict) and div.get("divergence"):
        score -= 2
        reasons.append("SP与参考研判分歧")

    ctrl = pred.get("control_level_cn") or ""
    if ctrl == "低":
        score += 1.5
    elif ctrl == "高":
        score -= 1
        reasons.append("高控盘")

    risk = pred.get("risk_level_cn") or ""
    if risk == "常规":
        score += 1
    elif risk == "显著升高":
        score -= 1.5
        reasons.append("震荡显著")

    if pred.get("insufficient_data"):
        score -= 4
        reasons.append("样本不足")

    if sp is not None:
        if sweet:
            score += 3
        elif sp < lo:
            score += 1.5
            reasons.append(f"SP {sp} 低于甜区（更稳但回报低）")
        elif sp <= getattr(app_cfg, "ACCURACY_SP_SOFT_MAX", 1.85):
            score += 0.5
            reasons.append(f"SP {sp} 略高于甜区 {lo:g}–{hi:g}")
        else:
            score -= 2
            reasons.append(f"SP {sp} 偏高，正确率与回报难兼顾")

    if buy_tier == "A":
        score += 1
    elif buy_tier == "C":
        score -= 2

    require_high = getattr(app_cfg, "ACCURACY_FIRST_REQUIRE_HIGH_CONF", True)
    hard_block = (
        pick_cn in SKIP_PICKS
        or not jc
        or (tags & DIVERGENCE_TAGS)
        or (isinstance(div, dict) and div.get("divergence"))
        or not aligned
    )

    if hard_block or score < 4:
        grade = "慎跟" if jc else "跳过"
    elif conf == "高" and aligned and score >= 7 and sweet:
        grade = "稳胆甜区"
    elif conf == "高" and aligned and score >= 6:
        grade = "稳胆"
    elif (conf in ("高", "中") and aligned and score >= 4) or (conf == "中" and score >= 5):
        grade = "可跟"
    else:
        grade = "慎跟"

    if require_high and grade in ("稳胆甜区", "稳胆") and conf != "高":
        grade = "可跟"
        reasons.append("稳胆需高置信")

    parlay_ok = grade in ("稳胆甜区", "稳胆") and buy_tier == "A"
    if grade == "稳胆甜区":
        reasons.insert(0, f"SP {sp} 在目标区间 {lo:g}–{hi:g}")
    elif grade == "稳胆" and sp:
        reasons.insert(0, f"重正确率；SP {sp}")

    return _out(grade, round(score, 2), sp, sweet, reasons[:4], parlay_ok=parlay_ok)


def _out(
    grade: str,
    score: float,
    sp: float | None,
    sweet: bool,
    reasons: list[str],
    *,
    parlay_ok: bool,
) -> dict[str, Any]:
    lo = getattr(app_cfg, "ACCURACY_SP_MIN", 1.30)
    hi = getattr(app_cfg, "ACCURACY_SP_MAX", 1.60)
    return {
        "accuracy_grade": grade,
        "accuracy_grade_cn": grade,
        "accuracy_score": score,
        "jingcai_sp": sp,
        "sweet_spot": sweet,
        "sp_target_min": lo,
        "sp_target_max": hi,
        "accuracy_reason": "；".join(r for r in reasons if r) or "—",
        "accuracy_parlay_ok": parlay_ok,
    }


def _model_prob_pct(pred: dict, pick_key: str) -> float | None:
    """Fair EU probability for the buy direction, if available."""
    if pick_key not in ("home", "draw", "away"):
        return None
    eu = pred.get("eu_implied") or {}
    key = f"fair_{pick_key}_pct"
    try:
        val = eu.get(key)
        return round(float(val), 1) if val is not None else None
    except (TypeError, ValueError):
        return None


def build_sweet_spot_analysis(pred: dict) -> dict[str, Any]:
    """
    Rich breakdown for accuracy-first betting.

    When SP ∈ [1.3, 1.6], expands alignment checklist, implied vs model prob,
    score headline, and stake guidance — the primary focus band for hit rate.
    """
    info = pred.get("accuracy_pick") or evaluate_accuracy_pick(pred)
    jc = actionable_jingcai_pick(pred)
    pick_cn = final_recommendation_cn(pred)
    row = pred.get("predict_row") or {}
    sp = info.get("jingcai_sp") or resolve_jingcai_sp(pred)
    sweet = sp_in_sweet_spot(sp)
    lo = getattr(app_cfg, "ACCURACY_SP_MIN", 1.30)
    hi = getattr(app_cfg, "ACCURACY_SP_MAX", 1.60)

    if pick_cn in SKIP_PICKS or not jc:
        return {
            "ok": False,
            "reason": "不可购或观望",
            "sweet_spot": sweet,
            "sp": sp,
            "sp_target_min": lo,
            "sp_target_max": hi,
        }

    pick_key = jc.get("pick_key") or "skip"
    from jingcai_pick import KEY_FROM_SP_CN

    ref_cn = (
        pred.get("reference_result_1x2_cn")
        or row.get("赛果预测")
        or pred.get("match_result_1x2_cn")
        or ""
    ).strip()
    open_cn = (pred.get("open_result_1x2_cn") or row.get("初盘倾向") or "").strip()
    ref_key = KEY_FROM_SP_CN.get(ref_cn, "")
    open_key = KEY_FROM_SP_CN.get(open_cn, "")
    aligned_ref = not ref_key or ref_key == pick_key
    aligned_open = not open_key or open_key == pick_key

    conf = (row.get("置信度") or pred.get("confidence_cn") or "").strip()
    tags = set(pred.get("alert_tags") or [])
    div = pred.get("jingcai_divergence") or {}
    ctrl = pred.get("control_level_cn") or ""
    risk = pred.get("risk_level_cn") or ""
    buy_tier = pred.get("buy_tier") or ""
    grade = info.get("accuracy_grade") or "慎跟"

    sp_implied_pct = round(100.0 / sp, 1) if sp and sp > 0 else None
    model_pct = _model_prob_pct(pred, pick_key)
    prob_gap = None
    if sp_implied_pct is not None and model_pct is not None:
        prob_gap = round(model_pct - sp_implied_pct, 1)

    checklist: list[dict[str, Any]] = [
        _check("竞彩可购", True, pick_cn),
        _check("高置信", conf == "高", conf or "—"),
        _check("参考一致", aligned_ref, ref_cn or "—"),
        _check("初盘一致", aligned_open, open_cn or "—"),
        _check("无欧亚分歧", not (tags & DIVERGENCE_TAGS), "；".join(sorted(tags & DIVERGENCE_TAGS)) or "通过"),
        _check(
            "无竞彩分歧",
            not (isinstance(div, dict) and div.get("divergence")),
            (div.get("summary") if isinstance(div, dict) else None) or "通过",
        ),
        _check("控盘可控", ctrl != "高", f"控盘{ctrl or '—'}"),
        _check("样本充足", not pred.get("insufficient_data"), "样本不足" if pred.get("insufficient_data") else "通过"),
        _check(f"SP 甜区 {lo}–{hi}", sweet, f"SP {sp}" if sp else "—"),
    ]
    passed = sum(1 for c in checklist if c.get("ok"))
    total = len(checklist)

    sr = pred.get("score_recommend") or {}
    if score_prediction_enabled():
        score_headline = sr.get("headline") or row.get("推荐比分") or "—"
    else:
        score_headline = "—"

    if sweet:
        band = "in_sweet"
        band_headline = f"SP {sp} · 稳胆甜区 {lo}–{hi}"
        band_note = (
            "目标区间：热门选项但不过热，竞彩 SP 隐含胜率约 "
            f"{sp_implied_pct}%——适合重正确率单关；回报低于超低赔，但模型与盘口共识更集中。"
        )
    elif sp is not None and sp < lo:
        band = "below_sweet"
        band_headline = f"SP {sp} · 低于甜区（更稳、回报更低）"
        band_note = (
            f"SP 低于 {lo}，命中倾向更高但返还有限；若只追求正确率可跟，"
            f"甜区 {lo}–{hi} 场次请优先看主页「SP 甜区」列表。"
        )
    elif sp is not None and sp > hi:
        band = "above_sweet"
        band_headline = f"SP {sp} · 高于甜区（回报升、不确定性升）"
        band_note = (
            f"SP 高于 {hi}，正确率与回报难兼顾；本场仍给对照清单，"
            f"单关/串关请优先筛选 SP {lo}–{hi} 且评级「稳胆甜区」的场次。"
        )
    else:
        band = "unknown"
        band_headline = "SP 未就绪"
        band_note = "暂无竞彩 SP，待 poll 更新后再做甜区分析。"

    if grade == "稳胆甜区":
        verdict = "优先跟单"
        stake_hint = "甜区 + 高置信 + 方向一致 → 可单关；串关优先与同级场次组 2 串 1。"
    elif grade == "稳胆":
        verdict = "可跟单关"
        stake_hint = "重正确率可单关；非甜区 SP 时串关降档或跳过。"
    elif grade == "可跟":
        verdict = "小注试探"
        stake_hint = "存在中置信或轻微风险项，建议小注单关，不建议进串。"
    else:
        verdict = "建议跳过"
        stake_hint = "分歧/样本/SP 有一项不达标，本场不作为稳胆候选。"

    if prob_gap is not None:
        if prob_gap >= 5:
            edge_note = f"模型公平概率 {model_pct}% 高于 SP 隐含 {sp_implied_pct}%（+{prob_gap}pp），方向有边际支撑。"
        elif prob_gap <= -5:
            edge_note = f"SP 隐含 {sp_implied_pct}% 高于模型 {model_pct}%（{prob_gap}pp），热门略偏贵，仍看对齐项是否全绿。"
        else:
            edge_note = f"模型 {model_pct}% vs SP 隐含 {sp_implied_pct}%，差距 {prob_gap:+.1f}pp，属合理区间。"
    elif sp_implied_pct is not None:
        edge_note = f"SP 隐含胜率约 {sp_implied_pct}%；暂无欧赔去水概率对照。"
    else:
        edge_note = "—"

    summary_parts = [band_headline, f"评级 {grade}", f"清单 {passed}/{total}"]
    if sweet and grade in ("稳胆甜区", "稳胆"):
        summary_parts.append("甜区重点场次")

    return {
        "ok": True,
        "sweet_spot": sweet,
        "sp": sp,
        "sp_target_min": lo,
        "sp_target_max": hi,
        "sp_implied_pct": sp_implied_pct,
        "model_prob_pct": model_pct,
        "prob_gap_pct": prob_gap,
        "pick_cn": pick_cn,
        "pick_key": pick_key,
        "accuracy_grade": grade,
        "accuracy_score": info.get("accuracy_score"),
        "buy_tier": buy_tier,
        "band": band,
        "band_headline": band_headline,
        "band_note": band_note,
        "edge_note": edge_note,
        "checklist": checklist,
        "checklist_passed": passed,
        "checklist_total": total,
        "score_headline": score_headline,
        "score_pick_1x2_cn": sr.get("pick_1x2_cn") or ref_cn or "—",
        "verdict": verdict,
        "stake_hint": stake_hint,
        "reasons": info.get("accuracy_reason") or "—",
        "summary": " · ".join(summary_parts),
        "confidence_cn": conf,
        "reference_cn": ref_cn or "—",
        "open_cn": open_cn or "—",
    }


def _check(label: str, ok: bool, detail: str) -> dict[str, Any]:
    return {"label": label, "ok": bool(ok), "detail": detail or "—"}


def attach_accuracy_pick(pred: dict) -> dict:
    info = evaluate_accuracy_pick(pred)
    pred["accuracy_pick"] = info
    pred["accuracy_grade"] = info["accuracy_grade"]
    pred["accuracy_grade_cn"] = info["accuracy_grade_cn"]
    pred["sweet_spot"] = info["sweet_spot"]
    if info.get("jingcai_sp") is not None:
        pred["accuracy_jingcai_sp"] = info["jingcai_sp"]

    try:
        pred["sweet_spot_analysis"] = build_sweet_spot_analysis(pred)
    except Exception:
        pred["sweet_spot_analysis"] = {"ok": False, "reason": "分析失败"}

    row = dict(pred.get("predict_row") or {})
    row["稳胆评级"] = info["accuracy_grade_cn"]
    if info.get("jingcai_sp") is not None:
        row["稳胆SP"] = info["jingcai_sp"]
    pred["predict_row"] = row
    return pred


def filter_sweet_spot_matches(matches: list[dict]) -> list[dict]:
    """Matches with 稳胆甜区 or sweet_spot SP in range."""
    out = []
    for m in matches:
        info = m.get("accuracy_pick") or evaluate_accuracy_pick(m)
        if info.get("sweet_spot") and info.get("accuracy_grade") in ("稳胆甜区", "稳胆", "可跟"):
            out.append(m)
    return out
