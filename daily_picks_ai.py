"""AI-generated daily 2串1 picks (稳健 / 折中 / 博冷门), refreshed hourly."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from time_utils import now_beijing, now_beijing_str

from ai_prompt import _extract_json_text
from ai_profiles import get_primary_profile
from daily_picks import (
    AI_KICKOFF_HOURS,
    PARLAY_LABEL,
    PARLAY_SIZE,
    DailyPick,
    ParlayLeg,
    RESULT_TO_KEY,
    _build_candidate,
    _build_floor_candidate,
    _build_floor_safe_parlay,
    _combined_odds,
    _eu_odds,
    _kickoff_date,
    _parlay_summary,
    _select_daily_candidates,
    build_daily_picks,
    kickoff_within_hours,
    load_kickoff_map,
    save_daily_picks,
)
from deepseek_client import DeepSeekError, chat

log = logging.getLogger(__name__)

DAILY_PARLAY_SYSTEM = """你是顶级体育赛事精算师，负责从当日候选场次中挑选竞彩风格的 2串1 组合。

规则：
1. 输出三档：safe（稳健）、balanced（折中）、upset（博冷门），每档恰好 2 场。
2. 只能使用用户提供的 fixture_id；suggested_pick 须为完整竞彩选项（如「主胜」）。
3. **优先 jingcai_market=sp（胜平负）**；仅让球（rqsp）默认不纳入，除非候选标注为极高置信（高置信+多模型一致或正EV）。
4. suggested_pick 须与候选中的 suggested_pick 完全一致。
5. 优先让三档共 6 场互不重复；若当日可推荐场次不足 6 场，可少量重叠并在 reason 说明。
6. 稳健档：两场方向较稳、模型一致或高置信、组合赔率偏低。
7. 折中档：单场风险适中，组合赔率中等。
8. 博冷门档：偏冷门或高赔，组合赔率较高。
9. 必须参考 eu_ah_conversion：欧亚基本一致可加分；亚盘偏浅/偏深或诱盘套路要在 reason 中说明并降低稳健档权重。
10. 禁止编造场次、赔率或模型结论。

