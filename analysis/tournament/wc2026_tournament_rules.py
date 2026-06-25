"""FIFA World Cup 2026 format rules — machine-readable + AI prompt blocks."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_GROUPS_PATH = _PROJECT_ROOT / "data" / "wc2026_groups.json"
_BRACKET_PATH = _PROJECT_ROOT / "data" / "wc2026_knockout_bracket.json"

WC2026_FORMAT_SUMMARY = """
2026 世界杯扩军至 48 队、12 个小组（A–L），每组 4 队单循环。
- 每组前 2 名（共 24 队）直接进 32 强。
- 12 个小组第三中积分最高的 8 队进入 32 强（跨组比积分→净胜球→进球，不比相互战绩）。
- 32 强对阵模板在赛前已固定；小组第一/第二路径确定。
- 8 个最佳第三进入哪场 32 强，取决于「哪 8 个组的第三出线」——FIFA Annex C 共 495 种组合，
  全部小组赛结束后自动锁定，赛前只能展示签位池与候选第三。
""".strip()

WC2026_TIEBREAK_GROUP = """
同分排序（FIFA 2026 规程 Art. 13，组内）：
1) 同分球队间相互比赛积分 → 净胜球 → 进球；
2) 仍同分则在该子集内递归上述规则；
3) 仍同分则全组净胜球 → 全组进球 → 公平竞赛 → FIFA 排名。
""".strip()

WC2026_BEST_THIRD = """
12 个小组第三横向排名（决定哪 8 个进 32 强）：
积分 → 净胜球 → 进球（仅在这 12 队之间比，不做相互战绩 mini-league）。
第 9–12 名第三直接出局。
""".strip()

WC2026_KNOCKOUT_PAIRING = """
32 强 16 场对阵结构（赛前固定，见 data/wc2026_knockout_bracket.json）：
- 8 场「组内第二 vs 组内第二」或「第一 vs 第二」固定配对（如 2A vs 2B、1F vs 2C）。
- 8 场「小组第一 vs 最佳第三」，第三来自指定 third_pool（如 1A 对 C/E/F/H/I 五组之一的最佳第三）。
- 第三 never 对第三；同组球队 32 强不相遇。
- K 组第三若晋级，仅可能进 M88（1K 对阵）；L 组第三仅可能进 M80（1L 对阵）——路径最窄。
""".strip()

WC2026_MOTIVATION_HINTS = """
战意与签位（分析时必须结合实时积分榜，不可臆测）：
- 已锁定前二/头名：末轮输赢通常不影响「是否出线」，但可能影响 32 强对手（第一 vs 第二 vs 最佳第三路径不同）。
- 存在「挑对手/控分」：强队可能争第二避开另一半区种子；也可能争最佳第三进相对温和的 first-vs-third 签位。
- 必须争胜：平局无法追平前二积分，且无法达到最佳第三门槛。
- 确认出局：最高可达积分仍低于前二或最佳第三门槛。
- 末轮两场同时开球时，后开球球队可能已知邻组结果后再决策。
""".strip()

WC2026_AI_ANALYSIS_INSTRUCTIONS = """
分析世界杯小组末轮 / 出线形势时，你必须：
1) 以用户提供的实时积分榜、赛程、fixtures 为准，禁止用过期排名。
2) 对每个结论标注依据：积分上限、FIFA 同分规则、 achievable_ranks / locked 状态。
3) 区分「已锁定出线/名次」与「仍开放」——德国类已锁定球队应写清「输赢与出线无关，仅影响签位/轮换」。
4) 给出若最终排名第 1/2/3 时的 32 强签位（固定路径或 third_pool）；第三需说明当前最佳第三排名与签位池。
5) 495 种 Annex C 具体表若未在 payload 中给出，不得编造第三的精确对阵，只能说「池内候选 + 赛后锁定」。
6) 战意判断结合：拼命球 / 默契球 / 开放争头名 / 轮换，与淘汰赛路径一并输出。
""".strip()


@lru_cache(maxsize=1)
def load_groups_config() -> dict[str, Any]:
    if not _GROUPS_PATH.is_file():
        return {}
    return json.loads(_GROUPS_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_bracket_config() -> dict[str, Any]:
    if not _BRACKET_PATH.is_file():
        return {}
    return json.loads(_BRACKET_PATH.read_text(encoding="utf-8"))


def r32_fixture_summary() -> list[dict[str, str]]:
    """Compact list of all 16 R32 slots for prompts."""
    bracket = load_bracket_config()
    rows: list[dict[str, str]] = []
    for m in bracket.get("r32") or []:
        rows.append({
            "match": str(m.get("match") or ""),
            "label": str(m.get("label") or ""),
            "home": str(m.get("home") or ""),
            "away": str(m.get("away") or ""),
            "third_pool": "".join(m.get("third_pool") or []) if m.get("third_pool") else "",
        })
    return rows


def tournament_rules_document() -> dict[str, Any]:
    cfg = load_groups_config()
    bracket = load_bracket_config()
    return {
        "tournament": "2026 FIFA World Cup",
        "format_summary": WC2026_FORMAT_SUMMARY,
        "advance_rule_cn": cfg.get("advance_rule_cn") or "",
        "group_tiebreakers_cn": cfg.get("group_tiebreakers_cn") or [],
        "third_rank_tiebreakers": cfg.get("third_rank_tiebreakers") or [],
        "tiebreak_group": WC2026_TIEBREAK_GROUP,
        "best_third": WC2026_BEST_THIRD,
        "knockout_pairing": WC2026_KNOCKOUT_PAIRING,
        "motivation_hints": WC2026_MOTIVATION_HINTS,
        "ai_instructions": WC2026_AI_ANALYSIS_INSTRUCTIONS,
        "r32_fixtures": r32_fixture_summary(),
        "bracket_notes": bracket.get("notes") or [],
        "bracket_halves": bracket.get("bracket_halves") or {},
    }


def tournament_rules_system_prompt(*, compact: bool = False) -> str:
    """System prompt block for AI analysis / deep analysis / group outlook."""
    doc = tournament_rules_document()
    if compact:
        return "\n\n".join([
            doc["format_summary"],
            doc["tiebreak_group"],
            doc["best_third"],
            doc["knockout_pairing"],
            doc["ai_instructions"],
        ])
    parts = [
        "# 2026 世界杯赛制与淘汰赛规则（项目内置，分析时必须遵守）",
        doc["format_summary"],
        "",
        "## 组内同分",
        doc["tiebreak_group"],
        "",
        "## 最佳第三",
        doc["best_third"],
        "",
        "## 32 强对阵",
        doc["knockout_pairing"],
        "",
        "## 战意提示",
        doc["motivation_hints"],
        "",
        "## 分析要求",
        doc["ai_instructions"],
        "",
        "## R32 固定场次（M73–M88）",
    ]
    for row in doc["r32_fixtures"]:
        pool = f" 池{row['third_pool']}" if row["third_pool"] else ""
        parts.append(f"- M{row['match']}: {row['label']}{pool}")
    for note in doc["bracket_notes"]:
        parts.append(f"- {note}")
    return "\n".join(parts)


def tournament_rules_for_match_context(
    *,
    group: str | None = None,
    outlook: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Payload slice for attach_tournament_context / match AI."""
    base = {
        "rules_version": "wc2026_v1",
        "format_summary": WC2026_FORMAT_SUMMARY,
        "best_third_rule": WC2026_BEST_THIRD,
        "knockout_pairing_summary": WC2026_KNOCKOUT_PAIRING,
        "analysis_instructions": WC2026_AI_ANALYSIS_INSTRUCTIONS,
    }
    if group and outlook:
        grp = next((g for g in (outlook.get("groups") or []) if g.get("group") == group), None)
        if grp:
            base["group_outlook"] = {
                "group": group,
                "group_complete": grp.get("group_complete"),
                "chaos": grp.get("chaos"),
                "teams": [
                    {
                        "team": t.get("team"),
                        "status_cn": t.get("status_cn"),
                        "rank": t.get("rank"),
                        "qualification_locked": t.get("qualification_locked"),
                        "rank_scenarios": t.get("rank_scenarios"),
                    }
                    for t in (grp.get("teams") or [])
                ],
            }
        base["best_third_live"] = outlook.get("best_third_live")
    return base
