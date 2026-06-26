"""Post-match diagnostic agent for explaining why recommendations failed."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any


def _parse_dt(text: str | None) -> datetime | None:
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(str(text)[: len(fmt)], fmt)
        except ValueError:
            continue
    return None


def _lead_hours(run_id: str | None, kickoff_at: str | None) -> float | None:
    if not run_id or len(run_id) < 16:
        return None
    try:
        run_dt = datetime.strptime(run_id[:16], "%Y-%m-%d_%H%M")
    except ValueError:
        return None
    ko_dt = _parse_dt(kickoff_at)
    if not ko_dt:
        return None
    return round((ko_dt - run_dt).total_seconds() / 3600, 1)


def _market_kind(record: dict) -> str:
    pick = str(record.get("pick_jingcai_cn") or "")
    market = str(record.get("jingcai_market") or "")
    if "让球" in pick or "让球" in market:
        return "rqsp"
    if pick and pick not in ("—", "观望", "暂无竞彩"):
        return "sp"
    return "none"


def diagnose_record(record: dict) -> dict[str, Any]:
    """Return structured failure diagnosis for one settled recommendation."""
    lead = _lead_hours(record.get("run_id"), record.get("kickoff_at"))
    market = _market_kind(record)
    tags: list[str] = []
    evidence: list[str] = []
    recommendations: list[str] = []

    pick = record.get("pick_jingcai_cn") or "—"
    actual = f"{record.get('score_text') or '—'} {record.get('result_1x2_cn') or ''}".strip()

    if market == "rqsp":
        tags.append("RQSP")
        evidence.append("竞彩玩法为让球胜平负，错误来自净胜球判断而不只是自然赛果")
        recommendations.append("让球胜平负与普通胜平负分开评估，不进入默认稳健串关")
        handicap = record.get("jingcai_handicap")
        if handicap is not None:
            try:
                h = int(handicap)
                if abs(h) >= 2:
                    tags.append("大让球")
                    evidence.append(f"让球数 {h:+d}，净胜球阈值过高，一球差会改变让胜/让平/让负")
                    recommendations.append("让球绝对值 >= 2 默认观望，必须 AI/人工二次确认")
            except (TypeError, ValueError):
                pass

    ref = record.get("reference_result_1x2_cn")
    if ref and ref not in str(pick):
        tags.append("竞彩与参考分离")
        evidence.append(f"自然赛果参考为 {ref}，但最终竞彩推荐为 {pick}")
        recommendations.append("竞彩方向与自然赛果参考分离时降级或观望")

    conf = record.get("confidence_cn")
    if conf == "低":
        tags.append("低置信")
        evidence.append("赛前置信度为低")
        recommendations.append("低置信不进 2 串 1，只能作为观察项")

    risk = record.get("risk_level_cn")
    if risk in ("升高", "显著升高"):
        tags.append("风险升高")
        evidence.append(f"风险等级为 {risk}")
        recommendations.append("风险升高场次降档；显著升高默认跳过串关")

    ctrl = record.get("control_level_cn")
    if ctrl == "高":
        tags.append("高控盘")
        evidence.append("控盘等级为高，盘口噪声/诱导风险大")
        recommendations.append("高控盘 + 非高置信直接观望")

    line_move = record.get("line_move")
    if line_move not in (None, "", 0, 0.0):
        try:
            mv = float(line_move)
            if abs(mv) >= 0.5:
                tags.append("临终盘波动")
                evidence.append(f"盘口从开盘到终盘移动 {mv:+.2f}")
                recommendations.append("开球前 3 小时内检测到盘口大幅变动时强制重算")
        except (TypeError, ValueError):
            pass

    if lead is not None and lead >= 3:
        tags.append("快照偏旧")
        evidence.append(f"推荐快照距开球约 {lead:g} 小时")
        recommendations.append("开球前 3 小时内不复用旧预测")

    tier = record.get("buy_tier")
    if tier in ("B", "C"):
        tags.append("档位不适合串关")
        evidence.append(f"购买档位为 {record.get('buy_tier_cn') or tier}")
        recommendations.append("daily picks 只允许 A 档 / parlay_eligible")

    if not tags:
        tags.append("常规方向失败")
        evidence.append("未命中但缺少明显风险字段，需要增加更多赛前特征")
        recommendations.append("累计同类样本后再调权重")

    return {
        "fixture_id": record.get("fixture_id"),
        "match_name": record.get("match_name"),
        "kickoff_at": record.get("kickoff_at"),
        "pick": pick,
        "actual": actual,
        "market": market,
        "tags": list(dict.fromkeys(tags)),
        "evidence": list(dict.fromkeys(evidence)),
        "recommendations": list(dict.fromkeys(recommendations)),
        "lead_hours": lead,
    }


def build_review_agent_report(records: list[dict]) -> dict[str, Any]:
    """Overall intelligent diagnostic report for settled misses."""
    misses = [
        r for r in records
        if r.get("pick_jingcai_cn") not in (None, "", "—", "观望", "暂无竞彩")
        and r.get("hit_1x2") is False
    ]
    diagnoses = [diagnose_record(r) for r in misses]
    tag_counter: Counter[str] = Counter()
    rec_counter: Counter[str] = Counter()
    market_counter: Counter[str] = Counter()
    for d in diagnoses:
        market_counter[d.get("market") or "unknown"] += 1
        tag_counter.update(d.get("tags") or [])
        rec_counter.update(d.get("recommendations") or [])

    headline = "暂无错误样本"
    if diagnoses:
        top = tag_counter.most_common(3)
        headline = "主要错因：" + " / ".join(f"{k}×{v}" for k, v in top)

    prompt = build_review_agent_prompt(diagnoses)
    return {
        "ok": True,
        "miss_count": len(diagnoses),
        "headline": headline,
        "tag_counts": [{"tag": k, "count": v} for k, v in tag_counter.most_common()],
        "market_counts": [{"market": k, "count": v} for k, v in market_counter.most_common()],
        "policy_suggestions": [
            {"suggestion": k, "count": v}
            for k, v in rec_counter.most_common(8)
        ],
        "cases": diagnoses[:20],
        "prompt": prompt,
    }


def build_review_agent_prompt(cases: list[dict]) -> str:
    """Prompt for a stronger LLM analyst, using already-normalized evidence."""
    payload = [
        {
            "match": c.get("match_name"),
            "kickoff_at": c.get("kickoff_at"),
            "pick": c.get("pick"),
            "actual": c.get("actual"),
            "market": c.get("market"),
            "tags": c.get("tags"),
            "evidence": c.get("evidence"),
        }
        for c in cases[:12]
    ]
    return (
        "你是足球竞彩赛后诊断智能体。请只基于下面 JSON 做错误归因，"
        "不要事后诸葛亮，不要编造未给出的信息。\n\n"
        "任务：\n"
        "1. 按整体层面总结主要错因。\n"
        "2. 分别分析临盘/终盘波动、竞彩让球、亚盘、战意、缓存时效、置信度/风控是否导致错误。\n"
        "3. 给出可以落到程序规则的修复项，按 P0/P1/P2 排序。\n"
        "4. 说明哪些错误不能靠规则完全避免，只能降级或观望。\n\n"
        f"错误样本 JSON：\n{payload}\n"
    )