只返回 JSON，不要 markdown：
{
  "tiers": {
    "safe": {
      "legs": [{"fixture_id": "123", "pick_cn": "主胜"}, {"fixture_id": "456", "pick_cn": "主胜"}],
      "reason": "50字内说明为何选这两场"
    },
    "balanced": { "legs": [...], "reason": "..." },
    "upset": { "legs": [...], "reason": "..." }
  }
}"""


def _prepare_day_context(
    matches: list[dict],
    *,
    match_date: str | None = None,
    kickoff_map: dict | None = None,
    relax_kickoff_window: bool = False,
) -> tuple[dict[str, Any], list[dict], str, list[dict]]:
    today = now_beijing().date().isoformat()
    kickoff_map = kickoff_map or load_kickoff_map()

    available_dates = sorted({
        d for m in matches if (d := _kickoff_date(m, kickoff_map))
    })

    target = match_date or today
    if match_date is None and target not in available_dates and available_dates:
        future = [d for d in available_dates if d >= today]
        target = future[0] if future else available_dates[-1]

    day_matches = [m for m in matches if _kickoff_date(m, kickoff_map) == target]
    if not relax_kickoff_window:
        day_matches = [
            m for m in day_matches
            if kickoff_within_hours(m.get("fixture_id", ""), AI_KICKOFF_HOURS, kickoff_map)
        ]
    all_actionable = [
        c for m in day_matches if (c := _build_candidate(m, kickoff_map))
    ]
    floor_candidates = [
        c for m in day_matches if (c := _build_floor_candidate(m, kickoff_map))
    ]
    candidates, mkt = _select_daily_candidates(all_actionable)
    sp_count = mkt["sp_count"]
    rqsp_count = mkt["rqsp_total"]
    rqsp_eligible = mkt["rqsp_eligible"]

    skeleton: dict[str, Any] = {
        "date": target,
        "generated_at": now_beijing_str(),
        "match_count": len(day_matches),
        "actionable_count": len(candidates),
        "sp_actionable_count": sp_count,
        "rqsp_actionable_count": rqsp_count,
        "rqsp_eligible_count": rqsp_eligible,
        "pick_policy": "胜平负优先，极高置信让球可入选",
        "available_dates": available_dates,
        "tiers": {},
        "fallback_safe": _build_floor_safe_parlay(floor_candidates, target=target),
        "source": "rules",
    }
    if skeleton["fallback_safe"]:
        skeleton["fallback_safe_note"] = "保底候选仅用于当正常推荐偏少/观望较多时参考，建议小仓位。"
    if rqsp_count and not rqsp_eligible:
        skeleton["pick_policy_note"] = (
            f"优先胜平负（{sp_count} 场）；"
            f"{rqsp_count} 场仅让球未达极高置信门槛"
        )
    elif rqsp_eligible:
        skeleton["pick_policy_note"] = (
            f"胜平负 {sp_count} 场 + 极高置信让球 {rqsp_eligible} 场"
        )
    return skeleton, candidates, target, day_matches


def _candidate_brief(c: dict) -> dict[str, Any]:
    return {
        "fixture_id": c["fixture_id"],
        "match": c["match"],
        "kickoff": c["kickoff"],
        "suggested_pick": c["pick_cn"],
        "jingcai_market": c.get("jingcai_market"),
        "confidence": c["confidence_cn"],
        "consensus": c.get("consensus"),
        "value_bet": c.get("value_bet"),
        "jingcai_sp": c.get("jingcai_sp") or c.get("eu_odds"),
        "model_note": c.get("model_note"),
        "asian_handicap": c.get("asian_handicap_cn"),
        "eu_ah_conversion": c.get("market_pattern_summary") or "",
        "reason": (c.get("reason") or "")[:160],
    }


def _build_user_prompt(*, target: str, candidates: list[dict]) -> str:
    payload = {
        "date": target,
        "parlay_type": PARLAY_LABEL,
        "candidate_count": len(candidates),
        "candidates": [_candidate_brief(c) for c in candidates],
    }
    return (
        f"请为 {target} 挑选三档 {PARLAY_LABEL} 推荐。\n"
        f"候选场次 JSON：\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def _parse_ai_tiers(content: str) -> dict[str, Any]:
    data = json.loads(_extract_json_text(content))
    tiers = data.get("tiers")
    if not isinstance(tiers, dict):
        raise ValueError("缺少 tiers 对象")
    return tiers


def _enrich_leg(
    leg: dict,
    *,
    cand_by_fid: dict[str, dict],
    match_by_fid: dict[str, dict],
) -> ParlayLeg | None:
    fid = str(leg.get("fixture_id") or "")
    cand = cand_by_fid.get(fid)
    if not cand:
        return None
    pick_cn = str(leg.get("pick_cn") or cand["pick_cn"])
    if pick_cn not in RESULT_TO_KEY:
        pick_cn = cand["pick_cn"]
    pick_key = RESULT_TO_KEY.get(pick_cn, "")
    m = match_by_fid.get(fid)
    eu = _eu_odds(m, pick_key) if m and pick_key else cand.get("eu_odds")
    return ParlayLeg(
        fixture_id=fid,
        match=cand["match"],
        kickoff=cand["kickoff"],
        pick_cn=pick_cn,
        scores=cand.get("scores") or "",
        asian_handicap_cn=cand.get("asian_handicap_cn") or "—",
        confidence_cn=cand.get("confidence_cn") or "低",
        eu_odds=round(eu, 2) if eu else cand.get("eu_odds"),
        reason=(cand.get("reason") or "")[:200],
        model_note=cand.get("model_note") or "",
        market_pattern_summary=cand.get("market_pattern_summary") or "",
    )


def _merge_ai_tiers(
    skeleton: dict[str, Any],
    ai_tiers: dict[str, Any],
    *,
    candidates: list[dict],
    day_matches: list[dict],
) -> dict[str, Any]:
    cand_by_fid = {c["fixture_id"]: c for c in candidates}
    match_by_fid = {str(m.get("fixture_id")): m for m in day_matches}

    tier_labels = {
        "safe": "稳健",
        "balanced": "折中",
        "upset": "博冷门",
    }
    out_tiers: dict[str, Any] = {}

    for tier_id, tier_label in tier_labels.items():
        block = ai_tiers.get(tier_id)
        if not isinstance(block, dict):
            out_tiers[tier_id] = None
            continue
        raw_legs = block.get("legs") or []
        if not isinstance(raw_legs, list) or len(raw_legs) != PARLAY_SIZE:
            out_tiers[tier_id] = None
            continue

        legs: list[ParlayLeg] = []
        leg_dicts: list[dict] = []
        for raw in raw_legs:
            leg = _enrich_leg(raw, cand_by_fid=cand_by_fid, match_by_fid=match_by_fid)
            if not leg:
                break
            legs.append(leg)
            leg_dicts.append(asdict(leg))
        if len(legs) != PARLAY_SIZE:
            out_tiers[tier_id] = None
            continue

        combined = _combined_odds(leg_dicts)
        ai_reason = str(block.get("reason") or "").strip()
        summary = _parlay_summary(legs, combined)
        if ai_reason:
            summary = f"{summary}\n{ai_reason}"

        out_tiers[tier_id] = asdict(DailyPick(
            tier=tier_id,
            tier_label=tier_label,
            parlay_type=PARLAY_LABEL,
            legs=leg_dicts,
            combined_odds=combined,
            reason=summary,
            score=0.0,
        ))

    result = dict(skeleton)
    result["tiers"] = out_tiers
    result["source"] = "ai"
    if not any(out_tiers.values()):
        raise ValueError("AI 未返回有效三档 2串1")
    return result


def build_daily_picks_with_ai(
    matches: list[dict],
    *,
    match_date: str | None = None,
    kickoff_map: dict | None = None,
    relax_kickoff_window: bool = False,
) -> dict[str, Any]:
    """Use DeepSeek to pick 2串1 parlays; fall back to rule-based on failure."""
    skeleton, candidates, target, day_matches = _prepare_day_context(
        matches,
        match_date=match_date,
        kickoff_map=kickoff_map,
        relax_kickoff_window=relax_kickoff_window,
    )

    if not candidates:
        skeleton["message"] = f"{target} 暂无可用推荐（无明确方向或均为观望）"
        return skeleton
    if len(candidates) < PARLAY_SIZE:
        skeleton["message"] = (
            f"{target} 可推荐场次不足 {PARLAY_SIZE} 场，暂无法组成 {PARLAY_LABEL}"
        )
        return skeleton

    profile = get_primary_profile()
    api_key = profile.resolve_api_key()
    if not api_key:
        log.warning("未配置 %s，三档推荐回退规则引擎", profile.api_key_env)
        return build_daily_picks(matches, match_date=match_date, kickoff_map=kickoff_map)

    try:
        content = chat(
            [
                {"role": "system", "content": DAILY_PARLAY_SYSTEM},
                {"role": "user", "content": _build_user_prompt(target=target, candidates=candidates)},
            ],
            api_key=api_key,
            model=profile.model,
            base_url=profile.base_url,
            temperature=0.2,
            max_tokens=2048,
        )
        ai_tiers = _parse_ai_tiers(content)
        result = _merge_ai_tiers(
            skeleton, ai_tiers,
            candidates=candidates, day_matches=day_matches,
        )
        result["ai_provider"] = profile.label
        result["ai_model"] = profile.model
        log.info("AI 三档 %s 推荐已生成（%s）", target, profile.model)
        return result
    except (DeepSeekError, ValueError, json.JSONDecodeError) as exc:
        log.warning("AI 三档推荐失败，回退规则引擎: %s", exc)
        fallback = build_daily_picks(matches, match_date=match_date, kickoff_map=kickoff_map)
        fallback["ai_error"] = str(exc)
        return fallback


def build_daily_picks_auto(
    matches: list[dict],
    *,
    match_date: str | None = None,
    kickoff_map: dict | None = None,
    use_ai: bool = False,
    relax_kickoff_window: bool = False,
) -> dict[str, Any]:
    if use_ai:
        return build_daily_picks_with_ai(
            matches,
            match_date=match_date,
            kickoff_map=kickoff_map,
            relax_kickoff_window=relax_kickoff_window,
        )
    return build_daily_picks(matches, match_date=match_date, kickoff_map=kickoff_map)


def _reload_latest_matches(output_root: str | Path) -> list[dict]:
    path = Path(output_root) / "latest.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return list(data.get("matches") or [])
    except json.JSONDecodeError:
        return []


def load_matches_for_date(
    output_root: str | Path,
    match_date: str,
    *,
    within_days: float | None = None,
) -> list[dict]:
    """All fixtures kicking off on match_date (calendar day, Beijing)."""
    from daily_picks import _kickoff_date, load_dashboard_matches

    import config as app_cfg

    root = Path(output_root)
    days = within_days if within_days is not None else app_cfg.SERVICE_WITHIN_DAYS
    kickoff_map = load_kickoff_map(within_days=days)
    by_id: dict[str, dict] = {}

    for m in _reload_latest_matches(root):
        fid = str(m.get("fixture_id") or "")
        if fid:
            by_id[fid] = m

    for m in load_dashboard_matches(root, within_days=days):
        fid = str(m.get("fixture_id") or "")
        if fid and fid not in by_id:
            by_id[fid] = m

    out: list[dict] = []
    for m in by_id.values():
        if _kickoff_date(m, kickoff_map) == match_date:
            out.append(m)
    out.sort(key=lambda x: str(x.get("fixture_id") or ""))
    return out


def run_daily_ai_analysis(
    output_root: str | Path,
    match_date: str,
    *,
    analyze_matches: bool = True,
    ai_model: str = "deepseek-chat",
    ai_mode: str = "expert",
    ai_base_url: str | None = None,
    dual_ai: bool = False,
    ai_model_b: str | None = None,
    ai_base_url_b: str | None = None,
    within_days: float | None = None,
) -> dict[str, Any]:
    """
    AI-analyze each match on match_date, then build & save AI 2串1 tiers.
    """
    from hourly_pipeline import run_single_match_ai

    root = Path(output_root)
    day_matches = load_matches_for_date(root, match_date, within_days=within_days)
    kickoff_map = load_kickoff_map()

    if not day_matches:
        return {
            "ok": False,
            "error": f"{match_date} 暂无赛程",
            "date": match_date,
        }

    analyzed: list[str] = []
    skipped: list[str] = []
    errors: list[dict[str, str]] = []

    if analyze_matches:
        for m in day_matches:
            fid = str(m.get("fixture_id") or "")
            name = m.get("match") or (m.get("predict_row") or {}).get("比赛") or fid
            if not fid:
                continue
            try:
                log.info("当日 AI 分析 %s (%s)", name, fid)
                run_single_match_ai(
                    root,
                    fid,
                    ai_model=ai_model,
                    ai_mode=ai_mode,
                    ai_base_url=ai_base_url,
                    dual_ai=dual_ai,
                    ai_model_b=ai_model_b,
                    ai_base_url_b=ai_base_url_b,
                )
                analyzed.append(fid)
            except RuntimeError as exc:
                msg = str(exc)
                if "正在进行中" in msg:
                    skipped.append(fid)
                else:
                    errors.append({"fixture_id": fid, "match": name, "error": msg})
                    log.warning("当日 AI 单场失败 %s: %s", fid, exc)
            except Exception as exc:
                errors.append({"fixture_id": fid, "match": name, "error": str(exc)})
                log.warning("当日 AI 单场失败 %s: %s", fid, exc)

    matches = _reload_latest_matches(root)
    if not matches:
        matches = day_matches

    payload = build_daily_picks_with_ai(
        matches,
        match_date=match_date,
        kickoff_map=kickoff_map,
        relax_kickoff_window=True,
    )
    payload["ai_analyzed"] = analyzed
    payload["ai_skipped"] = skipped
    payload["ai_errors"] = errors
    if analyzed:
        payload["ai_run_at"] = now_beijing_str()

    save_daily_picks(root, payload)

    ok = payload.get("source") == "ai" or bool(analyzed)
    message = payload.get("message") or ""
    if payload.get("source") == "ai":
        message = f"{match_date} AI 三档 {PARLAY_LABEL} 已生成"
    elif not message and errors:
        message = f"部分场次 AI 失败（{len(errors)}），请查看详情"

    return {
        "ok": ok,
        "message": message,
        "date": match_date,
        "analyzed": len(analyzed),
        "skipped": len(skipped),
        "errors": errors,
        "source": payload.get("source"),
        "actionable_count": payload.get("actionable_count"),
        "tiers": {
            k: bool(v) for k, v in (payload.get("tiers") or {}).items()
        },
        "payload": payload,
    }
