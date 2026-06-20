"""Serialize recommendations and CLI print helpers."""

from __future__ import annotations

from ai_schema import ACTUARY_JSON_KEYS, ANALYSIS_JSON_KEYS, RECOMMENDATION_KEYS
from analysis.rules.types import AH_CN, CONFIDENCE_CN, OU_CN, Recommendation
from match import SCORE_POOL_TOP_N


def recommendation_to_baseline(rec: Recommendation) -> dict:
    """Rule-based picks used as the single source of truth for final output."""
    return {
        "result_1x2": rec.result_1x2,
        "result_1x2_cn": rec.result_1x2_cn,
        "likely_scores": rec.likely_scores,
        "likely_scores_detail": rec.likely_scores_detail,
        "asian_handicap_pick": rec.asian_handicap_pick,
        "asian_handicap_cn": rec.asian_handicap_cn,
        "asian_handicap_reason": rec.asian_handicap_reason,
        "over_under_hint": rec.over_under_hint,
        "over_under_cn": rec.over_under_cn,
        "confidence": rec.confidence,
        "confidence_cn": rec.confidence_cn,
        "summary": rec.summary,
        "sample_count": rec.sample_count,
        "eu_sample_count": rec.eu_sample_count,
        "insufficient_data": rec.insufficient_data,
        "market_notes": rec.market_notes or [],
        "open_result_1x2_cn": rec.open_result_1x2_cn,
        "open_probability_summary": rec.open_probability_summary,
        "pattern_reference_cn": rec.pattern_reference_cn,
        "control_level_cn": rec.control_level_cn,
        "control_trajectory": rec.control_trajectory,
        "risk_level_cn": rec.risk_level_cn,
        "open_sample_count": rec.open_sample_count,
        "open_eu_sample_count": rec.open_eu_sample_count,
        "trap_notes": rec.trap_notes or [],
        "confidence_reason": rec.confidence_reason,
        "funds_interpretation": rec.funds_interpretation,
        "market_pattern_summary": rec.market_pattern_summary,
        "market_pattern_names": rec.market_pattern_names or [],
        "odds_blend_summary": rec.odds_blend_summary,
        "alert_tags": rec.alert_tags or [],
        "qualification_divergence": rec.qualification_divergence,
        "eu_ah_divergence_score": rec.eu_ah_divergence_score,
    }


def merge_expert_prediction(
    ai: dict,
    baseline: dict,
    match_name: str = "",
    *,
    evidence_brief: dict | None = None,
) -> dict:
    """AI expert picks are final; baseline is kept as reference_baseline."""
    out = dict(baseline)
    out["match"] = match_name or ai.get("match") or baseline.get("match") or ""
    out["reference_baseline"] = baseline

    for key in RECOMMENDATION_KEYS:
        if ai.get(key) is not None and ai.get(key) != "":
            out[key] = ai[key]

    for key in ACTUARY_JSON_KEYS:
        if ai.get(key) is not None and ai.get(key) != "":
            out[key] = ai[key]

    for key in ANALYSIS_JSON_KEYS:
        if ai.get(key):
            out[key] = ai[key]

    for key in (
        "jingcai_rq_pick", "jingcai_rq_pick_cn", "jingcai_rq_reason",
        "jingcai_pick", "jingcai_pick_cn", "jingcai_reason",
    ):
        if ai.get(key) is not None and ai.get(key) != "":
            out[key] = ai[key]

    if not out.get("analysis_basis") and evidence_brief:
        out["analysis_basis"] = evidence_brief.get("lines") or []

    ref_pick = baseline.get("result_1x2")
    ai_pick = out.get("result_1x2")
    out["recommendation_source"] = "ai_expert"
    out["differs_from_reference"] = bool(
        ref_pick and ai_pick and ref_pick != ai_pick
    )
    if out["differs_from_reference"]:
        out["reference_result_1x2_cn"] = baseline.get("result_1x2_cn")

    if not out.get("likely_scores_detail") and out.get("likely_scores"):
        out["likely_scores_detail"] = list(out["likely_scores"])

    if baseline.get("insufficient_data") or baseline.get("control_level_cn") == "高":
        if out.get("confidence") == "high" or out.get("confidence_cn") == "高":
            out["confidence"] = "low" if baseline.get("insufficient_data") else "medium"
            out["confidence_cn"] = CONFIDENCE_CN[out["confidence"]]
            out["confidence_level"] = out["confidence_cn"]
            note = "样本不足" if baseline.get("insufficient_data") else "高控盘"
            reason = out.get("confidence_reason") or out.get("actuary_reasoning") or ""
            out["confidence_reason"] = f"{note}，AI 高置信已自动降级" + (f"；{reason}" if reason else "")

    out["_baseline_locked"] = False
    if evidence_brief:
        out["evidence_brief"] = evidence_brief
    return out


