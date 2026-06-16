"""DeepSeek prompt templates, writing hints, and JSON validation."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ai_schema import (
    ANALYSIS_JSON_KEYS,
    ACTUARY_JSON_KEYS,
    CONFIDENCE_CN_TO_EN,
    DEEP_ANALYSIS_JSON_KEYS,
    EXPERT_OUTPUT_KEYS,
    FORBIDDEN_AI_KEYS,
    RECOMMENDATION_CN_TO_1X2,
    RECOMMENDATION_KEYS,
    RESULT_CN,
    VALID_1X2,
    VALID_AH,
    VALID_CONF,
    VALID_OU,
)
from analysis_context import build_analysis_context

EXPERT_SYSTEM_PROMPT = """你现在是一位拥有 20 年经验的顶级体育赛事精算师（Actuary）与风控复核员。
你的工作不是「预测」比赛一定会发生什么，而是汇总系统提供的结构化数据，给出概率上的大概方向、期望值（Expected Value, EV）与风险决策。
你必须绝对理性，摒弃任何球迷情感与主观偏好。

══════════════════════════════════════
〇、竞彩投注（最高优先级）
══════════════════════════════════════
用户只购买国内竞彩。最终推荐必须对应 actuary_input.竞彩SP 中「可售玩法」：
- 有胜平负 SP → recommendation / result_1x2_cn 即竞彩胜平负（主胜/平局/客胜）
- 仅让球胜平负 → result_1x2_cn 仍写真实赛果方向；另必填 jingcai_rq_pick（胜/平/负）作为竞彩购买方向
- 无竞彩数据 → recommendation=放弃参与，result_1x2=skip
禁止输出用户无法购买的欧赔/亚盘方向作为最终推荐。

══════════════════════════════════════
一、核心原则
══════════════════════════════════════
1. 只做概率评估与 EV 判断，不做情绪化赛果猜测。
2. 所有数字（概率、样本量、盘口、水位、比分）只能来自用户提供的 actuary_input 与 structured_data，禁止编造。
3. reference_baseline 是本地规则引擎的量化参考；你主要负责复核、降级或在证据充分时修正，不得凭主观直觉推翻。
4. 输出的是「可执行决策」：参与 / 小注 / 观望；不是稳赢承诺。若证据冲突或 edge 不足，优先放弃参与。
5. 只返回下方 JSON，禁止额外文字、markdown 代码块。

══════════════════════════════════════
二、强制推理步骤（必须按序完成，写在 actuary_reasoning / analysis_basis 中）
══════════════════════════════════════
Step 1 基准概率：引用 actuary_input / structured_data 中代码预计算的去水隐含概率 → implied_probability，禁止自行重算或改写数字。
Step 2 历史修正：引用 precomputed_ev / historical_similar_samples 的实际打出频率；若历史概率显著高于隐含概率，可能存在 EV+。
Step 3 风险折损：结合 trap_control_signals、external_factors、双方近期状态（若有）对 adjusted_probability 做合理折损。
Step 4 欧亚互转暗线：必须解读 market_patterns 中欧转亚、亚转欧、line_gap、consistency 与 patterns，判断隐藏意图是「盘赔一致」「欧热亚浅诱主」「亚深阻上」「盘赔分裂」「平局分流」「诱下」或「数据不足」。
Step 5 资金博弈：结合 live_movement_signals、market_patterns 判断水位变动是引流/诱盘还是真实定价偏移。
Step 6 EV 决策：比较 adjusted_probability 与隐含概率，判定 value_bet；无正 EV、数据冲突明显、或风险吞噬 edge 时 recommendation=放弃参与。
Step 7 结果表述：final_verdict 必须写成「倾向/大概方向 + 风险条件」，不得写成确定性断言。

══════════════════════════════════════
三、输入数据说明
══════════════════════════════════════
用户会提供 actuary_input（人类可读标签）与 structured_data（完整 JSON）。
优先阅读 actuary_input；需要细节时查 structured_data。
external_factors 中未提供的项（如天气/新闻）不得臆造，应标注「数据未接入」。

══════════════════════════════════════
四、必须输出的 JSON（精算师报告 + 投注建议）
══════════════════════════════════════
【精算师核心 — 必填】
- implied_probability: {"主胜":"x%","平":"y%","客胜":"z%"}  ← 去水后的欧赔隐含概率
- adjusted_probability: {"主胜":"x%","平":"y%","客胜":"z%"}  ← 经历史/基本面/风险修正后
- value_bet: true | false  ← 是否存在正期望值机会
- recommendation: 主胜 | 平 | 客胜 | 放弃参与  ← 只有正 EV 且风险可接受时才给方向
- confidence_level: 高 | 中 | 低
- actuary_reasoning: 不超过 100 字，简述 EV 判断核心逻辑；必须体现「倾向」而非确定预测

【投注明细 — 必填，与 recommendation 一致】
- result_1x2: home | draw | away | skip
- result_1x2_cn: 主胜 | 平局 | 客胜 | 观望
- likely_scores: 3 个最可能比分字符串数组
- asian_handicap_pick: home | away | skip
- asian_handicap_cn: 如「上盘（主队 -0.5）」或「观望」
- asian_handicap_reason: 一句话
- over_under_hint: over_2.5 | under_2.5 | neutral
- over_under_cn: 大2.5 | 小2.5 | 中性
- confidence: high | medium | low
- confidence_cn: 高 | 中 | 低

【竞彩可售 — 若 actuary_input.竞彩SP.仅让球=true 则必填】
- jingcai_rq_pick: home | draw | away | skip  ← 让球胜平负下的推荐（胜/平/负）
- jingcai_rq_pick_cn: 胜 | 平 | 负 | 观望
- jingcai_rq_reason: 一句话，说明在让球线下为何选该方向（须引用比分推演或概率）
- 仅让球场次：result_1x2 仍写真实赛果方向；jingcai_rq_pick 写可购买的让球选项

【论证分析 — 必填】
- historical_overview: 2-3 句样本概览
- market_vs_history_analysis: 数组 3 条（主胜/平局/客胜 EV 对比）
- odds_movement_analysis: 初盘→临盘 + 资金博弈解读
- asian_handicap_deep_dive: 盘口深度 + 上下盘历史赢盘率
- score_pattern_analysis: 高频比分 + 场均进球
- historical_cases: ≥3 条，严格来自 required_historical_cases
- final_verdict: 3-5 句精算师结论
- key_risks: 2 条客观风险
- analysis_basis: 4-7 条，【层级】格式，含【EV结论】与【综合结论】

══════════════════════════════════════
五、一致性约束
══════════════════════════════════════
- recommendation 与 result_1x2 / result_1x2_cn 必须一致
- confidence_level 与 confidence / confidence_cn 必须一致
- value_bet=false 时 recommendation 应为「放弃参与」，result_1x2=skip
- likely_scores 方向须与 recommendation 一致
- 样本不足或控盘极高时，confidence_level 应偏低，优先「放弃参与」
- 竞彩仅让球时：必须输出 jingcai_rq_pick；用推荐比分验证让球(+N)/(-N) 下是胜/平/负
- precomputed_ev.edge 低于正EV阈值时，除非有明确补充证据，否则 value_bet=false
- 若 reference_baseline 与你的方向不同，必须在 analysis_basis 写清楚哪一层证据足以推翻；否则只允许降级为观望
- odds_movement_analysis 必须先写【欧亚互转暗线】：欧赔隐含盘口、实际亚盘、差值、亚转欧粗推与隐藏意图，再写水位/资金
- analysis_basis 必须包含【欧亚互转】一条；若欧亚互转提示诱盘或分裂，不能给高置信
- 禁止使用「稳胆」「必出」「确定」「稳赢」等确定性表述

