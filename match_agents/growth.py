"""Self-growth agent for post-match learning."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from review_agent import diagnose_record
from time_utils import now_beijing_str

from .storage import append_agent_artifact, load_latest_artifact

GROWTH_FILE = "growth_report.jsonl"


def load_latest_growth_report(output_root: str | Path, fixture_id: str) -> dict[str, Any] | None:
    return load_latest_artifact(output_root, fixture_id, GROWTH_FILE)


def _agent_by_id(board: dict | None) -> dict[str, dict]:
    return {str(a.get("agent_id")): a for a in ((board or {}).get("agents") or [])}


def _outcome(settled: dict | None, chief: dict | None) -> dict[str, Any]:
    analysis = (chief or {}).get("analysis") or {}
    return {
        "score_text": (settled or {}).get("score_text"),
        "actual": (settled or {}).get("result_1x2_cn"),
        "pick": (settled or {}).get("pick_jingcai_cn"),
        "hit_1x2": (settled or {}).get("hit_1x2"),
        "hit_ah": (settled or {}).get("hit_ah"),
        "buy_decision": analysis.get("buy_decision"),
        "chief_risk_level": analysis.get("risk_level"),
        "guardrail_downgraded": bool(analysis.get("guardrail_downgraded")),
    }


def build_growth_report(
    fixture_id: str,
    *,
    prediction: dict | None = None,
    index: dict | None = None,
    board: dict | None = None,
    chief: dict | None = None,
    settled: dict | None = None,
) -> dict[str, Any]:
    """Build an auditable learning report without mutating rules or weights."""
    match_name = (
        (index or {}).get("match_name")
        or (prediction or {}).get("match")
        or (settled or {}).get("match_name")
        or str(fixture_id)
    )
    agents = _agent_by_id(board)
    guards = (board or {}).get("hard_guards") or []
    analysis = (chief or {}).get("analysis") or {}
    lessons: list[dict[str, Any]] = []
    suggestions: list[dict[str, Any]] = []
    data_gaps: list[str] = []

    if not settled or settled.get("hit_1x2") is None:
        data_gaps.append("比赛尚未结算，Growth Agent 只记录待学习状态，不做事后归因。")
        return {
            "ok": True,
            "fixture_id": str(fixture_id),
            "match_name": match_name,
            "generated_at": now_beijing_str(),
            "status": "awaiting_settlement",
            "outcome": _outcome(settled, chief),
            "lessons": [],
            "agent_updates": [],
            "policy_suggestions": [],
            "data_gaps": data_gaps,
            "next_prompt_notes": ["完赛并结算后再生成成长报告。"],
        }

    hit = settled.get("hit_1x2") is True
    diagnosis = diagnose_record(settled) if not hit else None
    if hit:
        lessons.append({
            "priority": "P2",
            "title": "命中样本沉淀",
            "evidence": [f"赛果 {settled.get('score_text')}，竞彩方向命中"],
            "action": "保留当前 profile 和 Agent 编排，等待更多同类样本再调权。",
        })
        if guards:
            lessons.append({
                "priority": "P1",
                "title": "命中但触发硬风控",
                "evidence": guards[:5],
                "action": "不要立即放松风控；累计同类命中/漏买样本后再评估硬闸门阈值。",
            })
    else:
        lessons.append({
            "priority": "P0",
            "title": "未命中样本归因",
            "evidence": (diagnosis or {}).get("evidence") or ["未命中但缺少足够归因字段"],
            "action": "将本场加入错误模式样本池，后续同类场景默认降级。",
        })
        for rec in (diagnosis or {}).get("recommendations") or []:
            suggestions.append({"priority": "P0" if "默认" in rec or "强制" in rec else "P1", "suggestion": rec})
        if not guards:
            suggestions.append({
                "priority": "P0",
                "suggestion": "未命中且未触发 hard_guards，需要补充新的硬风控条件或提高相关 Agent 风险权重。",
            })

    agent_updates: list[dict[str, Any]] = []
    for agent_id, agent in agents.items():
        risk = float(agent.get("risk") or 0)
        if agent.get("raw", {}).get("status") == "insufficient_data":
            data_gaps.append(f"{agent.get('name') or agent_id} 缺少可靠数据源")
            agent_updates.append({
                "agent_id": agent_id,
                "action": "add_data_source",
                "suggested_delta": 0.0,
                "reason": "该角色数据不足，不能靠调权解决。",
            })
        elif not hit and risk < 0.5:
            agent_updates.append({
                "agent_id": agent_id,
                "action": "review_features",
                "suggested_delta": 0.05,
                "reason": "未命中但该 Agent 风险评分偏低，需复查特征或阈值。",
            })
        elif not hit and risk >= 0.7:
            agent_updates.append({
                "agent_id": agent_id,
                "action": "keep_or_increase",
                "suggested_delta": 0.03,
                "reason": "该 Agent 已识别风险，后续应确保 Chief 不覆盖其风险信号。",
            })

    if analysis.get("guardrail_downgraded"):
        lessons.append({
            "priority": "P1",
            "title": "硬风控成功介入",
            "evidence": analysis.get("must_not_buy_reasons") or guards,
            "action": "保留程序化降级；Chief 只能解释降级原因，不能绕过。",
        })

    next_prompt_notes = [
        "Chief Prompt 必须引用 Growth Agent 的历史教训，尤其是同玩法、同让球区间、同 profile 的错误模式。",
        "调权建议先作为人工审核项展示，不自动写回配置。",
    ]
    if data_gaps:
        next_prompt_notes.append("数据缺口优先级高于模型调权，缺情报时必须写明未参与判断。")

    return {
        "ok": True,
        "fixture_id": str(fixture_id),
        "match_name": match_name,
        "generated_at": now_beijing_str(),
        "status": "learned_hit" if hit else "learned_miss",
        "outcome": _outcome(settled, chief),
        "diagnosis": diagnosis,
        "lessons": lessons,
        "agent_updates": agent_updates[:12],
        "policy_suggestions": suggestions[:10],
        "data_gaps": list(dict.fromkeys(data_gaps))[:10],
        "next_prompt_notes": next_prompt_notes,
        "raw": {
            "hard_guards": guards,
            "chief_summary": analysis.get("summary"),
            "profile": (board or {}).get("scope") or ((board or {}).get("summary") or {}).get("profile"),
        },
    }


def build_and_archive_growth_report(
    output_root: str | Path,
    fixture_id: str,
    *,
    prediction: dict | None = None,
    index: dict | None = None,
    board: dict | None = None,
    chief: dict | None = None,
    settled: dict | None = None,
) -> dict[str, Any]:
    report = build_growth_report(
        fixture_id,
        prediction=prediction,
        index=index,
        board=board,
        chief=chief,
        settled=settled,
    )
    append_agent_artifact(output_root, fixture_id, GROWTH_FILE, report)
    return report
