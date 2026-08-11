"""P5: AI 分析打包上下文。

把盘口 + 战绩 + 规则结论打包成结构化 JSON，喂给 AI 或直接展示。
禁止 AI 自行脑补无盘口场。
"""
from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)


def build_ai_match_brief_payload(
    match_name: str,
    *,
    market: dict | None = None,
    form: dict | None = None,
    rule_conclusion: dict | None = None,
    jingcai: dict | None = None,
) -> dict[str, Any]:
    """组装单场 AI 分析 payload。

    Args:
        match_name: "主队 vs 客队"
        market: 盘口信号 {eu, ah, devig, divergence, betfair}
        form: 战绩 {overall, split}
        rule_conclusion: 规则结论 {pick, reasons, p_devig}
        jingcai: 竞彩 {has_sp, sp_home/draw/away}
    """
    missing: list[str] = []

    # 盘口
    market_data = market or {}
    devig = market_data.get("devig") or {}
    if not devig.get("p_home"):
        missing.append("devig")
    if not market_data.get("ah"):
        missing.append("asian")
    if not market_data.get("betfair"):
        missing.append("betfair")

    # 战绩
    form_data = form or {}
    if not form_data.get("overall"):
        missing.append("form")

    # 竞彩
    jc_data = jingcai or {}

    payload = {
        "match": match_name,
        "market": {
            "eu": market_data.get("eu"),
            "ah": market_data.get("ah"),
            "devig": devig,
            "divergence": market_data.get("divergence"),
            "betfair": market_data.get("betfair"),
        },
        "form": form_data,
        "rule_conclusion": rule_conclusion or {},
        "jingcai": jc_data,
        "missing": missing,
    }
    return payload


def payload_to_markdown(payload: dict) -> str:
    """把 payload 转成可读 markdown（给外部 AI 用）。"""
    lines: list[str] = []
    lines.append(f"# 比赛分析：{payload.get('match', '未知')}")
    lines.append("")

    market = payload.get("market") or {}
    devig = market.get("devig") or {}
    if devig.get("p_home") is not None:
        lines.append("## 盘口信号")
        lines.append(f"- 去水隐含概率：主 {devig['p_home']:.1%} / 平 {devig.get('p_draw', 0):.1%} / 客 {devig.get('p_away', 0):.1%}")
        if devig.get("overround"):
            lines.append(f"- 抽水：{devig['overround']:.1%}")
        ah = market.get("ah")
        if ah:
            lines.append(f"- 亚盘：让球 {ah.get('line', '—')}（{ah.get('favored_cn', '—')}方向）")
        bf = market.get("betfair")
        if bf:
            lines.append(f"- 必发：成交 {bf.get('volume_total', 0)/10000:.0f}万，热门 {bf.get('hot_cn', '—')}")
        div = market.get("divergence")
        if div:
            lines.append(f"- 欧亚分歧：{div}")
        lines.append("")

    form = payload.get("form") or {}
    overall = form.get("overall") or {}
    if overall:
        lines.append("## 近期战绩")
        for team_key in ("home_team", "away_team"):
            team = overall.get(team_key)
            if team:
                lines.append(f"- {team.get('summary_cn', team_key)}")
        split = form.get("split") or {}
        h_home = split.get("home_at_home_last_20") or {}
        a_away = split.get("away_at_away_last_20") or {}
        if h_home:
            lines.append(f"- 主队近 {h_home.get('played', 0)} 主场：{h_home.get('w', 0)}胜{h_home.get('d', 0)}平{h_home.get('l', 0)}负")
        if a_away:
            lines.append(f"- 客队近 {a_away.get('played', 0)} 客场：{a_away.get('w', 0)}胜{a_away.get('d', 0)}平{a_away.get('l', 0)}负")
        lines.append("")

    rule = payload.get("rule_conclusion") or {}
    if rule.get("pick"):
        lines.append("## 规则结论")
        lines.append(f"- 倾向：{rule.get('pick_cn', rule['pick'])}（置信度 {rule.get('confidence_cn', '—')}）")
        for r in (rule.get("reasons") or []):
            lines.append(f"  - {r}")
        lines.append("")

    jc = payload.get("jingcai") or {}
    if jc.get("has_sp"):
        lines.append("## 竞彩可购")
        lines.append(f"- SP：{jc.get('sp_home', '—')} / {jc.get('sp_draw', '—')} / {jc.get('sp_away', '—')}")
    else:
        lines.append("## 竞彩")
        lines.append("- 本场无竞彩 / 未开售")
    lines.append("")

    missing = payload.get("missing") or []
    if missing:
        missing_cn = {"devig": "去水概率", "asian": "亚盘", "betfair": "必发", "form": "战绩"}
        parts = [missing_cn.get(m, m) for m in missing]
        lines.append(f"> 缺数据：{'、'.join(parts)}（已降权处理）")

    lines.append("")
    lines.append("---")
    lines.append("请基于以上数据给出：1) 复述去水概率 2) 盘口与战绩是否同向 3) 分歧/必发预警 4) 结论（主/平/客或观望）+ 风险一句")

    return "\n".join(lines)