══════════════════════════════════════
六、输出 JSON 结构示例
══════════════════════════════════════
{
  "implied_probability": {"主胜":"42.3%","平":"28.1%","客胜":"29.6%"},
  "adjusted_probability": {"主胜":"45.0%","平":"26.0%","客胜":"29.0%"},
  "value_bet": true,
  "recommendation": "主胜",
  "confidence_level": "中",
  "actuary_reasoning": "历史主胜58%高于隐含42%，升盘降水支撑上盘，存在正EV。",
  "result_1x2": "home",
  "result_1x2_cn": "主胜",
  "likely_scores": ["1-0","2-1","1-1"],
  "asian_handicap_pick": "home",
  "asian_handicap_cn": "上盘（主队 -0.5）",
  "asian_handicap_reason": "...",
  "over_under_hint": "under_2.5",
  "over_under_cn": "小2.5",
  "confidence": "medium",
  "confidence_cn": "中",
  "historical_overview": "...",
  "market_vs_history_analysis": ["主胜：...", "平局：...", "客胜：..."],
  "odds_movement_analysis": "...",
  "asian_handicap_deep_dive": "...",
  "score_pattern_analysis": "...",
  "historical_cases": [{"date":"...","match":"...","lesson":"..."}],
  "final_verdict": "...",
  "key_risks": ["...", "..."],
  "analysis_basis": ["【基准概率】...", "【EV结论】...", "【综合结论】..."]
}"""

# Legacy locked-baseline prompt (full text kept for --locked-baseline)
LOCKED_SYSTEM_PROMPT = """你是足球数据分析师。用户会提供结构化历史统计数据、初盘/临盘分层样本、机构控盘解读，以及 baseline_recommendation（系统已算好的最终推荐）。

══════════════════════════════════════
一、硬性红线（必须遵守）
══════════════════════════════════════
1. 禁止给出或修改最终推荐。baseline_recommendation 是既定结果，你的全部输出只为佐证其合理性，不得提出相反结论。
2. 所有百分比、样本量、盘口、比分、场次数字只能使用用户提供的输入数据，禁止编造。
3. 只返回下方指定的 JSON 结构，禁止额外文字、注释、markdown 代码块，禁止添加任何推荐字段。

══════════════════════════════════════
二、三层分析逻辑（写作时必须体现）
══════════════════════════════════════
第一层「初盘赛事概率」：historical_open_* / open_asian_sample_analysis → 赛事本身概率（主依据）
第二层「机构风控解读」：control_analysis + trap_analysis + market_patterns（欧转亚/亚转欧、盘赔套路）
第三层「综合结论」：初盘概率 × 规律权重 × 诱盘惩罚 + 临盘信号 → 论证 baseline 合理

══════════════════════════════════════
二点五、盘赔套路（odds_movement_analysis 必须引用）
══════════════════════════════════════
1. 先写 market_patterns.conversion_summary（欧赔隐含盘口 vs 实际亚盘）
2. 逐条引用 market_patterns.patterns[].name 与 routine（若有）
3. 常见套路释义：
   - 亚盘偏浅：欧赔更热但亚盘不开深 → 诱主
   - 诱上三部曲：升盘+上盘降水
   - 盘赔分裂·阻主：亚盘升盘但欧赔主胜上调
   - 平局分流：平赔降、亚盘未升
   - 浅盘+欧热：欧赔主降但亚盘偏浅
4. 套路是机构风控/引流手法，不等于赛果判断改变

══════════════════════════════════════
三、强制内容项（9 项缺一不可）
══════════════════════════════════════
1. historical_overview：2-3 句，说明总样本量、数据来源、统计维度（初盘+临盘）
2. market_vs_history_analysis：数组 3 条（主胜/平局/客胜），统一句式见 writing_templates
3. odds_movement_analysis：初盘→临盘完整分析；**必须先写欧转亚/亚转欧对照与识别到的套路**，再写机构控赔付/资金对冲
4. asian_handicap_deep_dive：对照 eu_to_ah_line 与 ah_line_live；上下盘历史赢盘率 + 水位位置 + 赔付平衡逻辑
5. score_pattern_analysis：高频比分 + 场均进球，支撑大小球判断
6. historical_cases：≥3 条，必须严格基于 required_historical_cases（不得自造场次）
7. final_verdict：3-5 句，核心佐证 baseline，体现初盘→风控→综合三层逻辑
8. key_risks：数组 2 条，客观描述风险，不否定 baseline；优先从 suggested_risks 中选 2 条改写
9. analysis_basis：数组 4-7 条，逐条列出推荐结论的数据依据（见二点六）

══════════════════════════════════════
二点六、分析依据 analysis_basis（必须输出）
══════════════════════════════════════
analysis_basis 是「推荐结论从何而来」的条目化清单，每条必须：
- 以【层级名】开头，后接一句完整说明
- 数字只能来自 evidence_brief.layers 或 baseline_recommendation，禁止编造
- 必须覆盖 evidence_brief.required_layers 中的每一层（不可遗漏）
- 最后一层必须是【综合结论】，点明 baseline 的胜平负/比分/亚盘/大小球/置信度

示例（数字仅为示意）：
["【初盘赛事概率】初盘亚盘相似 312 场，主胜 42.3%…", "【综合结论】推荐主胜，比分 1-0/2-0…"]

══════════════════════════════════════
四、标准句式（优先套用 writing_templates，可微调措辞不可改数字）
══════════════════════════════════════
historical_overview 模板：
「本次分析基于 {N} 组历史赛事样本，数据取自近年欧洲主流赔率与亚洲盘口统计数据库，同时叠加世界杯/预选赛/美洲杯样本做交叉匹配。初盘亚盘相似 {open_ah} 场、临盘亚盘 {live_ah} 场，统计维度包含欧赔、亚盘及全场赛果。」

market_vs_history_analysis 每条模板：
「{赛果}：市场隐含概率 {X}% vs 历史赛果频率 {Y}%，相差 {Z} 个百分点，说明 {解读}」

odds_movement_analysis 模板要点：
亚盘初盘→临盘 + 欧赔初→临；**必须先写 market_patterns.conversion_summary**；
再写识别到的套路（诱上三部曲/亚盘偏浅/盘赔分裂等）；说明机构控赔付/引流意图。

asian_handicap_deep_dive 模板：
必须对照 eu_to_ah_line 与 ah_line_live：一致则参考性高，偏浅/偏深按 market_patterns 解读。

score_pattern_analysis 模板：
「同盘口历史赛事中，高频打出比分依次为 {比分1}、{比分2}、{比分3}；区间内场均总进球数为 {X} 球，结合进球数据可支撑本场大小球方向判断。」

historical_cases 每条模板：
{"date":"...", "match":"队伍A X-X 队伍B", "lesson":"本场盘口走势与当前赛事高度相似，最终赛果印证该盘口区间{倾向}具备较高参考性"}

final_verdict 模板要点（3-5句）：
综合初盘历史样本概率、盘赔变动轨迹与经典历史案例，论证 baseline 各项推荐有充分数据依据；说明规律参考价值（pattern_weight）与控盘强度；整体盘面无明显反常则强调参考价值。