def apply_baseline_to_prediction(
    prediction: dict,
    baseline: dict,
    match_name: str = "",
    *,
    evidence_brief: dict | None = None,
) -> dict:
    """Keep only AI analysis text; all picks come from rule-based baseline."""
    analysis_keys = ANALYSIS_JSON_KEYS
    out = dict(baseline)
    out["match"] = match_name or prediction.get("match") or ""
    for key in analysis_keys:
        if prediction.get(key):
            out[key] = prediction[key]
    basis = out.get("analysis_basis")
    if not basis and evidence_brief:
        out["analysis_basis"] = evidence_brief.get("lines") or []
    if evidence_brief:
        out["evidence_brief"] = evidence_brief
    out["_baseline_locked"] = True
    return out


def recommendation_from_dict(data: dict) -> Recommendation:
    return Recommendation(
        match=data.get("match", ""),
        result_1x2=data["result_1x2"],
        result_1x2_cn=data["result_1x2_cn"],
        likely_scores=data.get("likely_scores") or [],
        likely_scores_detail=data.get("likely_scores_detail") or [],
        asian_handicap_pick=data.get("asian_handicap_pick", "skip"),
        asian_handicap_cn=data.get("asian_handicap_cn", AH_CN["skip"]),
        asian_handicap_reason=data.get("asian_handicap_reason", ""),
        over_under_hint=data.get("over_under_hint", "neutral"),
        over_under_cn=data.get("over_under_cn", OU_CN["neutral"]),
        confidence=data.get("confidence", "low"),
        confidence_cn=data.get("confidence_cn", CONFIDENCE_CN["low"]),
        summary=data.get("summary", ""),
        sample_count=data.get("sample_count", 0),
        eu_sample_count=data.get("eu_sample_count", 0),
        insufficient_data=data.get("insufficient_data", False),
        market_notes=data.get("market_notes"),
        open_result_1x2_cn=data.get("open_result_1x2_cn", ""),
        open_probability_summary=data.get("open_probability_summary", ""),
        pattern_reference_cn=data.get("pattern_reference_cn", ""),
        control_level_cn=data.get("control_level_cn", ""),
        control_trajectory=data.get("control_trajectory", ""),
        risk_level_cn=data.get("risk_level_cn", ""),
        open_sample_count=data.get("open_sample_count", 0),
        open_eu_sample_count=data.get("open_eu_sample_count", 0),
        trap_notes=data.get("trap_notes"),
        confidence_reason=data.get("confidence_reason", ""),
        funds_interpretation=data.get("funds_interpretation", ""),
        market_pattern_summary=data.get("market_pattern_summary", ""),
        market_pattern_names=data.get("market_pattern_names"),
        odds_blend_summary=data.get("odds_blend_summary", ""),
        alert_tags=data.get("alert_tags"),
        qualification_divergence=data.get("qualification_divergence"),
        eu_ah_divergence_score=data.get("eu_ah_divergence_score"),
    )


def print_recommendation(rec: Recommendation, *, title_suffix: str = "最终推荐") -> None:
    print()
    print("=" * 44)
    print(f"  {rec.match}  ·  {title_suffix}")
    print("=" * 44)
    print()
    print(f"  【胜平负】{rec.result_1x2_cn}")
    if rec.open_probability_summary:
        print(f"  【初盘赛事概率】{rec.open_result_1x2_cn} ← {rec.open_probability_summary}")
    print(f"  【规律参考价值】{rec.pattern_reference_cn or '—'} | 控盘{rec.control_level_cn or '—'} | 风险{rec.risk_level_cn or '—'}")
    if rec.control_trajectory:
        print(f"  【变盘轨迹】{rec.control_trajectory}")
    if rec.likely_scores_detail:
        print(f"  【推荐比分】{'、'.join(rec.likely_scores_detail)}")
    elif rec.likely_scores:
        print(f"  【推荐比分】{'、'.join(rec.likely_scores)}")
    else:
        print("  【推荐比分】—")
    print(f"  【亚盘】{rec.asian_handicap_cn}")
    if rec.asian_handicap_pick != "skip":
        print(f"           {rec.asian_handicap_reason}")
    print(f"  【大小球】{rec.over_under_cn}")
    print(f"  【置信度】{rec.confidence_cn}", end="")
    if rec.confidence_reason:
        print(f"（{rec.confidence_reason}）")
    else:
        print()
    if rec.funds_interpretation:
        print(f"  【资金/诱盘解读】{rec.funds_interpretation}")
    if rec.market_pattern_summary or rec.market_pattern_names:
        print(f"  【盘赔套路】{rec.market_pattern_summary or '—'}")
        if rec.market_pattern_names:
            print(f"           识别：{'、'.join(rec.market_pattern_names)}")
    if rec.market_notes:
        print()
        print("  ▎机构风控与异动（非纯赛果判断）")
        for note in rec.market_notes:
            print(f"    · {note}")
    print()
    print(f"  {rec.summary}")
    print()
    print("-" * 44)
    print(f"  样本：初盘亚盘 {rec.open_sample_count} / 初盘欧赔 {rec.open_eu_sample_count} 场")
    print(f"        临盘亚盘 {rec.sample_count} / 临盘欧赔 {rec.eu_sample_count} 场")
    print(f"        比分统计基于最相似 Top {SCORE_POOL_TOP_N} 场加权")
    print("=" * 44)
    print()


