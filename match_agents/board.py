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
    knockout_motivation = by_id.get("knockout_motivation")
    intel = by_id.get("intel")
    external = by_id.get("external_context")
    goal_swing = by_id.get("goal_swing")
    schedule_venue = by_id.get("schedule_venue")
    knockout_path = by_id.get("knockout_path")
    late = by_id.get("late_confirmation")
    extra_time = by_id.get("extra_time_penalty")
    market_consistency = by_id.get("market_consistency")
    contrarian = by_id.get("contrarian")
    memory = by_id.get("memory")

    if jc and jc.risk >= 0.9:
        guards.append("竞彩 Agent 识别到仅让球/大让球硬风险，禁止升级为稳健串关")
    if ah and ah.risk >= 0.85:
        guards.append("亚盘 Agent 识别到大让球或盘口剧烈变化，必须降级或观望")
    if knockout_motivation and knockout_motivation.risk >= 0.75:
        guards.append("淘汰赛战意 Agent 识别到保守/激进策略分歧，不能只按盘口强弱判断")
    if goal_swing and goal_swing.risk >= 0.85:
        guards.append("一球杠杆 Agent 识别到 1 个进球可能改变让球结算，禁止升级为稳健串关")
    if knockout_path and knockout_path.risk >= 0.8:
        guards.append("淘汰赛路径 Agent 识别到半区强弱悬殊或潜在对手链风险，必须降级或观望")
    if late and late.risk >= 0.7:
        guards.append("临场确认 Agent 识别到首发/终盘/时间窗口缺口，当前报告不能当作最终临场版")
    if extra_time and extra_time.risk >= 0.78:
        guards.append("加时点球 Agent 识别到高概率加时/点球场景，必须解释平局价值和加时赛风险")
    if market_consistency and market_consistency.risk >= 0.8:
        guards.append("欧亚一致性 Agent 识别到欧赔与亚盘态度不一致，必须降级或观望")
    if contrarian and contrarian.risk >= 0.82:
        guards.append("反方辩手 Agent 给出强不买理由，禁止升级为稳健串关")
    if memory and memory.risk >= 0.75:
        guards.append("成长记忆库 Agent 命中历史相似翻车模式，必须降级并解释差异")
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
    """True when cup/tournament agents found meaningful knockout context."""
    for a in board.get("agents") or []:
        if a.get("agent_id") not in ("knockout_path", "knockout_motivation", "extra_time_penalty"):
            continue
        raw = a.get("raw") or {}
        if a.get("agent_id") == "knockout_path" and raw.get("knockout_context"):
            evidence = " ".join(a.get("evidence") or [])
            if "未识别" not in evidence:
                return True
        if a.get("agent_id") == "knockout_motivation" and raw.get("knockout_context"):
            return True
        if a.get("agent_id") == "extra_time_penalty" and raw.get("extra_time_data"):
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


