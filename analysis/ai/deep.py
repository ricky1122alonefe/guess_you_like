"""Second-pass deep AI analysis built on prior first-pass AI results.

核心职责：
    - 基于首轮 AI 分析（`analysis/ai/predict.py` 输出）做二次深度研判。
    - 聚合历史预测、赔率变化、规则引擎基线，生成更完整的结构化报告。
    - 对同一场比赛做并发互斥，防止用户重复点击导致多次 API 调用。

对外入口：
    - `run_deep_match_analysis(...)`: 执行完整深度分析并写入时间线。
    - `build_deep_analysis_bundle(...)`: 仅构造输入 bundle，可用于调试 prompt。
    - `has_prior_ai_analysis(...)`: 判断是否存在可用于深研的首轮 AI 结果。

注意：
    - 本模块不直接做首轮 AI 推理；如果缺少首轮结果会明确报错。
    - 锁表 `_deep_locks` 会限制最大条目数，避免长期运行后内存无限增长。
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from ai_profiles import _deepseek_profile
from ai_prompt import (
    DEEP_ANALYSIS_SYSTEM_PROMPT,
    _compact_prior_analysis,
    build_deep_analysis_user_prompt,
    parse_deep_analysis_json,
)
from deepseek_client import DeepSeekError, chat
from jingcai_pick import final_recommendation_cn
from match_timeline import append_deep_analysis, load_match_index
from time_utils import now_beijing_str

log = logging.getLogger(__name__)

# 比赛级互斥锁：防止同一 fixture 被同时触发多次深度分析。
# 考虑到 Web 服务长期运行，锁表会限制容量并在超限时做清理。
_deep_locks: dict[str, threading.Lock] = {}
_deep_locks_guard = threading.Lock()
_MAX_DEEP_LOCKS = 256


def _lock_for_deep(fixture_id: str) -> threading.Lock:
    """获取/创建指定比赛的深度分析锁，并做简单的 LRU 式清理。"""
    with _deep_locks_guard:
        # 简单 LRU 清理：当锁表过大时，移除当前未被持有的旧锁。
        if len(_deep_locks) >= _MAX_DEEP_LOCKS and fixture_id not in _deep_locks:
            still_locked: list[str] = []
            for fid, lock in _deep_locks.items():
                if lock.locked():
                    still_locked.append(fid)
            _deep_locks.clear()
            for fid in still_locked[:_MAX_DEEP_LOCKS // 2]:
                _deep_locks[fid] = threading.Lock()

        if fixture_id not in _deep_locks:
            _deep_locks[fixture_id] = threading.Lock()
        return _deep_locks[fixture_id]


def _pred_has_ai(pred: dict | None) -> bool:
    if not pred:
        return False
    if pred.get("ai_analyses"):
        return True
    src = pred.get("recommendation_source") or ""
    return "ai" in src


def load_richest_prediction(output_root: str | Path, fixture_id: str) -> dict | None:
    """Prefer latest.json entry with AI; else newest AI run from runs/."""
    return _richest_prediction(Path(output_root), str(fixture_id))


def _timeline_has_ai(index: dict | None) -> bool:
    if not index:
        return False
    for pt in index.get("timeline") or []:
        pick = pt.get("pick") or {}
        if pick.get("ai_analyses"):
            return True
        src = pick.get("recommendation_source") or ""
        if "ai" in src:
            return True
    return False


def has_prior_ai_analysis(
    prediction: dict | None,
    ai_records: list[dict] | None = None,
    *,
    output_root: str | Path | None = None,
    fixture_id: str | None = None,
    index: dict | None = None,
) -> bool:
    if _pred_has_ai(prediction):
        return True
    for rec in ai_records or []:
        if rec.get("analyses"):
            return True
    if _timeline_has_ai(index):
        return True
    if output_root and fixture_id:
        fid = str(fixture_id)
        if _load_pred_from_runs(Path(output_root), fid):
            return True
        if index is None:
            idx = load_match_index(output_root, fid)
            if _timeline_has_ai(idx):
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
    temperature: float = 0.35,
    max_tokens: int = 4096,
) -> dict[str, Any]:
    """执行基于首轮 AI 输出的二次深度分析。

    流程：
        1. 获取比赛级互斥锁，避免并发重复执行。
        2. 构造分析输入 bundle（历史预测 + 赔率变化 + 规则基线）。
        3. 调用 LLM 生成深度研判报告。
        4. 解析结构化 JSON 并写入比赛时间线。

    Args:
        output_root: 输出目录根路径。
        fixture_id: 比赛唯一标识。
        prediction: 可选的预测字典；不传时会从 `latest.json` / `runs/` 自动查找。
        index: 可选的比赛时间线索引。
        ai_records: 可选的 AI 分析记录列表。
        temperature: LLM 温度，默认 0.35（兼顾稳定与创造性）。
        max_tokens: 最大输出 token 数。

    Returns:
        包含 `analysis`、`run_id`、`ai_model` 等字段的记录字典。

    Raises:
        RuntimeError: 缺少首轮 AI 数据、API 密钥未配置或正在并发执行。
        DeepSeekError: 大模型 API 调用失败。
        ValueError: 返回内容无法解析为有效 JSON。
    """
    fid = str(fixture_id)
    lock = _lock_for_deep(fid)
    acquired = lock.acquire(blocking=False)
    if not acquired:
        raise RuntimeError(f"比赛 {fid} 的 AI 分析正在进行中，请稍候")

    root = Path(output_root)
    run_id = now_beijing_str("%Y-%m-%d_%H%M") + f"_deep_{fid}"
    try:
        # 1. 构造分析输入：优先用传入数据，否则从磁盘恢复最丰富的预测。
        bundle = build_deep_analysis_bundle(
            root, fid, prediction=prediction, index=index,
            ai_records=ai_records,
        )

        # 2. 解析模型配置并校验 API 密钥。
        profile = _deepseek_profile(ai_model)
        api_key = profile.resolve_api_key()
        if not api_key:
            raise RuntimeError("未配置 DEEPSEEK_API_KEY，无法进行深度分析")

        chat_kwargs: dict[str, Any] = {
            "base_url": ai_base_url or profile.base_url,
            "api_key": api_key,
        }

        # 3. 调用大模型生成深度研判。
        log.info("深度 AI 分析开始 fid=%s model=%s match=%s", fid, profile.model, bundle.get("match"))
        content = chat(
            [
                {"role": "system", "content": DEEP_ANALYSIS_SYSTEM_PROMPT},
                {"role": "user", "content": build_deep_analysis_user_prompt(bundle)},
            ],
            model=profile.model,
            temperature=temperature,
            max_tokens=max_tokens,
            **chat_kwargs,
        )

        # 4. 解析并持久化结果。
        try:
            analysis = parse_deep_analysis_json(content)
        except (json.JSONDecodeError, ValueError) as exc:
            log.warning("深度分析 JSON 解析失败 fid=%s: %s", fid, exc)
            raise ValueError(f"深度分析结果解析失败：{exc}") from exc

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
    except DeepSeekError:
        # 向上抛出原始异常，保留调用栈与状态码信息。
        log.exception("深度 AI API 调用失败 fid=%s", fid)
        raise
    finally:
        # 只有成功获取锁才释放，避免 release 未 acquired 的锁报错。
        if acquired:
            lock.release()