def print_batch_summary(recs: list[Recommendation]) -> None:
    if len(recs) <= 1:
        return
    print()
    print("=" * 60)
    print("  批量汇总")
    print("=" * 60)
    for rec in recs:
        ah = rec.asian_handicap_cn if rec.asian_handicap_pick != "skip" else "观望"
        score_txt = "/".join(rec.likely_scores[:2]) if rec.likely_scores else "—"
        pick = rec.result_1x2_cn
        print(
            f"  {rec.match}: {pick} | "
            f"比分 {score_txt} | "
            f"亚盘 {ah} | {rec.over_under_cn} | 置信{rec.confidence_cn}"
        )
    print("=" * 60)
    print()


def _print_section(title: str, lines: list[str] | str | None) -> None:
    if not lines:
        return
    print(f"\n  ▎{title}")
    if isinstance(lines, str):
        print(f"    {lines}")
        return
    for line in lines:
        print(f"    · {line}")


def print_ai_recommendation(data: dict) -> None:
    """Print expert/AI recommendation plus analysis sections."""
    rec = recommendation_from_dict(data)
    source = data.get("recommendation_source", "ai_expert")
    title = "AI 精算师推荐" if source == "ai_expert" else "DeepSeek 深度分析"
    print_recommendation(rec, title_suffix=title)

    if data.get("differs_from_reference"):
        ref = data.get("reference_result_1x2_cn") or (
            (data.get("reference_baseline") or {}).get("result_1x2_cn")
        )
        if ref:
            print(f"  【规则引擎参考】{ref}（与精算师判断不同，见分析依据）")
            print()

    actuary = data.get("actuary_reasoning")
    if actuary or data.get("implied_probability"):
        print("  ▎精算师 EV 报告")
        imp = data.get("implied_probability")
        adj = data.get("adjusted_probability")
        if imp:
            print(f"    隐含概率：{imp}")
        if adj:
            print(f"    修正概率：{adj}")
        vb = data.get("value_bet")
        if vb is not None:
            print(f"    正期望值：{'是 ✓' if vb else '否 ✗'}")
        rec_txt = data.get("recommendation") or data.get("result_1x2_cn")
        conf = data.get("confidence_level") or data.get("confidence_cn")
        if rec_txt:
            print(f"    精算建议：{rec_txt}（置信 {conf or '—'}）")
        if actuary:
            print(f"    核心逻辑：{actuary}")
        print()

    basis = data.get("analysis_basis") or []
    if basis:
        print("  ▎分析依据（推荐结论数据链）")
        for i, line in enumerate(basis, 1):
            print(f"    {i}. {line}")
        print()

    print("  ▎历史解读（DeepSeek）")

    _print_section("历史样本概览", data.get("historical_overview"))
    _print_section("市场 vs 历史（核心对比）", data.get("market_vs_history_analysis"))
    _print_section("盘赔走势与风控解读", data.get("odds_movement_analysis"))
    _print_section("亚盘深度分析", data.get("asian_handicap_deep_dive"))
    _print_section("比分规律", data.get("score_pattern_analysis"))

    cases = data.get("historical_cases") or []
    if cases:
        print(f"\n  ▎典型历史场次（{len(cases)} 场）")
        for i, c in enumerate(cases, 1):
            if isinstance(c, dict):
                print(f"    {i}. [{c.get('date', '')}] {c.get('match', '')}")
                if c.get("lesson"):
                    print(f"       → {c['lesson']}")
            else:
                print(f"    {i}. {c}")

    _print_section("综合结论", data.get("final_verdict"))
    risks = data.get("key_risks") or []
    if risks:
        _print_section("风险提示", risks)
    print()