def load_agent_board_map(
    output_root: str | Path,
    fixture_ids: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Load latest agent boards keyed by fixture_id."""
    from .storage import load_latest_artifact

    root = Path(output_root)
    out: dict[str, dict[str, Any]] = {}
    if fixture_ids:
        for fid in fixture_ids:
            if not fid:
                continue
            rec = load_latest_artifact(root, fid, BOARD_FILE)
            if rec:
                out[str(fid)] = rec
        return out
    matches_dir = root / "matches"
    if not matches_dir.is_dir():
        return out
    for mdir in matches_dir.iterdir():
        if not mdir.is_dir():
            continue
        rec = load_latest_artifact(root, mdir.name, BOARD_FILE)
        if rec:
            out[str(mdir.name)] = rec
    return out


_TIER_TO_DECISION = {
    "可串": "A 可串",
    "稳胆串关": "A 可串",
    "A 可串": "A 可串",
    "可单关": "B 可单关",
    "可跟": "B 可单关",
    "B 可单关": "B 可单关",
    "仅参考": "C 仅参考",
    "观望": "C 仅参考",
    "C 仅参考": "C 仅参考",
}


def list_verdict_from_board(board: dict[str, Any]) -> dict[str, Any]:
    """Deterministic list-page verdict synthesized from expert board."""
    guards = list(board.get("hard_guards") or [])
    summary = board.get("summary") or {}
    warnings = list(summary.get("warnings") or [])
    agents = list(board.get("agents") or [])
    action_counts: dict[str, int] = {}
    risk_high = 0
    for a in agents:
        act = str(a.get("recommended_action") or "watch")
        action_counts[act] = action_counts.get(act, 0) + 1
        if float(a.get("risk") or 0) >= 0.75:
            risk_high += 1

    if guards or action_counts.get("skip", 0) >= 2:
        buy_decision = "C 仅参考"
        risk_level = "高"
        confidence = "低"
    elif action_counts.get("buy", 0) >= 2 and not guards:
        buy_decision = "A 可串"
        risk_level = "中"
        confidence = "中"
    elif action_counts.get("single_only", 0) >= 1 or action_counts.get("buy", 0) >= 1:
        buy_decision = "B 可单关"
        risk_level = "中" if risk_high else "低"
        confidence = "中"
    else:
        buy_decision = "C 仅参考"
        risk_level = "高" if risk_high >= 2 else "中"
        confidence = "低" if risk_high >= 2 else "中"

    if guards:
        summary_text = str(guards[0])
    elif warnings:
        summary_text = str(warnings[0])
    elif risk_high:
        summary_text = f"{risk_high} 个专家 Agent 提示高风险"
    else:
        vc = summary.get("verdict_counts") or {}
        if vc:
            top = max(vc.items(), key=lambda x: x[1])
            summary_text = f"专家板 {len(agents)} 角色 · 主信号 {top[0]}×{top[1]}"
        else:
            summary_text = f"专家板 {len(agents)} 角色已汇总"

    return {
        "buy_decision": buy_decision,
        "risk_level": risk_level,
        "confidence": confidence,
        "summary": summary_text[:120],
        "source": "board",
    }


def list_verdict_from_prediction(match: dict[str, Any]) -> dict[str, Any]:
    """Lightweight verdict from existing prediction fields when no board/chief."""
    row = match.get("predict_row") or match
    tier_cn = str(match.get("buy_tier_cn") or row.get("购买档位") or "").strip()
    buy_decision = _TIER_TO_DECISION.get(tier_cn, tier_cn or "C 仅参考")
    risk_level = str(match.get("risk_level_cn") or row.get("风险") or "—").strip() or "—"
    confidence = str(row.get("置信度") or match.get("confidence_cn") or "—").strip() or "—"
    pick = str(row.get("竞彩推荐") or match.get("pick_jingcai_cn") or "").strip()
    ah = str(row.get("亚盘") or match.get("asian_handicap_cn") or "").strip()
    reasoning = str(
        match.get("actuary_reasoning")
        or row.get("精算理由")
        or match.get("ai_summary")
        or ""
    ).strip()
    parts = [x for x in (pick, ah) if x and x != "—"]
    if reasoning:
        summary_text = reasoning
    elif parts:
        summary_text = " · ".join(parts)
    else:
        summary_text = "规则引擎初判，待专家板更新"
    return {
        "buy_decision": buy_decision,
        "risk_level": risk_level,
        "confidence": confidence,
        "summary": summary_text[:120],
        "source": "prediction",
    }


_CONF_CN_SCORE = {"高": 0.88, "中": 0.62, "低": 0.38, "—": 0.45}
_DECISION_RANK = {"A 可串": 3, "B 可单关": 2, "C 仅参考": 1}


def _confidence_cn_score(label: str) -> float:
    return _CONF_CN_SCORE.get(str(label or "").strip(), 0.45)


def _certainty_label(score: float) -> str:
    if score >= 0.72:
        return "高"
    if score >= 0.45:
        return "中"
    return "低"


def _chief_certainty(analysis: dict[str, Any]) -> float:
    base = _confidence_cn_score(analysis.get("confidence"))
    if analysis.get("guardrail_downgraded"):
        base = min(base, 0.42)
    if str(analysis.get("risk_level") or "") == "高":
        base *= 0.85
    return min(1.0, base * 1.05)


def _board_certainty(board: dict[str, Any], analysis: dict[str, Any]) -> float:
    guards = board.get("hard_guards") or []
    if guards:
        return 0.82
    agents = list(board.get("agents") or [])
    if not agents:
        return 0.4
    weighted_conf = 0.0
    weight_sum = 0.0
    actions: list[str] = []
    for a in agents:
        conf = float(a.get("confidence") or 0)
        risk = float(a.get("risk") or 0)
        wt = float(a.get("weight") or 1)
        if risk < 0.72:
            weighted_conf += conf * wt
            weight_sum += wt
        actions.append(str(a.get("recommended_action") or "watch"))
    avg_conf = (weighted_conf / weight_sum) if weight_sum else 0.35
    if actions:
        top_action = max(set(actions), key=actions.count)
        agreement = actions.count(top_action) / len(actions)
    else:
        agreement = 0.5
    score = avg_conf * 0.55 + agreement * 0.35 + _confidence_cn_score(analysis.get("confidence")) * 0.1
    return min(1.0, max(0.25, score))


def _prediction_certainty(match: dict[str, Any], analysis: dict[str, Any]) -> float:
    row = match.get("predict_row") or match
    conf = _confidence_cn_score(row.get("置信度") or match.get("confidence_cn"))
    grade = str(match.get("accuracy_grade") or (match.get("accuracy_pick") or {}).get("accuracy_grade") or "")
    if grade in ("稳胆甜区", "稳胆"):
        conf = min(1.0, conf + 0.12)
    if str(analysis.get("risk_level") or "") == "高":
        conf *= 0.88
    return min(0.75, conf)


_OUTCOME_CN = {"home": "主胜", "draw": "平局", "away": "客胜"}
_CN_TO_OUTCOME = {"主胜": "home", "平局": "draw", "客胜": "away", "平": "draw", "胜": "home", "负": "away"}


def _agent_board_raw(board: dict[str, Any] | None, agent_id: str) -> dict[str, Any]:
    for a in (board or {}).get("agents") or []:
        if a.get("agent_id") == agent_id:
            return dict(a.get("raw") or {})
    return {}


def merge_result_and_scores(
    chief_report: dict[str, Any] | None = None,
    *,
    board: dict[str, Any] | None = None,
    match: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pick highest-confidence 1X2 and top-2 scorelines across all sources."""
    result_votes: dict[str, float] = {}
    score_weights: dict[str, float] = {}

    def _norm_result(cn: str) -> str:
        text = str(cn or "").strip()
        if not text or text == "—":
            return ""
        if text in _CN_TO_OUTCOME:
            return _OUTCOME_CN[_CN_TO_OUTCOME[text]]
        for label in _OUTCOME_CN.values():
            if label in text:
                return label
        if text in ("观望", "skip"):
            return ""
        return text

    def _vote_result(cn: str, weight: float) -> None:
        norm = _norm_result(cn)
        if norm:
            result_votes[norm] = result_votes.get(norm, 0.0) + weight

    def _vote_score(sc: str, weight: float) -> None:
        text = str(sc or "").strip().split("(")[0].strip()
        if text and text != "—":
            score_weights[text] = score_weights.get(text, 0.0) + weight

    if chief_report:
        analysis = chief_report.get("analysis") or {}
        fp = analysis.get("final_pick") or {}
        _vote_result(str(fp.get("sp") or analysis.get("result_1x2_cn") or ""), 1.05)
        for i, sc in enumerate(analysis.get("likely_scores") or analysis.get("top_scores") or []):
            _vote_score(str(sc), 0.92 - i * 0.08)

    if board:
        rraw = _agent_board_raw(board, "result_1x2")
        if rraw.get("pick_1x2_cn"):
            share = float(rraw.get("vote_share") or 0.5)
            _vote_result(str(rraw["pick_1x2_cn"]), 0.88 * max(0.35, share))
        sraw = _agent_board_raw(board, "scoreline")
        for i, sc in enumerate(sraw.get("top_scores") or []):
            _vote_score(str(sc), 0.95 - i * 0.12)

    if match:
        row = match.get("predict_row") or match
        _vote_result(str(match.get("result_1x2_cn") or match.get("reference_result_1x2_cn") or row.get("赛果预测") or ""), 0.72)
        try:
            from analysis.score_recommend import build_score_recommendation

            sr = build_score_recommendation(match)
            _vote_result(str(sr.get("pick_1x2_cn") or ""), 0.78)
            for i, item in enumerate(sr.get("primary") or []):
                _vote_score(str(item.get("score") or ""), 0.85 - i * 0.1)
        except Exception:
            pass
        raw_scores = match.get("likely_scores") or match.get("likely_scores_detail") or row.get("推荐比分")
        if isinstance(raw_scores, str):
            import re
            parts = re.split(r"[、,，/ ]+", raw_scores)
        elif isinstance(raw_scores, list):
            parts = [str(x) for x in raw_scores]
        else:
            parts = []
        for i, sc in enumerate(parts[:3]):
            _vote_score(sc, 0.55 - i * 0.08)

    result_1x2_cn = ""
    if result_votes:
        result_1x2_cn = max(result_votes.items(), key=lambda x: x[1])[0]
    top_scores = [s for s, _ in sorted(score_weights.items(), key=lambda x: -x[1])[:2]]
    return {"result_1x2_cn": result_1x2_cn, "top_scores": top_scores}


def resolve_best_list_verdict(
    chief_report: dict[str, Any] | None = None,
    *,
    board: dict[str, Any] | None = None,
    match: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Merge Chief / expert board / prediction into one highest-certainty verdict.
    When multiple sources agree on buy_decision, certainty is boosted.
    Hard guards always force conservative decision with high certainty.
    """
    pieces: list[dict[str, Any]] = []
    if chief_report:
        a = dict(chief_report.get("analysis") or {})
        if a:
            a = dict(a)
            a["source"] = "chief"
            a["_certainty"] = _chief_certainty(a)
            pieces.append(a)
    if board:
        a = list_verdict_from_board(board)
        a["_certainty"] = _board_certainty(board, a)
        pieces.append(a)
    if match:
        a = list_verdict_from_prediction(match)
        a["_certainty"] = _prediction_certainty(match, a)
        pieces.append(a)

    if not pieces:
        return {}

    guards = list((board or {}).get("hard_guards") or [])
    if guards:
        certainty = 0.86
        summary = str(guards[0])
        risk = "高"
        for p in pieces:
            if p.get("summary") and p.get("source") == "chief":
                summary = str(p["summary"])
                risk = str(p.get("risk_level") or risk)
                break
        out = {
            "buy_decision": "C 仅参考",
            "risk_level": risk,
            "confidence": _certainty_label(certainty),
            "certainty_score": round(certainty, 2),
            "certainty_label": _certainty_label(certainty),
            "summary": summary[:120],
            "source": "consensus" if len(pieces) > 1 else (pieces[0].get("source") or "board"),
            "agreement": f"{len(pieces)}/{len(pieces)}",
        }
        out.update(merge_result_and_scores(chief_report, board=board, match=match))
        return out

    by_decision: dict[str, list[dict[str, Any]]] = {}
    for p in pieces:
        decision = str(p.get("buy_decision") or "C 仅参考")
        by_decision.setdefault(decision, []).append(p)

    def _group_score(decision: str, group: list[dict[str, Any]]) -> tuple[float, int, float]:
        total = sum(float(x.get("_certainty") or 0) for x in group)
        best = max(float(x.get("_certainty") or 0) for x in group)
        rank = _DECISION_RANK.get(decision, 0)
        return (total + best * 0.25 + rank * 0.05, len(group), best)

    best_decision = max(by_decision.keys(), key=lambda d: _group_score(d, by_decision[d]))
    supporters = by_decision[best_decision]
    best_piece = max(supporters, key=lambda x: float(x.get("_certainty") or 0))
    n_sources = len(pieces)
    n_agree = len(supporters)

    certainty = float(best_piece.get("_certainty") or 0.45)
    if n_agree >= 2:
        certainty = min(1.0, certainty + 0.1 * (n_agree - 1))
    if n_agree == n_sources and n_sources >= 2:
        certainty = min(1.0, certainty + 0.08)

    label = _certainty_label(certainty)
    source = "consensus" if n_agree >= 2 else str(best_piece.get("source") or "board")
    summary = str(best_piece.get("summary") or "").strip()
    if n_agree >= 2 and summary and n_agree < n_sources:
        summary = f"{n_agree}/{n_sources}源一致 · {summary}"
    elif n_agree >= 2 and not summary:
        summary = f"{n_agree}/{n_sources} 源确认 {best_decision}"

    out = {
        "buy_decision": best_decision,
        "risk_level": best_piece.get("risk_level") or "—",
        "confidence": label,
        "certainty_score": round(certainty, 2),
        "certainty_label": label,
        "summary": summary[:120],
        "source": source,
        "agreement": f"{n_agree}/{n_sources}",
    }
    out.update(merge_result_and_scores(chief_report, board=board, match=match))
    return out
