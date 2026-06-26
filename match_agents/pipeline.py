"""Step-by-step streaming pipeline for multi-agent match analysis."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from time_utils import now_beijing_str

from .board import (
    BOARD_FILE,
    _fixture_id,
    _hard_guards,
    _match_name,
    _summary,
)
from .chief import run_chief_match_agent
from .profiles import agents_for_profile, profile_description, resolve_match_profile
from .types import AgentBoard, AgentReport


def _agent_id_from_fn(fn) -> str:
    name = getattr(fn, "__name__", "unknown")
    if name.endswith("_agent"):
        return name[: -len("_agent")]
    return name


def _emit(event: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"event": event, **payload}


def _run_expert(fn, prediction: dict, index: dict | None, output_root) -> AgentReport:
    try:
        return fn(prediction, index, output_root=output_root)
    except Exception as exc:
        aid = _agent_id_from_fn(fn)
        return AgentReport(
            agent_id=aid,
            name=aid,
            verdict="risk",
            confidence=0.0,
            risk=0.8,
            evidence=[],
            warnings=[f"Agent 执行失败：{exc}"],
            recommended_action="watch",
            raw={"error": str(exc)},
        )


def iter_match_pipeline_events(
    output_root: str | Path,
    fixture_id: str,
    prediction: dict,
    *,
    index: dict | None = None,
    profile: str | None = None,
    run_chief: bool = False,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield SSE-friendly step events for the multi-agent pipeline."""
    root = Path(output_root)
    fid = _fixture_id(prediction, index) or str(fixture_id)
    match_name = _match_name(prediction, index)
    profile_id = resolve_match_profile(prediction, explicit=profile, output_root=root)
    agent_fns = agents_for_profile(profile_id, output_root=root)
    total = 1 + len(agent_fns) + 2 + (1 if run_chief else 0)
    step = 0

    yield _emit(
        "pipeline_init",
        {
            "fixture_id": fid,
            "match_name": match_name,
            "profile": profile_id,
            "profile_description": profile_description(profile_id, output_root=root),
            "total_steps": total,
            "agent_count": len(agent_fns),
            "run_chief": run_chief,
        },
    )

    step += 1
    yield _emit(
        "step_start",
        {"step": step, "total": total, "id": "input", "title": "输入数据校验"},
    )
    yield _emit(
        "log",
        {"message": f"fixture_id={fid} · profile={profile_id} · {match_name}", "level": "info"},
    )
    row = prediction.get("predict_row") or {}
    input_summary = {
        "pick": row.get("竞彩推荐") or prediction.get("pick_jingcai_cn"),
        "asian": prediction.get("asian_handicap_cn") or row.get("亚盘"),
        "risk": prediction.get("risk_level_cn"),
    }
    for key, val in input_summary.items():
        if val:
            yield _emit("chunk", {"text": f"{key}: {val}", "kind": "evidence"})
    yield _emit(
        "step_done",
        {
            "step": step,
            "total": total,
            "id": "input",
            "title": "输入数据校验",
            "summary": f"Profile={profile_id} · {match_name}",
            "result": input_summary,
        },
    )

    reports: list[AgentReport] = []
    for fn in agent_fns:
        step += 1
        aid = _agent_id_from_fn(fn)
        title = aid
        yield _emit(
            "step_start",
            {"step": step, "total": total, "id": aid, "title": title, "agent_id": aid},
        )
        yield _emit("log", {"message": f"▶ 运行专家 Agent: {aid}", "level": "info"})
        report = _run_expert(fn, prediction, index, root)
        reports.append(report)
        d = report.to_dict()
        title = d.get("name") or aid
        for ev in d.get("evidence") or []:
            yield _emit("chunk", {"text": str(ev), "kind": "evidence"})
        for w in d.get("warnings") or []:
            yield _emit("chunk", {"text": str(w), "kind": "warning"})
        meta = (
            f"verdict={d.get('verdict')} · weight={d.get('weight')} · "
            f"confidence={d.get('confidence')} · risk={d.get('risk')}"
        )
        yield _emit("chunk", {"text": meta, "kind": "meta"})
        yield _emit(
            "step_done",
            {
                "step": step,
                "total": total,
                "id": aid,
                "title": title,
                "summary": meta,
                "agent": d,
            },
        )
        yield _emit("log", {"message": f"✓ 完成: {title} ({meta})", "level": "ok"})

    step += 1
    yield _emit(
        "step_start",
        {"step": step, "total": total, "id": "hard_guards", "title": "硬风险闸门"},
    )
    guards = _hard_guards(reports)
    if guards:
        for g in guards:
            yield _emit("chunk", {"text": g, "kind": "guard"})
    else:
        yield _emit("chunk", {"text": "未触发硬风险闸门", "kind": "evidence"})
    yield _emit(
        "step_done",
        {
            "step": step,
            "total": total,
            "id": "hard_guards",
            "title": "硬风险闸门",
            "summary": f"触发 {len(guards)} 条硬风险" if guards else "无硬风险",
            "guards": guards,
        },
    )
    yield _emit(
        "log",
        {"message": f"硬风险闸门: {len(guards)} 条", "level": "warn" if guards else "ok"},
    )

    step += 1
    yield _emit(
        "step_start",
        {"step": step, "total": total, "id": "archive", "title": "归档证据板"},
    )
    board_obj = AgentBoard(
        ok=True,
        fixture_id=fid,
        match_name=match_name,
        generated_at=now_beijing_str(),
        scope=profile_id,
        agents=reports,
        hard_guards=guards,
        summary={
            **_summary(reports),
            "profile": profile_id,
            "profile_description": profile_description(profile_id, output_root=root),
        },
    )
    board = board_obj.to_dict()
    from .storage import append_agent_artifact

    append_agent_artifact(root, fid, BOARD_FILE, board)
    yield _emit("chunk", {"text": f"已写入 {BOARD_FILE}", "kind": "evidence"})
    yield _emit(
        "step_done",
        {
            "step": step,
            "total": total,
            "id": "archive",
            "title": "归档证据板",
            "summary": f"{len(reports)} 个专家 · {len(guards)} 条硬风险",
            "board_summary": board.get("summary"),
        },
    )
    yield _emit("log", {"message": "证据板已归档", "level": "ok"})

    chief_record: dict[str, Any] | None = None
    if run_chief:
        step += 1
        yield _emit(
            "step_start",
            {"step": step, "total": total, "id": "chief", "title": "Chief AI 总 Agent"},
        )
        yield _emit("log", {"message": "正在调用 Chief AI 生成最终报告…", "level": "info"})
        chief_record = run_chief_match_agent(
            root,
            fid,
            prediction,
            index=index,
            board=board,
            provider=provider,
            model=model,
            base_url=base_url,
            profile=profile_id,
        )
        analysis = chief_record.get("analysis") or {}
        summary = analysis.get("summary") or analysis.get("buy_decision") or "Chief 报告已生成"
        yield _emit("chunk", {"text": f"决策: {analysis.get('buy_decision') or '—'}", "kind": "meta"})
        yield _emit("chunk", {"text": f"风险: {analysis.get('risk_level') or '—'}", "kind": "meta"})
        raw = chief_record.get("raw_text") or ""
        chunk_size = 120
        for i in range(0, len(raw), chunk_size):
            yield _emit("chunk", {"text": raw[i : i + chunk_size], "kind": "chief_raw"})
        yield _emit(
            "step_done",
            {
                "step": step,
                "total": total,
                "id": "chief",
                "title": "Chief AI 总 Agent",
                "summary": summary,
                "chief": {
                    "analysis": analysis,
                    "provider": chief_record.get("provider_label"),
                    "model": chief_record.get("model"),
                },
            },
        )
        yield _emit("log", {"message": f"✓ Chief 完成: {summary}", "level": "ok"})

    yield _emit(
        "pipeline_complete",
        {
            "fixture_id": fid,
            "match_name": match_name,
            "profile": profile_id,
            "board": board,
            "chief": chief_record,
            "hard_guards": guards,
        },
    )


def pipeline_event_json(evt: dict[str, Any]) -> str:
    """Serialize one pipeline event for SSE data field."""
    payload = {k: v for k, v in evt.items() if k != "event"}
    return json.dumps(payload, ensure_ascii=False, default=str)
