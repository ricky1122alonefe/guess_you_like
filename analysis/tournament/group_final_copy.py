"""Final-round group qualification copy — synthesized from AI match analyses."""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from analysis.tournament.group_race import build_group_race_context
from analysis.tournament.group_stage import (
    analyze_fixture_motivation,
    fetch_live_snapshot,
    rank_best_third_places,
)
from analysis.tournament.group_final_prompt import (
    DOUYIN_HASHTAGS,
    PERSONA_INTRO_LINES,
    SOCIAL_DISCLAIMER,
    chat_messages,
)
from share_card import NO_JINGCAI, _collect_ai_model_briefs, final_recommendation_cn
from time_utils import now_beijing_str

log = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_AI_CACHE_DIR = "group_final_copy"

_SOCIAL_REPLACEMENTS: list[tuple[str, str]] = [
    (r"SP\s*[\d.]+\s*", ""),
    (r"[\d.]+\s*倍(?:赔率)?", ""),
    (r"竞彩(?:足球|可购|推荐|SP|方向)?", "AI"),
    (r"赔率", "走势"),
    (r"欧赔", "参考"),
    (r"亚盘", "让球"),
    (r"盘赔", "走势"),
    (r"盘口", "走势"),
    (r"水位", ""),
    (r"正?\s*EV\b", ""),
    (r"隐含概率", "参考胜率"),
    (r"购彩|下注|投注|串关|2串1|仓位|Kelly|体彩", ""),
    (r"穿盘", "赢球幅度"),
    (r"欧亚分歧", "走势分歧"),
    (r"盘口套路", "走势参考"),
    (r"盘路AI", "AI解读"),
    (r"不追让球|追让球", "谨慎看让球"),
    (r"重仓|轻仓", ""),
]


def sanitize_social_copy(text: str) -> str:
    """Strip odds / betting terms for Douyin-style posts."""
    if not text:
        return ""
    out = str(text)
    out = re.sub(r"（[^）]*SP[^）]*）", "", out)
    out = re.sub(r"\([^)]*SP[^)]*\)", "", out, flags=re.IGNORECASE)
    for pat, repl in _SOCIAL_REPLACEMENTS:
        out = re.sub(pat, repl, out, flags=re.IGNORECASE)
    out = re.sub(r"[（(]\s*[）)]", "", out)
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def _social_pick_line(pick: str) -> str:
    pick = (pick or "").strip()
    if not pick or pick in ("—", "观望", "暂无竞彩", NO_JINGCAI):
        return ""
    return f"模型倾向：{pick}"


def _persona_intro(group: str, chaos: dict[str, Any]) -> list[str]:
    level = chaos.get("chaos_level_cn") or "—"
    summary = chaos.get("summary") or "末轮积分与净胜球将决定出线归属。"
    return [
        f"【{group}组 · 末轮出线 · 数据复盘】",
        "",
        *PERSONA_INTRO_LINES,
        "",
        f"📊 组别画像：{level} — {summary}",
    ]


def _persona_outro(group: str) -> str:
    return (
        f"——\n"
        f"以上由自建分析管线产出：积分榜引擎 + 战意规则 + 多模型 AI（{group}组）。\n"
        f"同是搞数据的球友，欢迎评论区交流建模思路。"
    )


def _finalize_social_narrative(text: str, *, group: str = "") -> str:
    body = sanitize_social_copy(text)
    if not body:
        return f"{SOCIAL_DISCLAIMER}\n\n{DOUYIN_HASHTAGS}"
    if SOCIAL_DISCLAIMER not in body:
        body = f"{body}\n\n{SOCIAL_DISCLAIMER}"
    if "#世界杯" not in body:
        body = f"{body}\n\n{DOUYIN_HASHTAGS}"
    return body


def _sort_table(table: list[dict]) -> list[dict]:
    return sorted(
        table,
        key=lambda x: (-int(x.get("points") or 0), -int(x.get("gd") or 0), -int(x.get("gf") or 0), x.get("team") or ""),
    )


def _standings_line(table: list[dict]) -> str:
    if not table:
        return "暂无积分榜"
    parts = []
    for i, r in enumerate(_sort_table(table), start=1):
        parts.append(f"{i}.{r.get('team')} {r.get('points')}分 净{r.get('gd', 0):+d}")
    return " · ".join(parts)


