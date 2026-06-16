"""AI-selected 2-leg parlay from the dashboard match list."""

from __future__ import annotations

import json
from typing import Any

from ai_prompt import _extract_json_text
from ai_profiles import _cursor_profile, _deepseek_profile
from custom_parlay import analyze_custom_parlay
from daily_picks import _best_actionable_pick, _combined_odds, _eu_odds, _kickoff_date, load_kickoff_map
from deepseek_client import chat
from jingcai_pick import actionable_jingcai_pick, final_recommendation_cn


SYSTEM_PROMPT = """你是竞彩2串1风控筛选助手。你只能从用户给出的候选 fixture_id 中选择2串1组合。

目标：结合初盘、实时盘口、欧赔变化、欧亚分歧、历史相似样本胜率、已有模型推荐，选出当前列表中最适合的两组2串1：
- safe：相对稳健，宁可赔率低一些。
- yield：在风险可接受前提下提高组合赔率，不要纯博冷。

规则：
1. 优先选择胜平负(sp)可购方向；让球(rqsp)只有在证据非常强时才选。
2. 不要只看单场胜率，要考虑两场组合风险叠加。
3. 初盘支持但实时盘变弱、欧赔挺但亚盘不跟、平赔下调、诱盘/控盘/过热，均要降级。
4. 每组两场必须来自同一个 match_date；用户提供的候选已经按同一天过滤，禁止跨天组合。
5. safe 与 yield 尽量不要完全相同；候选不足时可重叠，但 reason 必须说明。
6. 如果候选整体质量差，也必须选相对最合理的两组，但 reason 要明确“小仓位/不重仓”。
7. 禁止编造候选外比赛、赔率、伤停或新闻。

只返回 JSON：
{
  "options": [
    {
      "tier": "safe",
      "label": "稳健2串1",
      "legs": [{"fixture_id": "123", "pick_cn": "主胜"}, {"fixture_id": "456", "pick_cn": "主胜"}],
      "headline": "一句话结论",
      "reason": "为什么选这两场",
      "risk_notes": ["风险1"],
      "stake_advice": "仓位建议"
    },
    {
      "tier": "yield",
      "label": "提赔2串1",
      "legs": [{"fixture_id": "789", "pick_cn": "主胜"}, {"fixture_id": "456", "pick_cn": "主胜"}],
      "headline": "一句话结论",
      "reason": "为什么这组赔率更合适",
      "risk_notes": ["风险1"],
      "stake_advice": "仓位建议"
    }
  ]
}"""


def _profile(provider: str):
    provider = (provider or "deepseek").strip().lower()
    if provider == "cursor":
        return _cursor_profile()
    if provider == "deepseek":
        return _deepseek_profile()
    raise ValueError("provider 仅支持 deepseek 或 cursor")


def _odds_move(m: dict) -> dict[str, Any]:
    snap = m.get("odds_snapshot") or {}
    return {
        "ah_open": {
            "line": snap.get("ah_open_line"),
            "home_water": snap.get("ah_open_home_water"),
            "away_water": snap.get("ah_open_away_water"),
        },
        "ah_realtime": {
            "line": snap.get("ah_line"),
            "home_water": snap.get("ah_home_water"),
            "away_water": snap.get("ah_away_water"),
        },
        "eu_open": {
            "home": snap.get("eu_open_home"),
            "draw": snap.get("eu_open_draw"),
            "away": snap.get("eu_open_away"),
        },
        "eu_realtime": {
            "home": snap.get("eu_home"),
            "draw": snap.get("eu_draw"),
            "away": snap.get("eu_away"),
        },
    }


def _similarity_brief(m: dict) -> dict[str, Any]:
    sim = m.get("similarity_analysis") or {}

    def brief(blocks):
        out = []
        for b in blocks or []:
            if not b or not b.get("count"):
                continue
            out.append({
                "title": b.get("title"),
                "count": b.get("count"),
                "rate": b.get("rate_text"),
                "top_scores": b.get("top_scores", [])[:4],
            })
        return out

    return {
        "open": brief(sim.get("open")),
        "realtime_vs_history_close": brief(sim.get("live")),
    }


def _candidate(m: dict, kickoff_map: dict | None) -> dict[str, Any] | None:
    row = m.get("predict_row") or {}
    jc = actionable_jingcai_pick(m)
    if not jc:
        return None
    actionable = _best_actionable_pick(m)
    pick_key = (jc or {}).get("pick_key") or (actionable or {}).get("pick_key")
    if not pick_key or pick_key == "skip":
        return None
    sp = (jc or {}).get("sp") or (m.get("jingcai_pick_info") or {}).get("jingcai_sp")
    eu = _eu_odds(m, pick_key)
    odds = float(sp) if sp else (float(eu) if eu else None)
    return {
        "fixture_id": str(m.get("fixture_id") or ""),
        "match": m.get("match") or row.get("比赛") or "",
        "match_date": _kickoff_date(m, kickoff_map or {}) or "未知日期",
        "suggested_pick": final_recommendation_cn(m),
        "pick_key": pick_key,
        "jingcai_market": (jc or {}).get("market"),
        "jingcai_sp": sp,
        "eu_odds": round(eu, 2) if eu else None,
        "odds_used": round(odds, 2) if odds else None,
        "confidence": row.get("置信度") or m.get("confidence_cn"),
        "scores": row.get("推荐比分") or "",
        "asian_handicap": row.get("亚盘") or m.get("asian_handicap_cn"),
        "summary": (m.get("summary") or "")[:280],
        "actuary_reasoning": (m.get("actuary_reasoning") or "")[:220],
        "market_pattern_summary": m.get("market_pattern_summary") or "",
        "market_pattern_names": m.get("market_pattern_names") or [],
        "value_bet": m.get("value_bet"),
        "insufficient_data": m.get("insufficient_data"),
        "odds_move": _odds_move(m),
        "similarity": _similarity_brief(m),
    }


