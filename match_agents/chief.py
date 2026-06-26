"""AI chief agent that synthesizes expert evidence into a final report."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai_prompt import _extract_json_text
from deepseek_client import chat
from time_utils import now_beijing_str

from .board import BOARD_FILE, build_agent_board
from .config import load_match_agent_config
from .storage import append_agent_artifact, load_latest_artifact

CHIEF_FILE = "chief_report.jsonl"


def load_latest_chief_report(output_root: str | Path, fixture_id: str) -> dict[str, Any] | None:
    return load_latest_artifact(output_root, fixture_id, CHIEF_FILE)


def load_latest_agent_board(output_root: str | Path, fixture_id: str) -> dict[str, Any] | None:
    return load_latest_artifact(output_root, fixture_id, BOARD_FILE)


def _profile(provider: str | None, output_root: str | Path, *, model: str | None, base_url: str | None):
    from ai_profiles import get_primary_profile, get_profile_by_id

    if provider:
        prof = get_profile_by_id(provider, output_root=output_root, model=model, base_url=base_url)
        if prof:
            return prof
    return get_primary_profile(model=model, base_url=base_url, output_root=output_root)


def _guardrail_downgrade(data: dict[str, Any], hard_guards: list[str]) -> dict[str, Any]:
    if not hard_guards:
        return data
    buy = str(data.get("buy_decision") or "").strip()
    if buy in ("A 可串", "A", "可串", "稳健串关"):
        data["buy_decision"] = "C 仅参考"
        data.setdefault("must_not_buy_reasons", [])
        if isinstance(data["must_not_buy_reasons"], list):
            data["must_not_buy_reasons"].extend(hard_guards)
        data["risk_level"] = "高"
        data["guardrail_downgraded"] = True
    return data


def _normalize_ai_json(text: str) -> dict[str, Any]:
    data = json.loads(_extract_json_text(text))
    if not isinstance(data, dict):
        raise ValueError("AI 总 Agent 必须返回 JSON object")
    return data


def _chief_messages(
    board: dict[str, Any],
    prediction: dict | None = None,
    *,
    output_root: str | Path | None = None,
) -> list[dict[str, str]]:
    compact_pred = {}
    if prediction:
        row = prediction.get("predict_row") or {}
        compact_pred = {
            "fixture_id": prediction.get("fixture_id"),
            "match": prediction.get("match") or row.get("比赛"),
            "current_pick": row.get("竞彩推荐") or prediction.get("pick_jingcai_cn"),
            "reference_1x2": prediction.get("reference_result_1x2_cn") or row.get("赛果预测"),
            "asian_handicap": prediction.get("asian_handicap_cn") or row.get("亚盘"),
            "confidence": prediction.get("confidence_cn") or row.get("置信度"),
            "risk_level": prediction.get("risk_level_cn"),
            "control_level": prediction.get("control_level_cn"),
            "buy_tier": prediction.get("buy_tier_cn") or prediction.get("buy_tier"),
        }
    profile = board.get("scope") or (board.get("summary") or {}).get("profile") or "cup"
    profile_label = "杯赛" if profile == "cup" else "联赛"
    system = (
        f"你是足球{profile_label}多 Agent 总分析师。你必须基于输入的专家证据板做最终研判，"
        "不得编造未提供的伤停、天气、首发、新闻或盘口数据。"
        "如果情报 Agent 标记 insufficient_data，必须在报告中说明暂无可靠情报数据。"
        "你的目标不是强行给单，而是输出可执行的风险决策：可串、可单关、仅参考、跳过。"
        "只返回 JSON，不要 markdown 代码块。"
    )
    user = {
        "task": f"综合多个专家 Agent 的证据，输出最终中文深度报告与结构化决策。当前 profile={profile}",
        "hard_constraints": [
            "只基于 expert_board 和 compact_prediction 分析，不得臆测外部消息。",
            "如果 hard_guards 非空，不能输出 A 可串；必须解释降级原因。",
            "只卖让球或大让球场次，必须重点解释净胜球风险。",
            "若专家冲突明显，优先降级而不是给高置信。",
            "agent_weights 只表示证据重视程度，不能覆盖 hard_guards。",
            "schedule_venue Agent 是预测前提：必须先检查开球时间、球馆/城市、海拔、天气是否存在。",
            "如果 schedule_venue 缺少球馆/天气/海拔，必须写明这些维度未参与判断。",
            "late_confirmation Agent 是临场确认闸门：若首发、伤停、终盘或时间窗口缺失，不能把报告表述为最终临场版。",
            "如果 profile=cup：opening_structure 是本届杯赛整体开盘环境，需作为宏观背景纳入最终报告。",
            "如果 profile=cup：scenario_simulator 必须说明同组另一场、跨组第三、不同比分场景如何改变战意和结果价值。",
            "如果 profile=cup：goal_swing 代表一球杠杆风险，必须解释 1 个进球是否会改变出线、净胜球排序或让球结算。",
            "如果 profile=cup：cross_group_path 代表另一侧数据，必须分析小组第三动态排名、32强路径和默契球/控分动机。",
            "market_consistency 代表欧赔与亚盘态度是否一致；若不一致，必须降级并解释诱盘/分歧风险。",
            "contrarian 是强制反方辩手；必须逐条回应其不买理由，不能忽略。",
            "memory 若命中历史相似翻车模式，必须解释本场与历史错因的差异，否则降级。",
            "如果 profile=league：league_pressure 代表联赛赛程密度、多线战斗、轮换伤停和战意压力，必须说明数据是否充分。",
            "external_context 若无数据，必须写明新闻/天气/场地/海拔未接入，不得编造。",
        ],
        "required_json_schema": {
            "final_report_md": "完整中文报告；cup 需覆盖临场确认/场景模拟/跨组第三/出线路径/一球杠杆/欧亚一致性/反方理由/成长记忆，league 需覆盖赛程密度/多线压力/联赛战意",
            "final_pick": {
                "sp": "主胜|平局|客胜|观望",
                "rqsp": "胜|平|负|观望",
                "asian_handicap": "上盘|下盘|观望",
            },
            "buy_decision": "A 可串|B 可单关|C 仅参考|skip",
            "confidence": "高|中|低",
            "risk_level": "低|中|高",
            "conflicts": ["专家冲突点"],
            "must_not_buy_reasons": ["禁止购买/降级理由"],
            "watch_points": ["开球前需复核的信息"],
            "summary": "一句话结论",
        },
        "agent_config": load_match_agent_config(output_root),
        "profile": profile,
        "compact_prediction": compact_pred,
        "expert_board": board,
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False, default=str)},
    ]


def run_chief_match_agent(
    output_root: str | Path,
    fixture_id: str,
    prediction: dict,
    *,
    index: dict | None = None,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    board: dict[str, Any] | None = None,
    run_id: str | None = None,
    profile: str | None = None,
) -> dict[str, Any]:
    """Run the AI chief agent and archive its final report."""
    root = Path(output_root)
    board = board or build_agent_board(prediction, index=index, output_root=root, profile=profile)
    prof = _profile(provider, root, model=model, base_url=base_url)
    api_key = prof.resolve_api_key()
    if not api_key:
        raise RuntimeError(f"未配置 {prof.api_key_env}")

    prompt_messages = _chief_messages(board, prediction, output_root=root)
    raw_text = chat(
        prompt_messages,
        api_key=api_key,
        model=prof.model,
        base_url=prof.base_url,
        temperature=0.2,
        timeout=180,
        max_tokens=4096,
    )
    data = _normalize_ai_json(raw_text)
    data = _guardrail_downgrade(data, board.get("hard_guards") or [])
    record = {
        "ok": True,
        "fixture_id": str(fixture_id),
        "match_name": board.get("match_name") or prediction.get("match"),
        "ts": now_beijing_str(),
        "run_id": run_id,
        "provider": prof.provider_id,
        "provider_label": prof.label,
        "model": prof.model,
        "board": board,
        "prompt_messages": prompt_messages,
        "analysis": data,
        "raw_text": raw_text,
    }
    append_agent_artifact(root, fixture_id, CHIEF_FILE, record)
    return record