def _load_prediction(output_root: Path, fixture_id: str) -> dict | None:
    try:
        from analysis.ai.deep import load_richest_prediction

        return load_richest_prediction(output_root, fixture_id)
    except Exception:
        return None


def _load_ai_records(output_root: Path, fixture_id: str) -> list[dict]:
    try:
        from match_timeline import load_ai_records

        return load_ai_records(output_root, fixture_id, limit=5)
    except Exception:
        return []


def _load_deep_records(output_root: Path, fixture_id: str) -> list[dict]:
    try:
        from match_timeline import load_deep_analyses

        return load_deep_analyses(output_root, fixture_id, limit=3)
    except Exception:
        return []


def _load_wc_match_watch(output_root: Path, fixture_id: str) -> dict | None:
    safe = "".join(ch for ch in str(fixture_id) if ch.isdigit() or ch in ("_", "-")) or "unknown"
    path = output_root / "worldcup" / "match_ai_watch" / f"{safe}.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if data.get("ok") else None
    except (json.JSONDecodeError, OSError):
        return None


def _ai_cache_path(output_root: Path, group: str) -> Path:
    return output_root / "worldcup" / _AI_CACHE_DIR / f"{group}.json"


def _load_group_ai_copy_cache(output_root: Path, group: str, *, ttl_sec: int = 3600) -> dict | None:
    path = _ai_cache_path(output_root, group)
    if not path.is_file():
        return None
    if ttl_sec and time.time() - path.stat().st_mtime > ttl_sec:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _save_group_ai_copy_cache(output_root: Path, group: str, data: dict[str, Any]) -> None:
    path = _ai_cache_path(output_root, group)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _has_user_ai_recommend(pred: dict | None, ai_records: list[dict] | None) -> bool:
    """True when user ran match-level AI recommend (list/detail 「AI推荐」)."""
    for rec in ai_records or []:
        if rec.get("analyses"):
            return True
    if not pred:
        return False
    if pred.get("ai_analyses"):
        return True
    src = str(pred.get("recommendation_source") or "").lower()
    return "ai" in src


def collect_match_ai_brief(
    output_root: Path,
    fixture: dict,
    *,
    motivation: dict | None = None,
    prediction: dict | None = None,
    ai_records: list[dict] | None = None,
    deep_records: list[dict] | None = None,
    wc_watch: dict | None = None,
    user_ai_only: bool = True,
    social_safe: bool = True,
) -> dict[str, Any]:
    """Aggregate AI signals for one final-round fixture."""
    fid = str(fixture.get("fixture_id") or "")
    pred = prediction if prediction is not None else (_load_prediction(output_root, fid) if fid else None)
    ai_records = ai_records if ai_records is not None else (_load_ai_records(output_root, fid) if fid else [])
    has_user_ai = _has_user_ai_recommend(pred, ai_records)

    if user_ai_only:
        deep_records = []
        wc_watch = None
    else:
        deep_records = deep_records if deep_records is not None else (_load_deep_records(output_root, fid) if fid else [])
        wc_watch = wc_watch if wc_watch is not None else (_load_wc_match_watch(output_root, fid) if fid else None)

    model_briefs = _collect_ai_model_briefs(pred if has_user_ai else None, ai_records if has_user_ai else [])
    jc_pick = final_recommendation_cn(pred) if pred and has_user_ai else "—"
    row = (pred or {}).get("predict_row") or {}
    jc_sp = ""
    if has_user_ai:
        jc_sp = row.get("竞彩SP") or ((pred or {}).get("jingcai_pick_info") or {}).get("jingcai_sp") or ""

    ai_lines: list[str] = []
    for b in model_briefs[:3]:
        bit = f"{b.get('label')}→{b.get('pick')}"
        if b.get("summary"):
            summ = b["summary"][:100]
            if social_safe:
                summ = sanitize_social_copy(summ)
            if summ:
                bit += f"（{summ}）"
        ai_lines.append(sanitize_social_copy(bit) if social_safe else bit)

    watch_block = None
    if wc_watch and not user_ai_only:
        watch_block = {
            "headline": wc_watch.get("headline") or "",
            "verdict": wc_watch.get("verdict") or "",
            "action": wc_watch.get("action") or "",
            "reason": wc_watch.get("reason") or "",
            "risk": wc_watch.get("risk") or "",
            "stake_advice": wc_watch.get("stake_advice") or "",
        }
        if wc_watch.get("headline"):
            ai_lines.append(f"盘路AI：{wc_watch['headline']}")

    deep = (deep_records or [None])[0] or {}
    deep_headline = deep.get("headline") or deep.get("summary") or ""
    if deep_headline and not user_ai_only:
        line = f"深度综合：{deep_headline[:120]}"
        ai_lines.append(sanitize_social_copy(line) if social_safe else line)

    mot = motivation or {}
    return {
        "fixture_id": fid,
        "match_name": fixture.get("match_name") or f"{fixture.get('home')}VS{fixture.get('away')}",
        "home": fixture.get("home"),
        "away": fixture.get("away"),
        "kickoff": fixture.get("kickoff") or "",
        "round": fixture.get("round"),
        "is_finished": bool(fixture.get("is_finished")),
        "motivation_type": mot.get("match_type") or "",
        "motivation_type_cn": mot.get("match_type_cn") or "常规战意",
        "likely_direction_cn": mot.get("likely_direction_cn") or "",
        "motivation_reasons": (mot.get("reasoning") or [])[:3],
        "jingcai_pick": jc_pick,
        "jingcai_sp": jc_sp,
        "model_briefs": model_briefs,
        "ai_lines": ai_lines,
        "has_user_ai": has_user_ai,
        "has_ai": bool(model_briefs or watch_block or deep_headline) if not user_ai_only else has_user_ai,
        "wc_watch": watch_block,
        "deep_headline": deep_headline,
    }