def _parse_response(text: str) -> list[dict[str, Any]]:
    data = json.loads(_extract_json_text(text))
    options = data.get("options")
    if isinstance(options, list):
        parsed = [x for x in options if isinstance(x, dict)]
    else:
        # Backward-compatible with old single-combo response shape.
        parsed = [data]
    if not parsed:
        raise ValueError("AI 未返回 options")
    for opt in parsed[:2]:
        legs = opt.get("legs")
        if not isinstance(legs, list) or len(legs) != 2:
            raise ValueError("AI 每组必须返回恰好两场 legs")
    return parsed[:2]


def _pick_same_day_candidates(candidates: list[dict], target_date: str | None = None) -> tuple[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for c in candidates:
        grouped.setdefault(str(c.get("match_date") or "未知日期"), []).append(c)
    if target_date:
        picked = grouped.get(target_date, [])
        if len(picked) < 2:
            raise ValueError(f"{target_date} 可推荐候选不足 2 场")
        return target_date, picked
    eligible = [(d, cs) for d, cs in sorted(grouped.items()) if len(cs) >= 2]
    if not eligible:
        raise ValueError("可推荐候选不足 2 场")
    # 首页可能混有多天赛程；默认选最早一个具备2场候选的比赛日，避免跨天。
    return eligible[0]


def recommend_list_parlay(
    matches: list[dict],
    *,
    provider: str = "deepseek",
    kickoff_map: dict | None = None,
    target_date: str | None = None,
) -> dict[str, Any]:
    kickoff_map = kickoff_map or load_kickoff_map()
    all_candidates = [c for m in matches if (c := _candidate(m, kickoff_map))]
    match_date, candidates = _pick_same_day_candidates(all_candidates, target_date=target_date)

    prof = _profile(provider)
    api_key = prof.resolve_api_key()
    if not api_key:
        raise ValueError(f"未配置 {prof.api_key_env}")

    payload = {
        "parlay_type": "2串1",
        "requested_options": 2,
        "match_date": match_date,
        "candidate_count": len(candidates),
        "candidates": candidates[:24],
        "instruction": (
            f"请从 candidates 中挑选两组2串1；每组两场必须属于 {match_date}。"
            "第一组偏稳健，第二组在风险可接受前提下提高组合赔率。"
        ),
    }
    content = chat(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
        ],
        api_key=api_key,
        model=prof.model,
        base_url=prof.base_url,
        temperature=0.2,
        max_tokens=2200,
        timeout=180,
    )
    ai_options = _parse_response(content)
    by_id = {str(m.get("fixture_id")): m for m in matches}
    candidate_by_id = {c["fixture_id"]: c for c in candidates}

    options: list[dict[str, Any]] = []
    seen_combos: set[tuple[str, str]] = set()
    for ai in ai_options:
        selected_ids = [str(x.get("fixture_id")) for x in ai["legs"]]
        if len(set(selected_ids)) != 2:
            raise ValueError("AI 返回了重复场次")
        if any(fid not in by_id for fid in selected_ids):
            raise ValueError("AI 返回了候选外 fixture_id")
        selected_dates = {candidate_by_id.get(fid, {}).get("match_date") for fid in selected_ids}
        if selected_dates != {match_date}:
            raise ValueError("AI 返回了跨天组合")
        combo_key = tuple(sorted(selected_ids))
        local = analyze_custom_parlay([by_id[fid] for fid in selected_ids])
        local["source"] = f"list_ai_{prof.provider_id}"
        local["ai_provider"] = prof.provider_id
        local["ai_provider_label"] = prof.label
        local["ai_tier"] = ai.get("tier") or ("yield" if options else "safe")
        local["ai_label"] = ai.get("label") or ("提赔2串1" if local["ai_tier"] == "yield" else "稳健2串1")
        local["ai_headline"] = ai.get("headline") or ""
        local["ai_reason"] = ai.get("reason") or ""
        local["ai_risk_notes"] = ai.get("risk_notes") or []
        local["ai_stake_advice"] = ai.get("stake_advice") or ""
        local["candidate_count"] = len(candidates)
        local["match_date"] = match_date
        local["same_day_required"] = True
        local["duplicate_combo"] = combo_key in seen_combos
        seen_combos.add(combo_key)
        if len(local.get("legs") or []) == 2:
            combined = _combined_odds([{"eu_odds": leg.get("odds_used")} for leg in local["legs"]])
            local["combined_odds"] = combined
        options.append(local)

    if not options:
        raise ValueError("AI 未返回可用组合")
    primary = dict(options[0])
    primary["options"] = options
    primary["option_count"] = len(options)
    primary["source"] = f"list_ai_{prof.provider_id}_options"
    return primary
