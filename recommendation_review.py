"""Recommendation vs actual result — backtest rows from settled archives."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from match_settlement import load_settled_map
from prediction_archive import load_best_prediction
from time_utils import now_beijing_str
from worldcup_analytics import compute_accuracy_report

log = logging.getLogger(__name__)

SKIP_PICKS = frozenset({"—", "观望", "", None, "暂无竞彩"})


def _compare_summary(*, pick_cn: str, result_cn: str, hit: bool | None) -> str:
    pick = (pick_cn or "").strip()
    actual = (result_cn or "").strip()
    if not pick or pick in SKIP_PICKS:
        return "—"
    if hit is True:
        return f"推{pick} · 开{actual} ✓"
    if hit is False:
        return f"推{pick} → 开{actual} ✗"
    if actual:
        return f"推{pick} · 开{actual}"
    return f"推{pick}"


def _external_fixture_id(settled: dict) -> str:
    """Prefer 500 external id over internal DB fixture id."""
    return str(settled.get("external_id") or settled.get("fixture_id") or "")


def _row_from_settled(settled: dict, *, output_root: Path) -> dict[str, Any]:
    payload = settled.get("payload") or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = {}
    pred_snap = payload.get("prediction") or {}
    fid = _external_fixture_id(settled)

    full: dict | None = None
    if fid:
        try:
            full = load_best_prediction(output_root, fid, kickoff_at=settled.get("kickoff_at"))
        except Exception as exc:
            log.debug("归档预测读取失败 %s: %s", fid, exc)

    pred = full or {}
    row = pred.get("predict_row") or {}
    pick_jc = settled.get("pick_jingcai_cn") or pred_snap.get("pick_jingcai_cn") or row.get("竞彩推荐")
    result_cn = settled.get("result_1x2_cn") or "—"

    rec: dict[str, Any] = {
        "fixture_id": fid,
        "match_name": settled.get("match_name") or pred.get("match") or row.get("比赛") or fid,
        "kickoff_at": settled.get("kickoff_at"),
        "settled_at": settled.get("settled_at"),
        "score_text": settled.get("score_text"),
        "result_1x2": settled.get("result_1x2"),
        "result_1x2_cn": result_cn,
        "pick_jingcai_cn": pick_jc,
        "pick_1x2_cn": settled.get("pick_1x2_cn") or pred_snap.get("pick_1x2_cn") or row.get("胜平负"),
        "reference_result_1x2_cn": (
            pred.get("reference_result_1x2_cn") or row.get("赛果预测") or pred_snap.get("reference_result_1x2_cn")
        ),
        "open_result_1x2_cn": pred.get("open_result_1x2_cn") or row.get("初盘倾向"),
        "recommended_scores": (
            None
            if not __import__("product_focus").score_prediction_enabled()
            else (settled.get("recommended_scores") or pred_snap.get("recommended_scores") or row.get("推荐比分"))
        ),
        "asian_handicap_cn": (
            settled.get("pick_ah_cn") or pred_snap.get("asian_handicap_cn") or row.get("亚盘") or pred.get("asian_handicap_cn")
        ),
        "confidence_cn": pred_snap.get("confidence_cn") or row.get("置信度") or pred.get("confidence_cn"),
        "recommendation_source": (
            pred_snap.get("recommendation_source")
            or payload.get("recommendation_source")
            or pred.get("recommendation_source")
        ),
        "run_id": payload.get("run_id") or pred_snap.get("run_id") or pred.get("run_id"),
        "hit_1x2": settled.get("hit_1x2"),
        "hit_score": settled.get("hit_score"),
        "hit_ah": settled.get("hit_ah"),
        "ah_settlement": settled.get("ah_settlement"),
        "compare_summary": _compare_summary(
            pick_cn=str(pick_jc or ""),
            result_cn=str(result_cn),
            hit=settled.get("hit_1x2"),
        ),
    }

    ledger_row = {
        **rec,
        "pick_jingcai_cn": pick_jc,
        "confidence_cn": rec["confidence_cn"],
        "payload": payload,
    }
    if full:
        if not full.get("buy_tier"):
            from analysis.rules.output import attach_post_recommendation

            attach_post_recommendation(full)
        rec["buy_tier"] = full.get("buy_tier")
        rec["buy_tier_cn"] = full.get("buy_tier_cn") or (full.get("predict_row") or {}).get("购买档位")
        rec["buy_tier_reason"] = full.get("buy_tier_reason")
        rec["parlay_eligible"] = full.get("parlay_eligible")
    else:
        from jingcai_tier import resolve_record_buy_tier

        resolve_record_buy_tier(ledger_row, output_root=output_root)
        rec["buy_tier"] = ledger_row.get("buy_tier")
        rec["buy_tier_cn"] = ledger_row.get("buy_tier_cn")
        rec["buy_tier_reason"] = ledger_row.get("buy_tier_reason")
        rec["parlay_eligible"] = ledger_row.get("parlay_eligible")
    return rec


def build_recommendation_review(output_root: str | Path) -> dict[str, Any]:
    """All settled matches: recommendation vs actual, with tier accuracy."""
    root = Path(output_root)
    settled_map = load_settled_map(root)
    records: list[dict[str, Any]] = []
    for fid, settled in settled_map.items():
        if not settled.get("score_text"):
            continue
        try:
            records.append(_row_from_settled(settled, output_root=root))
        except Exception as exc:
            log.warning("复盘行构建失败 %s: %s", fid, exc)

    records.sort(key=lambda r: r.get("kickoff_at") or "", reverse=True)
    judged = [r for r in records if r.get("pick_jingcai_cn") and r["pick_jingcai_cn"] not in SKIP_PICKS]
    accuracy = compute_accuracy_report(records)

    misses = [r for r in judged if r.get("hit_1x2") is False]
    miss_patterns: dict[str, int] = {}
    for r in misses:
        pick = r.get("pick_jingcai_cn") or "?"
        actual = r.get("result_1x2_cn") or "?"
        key = f"{pick}→{actual}"
        miss_patterns[key] = miss_patterns.get(key, 0) + 1
    top_misses = sorted(miss_patterns.items(), key=lambda x: -x[1])[:8]

    return {
        "updated_at": now_beijing_str(),
        "total_settled": len(records),
        "with_recommendation": len(judged),
        "accuracy": accuracy,
        "miss_patterns": [{"pattern": k, "count": v} for k, v in top_misses],
        "records": records,
    }