def _match_copy_lines(brief: dict[str, Any], *, social_safe: bool = True) -> list[str]:
    name = brief.get("match_name") or "—"
    mot = brief.get("motivation_type_cn") or "常规战意"
    direction = brief.get("likely_direction_cn") or "—"
    lines = [f"▸ {name}（{mot} · 倾向{direction}）"]
    if brief.get("is_finished"):
        lines.append("  已完场，以下解读供复盘参考。")
    pick_line = _social_pick_line(brief.get("jingcai_pick") or "")
    if pick_line:
        lines.append(f"  {pick_line}")
    for bit in brief.get("ai_lines") or []:
        clean = sanitize_social_copy(bit) if social_safe else bit
        if clean:
            lines.append(f"  · 模型输出 {clean}")
    if not social_safe:
        watch = brief.get("wc_watch") or {}
        if watch.get("action"):
            lines.append(f"  建议：{watch['action']}")
        if watch.get("risk"):
            lines.append(f"  风险：{watch['risk']}")
    reasons = brief.get("motivation_reasons") or []
    if reasons:
        reason_txt = "；".join(str(x) for x in reasons[:2])
        if social_safe:
            reason_txt = sanitize_social_copy(reason_txt)
        lines.append(f"  战意：{reason_txt}")
    if not brief.get("has_user_ai") and not brief.get("has_ai"):
        lines.append("  （本场尚未跑模型，已从文案中跳过）")
    elif not brief.get("has_user_ai"):
        lines.append("  （暂无模型输出记录）")
    return lines


