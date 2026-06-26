"""Readable workflow/pipeline view for multi-agent match analysis."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .board import BOARD_FILE
from .chief import CHIEF_FILE
from .growth import GROWTH_FILE
from .storage import load_agent_artifacts


def _short(items: list[str], limit: int = 3) -> list[str]:
    return [str(x)[:220] for x in items[:limit]]


def _board_steps(board: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not board:
        return [{
            "id": "agent_board",
            "title": "Agent Evidence Board",
            "status": "missing",
            "summary": "暂无专家证据板，请先生成多 Agent 分析。",
            "items": [],
        }]
    steps = []
    for agent in board.get("agents") or []:
        warnings = agent.get("warnings") or []
        status = "risk" if float(agent.get("risk") or 0) >= 0.7 else "ok"
        steps.append({
            "id": agent.get("agent_id"),
            "title": agent.get("name") or agent.get("agent_id"),
            "status": status,
            "summary": (
                f"verdict={agent.get('verdict')} · weight={agent.get('weight')} · "
                f"confidence={agent.get('confidence')} · risk={agent.get('risk')}"
            ),
            "items": _short(agent.get("evidence") or []),
            "warnings": _short(warnings),
            "raw": agent.get("raw") or {},
        })
    guards = board.get("hard_guards") or []
    steps.append({
        "id": "hard_guards",
        "title": "硬风险闸门",
        "status": "risk" if guards else "ok",
        "summary": f"{len(guards)} 条硬风险" if guards else "未触发硬风险",
        "items": guards,
    })
    return steps


def _chief_steps(chief: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not chief:
        return [{
            "id": "chief_agent",
            "title": "AI 总 Agent",
            "status": "missing",
            "summary": "暂无 AI 总 Agent 报告。",
            "items": [],
        }]
    analysis = chief.get("analysis") or {}
    prompt_messages = chief.get("prompt_messages") or []
    return [
        {
            "id": "chief_prompt",
            "title": "总 Agent Prompt",
            "status": "ok" if prompt_messages else "missing",
            "summary": f"{len(prompt_messages)} 条 message",
            "items": [m.get("role", "") for m in prompt_messages],
            "prompt_messages": prompt_messages,
        },
        {
            "id": "chief_output",
            "title": "AI 输出解析",
            "status": "risk" if analysis.get("guardrail_downgraded") else "ok",
            "summary": analysis.get("summary") or "已输出结构化报告",
            "items": [
                f"buy_decision={analysis.get('buy_decision')}",
                f"confidence={analysis.get('confidence')}",
                f"risk_level={analysis.get('risk_level')}",
            ],
            "analysis": analysis,
            "raw_text": chief.get("raw_text"),
        },
    ]


def _growth_steps(growth: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not growth:
        return [{
            "id": "growth_agent",
            "title": "自我成长 Agent",
            "status": "missing",
            "summary": "暂无成长报告，完赛结算后可生成。",
            "items": [],
        }]
    status = growth.get("status") or "ok"
    lessons = growth.get("lessons") or []
    items = [x.get("title") or x.get("action") for x in lessons[:5] if isinstance(x, dict)]
    return [{
        "id": "growth_agent",
        "title": "自我成长 Agent",
        "status": "risk" if "miss" in str(status) else "ok",
        "summary": f"{status} · {len(lessons)} 条教训 · {len(growth.get('policy_suggestions') or [])} 条策略建议",
        "items": items,
        "growth": growth,
    }]


def build_agent_workflow(output_root: str | Path, fixture_id: str) -> dict[str, Any]:
    boards = load_agent_artifacts(output_root, fixture_id, BOARD_FILE, limit=5)
    chiefs = load_agent_artifacts(output_root, fixture_id, CHIEF_FILE, limit=5)
    growths = load_agent_artifacts(output_root, fixture_id, GROWTH_FILE, limit=5)
    board = boards[0] if boards else None
    chief = chiefs[0] if chiefs else None
    growth = growths[0] if growths else None
    steps = [
        {
            "id": "input",
            "title": "输入数据",
            "status": "ok" if board else "missing",
            "summary": (board or chief or {}).get("match_name") or str(fixture_id),
            "items": [
                f"fixture_id={fixture_id}",
                f"board_ts={(board or {}).get('generated_at') or '—'}",
                f"chief_ts={(chief or {}).get('ts') or '—'}",
            ],
        },
        *_board_steps(board),
        *_chief_steps(chief),
        *_growth_steps(growth),
        {
            "id": "archive",
            "title": "归档记录",
            "status": "ok",
            "summary": f"证据板 {len(boards)} 条 · 总报告 {len(chiefs)} 条 · 成长报告 {len(growths)} 条",
            "items": [
                "matches/{fixture_id}/agent_board.jsonl",
                "matches/{fixture_id}/chief_report.jsonl",
                "matches/{fixture_id}/growth_report.jsonl",
            ],
        },
    ]
    return {
        "ok": True,
        "fixture_id": str(fixture_id),
        "match_name": (board or chief or {}).get("match_name") or str(fixture_id),
        "steps": steps,
        "latest_board": board,
        "latest_chief": chief,
        "latest_growth": growth,
        "history_counts": {"agent_board": len(boards), "chief_report": len(chiefs), "growth_report": len(growths)},
    }