══════════════════════════════════════
五、输出 JSON 结构（仅此 9 个 key）
══════════════════════════════════════
{
  "historical_overview": "...",
  "market_vs_history_analysis": ["主胜：...", "平局：...", "客胜：..."],
  "odds_movement_analysis": "...",
  "asian_handicap_deep_dive": "...",
  "score_pattern_analysis": "...",
  "historical_cases": [{"date":"...","match":"...","lesson":"..."}],
  "final_verdict": "...",
  "key_risks": ["...", "..."],
  "analysis_basis": ["【初盘赛事概率】...", "【综合结论】..."]
}"""

SYSTEM_PROMPT = EXPERT_SYSTEM_PROMPT

RISK_LIBRARY = [
    "大赛临场投注量巨大，机构后续或再次大幅调盘，改变原有盘面逻辑。",
    "球队临场伤病、战术调整、现场氛围等场外因素，可能干扰历史规律落地。",
    "部分历史样本赛事战意、赛制与本场存在细微差异，存在规律失效可能。",
    "短时间内资金单向涌入，引发机构极端控盘，增加赛果不确定性。",
    "初盘样本与临盘样本统计口径存在差异，交叉验证时需注意样本来源权重。",
    "欧赔与亚盘信号偶发背离，单一维度规律可能出现短期失真。",
    "深盘或浅盘极端区间样本稀疏，统计结论外推需谨慎。",
    "机构临盘剧烈调水后，历史同初盘规律的参考价值会进一步下降。",
]


def _pct_num(v) -> float | None:
    if v is None:
        return None
    return round(float(v) * 100, 1)


def _water_level(home_w, away_w) -> str:
    vals = [v for v in (home_w, away_w) if v is not None]
    if not vals:
        return "中位"
    avg = sum(float(v) for v in vals) / len(vals)
    if avg >= 0.98:
        return "高位"
    if avg <= 0.88:
        return "低位"
    return "中位"


def _line_direction(open_line, live_line) -> str:
    if open_line is None or live_line is None:
        return "维持盘口"
    d = float(live_line) - float(open_line)
    if d < -0.01:
        return "升盘"
    if d > 0.01:
        return "降盘"
    return "维持盘口"


def _gap_sentence(label: str, gap_info: dict) -> str:
    m = _pct_num(gap_info.get("market_implied"))
    h = _pct_num(gap_info.get("historical_rate"))
    z = round(abs(gap_info.get("gap", 0)) * 100, 1)
    interp = gap_info.get("interpretation", "两者接近")
    return f"{label}：市场隐含概率 {m}% vs 历史赛果频率 {h}%，相差 {z} 个百分点，说明 {interp}。"


def build_required_historical_cases(ctx: dict, *, limit: int = 3) -> list[dict]:
    """Lock case source to first N highlights — AI must not invent matches."""
    highlights = (ctx.get("open_asian_sample_analysis") or {}).get("highlights") or []
    if len(highlights) < limit:
        live_hl = (ctx.get("live_asian_sample_analysis") or {}).get("highlights") or []
        seen = {h.get("match") for h in highlights}
        for h in live_hl:
            if h.get("match") not in seen:
                highlights.append(h)
                seen.add(h.get("match"))
            if len(highlights) >= limit:
                break

    cases = []
    for h in highlights[:limit]:
        tendency = h.get("result") or "赛果"
        cases.append({
            "date": h.get("date"),
            "match": h.get("match"),
            "result": tendency,
            "ah_line": h.get("ah_line"),
            "lesson_template": (
                f"本场盘口走势与当前赛事高度相似，最终赛果为{tendency}，"
                f"印证该盘口区间{tendency}倾向具备较高参考性"
            ),
        })
    return cases


def pick_suggested_risks(ctx: dict, *, count: int = 2) -> list[str]:
    """Pick risks based on control level and sample quality."""
    control = ctx.get("control_analysis") or {}
    level = control.get("level", "low")
    open_ah = (ctx.get("historical_open_asian") or {}).get("sample_count", 0)
    live_ah = (ctx.get("historical_live_asian") or {}).get("sample_count", 0)

    indices: list[int] = []
    if level == "high":
        indices.extend([0, 3, 7])
    elif level == "medium":
        indices.extend([0, 3])
    else:
        indices.extend([1, 2])

    if abs(open_ah - live_ah) > max(open_ah, live_ah) * 0.3:
        indices.append(4)

    mp = ctx.get("market_patterns") or {}
    if mp.get("consistency") == "ah_shallow":
        indices.append(5)
    if mp.get("patterns"):
        indices.append(7)

    picked: list[str] = []
    sc = ctx.get("style_clash") or {}
    if sc.get("available") and sc.get("variance_level") == "high":
        headline = sc.get("headline") or ""
        if headline:
            picked.append(f"球风相克变数偏高：{headline}")

    for i in indices:
        if i < len(RISK_LIBRARY) and RISK_LIBRARY[i] not in picked:
            picked.append(RISK_LIBRARY[i])
        if len(picked) >= count:
            break

    for r in RISK_LIBRARY:
        if len(picked) >= count:
            break
        if r not in picked:
            picked.append(r)
    return picked[:count]


def build_actuary_input_brief(ctx: dict) -> dict:
    """
    Human-readable tags for the actuary user prompt.
    All numbers are pre-computed locally — AI must not invent alternatives.
    """
    cur = ctx.get("current_odds") or {}
    ah_open = cur.get("asian_handicap_open") or {}
    ah_live = cur.get("asian_handicap_live") or {}
    eu_open = cur.get("european_open") or {}
    eu_live = cur.get("european_live") or {}
    mp = ctx.get("market_patterns") or {}
    signals = ctx.get("market_signals") or {}
    movement = ctx.get("odds_movement") or {}
    hist = ctx.get("historical_open_asian") or {}
    hist_eu = ctx.get("historical_open_eu") or {}
    gaps = ctx.get("market_vs_history_gap") or {}
    control = ctx.get("control_analysis") or {}
    trap = ctx.get("trap_analysis") or {}
    ref = ctx.get("reference_baseline") or ctx.get("baseline_recommendation") or {}

    ah_line = ah_live.get("line")
    ah_open_line = ah_open.get("line")
    line_txt = f"主让 {abs(ah_line)} 球" if ah_line is not None and ah_line < 0 else (
        f"主受 {ah_line} 球" if ah_line is not None and ah_line > 0 else "平手"
    ) if ah_line is not None else "—"

    n = hist.get("sample_count") or 0
    hw = _pct_num(hist.get("home_win_rate"))
    dr = _pct_num(hist.get("draw_rate"))
    aw = _pct_num(hist.get("away_win_rate"))
    if n >= 1 and hw is not None:
        hist_summary = (
            f"检索到初盘亚盘相似样本共 {n} 场，"
            f"主胜 {round(hw * n / 100):.0f} 场({hw}%)，"
            f"平局 {round(dr * n / 100):.0f} 场({dr}%)，"
            f"客胜 {round(aw * n / 100):.0f} 场({aw}%)"
        )
    else:
        n_eu = hist_eu.get("sample_count") or 0
        hist_summary = (
            f"初盘亚盘样本不足（{n} 场），欧赔扩展样本 {n_eu} 场"
            if n_eu else "历史相似样本不足，EV 评估置信度应降低"
        )

    eu_imp = ctx.get("market_implied_probability") or {}
    imp_parts = []
    if eu_imp:
        for label, key in (("主胜", "home"), ("平", "draw"), ("客胜", "away")):
            v = eu_imp.get(key)
            if v is not None:
                imp_parts.append(f"{label}{_pct_num(v)}%")
    implied_hint = " / ".join(imp_parts) if imp_parts else "欧赔隐含概率数据不足"

    mvh_lines = []
    for label in ("主胜", "平局", "客胜"):
        if label in gaps:
            g = gaps[label]
            m = _pct_num(g.get("market_implied"))
            h = _pct_num(g.get("historical_rate"))
            z = round(abs(g.get("gap", 0)) * 100, 1)
            ev_hint = "可能存在 EV+" if (g.get("gap") or 0) > 0.03 else (
                "可能被高估" if (g.get("gap") or 0) < -0.03 else "接近公允"
            )
            mvh_lines.append(
                f"{label}：隐含 {m}% vs 历史 {h}%，差 {z}pp → {ev_hint}"
            )

    ah_move = movement.get("asian") or {}
    eu_move = movement.get("european") or {}
    live_moves = []
    if ah_move:
        live_moves.append(
            f"亚盘 {ah_move.get('open_line')}→{ah_move.get('live_line')} "
            f"({ah_move.get('direction', '—')})，"
            f"水位 {ah_move.get('open_water')}→{ah_move.get('live_water')}"
        )
    if eu_move:
        live_moves.append(
            f"欧赔 主{eu_move.get('home')} 平{eu_move.get('draw')} 客{eu_move.get('away')}"
        )
    if signals.get("water_summary"):
        live_moves.append(signals["water_summary"])
    if signals.get("line_summary"):
        live_moves.append(signals["line_summary"])

    pat_names = [p.get("name") for p in (mp.get("patterns") or []) if p.get("name")]
    consistency_cn = {
        "aligned": "欧亚基本一致",
        "ah_shallow": "亚盘偏浅",
        "ah_deep": "亚盘偏深",
        "unknown": "数据不足",
    }.get(mp.get("consistency") or "unknown", mp.get("consistency") or "unknown")
    hidden_flags = []
    for p in mp.get("patterns") or []:
        name = p.get("name")
        routine = p.get("routine")
        bias = p.get("bias")
        if name or routine:
            hidden_flags.append({
                "套路": name or "未命名",
                "隐藏含义": routine or "",
                "倾向/风险": bias or "neutral",
            })
    hidden_read = "盘赔对照数据不足"
    if mp.get("conversion_summary"):
        if mp.get("consistency") == "aligned":
            hidden_read = "欧亚基本一致，盘口参考性相对较高，但仍需结合水位判断是否诱盘"
        elif mp.get("consistency") == "ah_shallow":
            hidden_read = "欧赔更支持热门方向，但亚盘没有给足门槛，常见欧热亚浅/诱热门"
        elif mp.get("consistency") == "ah_deep":
            hidden_read = "亚盘比欧赔隐含更深，可能是真看上盘，也可能是抬高门槛阻上"
        else:
            hidden_read = "需结合套路 notes 判断隐藏意图"
    ah_to_eu = mp.get("ah_to_eu_sketch") or {}
    trap_notes = trap.get("notes") or []
    external = []
    if trap_notes:
        external.extend(trap_notes[:3])
    if control.get("payout_pressure_note"):
        external.append(control["payout_pressure_note"])
    for r in ctx.get("suggested_risks") or []:
        if r not in external:
            external.append(r)
    tf = ctx.get("team_recent_form") or {}
    if tf.get("available"):
        external.insert(0, ctx.get("team_recent_form_headline") or "双方近期国际赛状态已接入")
    sc = ctx.get("style_clash") or {}
    if sc.get("available") and sc.get("variance_level") in ("medium", "high"):
        external.insert(0, ctx.get("style_clash_headline") or sc.get("headline") or "")
    external.append("天气/伤病新闻 API：未接入，不得臆造")
    if not trap_notes and control.get("level") == "low":
        external.insert(0, "无明显诱盘/突发利空信号")

    ref_pick = ref.get("result_1x2_cn") or "—"
    ref_conf = ref.get("confidence_cn") or "—"
    ev = ctx.get("precomputed_ev") or {}
    ev_base = ev.get("baseline") or {}
    ev_block = {
        "概率来源": ev.get("probability_source") or "代码预计算",
        "正EV阈值": f"{round((ev.get('threshold_positive_edge') or 0.03) * 100, 1)}pp",
        "规则引擎方向": ev_base.get("pick") or ref_pick,
        "市场去水概率": (
            f"{_pct_num(ev_base.get('market_implied_probability'))}%"
            if ev_base.get("market_implied_probability") is not None else "—"
        ),
        "历史修正概率": (
            f"{_pct_num(ev_base.get('historical_adjusted_probability'))}%"
            if ev_base.get("historical_adjusted_probability") is not None else "—"
        ),
        "edge": (
            f"{ev_base.get('edge_pp')}pp"
            if ev_base.get("edge_pp") is not None else "—"
        ),
        "value_hint": ev_base.get("value_hint") or "unknown",
        "说明": ev_base.get("note") or "样本或赔率不足，不能确认正EV",
    }

    bf = ctx.get("betfair") or {}
    bf_block = "未接入"
    if bf.get("has_data"):
        pct = bf.get("volume_pct") or {}
        bf_block = {
            "总成交量": bf.get("volume_total"),
            "主平客占比": f"主{pct.get('home')}% / 平{pct.get('draw')}% / 客{pct.get('away')}%",
            "成交价": bf.get("trade_price"),
            "必发指数": bf.get("bf_index"),
            "数据提点": bf.get("summary") or "—",
        }

    jc = ctx.get("jingcai") or {}
    jc_block = "未接入"
    jc_mode = "none"
    if jc.get("has_sp") or jc.get("has_rqsp"):
        jc_mode = "sp" if jc.get("has_sp") else "rqsp"
        hcap = jc.get("handicap_label") or jc.get("handicap") or "—"
        jc_block = {
            "场次号": jc.get("match_num") or "—",
            "可售玩法": "胜平负" if jc.get("has_sp") else f"仅让球胜平负（让球 {hcap}）",
            "仅让球": not jc.get("has_sp") and jc.get("has_rqsp"),
            "胜平负SP": (
                f"{jc.get('sp_home')}/{jc.get('sp_draw')}/{jc.get('sp_away')}"
                if jc.get("has_sp") else "未开售"
            ),
            "让球": hcap,
            "让球SP": (
                f"{jc.get('rqsp_home')}/{jc.get('rqsp_draw')}/{jc.get('rqsp_away')}"
                if jc.get("has_rqsp") else "—"
            ),
            "让球结算说明": (
                f"主队进球 + ({hcap}) 后与客队比较：大于=胜，等于=平，小于=负"
                if jc_mode == "rqsp" else "—"
            ),
        }

    return {
        "match": ctx.get("match_name") or ref.get("match") or "—",
        "当前盘口与水位": {
            "亚盘": f"{line_txt}，初盘 {ah_open_line} → 临盘 {ah_line}，"
                    f"水位 上{ah_live.get('home_water')}/下{ah_live.get('away_water')}",
            "欧赔": f"胜 {eu_live.get('home')} / 平 {eu_live.get('draw')} / 负 {eu_live.get('away')}",
            "欧赔初盘": f"胜 {eu_open.get('home')} / 平 {eu_open.get('draw')} / 负 {eu_open.get('away')}",
            "去水隐含概率": implied_hint,
            "欧转亚对照": mp.get("conversion_summary") or "—",
        },
        "欧亚互转暗线": {
            "欧赔隐含亚盘": mp.get("eu_to_ah_line"),
            "实际临盘亚盘": mp.get("ah_line_live"),
            "盘口差值": mp.get("line_gap"),
            "一致性": consistency_cn,
            "亚转欧粗推": ah_to_eu or "—",
            "隐藏解读": hidden_read,
            "识别套路": hidden_flags or "未识别典型套路",
            "分析要求": "AI 必须判断这是盘赔一致、欧热亚浅诱主、亚深阻上、盘赔分裂、平局分流、诱下或数据不足",
        },
        "临场波动指标": live_moves or ["盘口变动数据不足"],
        "历史相似样本库": {
            "summary": hist_summary,
            "ev_gap_analysis": mvh_lines or ["样本不足，无法做 EV 对比"],
            "上下盘赢盘率": (
                f"上盘 { _pct_num(hist.get('ah_upper_win_rate')) }%，"
                f"下盘 { _pct_num(hist.get('ah_lower_win_rate')) }%"
                if hist.get("ah_upper_win_rate") is not None else "—"
            ),
        },
        "预计算EV": ev_block,
        "资金博弈与控盘": {
            "控盘强度": control.get("level_cn") or "—",
            "规律权重": f"{int((control.get('pattern_weight') or 1) * 100)}%",
            "识别套路": "、".join(pat_names) if pat_names else "未识别典型套路",
            "轨迹": control.get("trajectory") or "—",
        },
        "必发资金分布": bf_block,
        "竞彩SP": jc_block,
        "双方近期状态": _team_form_block(ctx),
        "战术变数": _style_clash_block(ctx),
        "外部干扰因子": external[:5],
        "规则引擎参考": {
            "胜平负": ref_pick,
            "比分": "、".join((ref.get("likely_scores_detail") or ref.get("likely_scores") or [])[:3]) or "—",
            "亚盘": ref.get("asian_handicap_cn") or "—",
            "置信度": ref_conf,
            "说明": "本地量化模型结论，可采纳、修正或推翻",
        },
    }


def _team_form_block(ctx: dict) -> Any:
    tf = ctx.get("team_recent_form") or {}
    if not tf.get("available"):
        return tf.get("note") or "未接入（队名无法映射或无国际赛记录）"
    home = tf.get("home") or {}
    away = tf.get("away") or {}
    block: dict[str, Any] = {
        "摘要": ctx.get("team_recent_form_headline") or "",
        "主队": {
            "战绩": home.get("summary"),
            "近场": [
                {
                    "日期": m.get("date"),
                    "对手": m.get("opponent"),
                    "主客": m.get("venue"),
                    "比分": m.get("score"),
                    "赛果": m.get("result"),
                    "欧赔": m.get("eu_odds"),
                }
                for m in (home.get("recent_matches") or [])[:5]
            ],
        },
        "客队": {
            "战绩": away.get("summary"),
            "近场": [
                {
                    "日期": m.get("date"),
                    "对手": m.get("opponent"),
                    "主客": m.get("venue"),
                    "比分": m.get("score"),
                    "赛果": m.get("result"),
                    "欧赔": m.get("eu_odds"),
                }
                for m in (away.get("recent_matches") or [])[:5]
            ],
        },
        "近一年交锋": tf.get("head_to_head") or [],
        "数据说明": tf.get("note"),
    }
    return block


def _style_clash_block(ctx: dict) -> Any:
    sc = ctx.get("style_clash") or {}
    if not sc.get("available"):
        return sc.get("headline") or "样本不足，未作球风相克判断"
    hs = sc.get("home_style") or {}
    aws = sc.get("away_style") or {}
    return {
        "变数等级": sc.get("variance_cn"),
        "结论": sc.get("headline"),
        "说明": sc.get("detail"),
        "关注": sc.get("watch"),
        "主队风格": f"{hs.get('style_cn')}（{hs.get('reason')}）",
        "客队风格": f"{aws.get('style_cn')}（{aws.get('reason')}）",
        "权重": "低，仅作防一手参考，不得替代盘口结论",
    }


def build_evidence_brief(ctx: dict, baseline: dict, *, expert: bool = False) -> dict:
    """
    Pre-compute structured evidence for analysis_basis.
    AI must cite these layers; fallback lines used if AI omits the field.
    """
    layers: list[dict] = []
    lines: list[str] = []

    open_ah = (ctx.get("historical_open_asian") or {}).get("sample_count", 0)
    open_eu = (ctx.get("historical_open_eu") or {}).get("sample_count", 0)
    open_prob = baseline.get("open_probability_summary") or ""
    open_pick = baseline.get("open_result_1x2_cn") or "—"

    t1 = (
        f"初盘相似样本：亚盘 {open_ah} 场、欧赔扩展 {open_eu} 场；"
        f"{open_prob or '样本不足'}"
    )
    layers.append({"id": "open_prob", "title": "初盘赛事概率", "text": t1})
    lines.append(f"【初盘赛事概率】{t1}")

    gaps = ctx.get("market_vs_history_gap") or {}
    pick_cn = baseline.get("result_1x2_cn", "")
    gap_key = {"主胜": "主胜", "平局": "平局", "客胜": "客胜"}.get(pick_cn, pick_cn)
    if gap_key in gaps:
        g = gaps[gap_key]
        m = _pct_num(g.get("market_implied"))
        h = _pct_num(g.get("historical_rate"))
        z = round(abs(g.get("gap", 0)) * 100, 1)
        interp = g.get("interpretation", "")
        t2 = f"推荐方向 {pick_cn}：市场隐含 {m}% vs 初盘历史 {h}%，差 {z} 个百分点，{interp}"
    elif gaps:
        parts = []
        for label in ("主胜", "平局", "客胜"):
            if label in gaps:
                g = gaps[label]
                parts.append(
                    f"{label} 市场{_pct_num(g.get('market_implied'))}%/历史{_pct_num(g.get('historical_rate'))}%"
                )
        t2 = "市场 vs 初盘历史：" + "；".join(parts)
    else:
        t2 = "市场 vs 初盘历史：数据不足或未达样本门槛"
    layers.append({"id": "market_vs_history", "title": "市场vs历史", "text": t2})
    lines.append(f"【市场vs历史】{t2}")

    mp = ctx.get("market_patterns") or {}
    conv = mp.get("conversion_summary") or "盘赔对照数据不足"
    pat_names = [p.get("name") for p in (mp.get("patterns") or []) if p.get("name")]
    pat_part = f"，识别套路：{'、'.join(pat_names)}" if pat_names else "，未识别典型诱盘套路"
    ah_to_eu = mp.get("ah_to_eu_sketch") or {}
    ah_to_eu_txt = ""
    if isinstance(ah_to_eu, dict) and ah_to_eu:
        ah_to_eu_txt = (
            f"，亚转欧粗推主{ah_to_eu.get('home')}/"
            f"平{ah_to_eu.get('draw')}/客{ah_to_eu.get('away')}"
        )
    t3 = f"{conv}{ah_to_eu_txt}{pat_part}"
    layers.append({"id": "market_patterns", "title": "欧亚互转", "text": t3})
    lines.append(f"【欧亚互转】{t3}")

    control = ctx.get("control_analysis") or {}
    trap = ctx.get("trap_analysis") or {}
    pw = int((control.get("pattern_weight") or 1) * 100)
    trap_notes = trap.get("notes") or []
    trap_head = "；".join(trap_notes[:3]) if trap_notes else "无明显诱盘信号"
    flagged = trap.get("flagged_direction")
    flag_txt = f"，标记方向 {flagged}" if flagged else ""
    t4 = (
        f"控盘{control.get('level_cn', '—')}，规律权重 {pw}%，轨迹 {control.get('trajectory', '—')}；"
        f"{trap_head}{flag_txt}"
    )
    layers.append({"id": "trap_control", "title": "诱盘/控盘", "text": t4})
    lines.append(f"【诱盘/控盘】{t4}")

    wc = ctx.get("tournament_opening") or {}
    if wc.get("sample_size"):
        headline = wc.get("summary") or ""
        actions = wc.get("traits") or []
        t_wc = headline
        if actions:
            t_wc += " 建议：" + "；".join(actions[:3])
        layers.append({"id": "wc_opening", "title": "本届开盘特征", "text": t_wc.strip()})
        lines.append(f"【本届开盘特征】{t_wc.strip()}")

    tf_head = ctx.get("team_recent_form_headline") or ""
    if tf_head and (ctx.get("team_recent_form") or {}).get("available"):
        layers.append({"id": "team_form", "title": "双方近期状态", "text": tf_head})
        lines.append(f"【双方近期状态】{tf_head}")

    sc = ctx.get("style_clash") or {}
    if sc.get("available") and sc.get("variance_level") in ("medium", "high"):
        sc_txt = ctx.get("style_clash_headline") or sc.get("headline") or ""
        layers.append({"id": "style_clash", "title": "战术变数", "text": sc_txt})
        lines.append(f"【战术变数】{sc_txt}")

    if open_pick and open_pick != "—" and open_pick != pick_cn:
        t5 = f"初盘单项最高 {open_pick}，经临盘诱盘惩罚/控盘调整后，综合推荐 {pick_cn}"
        layers.append({"id": "adjustment", "title": "临盘调整", "text": t5})
        lines.append(f"【临盘调整】{t5}")

    scores = baseline.get("likely_scores_detail") or baseline.get("likely_scores") or []
    score_txt = "、".join(scores[:3]) if scores else "—"
    ah = baseline.get("asian_handicap_cn") or "—"
    ah_reason = baseline.get("asian_handicap_reason") or ""
    ou = baseline.get("over_under_cn") or "—"
    conf = baseline.get("confidence_cn") or "—"
    conf_reason = baseline.get("confidence_reason") or ""
    conf_tail = f"（{conf_reason}）" if conf_reason else ""
    t6 = (
        f"胜平负 {pick_cn}；推荐比分 {score_txt}；"
        f"亚盘 {ah}" + (f"（{ah_reason}）" if ah_reason else "") + f"；"
        f"大小球 {ou}；置信度 {conf}{conf_tail}"
    )
    if expert:
        t6 += "。你可采纳、修正或推翻，须在 analysis_basis 说明若不一致的原因"
        layers.append({"id": "reference", "title": "规则引擎参考", "text": t6})
        lines.append(f"【规则引擎参考】{t6}")
    else:
        layers.append({"id": "conclusion", "title": "综合结论", "text": t6})
        lines.append(f"【综合结论】{t6}")

    required = [layer["title"] for layer in layers]
    return {
        "layers": layers,
        "lines": lines,
        "required_layers": required,
    }


def build_writing_templates(ctx: dict) -> dict:
    """Pre-fill standard sentence templates with computed numbers."""
    cur = ctx.get("current_odds") or {}
    ah_open = cur.get("asian_handicap_open") or {}
    ah_live = cur.get("asian_handicap_live") or {}
    eu_open = cur.get("european_open") or {}
    eu_live = cur.get("european_live") or {}

    open_ah = (ctx.get("historical_open_asian") or {}).get("sample_count", 0)
    live_ah = (ctx.get("historical_live_asian") or {}).get("sample_count", 0)
    open_eu = (ctx.get("historical_open_eu") or {}).get("sample_count", 0)
    total = max(open_ah, live_ah, open_eu)
    hist_total = ctx.get("history_total_in_db", 0)

    hist_ref = ctx.get("historical_open_asian") or ctx.get("historical_open_eu") or {}
    upper = _pct_num(hist_ref.get("ah_upper_win_rate"))
    lower = _pct_num(hist_ref.get("ah_lower_win_rate"))
    avg_goals = hist_ref.get("avg_total_goals")

    open_analysis = ctx.get("open_asian_sample_analysis") or {}
    score_top = open_analysis.get("score_top") or []
    top_scores = [s.get("score") if isinstance(s, dict) else s for s in score_top[:3]]
    while len(top_scores) < 3:
        top_scores.append("—")

    gaps = ctx.get("market_vs_history_gap") or {}
    mvh_lines = []
    for label in ("主胜", "平局", "客胜"):
        if label in gaps:
            mvh_lines.append(_gap_sentence(label, gaps[label]))

    control = ctx.get("control_analysis") or {}
    pw = int((control.get("pattern_weight") or 1) * 100)
    mp = ctx.get("market_patterns") or {}
    conv = mp.get("conversion_summary") or ""
    routines = mp.get("routine_notes") or []
    pat_names = [p.get("name") for p in (mp.get("patterns") or []) if p.get("name")]
    routine_txt = "；".join(routines[:4]) if routines else "未识别典型诱盘套路"
    pat_line = f"识别套路：{'、'.join(pat_names)}。" if pat_names else ""
    ah_to_eu = mp.get("ah_to_eu_sketch") or {}
    if isinstance(ah_to_eu, dict) and ah_to_eu:
        ah_to_eu_txt = (
            f"亚转欧粗推主胜约 {ah_to_eu.get('home')}、"
            f"平赔约 {ah_to_eu.get('draw')}、客胜约 {ah_to_eu.get('away')}。"
        )
    else:
        ah_to_eu_txt = "亚转欧粗推数据不足。"
    hidden_hint = {
        "aligned": "盘赔基本一致，欧亚互相验证，盘口参考性较高",
        "ah_shallow": "欧赔更热但亚盘偏浅，隐藏风险偏向诱热门/诱上盘",
        "ah_deep": "亚盘比欧赔更深，隐藏信息可能是真看上盘或抬门槛阻上",
        "unknown": "欧亚互转数据不足，不能据此强化方向",
    }.get(mp.get("consistency") or "unknown", "欧亚互转需结合水位和套路判断")

    return {
        "historical_overview": (
            f"本次分析基于 {total} 组历史赛事样本（全库 {hist_total} 场），"
            f"数据取自近年欧洲主流赔率与亚洲盘口统计数据库，"
            f"同时叠加世界杯/预选赛/美洲杯样本做交叉匹配。"
            f"初盘亚盘相似 {open_ah} 场、临盘亚盘 {live_ah} 场、初盘欧赔扩展 {open_eu} 场，"
            f"统计维度包含欧赔、亚盘及全场赛果。"
        ),
        "market_vs_history_analysis": mvh_lines,
        "odds_movement_analysis": (
            (f"【欧亚互转暗线】{conv}。" if conv else "【欧亚互转暗线】盘赔对照数据不足。")
            + ah_to_eu_txt
            + f"隐藏解读：{hidden_hint}。"
            + (f"{pat_line}" if pat_line else "")
            + f"亚盘初盘开出 {ah_open.get('line')}，初始水位上 {ah_open.get('home_water')}/"
            f"下 {ah_open.get('away_water')}，临盘调整为 {ah_live.get('line')}，"
            f"水位变动至上 {ah_live.get('home_water')}/下 {ah_live.get('away_water')}，"
            f"整体 {_line_direction(ah_open.get('line'), ah_live.get('line'))}；"
            f"欧赔主 {eu_open.get('home')}→{eu_live.get('home')}、"
            f"平 {eu_open.get('draw')}→{eu_live.get('draw')}、"
            f"客 {eu_open.get('away')}→{eu_live.get('away')}。"
            f"套路解读：{routine_txt}。"
            f"控盘强度 {control.get('level_cn', '—')}，轨迹 {control.get('trajectory', '—')}，"
            f"规律参考价值 {pw}%。"
            f"{control.get('payout_pressure_note', '')}"
            " 临盘变动更反映机构控赔付与资金对冲，不等于对赛果判断的根本改变。"
        ),
        "asian_handicap_deep_dive": (
            f"欧转亚隐含盘口约 {mp.get('eu_to_ah_line')}，实际临盘 {mp.get('ah_line_live')}，"
            f"一致性 {mp.get('consistency', 'unknown')}（差 {mp.get('line_gap')}）。"
            f"{ah_to_eu_txt}"
            f"该盘口区间下，历史上盘赢盘率 {upper}%，下盘赢盘率 {lower}%；"
            f"当前临场水位处于 {_water_level(ah_live.get('home_water'), ah_live.get('away_water'))}，"
            f"机构通过水位调整平衡两端赔付压力，规避大额资金集中投注带来的亏损风险。"
        ),
        "score_pattern_analysis": (
            f"同盘口历史赛事中，高频打出比分依次为 {top_scores[0]}、{top_scores[1]}、{top_scores[2]}；"
            f"区间内场均总进球数为 {round(avg_goals, 2) if avg_goals is not None else 'n/a'} 球，"
            f"结合进球数据可支撑本场大小球方向判断。"
        ),
        "final_verdict_hint": (
            f"综合初盘历史样本概率（规律权重 {pw}%）、盘赔变动轨迹与历史案例，"
            f"论证 baseline 推荐具备数据依据；控盘{control.get('level_cn', '低')}时"
            f"{'需警惕规律打折' if pw < 100 else '规律参考价值较高'}。"
        ),
    }


def enrich_analysis_context(
    payload: dict,
    *,
    baseline: dict | None = None,
    mode: str = "expert",
    output_root: str | Path = "output/service",
) -> dict:
    bl = baseline
    if bl is None:
        from recommend import build_recommendation, recommendation_to_baseline
        bl = recommendation_to_baseline(build_recommendation(payload))
    expert = mode == "expert"
    ctx = build_analysis_context(payload, baseline=bl)
    from analysis_context import attach_tournament_context
    attach_tournament_context(ctx, output_root)
    poll = payload.get("poll_meta") or {}
    if poll.get("jingcai"):
        ctx["jingcai"] = poll["jingcai"]
    if poll.get("betfair"):
        ctx["betfair"] = poll["betfair"]
    if poll.get("captured_at"):
        ctx["poll_captured_at"] = poll["captured_at"]
    ctx["mode"] = mode
    ctx["reference_baseline"] = bl
    ctx["writing_templates"] = build_writing_templates(ctx)
    ctx["required_historical_cases"] = build_required_historical_cases(ctx, limit=3)
    ctx["suggested_risks"] = pick_suggested_risks(ctx, count=2)
    ctx["evidence_brief"] = build_evidence_brief(ctx, bl, expert=expert)
    ctx["actuary_input"] = build_actuary_input_brief(ctx)
    ctx["writing_templates"]["analysis_basis"] = ctx["evidence_brief"]["lines"]
    ctx["allowed_json_keys"] = list(EXPERT_OUTPUT_KEYS if expert else ANALYSIS_JSON_KEYS)
    return ctx


def build_expert_user_prompt(payload: dict, baseline: dict) -> str:
    ctx = enrich_analysis_context(payload, baseline=baseline, mode="expert")
    actuary = ctx.get("actuary_input") or {}
    return (
        "请严格按 SYSTEM 要求，以精算师身份输出纯 JSON（精算师报告 + 投注明细 + 论证分析）。\n"
        "══════════════════════════════════════\n"
        "【精算师输入 — actuary_input】\n"
        "以下标签由本地数据库/规则引擎预计算，禁止编造替代数字：\n\n"
        f"{json.dumps(actuary, ensure_ascii=False, indent=2)}\n\n"
        "══════════════════════════════════════\n"
        "【推理要求】\n"
        "1. 按 Step1→Step5 完成 EV 评估，写入 actuary_reasoning 与 analysis_basis。\n"
        "2. implied_probability 须引用 actuary_input 中「预计算EV」或「去水隐含概率」，不得自行重算。\n"
        "3. adjusted_probability 须引用 precomputed_ev、historical_similar_samples、双方近期状态与 external_factors 修正。\n"
        "4. value_bet=false 时 recommendation=放弃参与，result_1x2=skip。\n"
        "5. 若竞彩SP.仅让球=true，必须额外输出 jingcai_rq_pick / jingcai_rq_pick_cn / jingcai_rq_reason。\n"
        "6. historical_cases ≥3 条，必须来自 required_historical_cases。\n"
        "7. analysis_basis 须覆盖 evidence_brief 各层，含【EV结论】。\n"
        "8. final_verdict 写成概率性决策：倾向、参与价值、风险条件；不得写稳赢/必出。\n\n"
        "══════════════════════════════════════\n"
        "【完整结构化数据 — structured_data】\n"
        f"{json.dumps(ctx, ensure_ascii=False, indent=2)}"
    )


def build_locked_user_prompt(payload: dict, baseline: dict) -> str:
    ctx = enrich_analysis_context(payload, baseline=baseline, mode="locked")
    ctx["baseline_recommendation"] = baseline
    return (
        "请严格按 SYSTEM 要求输出纯 JSON（9 个 key，无多余字段）。\n"
        "优先套用 writing_templates 中的标准句式与数字；historical_cases 必须基于 "
        "required_historical_cases（至少 3 条，不得自造场次）；key_risks 从 suggested_risks "
        "选 2 条客观改写；analysis_basis 必须覆盖 evidence_brief.required_layers 每一层，"
        "数字引用 evidence_brief.layers 或 baseline_recommendation，可微调措辞不可改数字。\n"
        "baseline_recommendation 是既定推荐，你只论证，不得修改或提出相反结论。\n\n"
        f"{json.dumps(ctx, ensure_ascii=False, indent=2)}"
    )


def build_user_prompt(payload: dict, baseline: dict, *, mode: str = "expert") -> str:
    if mode == "locked":
        return build_locked_user_prompt(payload, baseline)
    return build_expert_user_prompt(payload, baseline)


def _extract_json_text(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text


def _validate_recommendation_fields(data: dict) -> None:
    r = data.get("result_1x2")
    if r is not None and r not in VALID_1X2:
        raise ValueError(f"result_1x2 无效: {r}")
    ah = data.get("asian_handicap_pick")
    if ah is not None and ah not in VALID_AH:
        raise ValueError(f"asian_handicap_pick 无效: {ah}")
    ou = data.get("over_under_hint")
    if ou is not None and ou not in VALID_OU:
        raise ValueError(f"over_under_hint 无效: {ou}")
    conf = data.get("confidence")
    if conf is not None and conf not in VALID_CONF:
        raise ValueError(f"confidence 无效: {conf}")
    scores = data.get("likely_scores")
    if scores is not None and not isinstance(scores, list):
        raise ValueError("likely_scores 必须是数组")


def _score_matches_pick(score: str, pick: str) -> bool:
    m = re.search(r"(\d+)\s*[-:：]\s*(\d+)", str(score))
    if not m:
        return True
    home, away = int(m.group(1)), int(m.group(2))
    if pick == "home":
        return home > away
    if pick == "draw":
        return home == away
    if pick == "away":
        return away > home
    return True


def _normalize_business_constraints(data: dict) -> dict:
    """Enforce final-pick invariants before AI output can override baseline."""
    if data.get("value_bet") is False:
        data["recommendation"] = "放弃参与"
        data["result_1x2"] = "skip"
        data["result_1x2_cn"] = "观望"
        data["confidence"] = "low"
        data["confidence_cn"] = "低"
        data["confidence_level"] = "低"
        return data

    rec_cn = (data.get("recommendation") or "").strip()
    mapped = RECOMMENDATION_CN_TO_1X2.get(rec_cn)
    if mapped and data.get("result_1x2") and data["result_1x2"] != mapped:
        raise ValueError(
            f"AI recommendation 与 result_1x2 不一致: {rec_cn} vs {data['result_1x2']}"
        )
    if mapped and not data.get("result_1x2"):
        data["result_1x2"] = mapped
        data["result_1x2_cn"] = RESULT_CN.get(mapped, rec_cn)

    conf_cn = (data.get("confidence_level") or data.get("confidence_cn") or "").strip()
    if conf_cn:
        en = CONFIDENCE_CN_TO_EN.get(conf_cn)
        if en:
            data["confidence_level"] = conf_cn
            data["confidence_cn"] = conf_cn
            data["confidence"] = en

    pick = data.get("result_1x2")
    if pick in ("home", "draw", "away") and isinstance(data.get("likely_scores"), list):
        kept = [s for s in data["likely_scores"] if _score_matches_pick(str(s), pick)]
        if kept:
            data["likely_scores"] = kept[:3]
        else:
            raise ValueError("AI likely_scores 与推荐方向全部不一致")

    return data


def _normalize_actuary_output(data: dict) -> dict:
    """Map actuary core fields to legacy recommendation keys when missing."""
    rec_cn = (data.get("recommendation") or "").strip()
    if rec_cn and not data.get("result_1x2"):
        pick = RECOMMENDATION_CN_TO_1X2.get(rec_cn)
        if pick:
            data["result_1x2"] = pick
            data["result_1x2_cn"] = RESULT_CN.get(pick, rec_cn)

    conf_cn = (data.get("confidence_level") or "").strip()
    if conf_cn and not data.get("confidence"):
        en = CONFIDENCE_CN_TO_EN.get(conf_cn)
        if en:
            data["confidence"] = en
            data["confidence_cn"] = conf_cn

    reasoning = (data.get("actuary_reasoning") or "").strip()
    if reasoning:
        if not data.get("final_verdict"):
            data["final_verdict"] = reasoning
        if not data.get("summary"):
            data["summary"] = reasoning[:200]

    if data.get("value_bet") is False and not data.get("result_1x2"):
        data["result_1x2"] = "skip"
        data["result_1x2_cn"] = "观望"
        if not data.get("recommendation"):
            data["recommendation"] = "放弃参与"

    return _normalize_business_constraints(data)


def parse_expert_json(content: str) -> dict[str, Any]:
    """Parse AI actuary/expert output: EV report + recommendation + analysis."""
    data = json.loads(_extract_json_text(content))
    if not isinstance(data, dict):
        raise json.JSONDecodeError("root must be object", content, 0)
    data = _normalize_actuary_output(data)
    if not data.get("result_1x2") and not data.get("recommendation"):
        raise ValueError("AI 未输出 result_1x2 或 recommendation")
    if not data.get("result_1x2"):
        raise ValueError("AI recommendation 无法映射为 result_1x2")
    _validate_recommendation_fields(data)
    if not data.get("result_1x2_cn") and data.get("result_1x2") in RESULT_CN:
        data["result_1x2_cn"] = RESULT_CN[data["result_1x2"]]
    if not data.get("actuary_reasoning") and data.get("final_verdict"):
        data["actuary_reasoning"] = str(data["final_verdict"])[:100]
    return data


def parse_analysis_json(content: str) -> dict[str, Any]:
    """Extract and validate locked-baseline analysis JSON."""
    data = json.loads(_extract_json_text(content))
    if not isinstance(data, dict):
        raise json.JSONDecodeError("root must be object", content, 0)

    bad = FORBIDDEN_AI_KEYS & set(data.keys())
    if bad:
        raise ValueError(f"AI 输出含禁止字段: {', '.join(sorted(bad))}")

    return data


DEEP_ANALYSIS_SYSTEM_PROMPT = """你是一位资深体育赛事首席精算师与风控负责人，负责对「已完成首轮 AI 精算分析」的比赛做二次深度研判。
首轮分析已完成 EV 评估与基础论证；你的任务是站在更高视角做综合、挑刺、降噪，并落地到竞彩可执行方案。
你输出的是概率性决策，不是确定性赛果预测；证据冲突、edge 不足或风险过高时，最优结论可以是观望。