def compose_group_narrative(
    group: str,
    *,
    race_ctx: dict[str, Any],
    table: list[dict],
    match_briefs: list[dict[str, Any]],
    archetype: str = "",
    strategy_hint: str = "",
    user_ai_only: bool = True,
    social_safe: bool = True,
) -> str:
    """Rule-based group copy from race logic + per-match AI briefs."""
    if user_ai_only:
        match_briefs = [b for b in match_briefs if b.get("has_user_ai")]
    chaos = race_ctx.get("chaos") or {}
    if social_safe:
        parts: list[str] = list(_persona_intro(group, chaos))
        if archetype or strategy_hint:
            parts.extend([
                "",
                f"🏷️ 小组特征：{archetype or '—'} · {strategy_hint or ''}".strip(" ·"),
            ])
        parts.extend(["", "📋 核心指标（积分榜）", _standings_line(table), "", "🧮 出线状态机（各队还能到哪）"])
    else:
        parts = [
            f"【{group}组 · 末轮出线形势】",
            "",
            f"形势：{chaos.get('chaos_level_cn') or '—'} — {chaos.get('summary') or '末轮积分与净胜球将决定出线归属。'}",
        ]
        if archetype or strategy_hint:
            parts.append(f"小组结构：{archetype or '—'} · {strategy_hint or ''}".strip(" ·"))
        parts.extend(["", f"积分榜：{_standings_line(table)}", "", "各队形势："])

    for t in race_ctx.get("teams") or []:
        if not t.get("known"):
            continue
        extra = ""
        if t.get("locked_first"):
            prev = next(
                (p for p in race_ctx.get("locked_first_previews") or [] if p.get("team") == t.get("team")),
                None,
            )
            if prev and prev.get("summary"):
                extra = f" {prev['summary']}"
        ranks = t.get("possible_ranks") or []
        rank_txt = f"仍可能名次：{('/'.join(str(x) for x in ranks))}" if ranks else ""
        parts.append(f"· {t['team']}（{t.get('status_cn')}）{rank_txt}")
        form_cn = t.get("form_cn") or ""
        if form_cn:
            parts.append(f"  前两场 {sanitize_social_copy(form_cn) if social_safe else form_cn}")
        note = sanitize_social_copy(t.get("note") or "") if social_safe else (t.get("note") or "")
        extra_clean = sanitize_social_copy(extra) if social_safe else extra
        parts.append(f"  {note}{extra_clean}".strip())

    parts.extend(["", "🤖 模型逐场输出（我的 AI 分析管线）：" if social_safe else "", "末轮场次 · AI 解读："])
    parts = [p for p in parts if p]
    if match_briefs:
        for brief in match_briefs:
            parts.extend(_match_copy_lines(brief, social_safe=social_safe))
            parts.append("")
    else:
        parts.append(
            "该组末轮场次尚未接入模型输出，请先在分析页跑完 AI 再生成。"
            if social_safe else
            "所选小组中，末轮场次尚未完成 AI 分析。请先在列表/详情页分析后再生成。"
        )

    parts.extend([
        "",
        "📌 Pipeline 结论" if social_safe else "小组研判：",
        _compose_group_closing(race_ctx, match_briefs, user_ai_only=user_ai_only, social_safe=social_safe),
    ])
    if social_safe:
        parts.extend(["", _persona_outro(group)])
    text = "\n".join(line for line in parts if line is not None).strip()
    if social_safe:
        return _finalize_social_narrative(text, group=group)
    return text


def _compose_group_closing(
    race_ctx: dict[str, Any],
    match_briefs: list[dict[str, Any]],
    *,
    user_ai_only: bool = True,
    social_safe: bool = True,
) -> str:
    chaos = race_ctx.get("chaos") or {}
    fighters = chaos.get("fighting_1st") or []
    locked = [t for t in (race_ctx.get("teams") or []) if t.get("locked_first")]
    picks = [b.get("jingcai_pick") for b in match_briefs if b.get("jingcai_pick") not in ("—", "", "观望", "暂无竞彩")]
    ai_ready = sum(
        1 for b in match_briefs
        if (b.get("has_user_ai") if user_ai_only else b.get("has_ai"))
    )

    bits: list[str] = []
    if locked:
        bits.append(f"{'、'.join(t['team'] for t in locked)} 已基本锁定头名，末轮更关注轮换与 32 强签位。")
    if len(fighters) >= 3:
        bits.append("本组头名仍开放，任何赛果都可能改写排名与最佳第三形势，平局与小比分权重上升。")
    elif len(fighters) == 2:
        bits.append(f"头名争夺主要在 {'、'.join(fighters)} 之间，直接对话场次战意拉满。")

    mot_types = {b.get("motivation_type_cn") for b in match_briefs if b.get("motivation_type_cn")}
    if "默契球观察" in mot_types:
        bits.append("存在默契球/控节奏观察场次，需防小比分或平局分流。" if social_safe
                      else "存在默契球/控节奏观察场次，盘口降热时需防赢球不穿或平局分流。")
    if "拼命球" in mot_types:
        bits.append("存在必须抢分场次，落后方强攻与强队保守可能并存。" if social_safe
                      else "存在必须抢分场次，落后方强攻与热门保守可能并存，注意欧亚分歧。")

    if picks:
        label = "模型倾向汇总" if social_safe else "AI 竞彩方向"
        bits.append(f"{label}：{'、'.join(dict.fromkeys(picks))}（{ai_ready}/{len(match_briefs)} 场已接入模型）。")
    elif match_briefs:
        bits.append(f"末轮 {len(match_briefs)} 场中 {ai_ready} 场已有模型输出，建议先补齐再发文。")

    if not bits:
        bits.append("结合积分榜与 48 队最佳第三规则，末轮重点看真实战意与走势。" if social_safe
                      else "结合积分榜与 48 队最佳第三规则，末轮勿只看纸面强弱，重点看真实战意与盘口套路。")
    out = " ".join(bits)
    return sanitize_social_copy(out) if social_safe else out


