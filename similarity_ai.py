"""AI analysis of historical similar-odds / handicap samples."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from jingcai_pick import final_recommendation_cn
from recommend import MIN_SAMPLES_FOR_PICK
from time_utils import now_beijing_str

log = logging.getLogger(__name__)

VALID_SOURCES = frozenset({"open_ah", "open_eu", "live_ah", "live_eu"})

SECTION_META: dict[str, dict[str, str]] = {
    "open_ah": {
        "title": "初盘亚盘相似",
        "compare": "当前初盘亚盘 vs 历史初盘亚盘",
        "dimension": "asian",
    },
    "open_eu": {
        "title": "初盘欧赔相似",
        "compare": "当前初盘欧赔 vs 历史初盘欧赔",
        "dimension": "european",
    },
    "live_ah": {
        "title": "实时亚盘 vs 历史终盘相似",
        "compare": "当前实时亚盘 vs 历史终盘/收盘亚盘",
        "dimension": "asian",
    },
    "live_eu": {
        "title": "实时欧赔 vs 历史终盘相似",
        "compare": "当前实时欧赔 vs 历史终盘/收盘欧赔",
        "dimension": "european",
    },
}

SYSTEM_PROMPT = """你是足球盘口「历史相似样本」分析师。用户会给你：
1) 当前比赛的盘口（初盘或实时，取决于 section）
2) 按盘口相似度筛出的历史样本统计（胜平负、上下盘赢盘率、Top比分、Top10明细）
3) 可选的规则引擎 baseline 推荐

你的任务：只基于这些相似样本和当前盘口，给出本场解读与推荐。不得编造伤停、阵容、新闻。

分析要点：
- 先判断样本量是否足够（≥100 场较可靠；30–99 场仅参考；<30 场应观望或降置信）
- 解读胜平负分布是否与当前盘口方向一致；若欧赔块无亚盘，不要强行推上下盘
- 若有上下盘统计，说明上盘/下盘谁更有历史支撑，并解释全赢/半赢/走水分布
- 结合 Top 比分与场均进球给出 2–3 个最可能比分
- 若 baseline 与样本方向冲突，必须说明以谁为主、为何

