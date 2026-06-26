"""Recommendation vs actual result — backtest rows from settled archives."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from match_settlement import load_settled_map
from prediction_archive import load_best_prediction
from review_agent import build_review_agent_report
from time_utils import now_beijing_str
from worldcup_analytics import compute_accuracy_report
from user_final_picks import enrich_settled_with_user_pick, list_locked_picks, user_pick_accuracy

log = logging.getLogger(__name__)

SKIP_PICKS = frozenset({"—", "观望", "", None, "暂无竞彩"})

_RQ_PICK_RE = re.compile(r"让球\s*\(([+\-]?\d+)\)\s*(胜|平|负)")


def _review_tier_display(tier_cn: str | None) -> str:
    """Social-safe tier label for /review export."""
    cn = str(tier_cn or "").strip()
    if cn in ("可串", "可单关"):
        return "重点场次"
    if cn == "仅参考":
        return "观察参考"
    return cn or "—"


def _review_pick_display(pick_cn: str | None) -> str:
    """Convert handicap picks to natural goal-margin wording (no lottery terms)."""
    raw = str(pick_cn or "").strip()
    if not raw or raw in SKIP_PICKS:
        return raw or "—"
    m = _RQ_PICK_RE.search(raw)
    if not m:
        return raw
    h = int(m.group(1))
    side = m.group(2)
    n = abs(h)
    if side == "负":
        return f"客队净胜 {n} 球+"
    if side == "胜":
        if h >= 0:
            return f"客队净胜 {n} 球+"
        return f"主队净胜 {n} 球+"
    if side == "平":
        if h < 0:
            return f"主队净胜 {n} 球"
        return "平局方向"
    return raw


def _compare_summary(*, pick_cn: str, result_cn: str, hit: bool | None) -> str:
    pick = _review_pick_display(pick_cn)
    actual = (result_cn or "").strip()
    if not pick or pick in SKIP_PICKS:
        return "—"
    if hit is True:
        return f"预判{pick} · 实际{actual} ✓"
    if hit is False:
        return f"预判{pick} → 实际{actual} ✗"
    if actual:
        return f"预判{pick} · 实际{actual}"
    return f"预判{pick}"


def _pick_market(pick_cn: str | None, row: dict | None = None) -> str:
    pick = str(pick_cn or "")
    market = str((row or {}).get("竞彩玩法") or "")
    if "让球" in pick or "让球" in market:
        return "rqsp"
    if pick and pick not in SKIP_PICKS:
        return "sp"
    return "none"


def _handicap_from_pick(pick_cn: str | None) -> int | None:
    m = re.search(r"让球\(([+\-]?\d+)\)", str(pick_cn or ""))
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _hours_between_run_and_kickoff(run_id: str | None, kickoff_at: str | None) -> float | None:
    if not run_id or not kickoff_at or len(run_id) < 16:
        return None
    try:
        run_dt = datetime.strptime(run_id[:16], "%Y-%m-%d_%H%M")
        ko_dt = datetime.strptime(str(kickoff_at)[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    return round((ko_dt - run_dt).total_seconds() / 3600, 1)


def _error_review_item(r: dict) -> dict[str, Any]:
    """Explain why a missed recommendation was risky."""
    pick = r.get("pick_jingcai_cn") or "—"
    ref = r.get("reference_result_1x2_cn") or ""
    open_cn = r.get("open_result_1x2_cn") or ""
    market = r.get("jingcai_market") or _pick_market(pick)
    handicap = r.get("jingcai_handicap")
    if handicap is None:
        handicap = _handicap_from_pick(pick)
    lead_hours = _hours_between_run_and_kickoff(r.get("run_id"), r.get("kickoff_at"))

    reasons: list[str] = []
    actions: list[str] = []
    category = "方向判断失误"

    if market == "rqsp":
        category = "让球胜平负失误"
        reasons.append("只卖让球胜平负，推荐依赖净胜球判断，波动大于普通胜平负")
        actions.append("RQSP 不进 2 串 1；大让球默认观望")
        if handicap is not None and abs(int(handicap)) >= 2:
            reasons.append(f"大让球 {handicap:+d}，一球差就可能从让胜变让平/让负")
            actions.append("让球绝对值 >=2 需 AI/人工二次确认")
        if ref and ref not in pick:
            reasons.append(f"自然赛果参考为 {ref}，但竞彩让球方向为 {pick}")
            actions.append("让球方向与自然赛果参考分离时降级")

    if r.get("confidence_cn") == "低":
        reasons.append("低置信仍给出可买方向")
        actions.append("低置信不入串关，只能单场观察")

    if r.get("risk_level_cn") in ("显著升高", "升高"):
        reasons.append(f"风险等级 {r.get('risk_level_cn')}")
        actions.append("风险升高场次降档或跳过")

    if r.get("control_level_cn") == "高":
        reasons.append("高控盘场次临盘噪声大")
        actions.append("高控盘 + 非高置信直接观望")

    if r.get("buy_tier") in ("B", "C"):
        reasons.append(f"购买档位为 {r.get('buy_tier_cn') or r.get('buy_tier')}，不适合作为稳健串关")
        actions.append("daily picks 只允许 A 档 / parlay_eligible")

    guards = r.get("agent_hard_guards") or []
    if guards:
        category = "多 Agent 预警未充分执行"
        reasons.append("赛前多 Agent 已触发硬风险闸门：" + "；".join(str(x) for x in guards[:2]))
        actions.append("硬风险闸门触发时，总推荐必须降级为仅参考或观望")

    chief_buy = r.get("chief_buy_decision")
    if chief_buy and chief_buy not in ("A 可串", "可串", "A"):
        reasons.append(f"AI 总 Agent 当时已给出 {chief_buy}")
        actions.append("复盘时优先检查 daily picks 是否绕过了总 Agent 降级")

    if lead_hours is not None and lead_hours >= 3:
        reasons.append(f"推荐快照距开球约 {lead_hours:g} 小时，可能未吸收临盘变化")
        actions.append("开球前 3 小时内强制重算")

    if not reasons:
        if ref and ref != r.get("result_1x2_cn"):
            reasons.append(f"参考研判 {ref} 未打出")
        if open_cn and open_cn != r.get("result_1x2_cn"):
            reasons.append(f"初盘倾向 {open_cn} 未打出")
        if not reasons:
            reasons.append("常规方向判断失败，样本不足以解释")
        actions.append("累计同类样本后调整权重")

    # Preserve order while removing duplicates.
    dedup_actions = list(dict.fromkeys(actions))
    dedup_reasons = list(dict.fromkeys(reasons))
    return {
        "fixture_id": r.get("fixture_id"),
        "match_name": r.get("match_name"),
        "kickoff_at": r.get("kickoff_at"),
        "score_text": r.get("score_text"),
        "result_1x2_cn": r.get("result_1x2_cn"),
        "pick_jingcai_cn": pick,
        "buy_tier_cn": r.get("buy_tier_cn"),
        "confidence_cn": r.get("confidence_cn"),
        "category": category,
        "market": market,
        "handicap": handicap,
        "lead_hours": lead_hours,
        "chief_agent_summary": r.get("chief_agent_summary"),
        "chief_buy_decision": r.get("chief_buy_decision"),
        "agent_hard_guards": guards[:4],
        "reasons": dedup_reasons[:5],
        "actions": dedup_actions[:4],
    }


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
        "jingcai_market": pred_snap.get("jingcai_market") or row.get("竞彩玩法"),
        "jingcai_handicap": (pred.get("jingcai_snapshot") or {}).get("handicap"),
        "risk_level_cn": pred_snap.get("risk_level_cn") or pred.get("risk_level_cn"),
        "control_level_cn": pred_snap.get("control_level_cn") or pred.get("control_level_cn"),
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
    try:
        from match_agents.chief import load_latest_agent_board, load_latest_chief_report

        board = load_latest_agent_board(output_root, fid) if fid else None
        chief = load_latest_chief_report(output_root, fid) if fid else None
        rec["agent_hard_guards"] = (board or {}).get("hard_guards") or []
        rec["chief_agent_summary"] = ((chief or {}).get("analysis") or {}).get("summary")
        rec["chief_buy_decision"] = ((chief or {}).get("analysis") or {}).get("buy_decision")
        rec["chief_risk_level"] = ((chief or {}).get("analysis") or {}).get("risk_level")
        rec["chief_guardrail_downgraded"] = ((chief or {}).get("analysis") or {}).get("guardrail_downgraded")
    except Exception:
        pass

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
            rec = _row_from_settled(settled, output_root=root)
            records.append(enrich_settled_with_user_pick(rec, output_root=root))
        except Exception as exc:
            log.warning("复盘行构建失败 %s: %s", fid, exc)

    records.sort(key=lambda r: r.get("kickoff_at") or "", reverse=True)
    judged = [r for r in records if r.get("pick_jingcai_cn") and r["pick_jingcai_cn"] not in SKIP_PICKS]
    accuracy = compute_accuracy_report(records)

    misses = [r for r in judged if r.get("hit_1x2") is False]
    miss_patterns: dict[str, int] = {}
    for r in misses:
        pick = _review_pick_display(r.get("pick_jingcai_cn")) or "?"
        actual = r.get("result_1x2_cn") or "?"
        key = f"预判{pick}→实际{actual}"
        miss_patterns[key] = miss_patterns.get(key, 0) + 1
    top_misses = sorted(miss_patterns.items(), key=lambda x: -x[1])[:8]
    error_items = [_error_review_item(r) for r in misses]
    error_categories: dict[str, int] = {}
    for item in error_items:
        cat = item.get("category") or "未分类"
        error_categories[cat] = error_categories.get(cat, 0) + 1
    user_locked = list_locked_picks(root)
    user_acc = user_pick_accuracy(records)

    return {
        "updated_at": now_beijing_str(),
        "total_settled": len(records),
        "with_recommendation": len(judged),
        "accuracy": accuracy,
        "review_agent": build_review_agent_report(records),
        "miss_patterns": [{"pattern": k, "count": v} for k, v in top_misses],
        "error_review": {
            "count": len(error_items),
            "categories": [
                {"category": k, "count": v}
                for k, v in sorted(error_categories.items(), key=lambda x: -x[1])
            ],
            "items": error_items[:12],
        },
        "user_locked_count": len(user_locked),
        "user_pick_accuracy": user_acc,
        "records": records,
    }