def build_group_final_copy(
    output_root: str | Path,
    group: str,
    *,
    standings: dict[str, list[dict]] | None = None,
    fixtures: list[dict] | None = None,
    round_num: int = 3,
    archetype: str = "",
    strategy_hint: str = "",
    user_ai_only: bool = True,
    social_safe: bool = True,
) -> dict[str, Any]:
    """One group's final-round copy payload."""
    output_root = Path(output_root)
    standings = standings or {}
    table = standings.get(group) or []
    group_all_fx = [f for f in (fixtures or []) if f.get("group") == group]
    best_thirds = rank_best_third_places(standings, fixtures=fixtures)
    race_ctx = build_group_race_context(
        group, standings, round_num=round_num, fixtures=group_all_fx or None,
    )

    group_fixtures = [
        f for f in (fixtures or [])
        if f.get("group") == group and int(f.get("round") or 0) == round_num
    ]
    group_fixtures.sort(key=lambda x: x.get("kickoff") or "")

    match_briefs: list[dict[str, Any]] = []
    for fx in group_fixtures:
        mot = analyze_fixture_motivation(
            home=fx.get("home") or "",
            away=fx.get("away") or "",
            group=group,
            standings=standings,
            round_num=round_num,
            best_thirds=best_thirds,
        )
        match_briefs.append(
            collect_match_ai_brief(
                output_root, fx, motivation=mot,
                user_ai_only=user_ai_only, social_safe=social_safe,
            )
        )

    user_briefs = [b for b in match_briefs if b.get("has_user_ai")] if user_ai_only else match_briefs
    narrative = compose_group_narrative(
        group,
        race_ctx=race_ctx,
        table=table,
        match_briefs=match_briefs,
        archetype=archetype,
        strategy_hint=strategy_hint,
        user_ai_only=user_ai_only,
        social_safe=social_safe,
    )
    return {
        "group": group,
        "round_num": round_num,
        "race": race_ctx,
        "standings": table,
        "matches": match_briefs,
        "narrative": narrative,
        "user_ai_match_count": sum(1 for m in match_briefs if m.get("has_user_ai")),
        "ai_match_count": sum(1 for m in user_briefs if m.get("has_ai") or m.get("has_user_ai")),
        "match_count": len(match_briefs),
        "social_safe": social_safe,
    }


def _parse_groups_param(raw: str | list[str] | None) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        parts = re.split(r"[,，\s]+", raw.upper())
    else:
        parts = [str(x).upper() for x in raw]
    valid = []
    for p in parts:
        p = p.strip()
        if len(p) == 1 and p in "ABCDEFGHIJKL" and p not in valid:
            valid.append(p)
    return valid