══════════════════════════════════════
一、输入说明
══════════════════════════════════════
用户会提供：
- prior_analyses：各模型首轮精算结论（含 EV、推荐、analysis_basis 等）
- match_context：最新盘口、竞彩 SP、临盘变动、必发占比等
- rule_baseline：规则引擎量化参考（可采纳或推翻，须说明）

禁止编造输入中不存在的数字、样本量、历史场次。

══════════════════════════════════════
二、深度分析任务（必须全部完成）
══════════════════════════════════════
1. 多模型综合：若 prior_analyses 含多个模型，说明一致点与分歧点，给出你的最终立场。
2. 推翻检验：首轮推荐若存在样本不足/高控盘/模型分歧，必须明确是否维持、降级或改为观望。
3. 比分深度：score_outlook 须给出 primary（最可能2-3个）、secondary（备选1-2个）、upset_watch（冷门1个），
   并说明为何不是千篇一律的 1-0/2-0；须结合场均进球、大小球方向与让球线推演。
4. 竞彩落地：final_pick 必须是用户可购买的竞彩方向（胜平负 SP 或让球胜平负），与 jingcai 数据一致。
5. 仓位建议：stake_advice 明确「不参与 / 娱乐小注 / 标准仓位 / 仅观察」及理由。
6. 赛前关注：pre_match_watchlist 2-4 条，写开赛前若出现何种盘口/水位变化应改变结论。
7. 风控红线：不得使用「稳胆」「必出」「确定」「稳赢」；高控盘/样本不足/模型分歧时不得给高置信。

