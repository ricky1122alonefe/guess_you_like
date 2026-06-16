"""Second-pass deep AI analysis built on prior first-pass AI results."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ai_profiles import _deepseek_profile
from ai_prompt import (
    DEEP_ANALYSIS_SYSTEM_PROMPT,
    _compact_prior_analysis,
    build_deep_analysis_user_prompt,
    parse_deep_analysis_json,
)
from deepseek_client import chat
from jingcai_pick import final_recommendation_cn
from match_timeline import append_deep_analysis, load_match_index
from time_utils import now_beijing_str

log = logging.getLogger(__name__)

def _pred_has_ai(pred: dict | None) -> bool:
    if not pred:
        return False
    if pred.get("ai_analyses"):
        return True
    src = pred.get("recommendation_source") or ""
    return "ai" in src


def has_prior_ai_analysis(
    prediction: dict | None,
    ai_records: list[dict] | None = None,
) -> bool:
    if _pred_has_ai(prediction):
        return True
    for rec in ai_records or []:
        if rec.get("analyses"):
            return True
    return False


def _load_pred_from_runs(root: Path, fixture_id: str) -> dict | None:
    runs_dir = root / "runs"
    if not runs_dir.is_dir():
        return None
    fid = str(fixture_id)
    for rf in sorted(runs_dir.glob("*/predictions.json"), reverse=True):
        try:
            data = json.loads(rf.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for pred in data.get("matches") or []:
            if str(pred.get("fixture_id")) != fid:
                continue
            if _pred_has_ai(pred):
                return pred
    return None


def _load_latest_pred(root: Path, fixture_id: str) -> dict | None:
    path = root / "latest.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    fid = str(fixture_id)
    for m in data.get("matches") or []:
        if str(m.get("fixture_id")) == fid:
            return m
    return None


def _richest_prediction(root: Path, fixture_id: str) -> dict | None:
    pred = _load_latest_pred(root, fixture_id)
    if _pred_has_ai(pred):
        return pred
    richer = _load_pred_from_runs(root, fixture_id)
    return richer or pred


def _collect_prior_analyses(pred: dict | None) -> list[dict[str, Any]]:
    if not pred:
        return []
    analyses = pred.get("ai_analyses") or {}
    if analyses:
        return [
            _compact_prior_analysis(p, label=p.get("ai_provider_label") or pid)
            for pid, p in analyses.items()
        ]
    if _pred_has_ai(pred):
        return [_compact_prior_analysis(pred)]
    return []


def _build_match_context(
    pred: dict | None,
    index: dict | None,
) -> dict[str, Any]:
    ctx: dict[str, Any] = {
        "match": (pred or {}).get("match") or (index or {}).get("match_name") or "",
        "fixture_id": (pred or {}).get("fixture_id") or (index or {}).get("fixture_id"),
    }
    if pred:
        ctx["odds_snapshot"] = pred.get("odds_snapshot")
        ctx["eu_implied"] = pred.get("eu_implied")
        ctx["jingcai_snapshot"] = pred.get("jingcai_snapshot")
        ctx["jingcai_pick_info"] = pred.get("jingcai_pick_info")
        ctx["control_level_cn"] = pred.get("control_level_cn")
        ctx["pattern_reference_cn"] = pred.get("pattern_reference_cn")
        ctx["open_probability_summary"] = pred.get("open_probability_summary")
        ctx["funds_interpretation"] = (pred.get("funds_interpretation") or "")[:800]
        row = pred.get("predict_row") or {}
        ctx["rule_engine_pick"] = final_recommendation_cn(pred) if not _pred_has_ai(pred) else row.get("竞彩推荐")

    timeline = (index or {}).get("timeline") or []
    if timeline:
        last = timeline[-1]
        ctx["latest_odds"] = last.get("odds")
        ctx["latest_pick"] = last.get("pick")
        ctx["latest_ts"] = last.get("ts")

    changes = (index or {}).get("changes") or []
    if changes:
        ctx["recent_changes"] = [
            {
                "ts": c.get("ts"),
                "field": c.get("field"),
                "from": c.get("from"),
                "to": c.get("to"),
            }
            for c in changes[-8:]
        ]
    return ctx


def _build_rule_baseline(pred: dict | None) -> dict[str, Any]:
    ref = (pred or {}).get("reference_baseline")
    if ref:
        return {
            "result_1x2_cn": ref.get("result_1x2_cn"),
            "likely_scores": ref.get("likely_scores_detail") or ref.get("likely_scores"),
            "asian_handicap_cn": ref.get("asian_handicap_cn"),
            "over_under_cn": ref.get("over_under_cn"),
            "confidence_cn": ref.get("confidence_cn"),
            "open_probability_summary": ref.get("open_probability_summary"),
        }
    if pred and not _pred_has_ai(pred):
        row = pred.get("predict_row") or {}
        return {
            "result_1x2_cn": row.get("胜平负") or pred.get("result_1x2_cn"),
            "likely_scores": row.get("推荐比分"),
            "asian_handicap_cn": row.get("亚盘") or pred.get("asian_handicap_cn"),
            "over_under_cn": row.get("大小球") or pred.get("over_under_cn"),
            "confidence_cn": row.get("置信度") or pred.get("confidence_cn"),
            "open_probability_summary": pred.get("open_probability_summary"),
        }
    return {}


def _collect_prior_from_ai_records(ai_records: list[dict] | None) -> list[dict[str, Any]]:
    if not ai_records:
        return []
    latest = ai_records[0]
    analyses = latest.get("analyses") or {}
    out = []
    for pid, a in analyses.items():
        out.append({
            "label": a.get("label") or pid,
            "jingcai_pick": a.get("result_1x2_cn"),
            "likely_scores": a.get("likely_scores"),
            "asian_handicap_cn": a.get("asian_handicap_cn"),
            "confidence_cn": a.get("confidence_cn"),
            "actuary_reasoning": a.get("actuary_reasoning") or "",
            "note": "来自 AI 记录摘要（完整论证请重新跑首轮 AI）",
        })
    return out


def build_deep_analysis_bundle(
    output_root: str | Path,
    fixture_id: str,
    *,
    prediction: dict | None = None,
    index: dict | None = None,
    ai_records: list[dict] | None = None,
) -> dict[str, Any]:
    root = Path(output_root)
    fid = str(fixture_id)
    pred = prediction or _richest_prediction(root, fid)
    if pred and not _pred_has_ai(pred):
        richer = _load_pred_from_runs(root, fid)
        if richer:
            pred = richer
    idx = index or load_match_index(root, fid) or {}

    prior = _collect_prior_analyses(pred)
    if not prior:
        prior = _collect_prior_from_ai_records(ai_records)
    if not prior:
        raise RuntimeError("暂无首轮 AI 分析数据，请先点击「AI 推荐本场」")

    return {
        "fixture_id": fid,
        "match": pred.get("match") if pred else idx.get("match_name"),
        "prior_analyses": prior,
        "match_context": _build_match_context(pred, idx),
        "rule_baseline": _build_rule_baseline(pred),
    }


def run_deep_match_analysis(
    output_root: str | Path,
    fixture_id: str,
    *,
    ai_model: str = "deepseek-chat",
    ai_base_url: str | None = None,
    prediction: dict | None = None,
    index: dict | None = None,
    ai_records: list[dict] | None = None,
) -> dict[str, Any]:
    """Run second-pass deep analysis using prior AI output."""
    from hourly_pipeline import _lock_for_fixture

    fid = str(fixture_id)
    lock = _lock_for_fixture(fid)
    if not lock.acquire(blocking=False):
        raise RuntimeError(f"比赛 {fid} 的 AI 分析正在进行中，请稍候")

    root = Path(output_root)
    run_id = now_beijing_str("%Y-%m-%d_%H%M") + f"_deep_{fid}"
    try:
        bundle = build_deep_analysis_bundle(
            root, fid, prediction=prediction, index=index,
            ai_records=ai_records,
        )
        profile = _deepseek_profile(ai_model)
        api_key = profile.resolve_api_key()
        if not api_key:
            raise RuntimeError("未配置 DEEPSEEK_API_KEY，无法进行深度分析")

        chat_kwargs: dict[str, Any] = {"base_url": ai_base_url or profile.base_url, "api_key": api_key}
        log.info("深度 AI 分析 fid=%s (%s)", fid, bundle.get("match"))
        content = chat(
            [
                {"role": "system", "content": DEEP_ANALYSIS_SYSTEM_PROMPT},
                {"role": "user", "content": build_deep_analysis_user_prompt(bundle)},
            ],
            model=profile.model,
            temperature=0.35,
            max_tokens=4096,
            **chat_kwargs,
        )
        analysis = parse_deep_analysis_json(content)
        record = {
            "ts": now_beijing_str(),
            "run_id": run_id,
            "manual": True,
            "ai_model": profile.model,
            "ai_provider_label": "DeepSeek 深度研判",
            "prior_model_count": len(bundle.get("prior_analyses") or []),
            "analysis": analysis,
        }
        append_deep_analysis(root, fid, record)
        log.info(
            "深度 AI 完成 %s → %s",
            bundle.get("match"), analysis.get("headline"),
        )
        return record
    finally:
        lock.release()