def build_group_final_copy_report(
    output_root: str | Path,
    *,
    round_num: int = 3,
    force_refresh: bool = False,
    groups: list[str] | None = None,
    user_ai_only: bool = True,
    social_safe: bool = True,
) -> dict[str, Any]:
    """All groups meta + narratives for user-selected groups only."""
    snap = fetch_live_snapshot(force=force_refresh)
    if not snap.get("ok"):
        return {"ok": False, "error": snap.get("error"), "groups": []}

    output_root = Path(output_root)
    standings = snap.get("standings") or {}
    fixtures = snap.get("fixtures") or []

    profiles: dict[str, Any] = {}
    try:
        from worldcup_analytics import _build_group_strategy_profiles
        from analysis.tournament.group_stage import _load_config

        cfg = _load_config()
        profiles = _build_group_strategy_profiles(
            cfg.get("groups") or {},
            cfg.get("team_strength_tiers") or {},
            cfg.get("tier_labels") or {},
        )
    except Exception:
        pass

    groups_out: list[dict] = []
    for group in "ABCDEFGHIJKL":
        prof = profiles.get(group) or {}
        payload = build_group_final_copy(
            output_root,
            group,
            standings=standings,
            fixtures=fixtures,
            round_num=round_num,
            archetype=str(prof.get("archetype") or ""),
            strategy_hint=str(prof.get("strategy_hint") or ""),
            user_ai_only=user_ai_only,
            social_safe=social_safe,
        )
        cached_ai = _load_group_ai_copy_cache(output_root, group, ttl_sec=0)
        if cached_ai and cached_ai.get("narrative"):
            ai_text = cached_ai.get("narrative") or ""
            if cached_ai.get("headline"):
                ai_text = f"{cached_ai['headline']}\n\n{ai_text}".strip()
            payload["ai_narrative"] = (
                _finalize_social_narrative(ai_text, group=group) if social_safe else ai_text
            )
            payload["ai_narrative_at"] = cached_ai.get("generated_at")
        groups_out.append(payload)

    total_matches = sum(g.get("match_count") or 0 for g in groups_out)
    total_ai = sum(g.get("ai_match_count") or 0 for g in groups_out)
    selected_keys = _parse_groups_param(groups) if groups else []
    selected_set = set(selected_keys)
    selected_out = [g for g in groups_out if g.get("group") in selected_set] if selected_set else []

    total_user_ai = sum(g.get("user_ai_match_count") or 0 for g in groups_out)
    active_groups = [g for g in groups_out if (g.get("match_count") or 0) > 0]

    return {
        "ok": True,
        "updated_at": now_beijing_str(),
        "round_num": round_num,
        "round_summary": snap.get("round_summary") or {},
        "advance_rule_cn": (snap.get("format") or {}).get("advance_rule_cn"),
        "best_third_ranking": rank_best_third_places(standings, fixtures=fixtures),
        "groups": groups_out,
        "selected_groups": selected_keys,
        "selected": selected_out,
        "user_ai_only": user_ai_only,
        "social_safe": social_safe,
        "stats": {
            "group_count": len(active_groups),
            "match_count": total_matches,
            "user_ai_match_count": total_user_ai,
            "ai_match_count": total_ai,
        },
    }


def build_group_final_ai_narrative(
    output_root: str | Path,
    group_payload: dict[str, Any],
    *,
    ai_model: str | None = None,
    ai_base_url: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Call LLM to rewrite group copy from structured AI match briefs."""
    group = group_payload.get("group") or ""
    output_root = Path(output_root)
    if not force:
        cached = _load_group_ai_copy_cache(output_root, group, ttl_sec=3600)
        if cached and cached.get("narrative"):
            return cached

    try:
        from ai_profiles import get_primary_profile
        from ai_prompt import _extract_json_text
        from deepseek_client import chat

        prof = get_primary_profile(ai_model, ai_base_url)
        api_key = prof.resolve_api_key()
        if not api_key:
            raise ValueError(f"未配置 {prof.api_key_env}")

        messages = chat_messages(group_payload)
        text = chat(
            messages,
            api_key=api_key,
            model=prof.model,
            base_url=prof.base_url,
            temperature=0.25,
            max_tokens=1600,
            timeout=180,
        )
        data = json.loads(_extract_json_text(text))
        if group_payload.get("social_safe", True):
            if data.get("headline"):
                data["headline"] = sanitize_social_copy(data["headline"])
            if data.get("narrative"):
                data["narrative"] = _finalize_social_narrative(data["narrative"], group=group)
        data["ok"] = True
        data["group"] = group
        data["generated_at"] = now_beijing_str()
        data["ai_provider"] = prof.provider_id
        data["ai_provider_label"] = prof.label
        _save_group_ai_copy_cache(output_root, group, data)
        return data
    except Exception as exc:
        log.exception("小组末轮 AI 文案失败 %s", group)
        return {
            "ok": False,
            "group": group,
            "error": str(exc),
            "generated_at": now_beijing_str(),
        }


def build_all_groups_final_ai_narratives(
    output_root: str | Path,
    report: dict[str, Any],
    *,
    ai_model: str | None = None,
    ai_base_url: str | None = None,
    force: bool = False,
    groups: list[str] | None = None,
) -> dict[str, Any]:
    """Generate AI narratives for selected groups (default: groups with R3 fixtures)."""
    wanted = set(groups or [])
    results: dict[str, Any] = {}
    for g in report.get("groups") or []:
        grp = g.get("group") or ""
        if wanted and grp not in wanted:
            continue
        if not g.get("match_count"):
            continue
        results[grp] = build_group_final_ai_narrative(
            output_root, g, ai_model=ai_model, ai_base_url=ai_base_url, force=force,
        )
    ok_n = sum(1 for v in results.values() if v.get("ok"))
    return {
        "ok": ok_n > 0,
        "generated_at": now_beijing_str(),
        "results": results,
        "success_count": ok_n,
        "total": len(results),
    }