══════════════════════════════════════
三、输出 JSON（纯 JSON，无 markdown）
══════════════════════════════════════
{
  "headline": "一句话核心结论（≤30字）",
  "deep_verdict": "3-5句深度综合结论，必须体现倾向与不确定性",
  "final_pick": "竞彩可购方向，如 主胜 / 让球(-1) 胜 / 观望",
  "final_pick_reason": "为何选该玩法（须引用 prior 与盘口）",
  "confidence_level": "高 | 中 | 低",
  "stake_advice": "仓位建议一句话",
  "score_outlook": {
    "primary": ["2-1", "1-0"],
    "secondary": ["1-1"],
    "upset_watch": ["0-2"]
  },
  "model_synthesis": "多模型综合（单模型则写首轮结论复核）",
  "contrarian_case": "最可能的翻车场景",
  "handicap_deep": "亚盘深度判断（上/下盘、水位陷阱）",
  "over_under_deep": "大小球深度判断",
  "pre_match_watchlist": ["若临场升盘则…", "若平赔再降则…"],
  "key_risks": ["风险1", "风险2"],
  "analysis_layers": ["【模型复核】...", "【比分推演】...", "【竞彩方案】...", "【综合结论】..."]
}"""


def _compact_prior_analysis(pred: dict, *, label: str = "") -> dict[str, Any]:
    """Extract first-pass AI fields for deep-analysis input."""
    row = pred.get("predict_row") or {}
    scores = pred.get("likely_scores_detail") or pred.get("likely_scores") or []
    if isinstance(scores, list):
        score_txt = "、".join(str(s) for s in scores[:3])
    else:
        score_txt = str(scores) if scores else str(row.get("推荐比分") or "")
    from jingcai_pick import final_recommendation_cn
    return {
        "label": label or pred.get("ai_provider_label") or "精算师",
        "model": pred.get("ai_model") or "",
        "recommendation": pred.get("recommendation") or row.get("胜平负") or pred.get("result_1x2_cn"),
        "jingcai_pick": final_recommendation_cn(pred),
        "likely_scores": score_txt,
        "asian_handicap_cn": row.get("亚盘") or pred.get("asian_handicap_cn"),
        "over_under_cn": row.get("大小球") or pred.get("over_under_cn"),
        "confidence_cn": row.get("置信度") or pred.get("confidence_cn"),
        "value_bet": pred.get("value_bet"),
        "implied_probability": pred.get("implied_probability"),
        "adjusted_probability": pred.get("adjusted_probability"),
        "actuary_reasoning": pred.get("actuary_reasoning") or "",
        "final_verdict": pred.get("final_verdict") or "",
        "analysis_basis": pred.get("analysis_basis") or [],
        "key_risks": pred.get("key_risks") or [],
        "score_pattern_analysis": pred.get("score_pattern_analysis") or "",
        "odds_movement_analysis": pred.get("odds_movement_analysis") or "",
        "asian_handicap_deep_dive": pred.get("asian_handicap_deep_dive") or "",
    }


def build_deep_analysis_user_prompt(bundle: dict[str, Any]) -> str:
    return (
        "请严格按 SYSTEM 要求输出纯 JSON（深度分析二次研判）。\n"
        "══════════════════════════════════════\n"
        "【首轮 AI 精算结论 — prior_analyses】\n"
        f"{json.dumps(bundle.get('prior_analyses') or [], ensure_ascii=False, indent=2)}\n\n"
        "══════════════════════════════════════\n"
        "【比赛上下文 — match_context】\n"
        f"{json.dumps(bundle.get('match_context') or {}, ensure_ascii=False, indent=2)}\n\n"
        "══════════════════════════════════════\n"
        "【规则引擎参考 — rule_baseline】\n"
        f"{json.dumps(bundle.get('rule_baseline') or {}, ensure_ascii=False, indent=2)}\n\n"
        "请完成深度综合：挑刺首轮结论、细化比分分布、给出可执行的竞彩方案与仓位建议。"
    )


def parse_deep_analysis_json(content: str) -> dict[str, Any]:
    data = json.loads(_extract_json_text(content))
    if not isinstance(data, dict):
        raise json.JSONDecodeError("root must be object", content, 0)
    missing = [k for k in ("headline", "deep_verdict", "final_pick", "confidence_level") if not data.get(k)]
    if missing:
        raise ValueError(f"深度分析缺少必填字段: {', '.join(missing)}")
    outlook = data.get("score_outlook")
    if outlook is not None and not isinstance(outlook, dict):
        raise ValueError("score_outlook 必须是对象")
    for key in ("pre_match_watchlist", "key_risks", "analysis_layers"):
        val = data.get(key)
        if val is not None and not isinstance(val, list):
            raise ValueError(f"{key} 必须是数组")
    return data