输出 JSON（字段都要填，无法判断时用「观望」）：
{
  "headline": "一句话结论",
  "result_pick_cn": "主胜|平局|客胜|观望",
  "result_pick_key": "home|draw|away|skip",
  "handicap_pick_cn": "上盘|下盘|观望",
  "handicap_pick_key": "home|away|skip",
  "likely_scores": "如 1-0、1-1",
  "confidence_cn": "高|中|低",
  "sample_reliability": "样本可靠性一句话",
  "summary": "2-4 句综合解读",
  "key_evidence": ["依据1", "依据2"],
  "risk": "最大风险",
  "vs_baseline": "与 baseline 一致或分歧说明",
  "action": "可执行建议（仓位/是否追让球）"
}"""


def _cache_path(output_root: str | Path, fixture_id: str, source: str) -> Path:
    safe_fid = "".join(ch for ch in str(fixture_id) if ch.isdigit() or ch in ("_", "-")) or "unknown"
    safe_src = source if source in VALID_SOURCES else "unknown"
    return Path(output_root) / "similarity_ai" / safe_fid / f"{safe_src}.json"


def load_cached_analysis(
    output_root: str | Path,
    fixture_id: str,
    source: str,
    *,
    ttl_sec: int = 7200,
) -> dict[str, Any] | None:
    path = _cache_path(output_root, fixture_id, source)
    if not path.is_file():
        return None
    if ttl_sec and time.time() - path.stat().st_mtime > ttl_sec:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not data.get("ok"):
        return None
    return data


def load_cached_analyses(output_root: str | Path, fixture_id: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for source in VALID_SOURCES:
        cached = load_cached_analysis(output_root, fixture_id, source)
        if cached:
            out[source] = cached
    return out


def _save_cache(output_root: str | Path, fixture_id: str, source: str, data: dict[str, Any]) -> None:
    path = _cache_path(output_root, fixture_id, source)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def get_similarity_block(pred: dict | None, source: str) -> dict | None:
    if not pred or source not in VALID_SOURCES:
        return None
    layer = "open" if source.startswith("open_") else "live"
    for block in (pred.get("similarity_analysis") or {}).get(layer) or []:
        if block.get("source") == source:
            return block
    return None


def _current_odds(pred: dict, source: str) -> dict[str, Any]:
    snap = pred.get("odds_snapshot") or {}
    if source.startswith("open_"):
        return {
            "asian_handicap": {
                "line": snap.get("ah_open_line"),
                "home_water": snap.get("ah_open_home_water"),
                "away_water": snap.get("ah_open_away_water"),
            },
            "european": {
                "home": snap.get("eu_open_home"),
                "draw": snap.get("eu_open_draw"),
                "away": snap.get("eu_open_away"),
            },
        }
    return {
        "asian_handicap": {
            "line": snap.get("ah_line"),
            "home_water": snap.get("ah_home_water"),
            "away_water": snap.get("ah_away_water"),
        },
        "european": {
            "home": snap.get("eu_home"),
            "draw": snap.get("eu_draw"),
            "away": snap.get("eu_away"),
        },
    }


def _compact_block(block: dict) -> dict[str, Any]:
    return {
        "title": block.get("title"),
        "count": block.get("count"),
        "rate_text": block.get("rate_text"),
        "home_win_rate": block.get("home_win_rate"),
        "draw_rate": block.get("draw_rate"),
        "away_win_rate": block.get("away_win_rate"),
        "ah_rate_text": block.get("ah_rate_text"),
        "ah_upper_win_rate": block.get("ah_upper_win_rate"),
        "ah_lower_win_rate": block.get("ah_lower_win_rate"),
        "ah_home_full_win": block.get("ah_home_full_win"),
        "ah_home_half_win": block.get("ah_home_half_win"),
        "ah_home_push": block.get("ah_home_push"),
        "ah_home_half_loss": block.get("ah_home_half_loss"),
        "ah_home_full_loss": block.get("ah_home_full_loss"),
        "avg_total_goals": block.get("avg_total_goals"),
        "top_scores": (block.get("top_scores") or [])[:8],
        "samples": (block.get("samples") or [])[:10],
    }


def _baseline_brief(pred: dict | None) -> dict[str, Any]:
    if not pred:
        return {}
    row = pred.get("predict_row") or {}
    return {
        "final_pick_cn": final_recommendation_cn(pred),
        "result_1x2_cn": pred.get("result_1x2_cn") or row.get("赛果预测"),
        "asian_handicap_cn": pred.get("asian_handicap_cn") or row.get("亚盘"),
        "likely_scores": pred.get("likely_scores") or row.get("推荐比分"),
        "confidence_cn": pred.get("confidence_cn") or row.get("置信度"),
        "summary": (pred.get("summary") or "")[:400],
    }


def build_similarity_ai_payload(
    pred: dict,
    source: str,
    *,
    match_name: str | None = None,
) -> dict[str, Any]:
    if source not in VALID_SOURCES:
        raise ValueError(f"未知 source: {source}")
    block = get_similarity_block(pred, source)
    if not block or not (block.get("count") or 0):
        raise ValueError("暂无足够相似样本，无法分析")

    meta = SECTION_META[source]
    sim_root = pred.get("similarity_analysis") or {}
    return {
        "generated_at": now_beijing_str(),
        "fixture_id": pred.get("fixture_id"),
        "match": match_name or pred.get("match"),
        "section": meta["title"],
        "source": source,
        "comparison": meta["compare"],
        "dimension": meta["dimension"],
        "min_samples_reliable": MIN_SAMPLES_FOR_PICK,
        "current_odds": _current_odds(pred, source),
        "sample_stats": _compact_block(block),
        "history_total": sim_root.get("history_total"),
        "auto_relaxed": sim_root.get("auto_relaxed"),
        "baseline_recommendation": _baseline_brief(pred),
        "instruction": (
            "请只基于 sample_stats 与 current_odds 做解读并给出推荐。"
            "样本 count 低于门槛时要降置信或观望。"
            "这是相似样本专项分析，不是全场新闻分析。"
        ),
    }


def analyze_similarity(
    output_root: str | Path,
    fixture_id: str,
    source: str,
    pred: dict,
    *,
    match_name: str | None = None,
    ai_model: str | None = None,
    ai_base_url: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    source = str(source or "").strip()
    if source not in VALID_SOURCES:
        raise ValueError(f"source 须为 {', '.join(sorted(VALID_SOURCES))}")

    if not force:
        cached = load_cached_analysis(output_root, fixture_id, source)
        if cached:
            return cached

    payload = build_similarity_ai_payload(pred, source, match_name=match_name)

    try:
        from ai_profiles import get_primary_profile
        from ai_prompt import _extract_json_text
        from deepseek_client import chat

        prof = get_primary_profile(ai_model, ai_base_url)
        api_key = prof.resolve_api_key()
        if not api_key:
            raise ValueError(f"未配置 {prof.api_key_env}")

        text = chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
            ],
            api_key=api_key,
            model=prof.model,
            base_url=prof.base_url,
            temperature=0.2,
            max_tokens=1600,
            timeout=120,
        )
        data = json.loads(_extract_json_text(text))
        if not isinstance(data, dict):
            raise ValueError("AI 返回非 JSON 对象")

        result = {
            "ok": True,
            "fixture_id": str(fixture_id),
            "source": source,
            "section": SECTION_META[source]["title"],
            "match": payload.get("match"),
            "sample_count": payload["sample_stats"].get("count"),
            "generated_at": now_beijing_str(),
            "ai_provider": prof.provider_id,
            "ai_provider_label": prof.label,
            **data,
        }
        _save_cache(output_root, fixture_id, source, result)
        return result
    except Exception as exc:
        log.exception("相似盘口 AI 分析失败 fid=%s source=%s", fixture_id, source)
        err = {
            "ok": False,
            "fixture_id": str(fixture_id),
            "source": source,
            "section": SECTION_META.get(source, {}).get("title"),
            "match": match_name or pred.get("match"),
            "generated_at": now_beijing_str(),
            "error": str(exc),
        }
        return err
