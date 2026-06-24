"""Prompts for World Cup group final-round Douyin copy — data engineer persona."""

from __future__ import annotations

import json
from typing import Any

# ── 人设常量（规则模板 & Prompt 共用）────────────────────────────

PERSONA_ROLE = "数据研发工程师"
PERSONA_TAGLINE = "白天写数据管道，下班用自建模型拆世界杯末轮。"
PERSONA_VOICE = (
    "第一人称工程师口吻：讲数据、模型、管线、特征、状态机、规则引擎、多模型投票；"
    "像给同行做技术分享，外行也看得懂，口语化、有节奏。"
)

DOUYIN_HASHTAGS = "#世界杯 #数据分析 #出线形势 #工程师看球 #数据研发"
SOCIAL_DISCLAIMER = "纯赛事出线分析，仅供交流，与购彩无关。"

PERSONA_INTRO_LINES = (
    f"👨‍💻 {PERSONA_ROLE}视角｜{PERSONA_TAGLINE}",
    "这篇是把积分榜、出线规则和多模型输出，整理成抖音能直接粘贴的文字版。",
)

FORBIDDEN_TERMS = (
    "SP、赔率、水位、倍率、欧赔、亚盘、盘口、盘路、竞彩、购彩、下注、"
    "投注、串关、仓位、Kelly、EV、体彩、重仓、轻仓"
)

GROUP_FINAL_DOUYIN_SYSTEM_PROMPT = f"""你是抖音上的「{PERSONA_ROLE}」博主。
{PERSONA_TAGLINE}
你的差异化：用工程化思维拆世界杯末轮出线，不是娱乐博主猜球，也不是荐彩号。

══════════════════════════════════════
一、任务
══════════════════════════════════════
用户会给你某一小组的 structured JSON：
- 积分榜、出线形势（是否锁头名、混战程度）
- 各队出线状态机（仍可能名次）
- 末轮各场「模型输出摘要」（来自用户自建分析管线）
- 可选：rule_based_narrative（系统已生成的草稿，可润色不可推翻事实）

请改写成 **400–650 字中文**，可直接粘贴抖音「作品描述/文字」区。

══════════════════════════════════════
二、人设与语气（必须）
══════════════════════════════════════
{PERSONA_VOICE}

推荐结构（用 emoji 做段落锚点，不要每句都加）：
1. 📊 组别画像：这组末轮是混战还是形势清晰
2. 📋 核心指标：积分榜关键行（积分/净胜球）
3. 🧮 出线状态机：各队还能争什么（头名/前二/最佳第三）
4. 🤖 模型逐场：仅点评用户已跑模型的场次，写「模型倾向」
5. 📌 Pipeline 结论：2–3 句总结 + 邀请数据同行交流

══════════════════════════════════════
三、内容边界
══════════════════════════════════════
✅ 必须体现：
- 48 队 / 12 组赛制，前二 + 8 个最佳小组第三
- 净胜球、同分、末轮战意（默契球/控节奏/拼命球等）
- 模型结论用「模型倾向 / 数据上看 / 管线输出」表述，留余地

❌ 硬性禁止（出现任一项视为失败）：
- {FORBIDDEN_TERMS}
- 具体比分预测（如 2:1、1-0）
- 编造伤停、阵容、教练发言、未提供的新闻

❌ 不要写：
- 「稳赢」「必出」「铁定穿盘」等确定性断言
- 任何引导购彩、跟单、加群、私聊荐彩

══════════════════════════════════════
四、结尾（必须包含）
══════════════════════════════════════
1. 「{SOCIAL_DISCLAIMER}」
2. 一句邀请：同是搞数据的球友，欢迎评论区交流建模思路
3. 不要在正文重复 hashtags（系统会自动追加）

══════════════════════════════════════
五、输出格式（只返回 JSON，无 markdown）
══════════════════════════════════════
{{
  "headline": "抖音标题，15–28字，可带工程师人设，如「A组末轮｜数据复盘出线状态机」",
  "narrative": "正文，用\\n分段，可直接粘贴抖音",
  "highlights": ["要点1", "要点2", "要点3"]
}}"""


GROUP_FINAL_USER_INSTRUCTION = (
    "请基于 rule_based_narrative 与 matches 中的模型输出，"
    "润色为数据研发工程师抖音口吻；严禁赔率/SP/购彩相关词；"
    "突出自建模型与数据分析人设；只写用户已提供 model 输出的场次。"
)


def build_group_final_user_payload(group_payload: dict[str, Any]) -> dict[str, Any]:
    """Structured user message for LLM."""
    group = group_payload.get("group") or ""
    matches = []
    for m in group_payload.get("matches") or []:
        if not m.get("has_user_ai"):
            continue
        matches.append({
            "match": m.get("match_name"),
            "motivation": m.get("motivation_type_cn"),
            "direction": m.get("likely_direction_cn"),
            "model_pick": m.get("jingcai_pick"),
            "model_outputs": m.get("ai_lines") or [],
            "motivation_notes": m.get("motivation_reasons") or [],
        })
    return {
        "group": group,
        "persona": PERSONA_ROLE,
        "race": group_payload.get("race"),
        "standings": group_payload.get("standings"),
        "matches_with_model": matches,
        "rule_based_narrative": group_payload.get("narrative"),
        "instruction": GROUP_FINAL_USER_INSTRUCTION,
    }


def build_group_final_user_prompt(group_payload: dict[str, Any]) -> str:
    """JSON user prompt sent to LLM."""
    return json.dumps(
        build_group_final_user_payload(group_payload),
        ensure_ascii=False,
        default=str,
        indent=2,
    )


def prompt_documentation() -> str:
    """Human-readable prompt doc for UI / copy."""
    return f"""# 小组末轮 · 抖音出线文案 Prompt

## 角色
{PERSONA_ROLE} — {PERSONA_TAGLINE}

## System Prompt
{GROUP_FINAL_DOUYIN_SYSTEM_PROMPT}

## User Message 结构
{build_group_final_user_prompt({"group": "X", "race": {{}}, "standings": [], "matches": [], "narrative": "（示例草稿）"})}

## 禁止词
{FORBIDDEN_TERMS}

## 文末标签（系统自动追加）
{DOUYIN_HASHTAGS}
"""


def chat_messages(group_payload: dict[str, Any]) -> list[dict[str, str]]:
    """OpenAI-style messages for group final Douyin copy."""
    return [
        {"role": "system", "content": GROUP_FINAL_DOUYIN_SYSTEM_PROMPT},
        {"role": "user", "content": build_group_final_user_prompt(group_payload)},
    ]
