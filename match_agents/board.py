"""Build and archive the multi-agent evidence board."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from time_utils import now_beijing_str

from .profiles import agents_for_profile, profile_description, resolve_match_profile
from .storage import append_agent_artifact
from .types import AgentBoard, AgentReport

BOARD_FILE = "agent_board.jsonl"


def _match_name(pred: dict, index: dict | None = None) -> str:
    row = pred.get("predict_row") or {}
    return (
        pred.get("match")
        or pred.get("match_name")
        or row.get("比赛")
        or (index or {}).get("match_name")
        or ""
    )


def _fixture_id(pred: dict, index: dict | None = None) -> str:
    return str(pred.get("fixture_id") or (index or {}).get("fixture_id") or "")


def _hard_guards(agents: list[AgentReport]) -> list[str]:
    guards: list[str] = []
    by_id = {a.agent_id: a for a in agents}
    jc = by_id.get("jingcai")
    ah = by_id.get("asian_handicap")
    motivation = by_id.get("motivation")
    intel = by_id.get("intel")
    external = by_id.get("external_context")
    goal_swing = by_id.get("goal_swing")
    schedule_venue = by_id.get("schedule_venue")
    cross_group = by_id.get("cross_group_path")

    if jc and jc.risk >= 0.9:
        guards.append("竞彩 Agent 识别到仅让球/大让球硬风险，禁止升级为稳健串关")
    if ah and ah.risk >= 0.85:
        guards.append("亚盘 Agent 识别到大让球或盘口剧烈变化，必须降级或观望")
    if motivation and motivation.risk >= 0.75:
        guards.append("战意 Agent 识别到默契球/平局友好/无战意风险，不能只按盘口强弱判断")
    if goal_swing and goal_swing.risk >= 0.85:
        guards.append("一球杠杆 Agent 识别到 1 个进球可能改变出线/让球结算，禁止升级为稳健串关")
    if cross_group and cross_group.risk >= 0.8:
        guards.append("跨组出线路径 Agent 识别到最佳第三/32强路径/默契球风险，必须降级或观望")
    if intel and intel.raw.get("status") == "insufficient_data":
        guards.append("情报 Agent 未接入可靠伤停/天气/首发，AI 不得编造外部情报")
    if external and external.raw.get("status") == "insufficient_data":
        guards.append("外部因素 Agent 未接入新闻/天气/场地/海拔数据，AI 只能标注缺失不能臆测")
    if schedule_venue and schedule_venue.risk >= 0.7:
        guards.append("赛程球馆 Agent 缺少关键时间/地点数据，AI 不能判断天气海拔场地影响")
    return list(dict.fromkeys(guards))


def _summary(agents: list[AgentReport]) -> dict[str, Any]:
    verdict_counts: dict[str, int] = {}
    weighted_signal: dict[str, float] = {}
    risk_agents = []
    warnings = []
    for a in agents:
        verdict_counts[a.verdict] = verdict_counts.get(a.verdict, 0) + 1
        weighted_signal[a.verdict] = weighted_signal.get(a.verdict, 0.0) + float(a.weight or 1.0) * float(a.confidence or 0.0)
        if a.risk >= 0.7:
            risk_agents.append({"agent_id": a.agent_id, "name": a.name, "risk": a.risk})
        warnings.extend(a.warnings[:2])
    return {
        "verdict_counts": verdict_counts,
        "weighted_signal": {k: round(v, 3) for k, v in sorted(weighted_signal.items())},
        "risk_agents": risk_agents,
        "warnings": list(dict.fromkeys(warnings))[:10],
    }


def board_is_cup_context(board: dict[str, Any]) -> bool:
    """True when cup/tournament agents found meaningful context."""
    for a in board.get("agents") or []:
        if a.get("agent_id") not in ("cup_standing", "motivation"):
            continue
        raw = a.get("raw") or {}
        if raw.get("knockout_context", {}).get("ok") is not False and a.get("agent_id") == "cup_standing":
            evidence = " ".join(a.get("evidence") or [])
            if "未识别" not in evidence:
                return True
        if raw.get("motivation"):
            return True
    return False


def build_agent_board(
    prediction: dict,
    *,
    index: dict | None = None,
    output_root: str | Path | None = None,
    profile: str | None = None,
) -> dict[str, Any]:
    """Build deterministic expert evidence for one match."""
    fid = _fixture_id(prediction, index)
    profile_id = resolve_match_profile(prediction, explicit=profile, output_root=output_root)
    reports: list[AgentReport] = []
    for expert in agents_for_profile(profile_id, output_root=output_root):
        try:
            report = expert(prediction, index, output_root=output_root)
            reports.append(report)
        except Exception as exc:
            reports.append(
                AgentReport(
                    agent_id=getattr(expert, "__name__", "unknown"),
                    name=getattr(expert, "__name__", "未知 Agent"),
                    verdict="risk",
                    confidence=0.0,
                    risk=0.8,
                    evidence=[],
                    warnings=[f"Agent 执行失败：{exc}"],
                    recommended_action="watch",
                    raw={"error": str(exc)},
                )
            )

    board = AgentBoard(
        ok=True,
        fixture_id=fid,
        match_name=_match_name(prediction, index),
        generated_at=now_beijing_str(),
        scope=profile_id,
        agents=reports,
        hard_guards=_hard_guards(reports),
        summary={**_summary(reports), "profile": profile_id, "profile_description": profile_description(profile_id, output_root=output_root)},
    )
    return board.to_dict()


def build_and_archive_agent_board(
    output_root: str | Path,
    fixture_id: str,
    prediction: dict,
    *,
    index: dict | None = None,
    run_id: str | None = None,
    profile: str | None = None,
) -> dict[str, Any]:
    board = build_agent_board(prediction, index=index, output_root=output_root, profile=profile)
    if run_id:
        board["run_id"] = run_id
    append_agent_artifact(output_root, fixture_id, BOARD_FILE, board)
    return board
