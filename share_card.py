"""Single-match share card for WeChat Moments (HTML + browser export)."""

from __future__ import annotations

import html
import re
from datetime import datetime, timedelta
from typing import Any

from daily_picks import load_kickoff_map
from jingcai_pick import (
    NO_JINGCAI,
    final_pick_key,
    final_recommendation_cn,
    handicap_label,
    jingcai_market_mode,
    market_label,
)
from time_utils import format_beijing, to_beijing

_WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
_SCORE_SNIP_RE = re.compile(
    r"(\d+\s*[-:：]\s*\d+)|推荐比分|最可能比分|比分推荐|likely.?score|Poisson.*λ",
    re.I,
)


def _e(s) -> str:
    return html.escape(str(s) if s is not None else "")


def split_teams(match_name: str) -> tuple[str, str]:
    name = (match_name or "").strip()
    for sep in ("VS", "vs", "Vs", "对"):
        if sep in name:
            a, b = name.split(sep, 1)
            return a.strip(), b.strip()
    return name, ""


def _pick_row_key(pick_cn: str) -> str | None:
    if not pick_cn:
        return None
    if pick_cn.endswith(" 胜") or pick_cn in ("主胜", "胜"):
        return "home"
    if pick_cn.endswith(" 平") or pick_cn in ("平局", "平"):
        return "draw"
    if pick_cn.endswith(" 负") or pick_cn in ("客胜", "负"):
        return "away"
    return None


def _collect_ai_picks(prediction: dict | None) -> list[dict[str, str]]:
    if not prediction:
        return []
    out: list[dict[str, str]] = []
    analyses = prediction.get("ai_analyses") or {}
    if analyses:
        for pid, p in analyses.items():
            pick = final_recommendation_cn(p)
            label = p.get("ai_provider_label") or pid
            if pick and pick not in ("观望", "—", "暂无竞彩") and "观望" not in pick:
                out.append({"label": label.replace(" 精算师", ""), "pick": pick})
        return out
    pick = final_recommendation_cn(prediction)
    if pick and pick not in ("观望", "—", "暂无竞彩") and "观望" not in pick:
        out.append({"label": "AI", "pick": pick})
    return out


def _primary_highlight(prediction: dict | None) -> str | None:
    picks = _collect_ai_picks(prediction)
    if not picks:
        return None
    keys = {_pick_row_key(p["pick"]) for p in picks}
    keys.discard(None)
    if len(keys) == 1:
        return keys.pop()
    return _pick_row_key(picks[0]["pick"])


def _fmt_payout(sp: float | None) -> str:
    if sp is None:
        return "—"
    try:
        return f"{int(round(float(sp) * 1000)):,}"
    except (TypeError, ValueError):
        return "—"


def build_share_context(
    fixture_id: str,
    *,
    match_name: str = "",
    timeline: list | None = None,
    prediction: dict | None = None,
    kickoff_map: dict | None = None,
) -> dict[str, Any]:
    timeline = timeline or []
    kickoff_map = kickoff_map or load_kickoff_map()
    fid = str(fixture_id)

    jc: dict = {}
    for p in reversed(timeline):
        candidate = (p.get("odds") or {}).get("jingcai")
        if candidate and (candidate.get("has_sp") or candidate.get("has_rqsp")):
            jc = candidate
            break

    home, away = split_teams(match_name)
    ko = kickoff_map.get(fid)
    if isinstance(ko, datetime):
        bj = to_beijing(ko)
        weekday = _WEEKDAYS[bj.weekday()]
        kickoff_line = format_beijing(bj, "%m-%d %H:%M")
        stop_sale = format_beijing(bj - timedelta(minutes=5), "%H:%M")
        kickoff_full = f"{weekday} {kickoff_line}"
    else:
        weekday, kickoff_line, stop_sale, kickoff_full = "—", "—", "—", "—"

    highlight = _primary_highlight(prediction)
    ai_picks = _collect_ai_picks(prediction)

    sp_rows = []
    if jc.get("has_sp"):
        for key, label in (("home", "胜"), ("draw", "平"), ("away", "负")):
            sp = jc.get(f"sp_{key}")
            sp_rows.append({
                "label": label,
                "key": key,
                "line": f"{label}1000 中 {_fmt_payout(sp)}元",
                "highlight": highlight == key,
            })

    recommend = final_recommendation_cn(prediction or {})
    pred_row = (prediction or {}).get("predict_row") or {}
    scores = pred_row.get("推荐比分") or ""
    if not scores and prediction:
        scores = "、".join(prediction.get("likely_scores_detail") or prediction.get("likely_scores") or [])

    return {
        "fixture_id": fid,
        "match_name": match_name,
        "home": home or match_name,
        "away": away or "—",
        "match_num": jc.get("match_num") or "",
        "kickoff_full": kickoff_full,
        "stop_sale": stop_sale,
        "kickoff_line": kickoff_line,
        "sp_rows": sp_rows,
        "has_sp": bool(sp_rows),
        "ai_picks": ai_picks,
        "recommend": recommend,
        "scores": scores,
        "confidence": pred_row.get("置信度") or (prediction or {}).get("confidence_cn") or "",
        "asian": pred_row.get("亚盘") or (prediction or {}).get("asian_handicap_cn") or "",
    }


def _sanitize_jingcai_text(text: str) -> str:
    """Strip score-prediction lines — poster follows 竞彩 SP/RQSP only."""
    if not text:
        return ""
    parts: list[str] = []
    for chunk in re.split(r"[。\n；;]", str(text)):
        line = chunk.strip()
        if not line or _SCORE_SNIP_RE.search(line):
            continue
        if "比分" in line and any(c.isdigit() for c in line):
            continue
        parts.append(line)
    out = "。".join(parts)
    if out and not out.endswith("。"):
        out += "。"
    return out[:280]


def _latest_jingcai(timeline: list | None) -> dict:
    for p in reversed(timeline or []):
        jc = (p.get("odds") or {}).get("jingcai")
        if jc and (jc.get("has_sp") or jc.get("has_rqsp")):
            return jc
    return {}


def _jc_odds_cells(jc: dict, mode: str, pick_key: str) -> list[dict[str, Any]]:
    prefix = "sp" if mode == "sp" else "rqsp" if mode == "rqsp" else ""
    if not prefix:
        return []
    cells = []
    for key, lbl in (("home", "胜"), ("draw", "平"), ("away", "负")):
        val = jc.get(f"{prefix}_{key}")
        cells.append({
            "label": lbl,
            "sp": val,
            "highlight": pick_key == key and pick_key not in ("skip", ""),
        })
    return cells


def _model_jingcai_pick(a: dict) -> str:
    """竞彩可购方向 — 优先 竞彩推荐，其次胜平负/compact 字段."""
    row = a.get("predict_row") or {}
    for key in ("竞彩推荐", "胜平负"):
        val = row.get(key)
        if val and str(val) not in ("—", "", NO_JINGCAI):
            return str(val)
    val = a.get("result_1x2_cn")
    if val and str(val) not in ("—", "", NO_JINGCAI):
        return str(val)
    pick = final_recommendation_cn(a)
    return pick if pick != NO_JINGCAI else "—"


def _model_summary_text(a: dict) -> str:
    for key in ("actuary_reasoning", "summary"):
        val = a.get(key)
        if val and str(val).strip():
            return _sanitize_jingcai_text(str(val).strip())
    return ""


def _collect_ai_model_briefs(
    prediction: dict | None,
    ai_records: list[dict] | None,
) -> list[dict[str, str]]:
    """Per-model 竞彩推荐 + AI 总结（最新一轮）."""
    briefs: list[dict[str, str]] = []
    seen: set[str] = set()

    def _add(pid: str, a: dict) -> None:
        label = (a.get("ai_provider_label") or a.get("label") or pid or "AI").replace(" 精算师", "")
        key = label.lower()
        if key in seen:
            return
        pick = _model_jingcai_pick(a)
        summary = _model_summary_text(a)
        conf = a.get("confidence_cn") or (a.get("predict_row") or {}).get("置信度") or ""
        if pick in ("—", "", NO_JINGCAI) and not summary:
            return
        seen.add(key)
        briefs.append({
            "label": label,
            "pick": pick,
            "summary": summary,
            "confidence": str(conf) if conf else "",
        })

    analyses = (prediction or {}).get("ai_analyses") or {}
    if analyses:
        for pid, a in analyses.items():
            _add(pid, a)
    elif prediction and (prediction.get("recommendation_source") or "").find("ai") >= 0:
        _add(prediction.get("ai_provider") or "ai", prediction)

    if not briefs:
        latest = (ai_records or [None])[0]
        if latest:
            for pid, a in (latest.get("analyses") or {}).items():
                _add(pid, a)

    return briefs


def _build_ai_synthesis(
    prediction: dict | None,
    *,
    model_briefs: list[dict[str, str]],
    jc_reason: str = "",
) -> str:
    """综合 AI 总结文案（不含比分）."""
    if jc_reason:
        return _sanitize_jingcai_text(jc_reason)
    picks = [b["pick"] for b in model_briefs if b.get("pick") not in ("—", "", NO_JINGCAI, "观望")]
    unique = {p for p in picks if p}
    summaries = [b["summary"] for b in model_briefs if b.get("summary")]
    if len(unique) == 1 and summaries:
        pick = next(iter(unique))
        lead = f"多模型一致看好「{pick}」。"
        return _sanitize_jingcai_text(lead + summaries[0][:200])
    if len(unique) > 1:
        bits = "、".join(f"{b['label']}→{b['pick']}" for b in model_briefs if b.get("pick") not in ("—", ""))
        base = f"各模型结论：{bits}。综合竞彩推荐见上方。"
        if summaries:
            return _sanitize_jingcai_text(base + summaries[0][:120])
        return base
    pred = prediction or {}
    for key in ("actuary_reasoning", "summary"):
        val = pred.get(key)
        if val and str(val).strip():
            return _sanitize_jingcai_text(str(val).strip())
    if summaries:
        return summaries[0]
    return ""


def _pick_summary_text(
    prediction: dict | None,
    *,
    deep_record: dict | None = None,
    ai_records: list | None = None,
    model_briefs: list[dict[str, str]] | None = None,
) -> str:
    """Legacy single-block summary — delegates to synthesis builder."""
    pred = prediction or {}
    info = pred.get("jingcai_pick_info") or {}
    jc_reason = info.get("jingcai_reason") or ""
    briefs = model_briefs if model_briefs is not None else _collect_ai_model_briefs(pred, ai_records)
    synth = _build_ai_synthesis(pred, model_briefs=briefs, jc_reason=jc_reason)
    if synth:
        return synth
    if deep_record:
        a = deep_record.get("analysis") or {}
        for key in ("final_pick_reason", "deep_verdict"):
            val = a.get(key)
            if val and str(val).strip():
                return _sanitize_jingcai_text(str(val).strip())
    tier_reason = pred.get("buy_tier_reason") or (pred.get("predict_row") or {}).get("档位说明")
    if tier_reason and str(tier_reason).strip():
        return _sanitize_jingcai_text(str(tier_reason).strip())
    return ""


def build_ai_summary_context(
    fixture_id: str,
    *,
    match_name: str = "",
    timeline: list | None = None,
    prediction: dict | None = None,
    kickoff_map: dict | None = None,
    deep_record: dict | None = None,
    ai_records: list | None = None,
) -> dict[str, Any]:
    """Rich context for embedded AI recommendation summary card."""
    ctx = build_share_context(
        fixture_id,
        match_name=match_name,
        timeline=timeline,
        prediction=prediction,
        kickoff_map=kickoff_map,
    )
    pred = prediction or {}
    row = pred.get("predict_row") or {}
    info = pred.get("jingcai_pick_info") or {}
    recommend = ctx.get("recommend") or ""
    model_briefs = _collect_ai_model_briefs(pred, ai_records)
    jc_reason = info.get("jingcai_reason") or ""
    summary_text = _pick_summary_text(
        pred, deep_record=deep_record, ai_records=ai_records, model_briefs=model_briefs,
    )
    synth_text = _build_ai_synthesis(pred, model_briefs=model_briefs, jc_reason=jc_reason) or summary_text
    model_picks = [b["pick"] for b in model_briefs if b.get("pick") not in ("—", "", NO_JINGCAI, "观望")]
    models_agree = len({p for p in model_picks}) <= 1 and len(model_picks) > 1
    jc = _latest_jingcai(timeline)
    mode = jingcai_market_mode(jc) if jc else "none"
    pick_key = final_pick_key(pred) if pred else "skip"
    jc_cells = _jc_odds_cells(jc, mode, pick_key) if jc else []
    jc_market = row.get("竞彩玩法") or info.get("jingcai_market_label") or market_label(jc, mode) if jc else ""
    if mode == "none":
        jc_market = jc_market or "—"
    hcap = handicap_label(jc) if jc and mode == "rqsp" else ""
    rq_ref = row.get("让球参考胜率") or ""
    ref = row.get("赛果参考") or pred.get("reference_result_1x2_cn") or row.get("赛果预测") or ""
    parlay = bool(pred.get("parlay_eligible"))
    return {
        **ctx,
        "buy_tier_cn": pred.get("buy_tier_cn") or row.get("购买档位") or "",
        "buy_tier_reason": pred.get("buy_tier_reason") or row.get("档位说明") or "",
        "jc_play": jc_market,
        "jc_sp": row.get("竞彩SP") or info.get("jingcai_sp") or "",
        "jc_mode": mode,
        "jc_cells": jc_cells,
        "handicap": hcap,
        "rq_ref_rate": rq_ref,
        "reference": ref,
        "summary_text": synth_text,
        "ai_models": model_briefs,
        "models_agree": models_agree,
        "model_count": len(model_briefs),
        "has_pick": bool(recommend and recommend not in ("观望", "暂无竞彩", NO_JINGCAI, "—", "")),
        "parlay_eligible": parlay,
        "updated_at": (timeline or [])[-1].get("ts") if timeline else "",
    }


def _fmt_sp_val(sp) -> str:
    if sp is None or sp == "":
        return "—"
    try:
        return f"{float(sp):.2f}"
    except (TypeError, ValueError):
        return str(sp)


def html_ai_summary_card(ctx: dict[str, Any]) -> str:
    """竞彩可购推荐海报 — 专为「存图发抖音」设计，不含比分."""
    home = _e(ctx.get("home"))
    away = _e(ctx.get("away"))
    kickoff_full = _e(ctx.get("kickoff_full") or "—")
    stop_sale = _e(ctx.get("stop_sale") or "—")
    kickoff_line = _e(ctx.get("kickoff_line") or "—")
    num = _e(ctx.get("match_num") or "—")
    rec = ctx.get("recommend") or NO_JINGCAI
    rec_e = _e(rec)
    play = ctx.get("jc_play") or "—"
    sp = ctx.get("jc_sp")
    mode = ctx.get("jc_mode") or "none"
    hcap = ctx.get("handicap") or ""

    pick_cls = "jc-rec-pick"
    if not ctx.get("has_pick"):
        pick_cls += " is-wait"

    sp_sub = ""
    if sp:
        sp_sub = f"SP {_e(_fmt_sp_val(sp))}"
    if play and play != "—":
        sp_sub = f"{sp_sub} · {_e(play)}" if sp_sub else _e(play)

    grid_head = "胜平负 SP"
    if mode == "rqsp" and hcap:
        grid_head = f"让球({_e(hcap)}) 胜平负"
    elif mode == "rqsp":
        grid_head = "让球胜平负"

    grid_html = ""
    cells = ctx.get("jc_cells") or []
    if cells:
        for cell in cells:
            cls = "jc-sp-cell"
            if cell.get("highlight"):
                cls += " is-rec"
            tag = '<em class="jc-rec-tag">推荐</em>' if cell.get("highlight") else ""
            grid_html += (
                f'<div class="{cls}"><span class="jc-sp-lbl">{_e(cell.get("label"))}</span>'
                f'<strong class="jc-sp-val">{_e(_fmt_sp_val(cell.get("sp")))}</strong>{tag}</div>'
            )
    else:
        grid_html = '<div class="jc-sp-empty">暂无竞彩 SP 数据</div>'

    tier_cn = ctx.get("buy_tier_cn") or ""
    tier_html = ""
    if tier_cn:
        tier_css = {"可串": "a", "可单关": "b", "仅参考": "c"}.get(tier_cn, "c")
        parlay = " · 可加入 2串1" if ctx.get("parlay_eligible") else ""
        reason = ctx.get("buy_tier_reason") or ""
        tier_html = (
            f'<div class="jc-tier jc-tier-{tier_css}">'
            f'<strong>{_e(tier_cn)}</strong>{_e(parlay)}'
            f'{f"<span>{_e(reason)}</span>" if reason else ""}'
            f"</div>"
        )

    ai_models = ctx.get("ai_models") or []
    models_agree = ctx.get("models_agree")
    agree_html = ""
    if len(ai_models) > 1:
        agree_txt = "多模型一致" if models_agree else "模型存在分歧"
        agree_cls = "is-ok" if models_agree else "is-warn"
        agree_html = f'<div class="jc-agree {agree_cls}">{_e(agree_txt)}</div>'

    models_html = ""
    for m in ai_models[:3]:
        pick = m.get("pick") or "—"
        pick_cls = "jc-model-pick"
        if pick in ("观望", NO_JINGCAI, "—", ""):
            pick_cls += " is-muted"
        conf = m.get("confidence") or ""
        conf_tag = f'<span class="jc-model-conf">置信 {_e(conf)}</span>' if conf and conf != "—" else ""
        summ = m.get("summary") or ""
        summ_block = f'<p class="jc-model-sum">{_e(summ[:180])}</p>' if summ else '<p class="jc-model-sum is-muted">暂无文字总结</p>'
        models_html += (
            f'<div class="jc-model-card">'
            f'<div class="jc-model-head">'
            f'<strong class="jc-model-name">{_e(m.get("label", "AI"))}</strong>'
            f'<span class="{pick_cls}">推荐 · {_e(pick)}</span>'
            f'{conf_tag}'
            f"</div>{summ_block}</div>"
        )
    if not models_html:
        models_html = (
            '<div class="jc-model-card is-empty">'
            "<p>请先点击页顶「✨ AI 推荐本场」，生成各模型竞彩推荐与总结后再存图。</p></div>"
        )

    synth = ctx.get("summary_text") or ""
    synth_html = ""
    if synth:
        synth_html = (
            f'<div class="jc-synth">'
            f'<div class="jc-synth-hd">AI 综合总结</div>'
            f"<p>{_e(synth[:260])}</p></div>"
        )

    summary = ctx.get("summary_text") or ""
    if summary:
        reason_html = synth_html
    elif not ctx.get("has_pick"):
        reason_html = synth_html or (
            '<div class="jc-synth is-muted"><div class="jc-synth-hd">AI 综合总结</div>'
            "<p>点击页顶「✨ AI 推荐本场」生成竞彩推荐后，再点「保存推荐图」。</p></div>"
        )
    else:
        reason_html = synth_html

    ref = ctx.get("reference") or ""
    ref_html = ""
    if ref and ref not in (rec, "—", NO_JINGCAI, ""):
        ref_html = (
            f'<div class="jc-ref-box">'
            f'<span class="jc-ref-label">赛果参考</span>'
            f'<span class="jc-ref-note">（欧亚盘口 · 非竞彩购买项）</span>'
            f'<strong>{_e(ref)}</strong></div>'
        )
    rq_ref = ctx.get("rq_ref_rate") or ""
    rq_html = ""
    if rq_ref and mode == "rqsp":
        rq_html = f'<div class="jc-rq-ref">让球参考胜率 {_e(rq_ref)}</div>'

    conf = ctx.get("confidence") or ""
    conf_html = ""
    if conf and conf != "—":
        conf_html = f'<span class="jc-meta-chip">置信 {_e(conf)}</span>'

    return f"""
<div class="jc-poster">
  <div class="jc-poster-top">
    <div class="jc-brand">竞彩足球 · AI 推荐 &amp; 总结</div>
    <div class="jc-match-num">{num}</div>
  </div>
  <div class="jc-teams">
    <div class="jc-team"><span>{home}</span></div>
    <div class="jc-vs">VS</div>
    <div class="jc-team"><span>{away}</span></div>
  </div>
  <div class="jc-schedule">{kickoff_full} · {stop_sale} 停售 · {kickoff_line} 开球</div>
  <div class="jc-rec-panel">
    <div class="jc-rec-hd">竞彩可购</div>
    <div class="{pick_cls}">{rec_e}</div>
    {f'<div class="jc-rec-sub">{sp_sub}</div>' if sp_sub else ''}
    <div class="jc-sp-grid-hd">{grid_head}</div>
    <div class="jc-sp-grid">{grid_html}</div>
  </div>
  {tier_html}
  {reason_html}
  <div class="jc-ai-section">
    <div class="jc-ai-section-hd">各模型 AI 推荐 · 总结</div>
    {agree_html}
    <div class="jc-model-list">{models_html}</div>
  </div>
  {rq_html}
  {ref_html}
  <div class="jc-meta-row">{conf_html}</div>
  <div class="jc-foot">公益体彩 量力而行 · 仅供参考 · 不构成投注建议</div>
</div>"""


AI_SUMMARY_POSTER_CSS = """
.export-module-poster { max-width: 420px; margin: 0 auto 16px; }
.export-poster-actions { text-align: center; margin-bottom: 10px; }
.btn-poster-save {
  display: inline-block; width: 100%; max-width: 420px; padding: 12px 16px;
  border: none; border-radius: 10px; cursor: pointer; font-size: 15px; font-weight: 700;
  color: #fff; background: linear-gradient(90deg, #dc2626, #b91c1c);
  box-shadow: 0 4px 14px rgba(220,38,38,.35);
}
.btn-poster-save:hover { filter: brightness(1.05); }
.btn-poster-save:disabled { opacity: .65; cursor: wait; }
.export-poster { border-radius: 14px; overflow: hidden; box-shadow: 0 8px 28px rgba(15,23,42,.12); }
.jc-poster {
  background: #fff; color: #1e293b; font-family: system-ui, -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
}
.jc-poster-top {
  background: linear-gradient(135deg, #b91c1c 0%, #991b1b 55%, #7f1d1d 100%);
  color: #fff; padding: 14px 16px 12px; display: flex; justify-content: space-between; align-items: center; gap: 8px;
}
.jc-brand { font-size: 14px; font-weight: 800; letter-spacing: .04em; }
.jc-match-num {
  font-size: 12px; font-weight: 700; background: rgba(255,255,255,.18); padding: 3px 10px; border-radius: 999px;
}
.jc-teams {
  display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 8px;
  padding: 18px 16px 8px; text-align: center;
}
.jc-team span {
  display: block; font-size: clamp(1.05rem, 4.2vw, 1.35rem); font-weight: 900; line-height: 1.25; color: #0f172a;
}
.jc-vs {
  font-size: 13px; font-weight: 900; color: #dc2626; background: #fef2f2; border-radius: 999px;
  padding: 6px 10px; border: 1px solid #fecaca;
}
.jc-schedule { text-align: center; font-size: 12px; color: #64748b; padding: 0 16px 14px; line-height: 1.5; }
.jc-rec-panel {
  margin: 0 14px 12px; padding: 14px 12px 12px; border-radius: 12px;
  background: linear-gradient(180deg, #fffbeb 0%, #fff 100%); border: 2px solid #fbbf24;
}
.jc-rec-hd { font-size: 11px; font-weight: 800; color: #b45309; letter-spacing: .12em; text-align: center; }
.jc-rec-pick {
  font-size: clamp(2rem, 8vw, 2.6rem); font-weight: 900; color: #dc2626; text-align: center;
  line-height: 1.1; margin: 6px 0 2px;
}
.jc-rec-pick.is-wait { font-size: clamp(1.2rem, 5vw, 1.6rem); color: #64748b; }
.jc-rec-sub { text-align: center; font-size: 14px; font-weight: 700; color: #475569; margin-bottom: 10px; }
.jc-sp-grid-hd { font-size: 11px; color: #94a3b8; text-align: center; margin-bottom: 6px; font-weight: 600; }
.jc-sp-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.jc-sp-cell {
  background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 8px 4px; text-align: center;
}
.jc-sp-lbl { display: block; font-size: 12px; color: #64748b; font-weight: 600; }
.jc-sp-val { display: block; font-size: 18px; font-weight: 900; color: #0f172a; margin-top: 2px; }
.jc-sp-cell.is-rec {
  background: linear-gradient(180deg, #fef3c7, #fde68a); border-color: #f59e0b; position: relative;
}
.jc-sp-cell.is-rec .jc-sp-val { color: #92400e; }
.jc-rec-tag {
  display: block; font-style: normal; font-size: 10px; font-weight: 800; color: #fff;
  background: #dc2626; border-radius: 4px; margin-top: 4px; padding: 1px 0;
}
.jc-sp-empty { grid-column: 1 / -1; text-align: center; font-size: 13px; color: #94a3b8; padding: 8px; }
.jc-tier {
  margin: 0 14px 10px; padding: 8px 12px; border-radius: 10px; font-size: 13px; text-align: center; line-height: 1.45;
}
.jc-tier strong { font-weight: 800; }
.jc-tier span { display: block; font-size: 12px; opacity: .85; margin-top: 2px; }
.jc-tier-a { background: #ecfdf5; color: #166534; border: 1px solid #86efac; }
.jc-tier-b { background: #eff6ff; color: #1e40af; border: 1px solid #93c5fd; }
.jc-tier-c { background: #f8fafc; color: #64748b; border: 1px solid #e2e8f0; }
.jc-synth {
  margin: 0 14px 10px; padding: 10px 12px; background: #f0fdf4; border-radius: 10px;
  border: 1px solid #86efac; text-align: left;
}
.jc-synth-hd { font-size: 11px; font-weight: 800; color: #166534; margin-bottom: 4px; letter-spacing: .06em; }
.jc-synth p { margin: 0; font-size: 13px; line-height: 1.6; color: #14532d; }
.jc-synth.is-muted { background: #f8fafc; border-color: #e2e8f0; }
.jc-synth.is-muted .jc-synth-hd { color: #64748b; }
.jc-synth.is-muted p { color: #64748b; }
.jc-ai-section { margin: 0 14px 10px; text-align: left; }
.jc-ai-section-hd { font-size: 12px; font-weight: 800; color: #334155; margin-bottom: 6px; }
.jc-agree {
  display: inline-block; font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 999px;
  margin-bottom: 8px;
}
.jc-agree.is-ok { background: #dcfce7; color: #166534; }
.jc-agree.is-warn { background: #fff7ed; color: #c2410c; }
.jc-model-list { display: flex; flex-direction: column; gap: 8px; }
.jc-model-card {
  background: #faf5ff; border: 1px solid #ddd6fe; border-radius: 10px; padding: 10px 12px;
}
.jc-model-card.is-empty p { margin: 0; font-size: 12px; color: #64748b; line-height: 1.5; }
.jc-model-head { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 8px; margin-bottom: 6px; }
.jc-model-name { font-size: 13px; color: #5b21b6; }
.jc-model-pick {
  font-size: 12px; font-weight: 800; color: #dc2626; background: #fef2f2;
  padding: 2px 8px; border-radius: 999px; border: 1px solid #fecaca;
}
.jc-model-pick.is-muted { color: #64748b; background: #f1f5f9; border-color: #e2e8f0; }
.jc-model-conf { font-size: 11px; color: #64748b; }
.jc-model-sum { margin: 0; font-size: 12px; line-height: 1.55; color: #334155; }
.jc-model-sum.is-muted { color: #94a3b8; }
.jc-rq-ref { margin: 0 14px 8px; font-size: 12px; color: #475569; text-align: center; }
.jc-ref-box {
  margin: 0 14px 10px; padding: 8px 12px; background: #f1f5f9; border-radius: 8px;
  font-size: 12px; text-align: center; color: #475569;
}
.jc-ref-label { font-weight: 800; color: #334155; }
.jc-ref-note { font-size: 11px; color: #94a3b8; margin: 0 4px; }
.jc-ref-box strong { color: #1e293b; margin-left: 4px; }
.jc-meta-row { display: flex; justify-content: center; gap: 8px; padding: 0 14px 8px; }
.jc-meta-chip { font-size: 11px; color: #64748b; background: #f1f5f9; padding: 3px 10px; border-radius: 999px; }
.jc-foot {
  padding: 10px 14px 14px; text-align: center; font-size: 10px; color: #94a3b8; line-height: 1.45;
  border-top: 1px dashed #e2e8f0; margin-top: 4px;
}
"""


def html_ai_summary_panel(ctx: dict[str, Any], *, slug: str = "ai-summary") -> str:
    """Poster + prominent save button (button hidden inside saved PNG)."""
    poster = html_ai_summary_card(ctx)
    btn = (
        '<button type="button" class="btn-poster-save export-hide" '
        'onclick="saveModuleImage(this)">📷 保存推荐图（发抖音）</button>'
    )
    return (
        f'<div class="export-module export-module-poster" data-export-slug="{_e(slug)}">'
        f'<div class="export-poster-actions">{btn}</div>'
        f'<div class="export-poster">{poster}</div></div>'
    )


def html_share_match(ctx: dict[str, Any]) -> str:
    fid = ctx.get("fixture_id") or ""
    home = _e(ctx.get("home"))
    away = _e(ctx.get("away"))
    num = _e(ctx.get("match_num") or "—")
    kickoff_full = _e(ctx.get("kickoff_full"))
    stop_sale = _e(ctx.get("stop_sale"))
    kickoff_line = _e(ctx.get("kickoff_line"))

    sp_html = ""
    if ctx.get("has_sp"):
        for row in ctx.get("sp_rows") or []:
            cls = "sp-row highlight" if row.get("highlight") else "sp-row"
            tag = '<span class="rec-tag">推荐</span>' if row.get("highlight") else ""
            sp_html += f'<div class="{cls}">{tag}{_e(row.get("line"))}</div>\n'
    else:
        sp_html = '<div class="sp-row muted">暂无竞彩 SP，以下为 AI 分析推荐</div>'

    ai_html = ""
    for p in ctx.get("ai_picks") or []:
        ai_html += f'<span class="ai-chip">{_e(p["label"])}·{_e(p["pick"])}</span>'

    rec = _e(ctx.get("recommend") or "观望")
    scores = _e(ctx.get("scores") or "—")
    conf = _e(ctx.get("confidence") or "—")
    ah = _e(ctx.get("asian") or "—")
    fname = re.sub(r"[^\w\u4e00-\u9fff]+", "-", ctx.get("match_name") or fid)

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>朋友圈图 · {_e(ctx.get('match_name'))}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;700;900&display=swap" rel="stylesheet"/>
<script src="https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js"></script>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif;
  background: #1a1a1a; min-height: 100vh; padding: 16px;
  display: flex; flex-direction: column; align-items: center; gap: 16px;
}}
.toolbar {{
  width: min(750px, 100%); display: flex; gap: 10px; flex-wrap: wrap;
}}
.toolbar a, .toolbar button {{
  padding: 10px 18px; border-radius: 8px; border: none; cursor: pointer;
  font-size: 14px; text-decoration: none; display: inline-block;
}}
.btn-save {{ background: #dc2626; color: #fff; font-weight: 700; }}
.btn-back {{ background: #fff; color: #333; }}
#share-wrap {{
  width: min(750px, 100%);
  background: linear-gradient(160deg, #9b1c1c 0%, #6b0f0f 45%, #8b1515 100%);
  border-radius: 12px; padding: 28px 20px 24px;
  position: relative; overflow: hidden;
}}
#share-wrap::before {{
  content: ""; position: absolute; inset: 0; opacity: 0.08;
  background: radial-gradient(circle at 20% 30%, #fff 0%, transparent 50%),
              radial-gradient(circle at 80% 70%, #ffd700 0%, transparent 40%);
  pointer-events: none;
}}
.side-left, .side-right {{
  position: absolute; top: 50%; transform: translateY(-50%);
  writing-mode: vertical-rl; font-size: 22px; font-weight: 900;
  color: rgba(255,215,0,0.85); letter-spacing: 6px; z-index: 2;
}}
.side-left {{ left: 6px; }}
.side-right {{ right: 6px; }}
.scroll {{
  position: relative; z-index: 3; margin: 0 36px;
  background: linear-gradient(180deg, #fffef8 0%, #f5ecd8 100%);
  border: 3px solid #c9a227; border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0,0,0,.35), inset 0 0 0 1px #fff;
  padding: 28px 22px 20px; text-align: center;
}}
.teams {{
  font-size: clamp(28px, 6vw, 40px); font-weight: 900; color: #1a1a1a;
  line-height: 1.2; margin-bottom: 8px;
}}
.vs {{ color: #b91c1c; margin: 0 6px; font-size: 0.85em; }}
.sub {{ font-size: 15px; color: #666; margin-bottom: 14px; }}
.deadline {{
  display: inline-block; background: #16a34a; color: #fff;
  font-size: 14px; font-weight: 700; padding: 6px 14px; border-radius: 4px;
  margin-bottom: 18px;
}}
.sp-row {{
  font-size: clamp(22px, 5vw, 30px); font-weight: 900; color: #111;
  padding: 10px 8px; margin: 6px 0; border-radius: 6px;
  position: relative;
}}
.sp-row.highlight {{
  background: linear-gradient(90deg, #fef3c7, #fde68a);
  border: 2px solid #d97706;
  color: #92400e;
}}
.sp-row.muted {{ font-size: 16px; font-weight: 400; color: #888; }}
.rec-tag {{
  display: inline-block; background: #dc2626; color: #fff;
  font-size: 12px; padding: 2px 8px; border-radius: 4px;
  margin-right: 8px; vertical-align: middle; font-weight: 700;
}}
.ai-box {{
  margin-top: 16px; padding-top: 14px; border-top: 1px dashed #d4c4a8;
  text-align: left;
}}
.ai-title {{ font-size: 13px; color: #888; margin-bottom: 8px; }}
.ai-chip {{
  display: inline-block; background: #7c3aed; color: #fff;
  font-size: 13px; padding: 4px 10px; border-radius: 999px; margin: 0 6px 6px 0;
}}
.ai-main {{
  font-size: 18px; font-weight: 900; color: #b91c1c; margin-top: 8px;
}}
.ai-meta {{ font-size: 13px; color: #555; margin-top: 6px; line-height: 1.5; }}
.footer {{
  margin-top: 16px; font-size: 12px; color: rgba(255,255,255,.75);
  text-align: center; position: relative; z-index: 3;
}}
.hint {{ color: #aaa; font-size: 13px; text-align: center; max-width: 750px; }}
@media (max-width: 520px) {{
  body {{ padding: 10px; }}
  .side-left, .side-right {{ display: none; }}
  .scroll {{ margin: 0; padding: 22px 16px 18px; }}
  .toolbar {{ flex-direction: column; }}
  .toolbar a, .toolbar button {{ width: 100%; text-align: center; }}
}}
</style>
</head><body>
<div class="toolbar">
  <button type="button" class="btn-save" onclick="savePng()">📷 保存 PNG（发朋友圈）</button>
  <a class="btn-back" href="/match/{_e(fid)}">← 返回比赛详情</a>
</div>
<p class="hint">点击下方按钮保存图片；也可手机截屏。推荐方向已高亮。</p>

<div id="share-wrap">
  <div class="side-left">今日必买</div>
  <div class="side-right">一击制胜</div>
  <div id="share-card" class="scroll">
    <div class="teams">{home}<span class="vs">VS</span>{away}</div>
    <div class="sub">{kickoff_full} · {num} · 世界杯</div>
    <div class="deadline">{stop_sale} 停售 · {kickoff_line}</div>
    {sp_html}
    <div class="ai-box">
      <div class="ai-title">精算师推荐</div>
      {ai_html or '<span class="ai-chip">待分析</span>'}
      <div class="ai-main">推荐：{rec} · 置信 {conf}</div>
      <div class="ai-meta">比分 {scores}<br/>亚盘 {ah}</div>
    </div>
  </div>
  <div class="footer">公益体彩 量力而行 · 仅供参考 不构成投注建议</div>
</div>

<script>
async function savePng() {{
  const btn = document.querySelector('.btn-save');
  btn.disabled = true;
  btn.textContent = '生成中…';
  try {{
    const el = document.getElementById('share-wrap');
    const canvas = await html2canvas(el, {{
      scale: 2,
      useCORS: true,
      backgroundColor: null,
      logging: false,
    }});
    const a = document.createElement('a');
    a.download = '{_e(fname)}.png';
    a.href = canvas.toDataURL('image/png');
    a.click();
  }} catch (e) {{
    alert('生成失败，请截屏保存：' + e);
  }} finally {{
    btn.disabled = false;
    btn.textContent = '📷 保存 PNG（发朋友圈）';
  }}
}}
</script>
</body></html>"""


HTML2CANVAS_CDN = (
    '<script src="https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js"></script>'
)


def long_image_export_script(*, root_id: str, filename: str) -> str:
    """Reusable browser-side long PNG export + per-module PNG export."""
    safe_fname = re.sub(r"[^\w\-]+", "_", filename).strip("_") or "page"
    return f"""{HTML2CANVAS_CDN}
<script>
function _freezeCanvases(root) {{
  const backups = [];
  root.querySelectorAll('canvas').forEach(cv => {{
    try {{
      const chart = window.Chart && Chart.getChart ? Chart.getChart(cv) : null;
      const url = chart && chart.toBase64Image ? chart.toBase64Image() : cv.toDataURL('image/png');
      const img = document.createElement('img');
      img.src = url;
      img.className = 'export-chart-img';
      img.style.width = '100%';
      img.style.height = 'auto';
      img.style.display = 'block';
      cv.parentNode.insertBefore(img, cv);
      cv.style.display = 'none';
      backups.push({{ cv, img }});
    }} catch (e) {{}}
  }});
  return backups;
}}
function _restoreCanvases(backups) {{
  backups.forEach(({{ cv, img }}) => {{
    cv.style.display = '';
    if (img && img.parentNode) img.parentNode.removeChild(img);
  }});
}}
function _exportBaseName() {{
  const root = document.getElementById('{_e(root_id)}');
  return (root && root.dataset.exportBase) || '{_e(safe_fname)}';
}}
async function saveModuleImage(btn) {{
  const mod = btn && btn.closest ? btn.closest('.export-module') : null;
  if (!mod) {{
    alert('未找到可导出的模块');
    return;
  }}
  const label = btn ? btn.textContent : '';
  if (btn) {{ btn.disabled = true; btn.textContent = '生成中…'; }}
  const slug = mod.dataset.exportSlug || 'module';
  const filename = _exportBaseName() + '-' + slug + '.png';
  const detailsEl = mod.matches('details') ? mod : mod.closest('details');
  const wasOpen = detailsEl ? detailsEl.open : true;
  if (detailsEl && !detailsEl.open) detailsEl.open = true;
  const hidden = mod.querySelectorAll('.export-hide');
  hidden.forEach(n => {{ n.dataset.exportPrev = n.style.display; n.style.display = 'none'; }});
  const target = mod.querySelector('.export-poster') || mod;
  let canvasBackups = [];
  try {{
    canvasBackups = _freezeCanvases(target);
    await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
    const canvas = await html2canvas(target, {{
      scale: Math.min(2, window.devicePixelRatio || 1.5),
      useCORS: true,
      backgroundColor: '#ffffff',
      logging: false,
      scrollY: -window.scrollY,
      scrollX: 0,
      width: target.scrollWidth,
      height: target.scrollHeight,
    }});
    const a = document.createElement('a');
    a.download = filename;
    a.href = canvas.toDataURL('image/png');
    a.click();
  }} catch (e) {{
    alert('模块存图失败：' + e);
  }} finally {{
    _restoreCanvases(canvasBackups);
    if (detailsEl) detailsEl.open = wasOpen;
    hidden.forEach(n => {{
      n.style.display = n.dataset.exportPrev || '';
      delete n.dataset.exportPrev;
    }});
    if (btn) {{ btn.disabled = false; btn.textContent = label || '📷 存图'; }}
  }}
}}
async function savePageLongImage(btn) {{
  const root = document.getElementById('{_e(root_id)}');
  if (!root) {{
    alert('未找到导出区域');
    return;
  }}
  const label = btn ? btn.textContent : '';
  if (btn) {{ btn.disabled = true; btn.textContent = '长图生成中…'; }}
  const details = root.querySelectorAll('details');
  const detailStates = Array.from(details, d => d.open);
  details.forEach(d => {{ d.open = true; }});
  const hidden = root.querySelectorAll('.export-hide');
  hidden.forEach(n => {{ n.dataset.exportPrev = n.style.display; n.style.display = 'none'; }});
  let canvasBackups = [];
  try {{
    canvasBackups = _freezeCanvases(root);
    await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
    const canvas = await html2canvas(root, {{
      scale: Math.min(2, window.devicePixelRatio || 1.5),
      useCORS: true,
      backgroundColor: '#f8fafc',
      logging: false,
      scrollY: 0,
      scrollX: 0,
      windowWidth: root.scrollWidth,
      windowHeight: root.scrollHeight,
    }});
    const a = document.createElement('a');
    a.download = '{_e(safe_fname)}.png';
    a.href = canvas.toDataURL('image/png');
    a.click();
  }} catch (e) {{
    alert('长图生成失败，请尝试浏览器整页截屏：' + e);
  }} finally {{
    _restoreCanvases(canvasBackups);
    details.forEach((d, i) => {{ d.open = detailStates[i]; }});
    hidden.forEach(n => {{
      n.style.display = n.dataset.exportPrev || '';
      delete n.dataset.exportPrev;
    }});
    if (btn) {{ btn.disabled = false; btn.textContent = label || '📷 保存长图'; }}
  }}
}}
async function saveAllPosterImages(btn) {{
  const mods = document.querySelectorAll('.export-module-poster');
  if (!mods.length) {{
    alert('没有可导出的推荐图');
    return;
  }}
  const label = btn ? btn.textContent : '';
  if (btn) {{ btn.disabled = true; }}
  for (let i = 0; i < mods.length; i++) {{
    if (btn) btn.textContent = '生成中 ' + (i + 1) + '/' + mods.length + '…';
    const saveBtn = mods[i].querySelector('.btn-poster-save');
    if (saveBtn) await saveModuleImage(saveBtn);
    if (i + 1 < mods.length) await new Promise(r => setTimeout(r, 450));
  }}
  if (btn) {{ btn.disabled = false; btn.textContent = label || '📷 一键保存全部'; }}
}}
</script>"""


POSTER_BATCH_PAGE_CSS = """
body.poster-batch-page { background: #e2e8f0; }
.poster-batch-toolbar {
  position: sticky; top: 0; z-index: 20; background: rgba(248,250,252,.96);
  backdrop-filter: blur(8px); border-bottom: 1px solid #cbd5e1;
  padding: 12px clamp(12px, 3vw, 24px); margin: 0 0 16px;
  display: flex; gap: 10px; flex-wrap: wrap; align-items: center;
}
.poster-batch-toolbar .btn { margin: 0; }
.poster-batch-list { max-width: 460px; margin: 0 auto; padding: 0 12px 32px; }
.poster-batch-item { margin-bottom: 28px; }
.poster-batch-item h2 {
  font-size: 15px; margin: 0 0 10px; color: #334155; font-weight: 700;
}
.poster-batch-item h2 a { color: #1e40af; text-decoration: none; }
.poster-batch-meta { color: #64748b; font-size: 13px; margin: 0 0 16px; line-height: 1.5; }
"""


def html_share_posters_batch(items: list[dict[str, Any]]) -> str:
    """One AI recommendation poster per selected match."""
    if not items:
        return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"/><title>批量推荐图</title></head>
<body><p><a href="/">← 返回首页</a></p><p>未找到有效比赛。</p></body></html>"""

    sections: list[str] = []
    for item in items:
        ctx = item.get("ctx") or {}
        fid = str(item.get("fixture_id") or ctx.get("fixture_id") or "")
        name = item.get("match_name") or ctx.get("match_name") or fid or "—"
        slug = f"ai-summary-{fid}" if fid else "ai-summary"
        panel = html_ai_summary_panel(ctx, slug=slug)
        sections.append(
            f'<section class="poster-batch-item">'
            f'<h2><a href="/match/{_e(fid)}">{_e(name)}</a></h2>'
            f"{panel}</section>"
        )

    n = len(items)
    export_script = long_image_export_script(root_id="poster-batch-root", filename="batch-posters")
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>批量推荐图 · {n} 场</title>
{export_script}
<style>
{POSTER_BATCH_PAGE_CSS}
{AI_SUMMARY_POSTER_CSS}
.btn {{
  display: inline-block; padding: 8px 16px; background: #2563eb; color: #fff !important;
  border: none; border-radius: 6px; cursor: pointer; font-size: 14px; text-decoration: none;
}}
.btn:disabled {{ opacity: 0.6; cursor: wait; }}
</style>
</head>
<body class="poster-batch-page">
<div class="poster-batch-toolbar">
  <a class="btn" style="background:#64748b" href="/">← 返回列表</a>
  <button type="button" class="btn" style="background:#dc2626"
    onclick="saveAllPosterImages(this)">📷 一键保存全部（{n} 张）</button>
</div>
<p class="poster-batch-meta poster-batch-list" style="max-width:460px">
  共 {n} 场 · 每场一张 PNG，适合发抖音；也可点每张下方的「保存推荐图」单独下载。
  若某场尚无 AI 推荐，请先在列表或详情页点「AI推荐」后再刷新本页。
</p>
<div id="poster-batch-root" class="poster-batch-list" data-export-base="batch-posters">
{"".join(sections)}
</div>
</body></html>"""


def build_parlay_share_context(analysis: dict[str, Any]) -> dict[str, Any]:
    """Build render context for 2-leg parlay share card."""
    legs = analysis.get("legs") or []
    expl = analysis.get("explanation") or {}
    combined = analysis.get("combined_odds")
    payout = analysis.get("payout_per_100")
    return {
        "parlay_type": analysis.get("parlay_type") or "2串1",
        "verdict": analysis.get("verdict") or "—",
        "verdict_detail": analysis.get("verdict_detail") or "",
        "combined_odds": combined,
        "payout_per_100": payout,
        "implied_win_pct": analysis.get("implied_win_pct"),
        "generated_at": analysis.get("generated_at") or "",
        "summary": analysis.get("summary") or "",
        "legs": legs,
        "explanation": expl,
        "warnings": analysis.get("warnings") or [],
        "ai_note": expl.get("ai_note") or "",
    }


def html_share_parlay(ctx: dict[str, Any]) -> str:
    verdict = _e(ctx.get("verdict") or "—")
    combined = ctx.get("combined_odds")
    combined_txt = f"{combined:.2f}" if combined else "—"
    payout = ctx.get("payout_per_100")
    payout_txt = f"{int(payout):,}" if payout else "—"
    implied = ctx.get("implied_win_pct")
    implied_txt = f"{implied}%" if implied else "—"
    generated = _e(ctx.get("generated_at") or "")

    expl = ctx.get("explanation") or {}
    headline = _e(expl.get("headline") or ctx.get("verdict_detail") or ctx.get("summary") or "")
    stake = _e(expl.get("stake_advice") or "")
    paragraph = _e(expl.get("paragraph") or "")

    reasons_html = ""
    for r in expl.get("reasons") or []:
        reasons_html += f'<li>{_e(r)}</li>\n'
    if not reasons_html and ctx.get("warnings"):
        for w in ctx["warnings"][:4]:
            reasons_html += f'<li class="warn">{_e(w)}</li>\n'

    legs_html = ""
    for i, leg in enumerate(ctx.get("legs") or [], 1):
        home, away = split_teams(leg.get("match") or "")
        sp = leg.get("odds_used") or leg.get("jingcai_sp") or "—"
        pick = _e(leg.get("pick_cn") or "—")
        conf = _e(leg.get("confidence_cn") or "—")
        ko = _e(leg.get("kickoff") or "")
        scores = _e(leg.get("scores") or "—")
        market = _e(leg.get("market_pattern_summary") or "")
        leg_expl = ""
        for lr in expl.get("leg_reasons") or []:
            if lr.get("match") == leg.get("match"):
                leg_expl = _e(lr.get("text") or "")
                break
        legs_html += f"""
    <div class="leg-card">
      <div class="leg-num">第 {i} 场</div>
      <div class="teams">{_e(home)}<span class="vs">VS</span>{_e(away)}</div>
      <div class="sub">{ko}</div>
      <div class="pick-line">推荐 <strong>{pick}</strong> · SP {sp} · 置信 {conf}</div>
      <div class="leg-meta">比分 {scores}</div>
      {f'<div class="leg-meta">欧亚转换 {market}</div>' if market else ''}
      {f'<div class="leg-reason">{leg_expl}</div>' if leg_expl else ''}
    </div>"""

    ai_note = _e(ctx.get("ai_note") or "")
    ai_box = ""
    if ai_note:
        ai_box = f'<div class="ai-box"><div class="ai-title">AI 简评</div><div class="ai-main">{ai_note}</div></div>'

    fname = "2串1"
    for leg in ctx.get("legs") or []:
        home, _ = split_teams(leg.get("match") or "")
        if home:
            fname += "-" + home[:6]
    fname = re.sub(r"[^\w\u4e00-\u9fff\-]+", "", fname)

    verdict_cls = "verdict-ok" if ctx.get("verdict") == "可串" else (
        "verdict-bad" if ctx.get("verdict") == "不建议" else "verdict-warn"
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>2串1 分享图</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;700;900&display=swap" rel="stylesheet"/>
<script src="https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js"></script>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif;
  background: #1a1a1a; min-height: 100vh; padding: 16px;
  display: flex; flex-direction: column; align-items: center; gap: 16px;
}}
.toolbar {{
  width: min(750px, 100%); display: flex; gap: 10px; flex-wrap: wrap;
}}
.toolbar a, .toolbar button {{
  padding: 10px 18px; border-radius: 8px; border: none; cursor: pointer;
  font-size: 14px; text-decoration: none; display: inline-block;
}}
.btn-save {{ background: #dc2626; color: #fff; font-weight: 700; }}
.btn-back {{ background: #fff; color: #333; }}
#share-wrap {{
  width: min(750px, 100%);
  background: linear-gradient(160deg, #1e3a8a 0%, #1e40af 45%, #172554 100%);
  border-radius: 12px; padding: 28px 20px 24px;
  position: relative; overflow: hidden;
}}
#share-wrap::before {{
  content: ""; position: absolute; inset: 0; opacity: 0.1;
  background: radial-gradient(circle at 20% 30%, #fff 0%, transparent 50%),
              radial-gradient(circle at 80% 70%, #60a5fa 0%, transparent 40%);
  pointer-events: none;
}}
.side-left, .side-right {{
  position: absolute; top: 50%; transform: translateY(-50%);
  writing-mode: vertical-rl; font-size: 22px; font-weight: 900;
  color: rgba(147,197,253,0.9); letter-spacing: 6px; z-index: 2;
}}
.side-left {{ left: 6px; }}
.side-right {{ right: 6px; }}
.scroll {{
  position: relative; z-index: 3; margin: 0 36px;
  background: linear-gradient(180deg, #fffef8 0%, #f0f4ff 100%);
  border: 3px solid #3b82f6; border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0,0,0,.35), inset 0 0 0 1px #fff;
  padding: 24px 20px 18px; text-align: center;
}}
.title {{
  font-size: clamp(26px, 5vw, 34px); font-weight: 900; color: #1e3a8a;
  margin-bottom: 6px;
}}
.verdict-badge {{
  display: inline-block; font-size: 18px; font-weight: 900;
  padding: 6px 16px; border-radius: 999px; margin: 8px 0 14px;
}}
.verdict-ok {{ background: #dcfce7; color: #166534; border: 2px solid #22c55e; }}
.verdict-warn {{ background: #fef3c7; color: #92400e; border: 2px solid #f59e0b; }}
.verdict-bad {{ background: #fee2e2; color: #991b1b; border: 2px solid #ef4444; }}
.odds-banner {{
  background: linear-gradient(90deg, #dbeafe, #bfdbfe);
  border: 2px solid #2563eb; border-radius: 8px;
  padding: 12px; margin-bottom: 16px; font-size: clamp(20px, 4vw, 26px);
  font-weight: 900; color: #1e3a8a;
}}
.odds-sub {{ font-size: 14px; font-weight: 400; color: #475569; margin-top: 4px; }}
.leg-card {{
  text-align: left; background: #fff; border: 1px solid #cbd5e1;
  border-radius: 8px; padding: 14px; margin: 10px 0;
}}
.leg-num {{ font-size: 12px; color: #64748b; font-weight: 700; margin-bottom: 6px; }}
.teams {{
  font-size: clamp(20px, 4vw, 28px); font-weight: 900; color: #1a1a1a;
  line-height: 1.2; margin-bottom: 4px;
}}
.vs {{ color: #2563eb; margin: 0 4px; font-size: 0.85em; }}
.sub {{ font-size: 13px; color: #666; margin-bottom: 8px; }}
.pick-line {{ font-size: 16px; color: #111; margin-bottom: 4px; }}
.pick-line strong {{ color: #dc2626; }}
.leg-meta {{ font-size: 13px; color: #555; }}
.leg-reason {{
  margin-top: 8px; font-size: 13px; color: #475569; line-height: 1.5;
  padding-top: 8px; border-top: 1px dashed #e2e8f0;
}}
.explain-box {{
  margin-top: 14px; padding-top: 12px; border-top: 2px dashed #cbd5e1;
  text-align: left;
}}
.explain-title {{ font-size: 13px; color: #64748b; font-weight: 700; margin-bottom: 6px; }}
.explain-p {{ font-size: 14px; color: #334155; line-height: 1.6; margin-bottom: 8px; }}
.reason-list {{ margin: 0; padding-left: 18px; font-size: 13px; color: #475569; line-height: 1.6; }}
.reason-list li.warn {{ color: #b45309; }}
.stake-line {{
  margin-top: 10px; font-size: 14px; font-weight: 700; color: #1d4ed8;
  background: #eff6ff; padding: 8px 10px; border-radius: 6px;
}}
.ai-box {{
  margin-top: 12px; padding-top: 10px; border-top: 1px dashed #cbd5e1; text-align: left;
}}
.ai-title {{ font-size: 12px; color: #888; margin-bottom: 4px; }}
.ai-main {{ font-size: 14px; color: #4338ca; line-height: 1.5; }}
.footer {{
  margin-top: 16px; font-size: 12px; color: rgba(255,255,255,.75);
  text-align: center; position: relative; z-index: 3;
}}
.hint {{ color: #aaa; font-size: 13px; text-align: center; max-width: 750px; }}
@media (max-width: 520px) {{
  body {{ padding: 10px; }}
  .side-left, .side-right {{ display: none; }}
  .scroll {{ margin: 0; padding: 22px 16px 18px; }}
  .toolbar {{ flex-direction: column; }}
  .toolbar a, .toolbar button {{ width: 100%; text-align: center; }}
}}
</style>
</head><body>
<div class="toolbar">
  <button type="button" class="btn-save" onclick="savePng()">📷 保存 PNG（发朋友圈）</button>
  <a class="btn-back" href="/">← 返回首页</a>
</div>
<p class="hint">点击下方按钮保存图片；也可手机截屏。含选场理由与仓位建议。</p>

<div id="share-wrap">
  <div class="side-left">自选串关</div>
  <div class="side-right">2串1</div>
  <div id="share-card" class="scroll">
    <div class="title">竞彩 2串1</div>
    <div class="verdict-badge {verdict_cls}">{verdict}</div>
    <div class="odds-banner">
      组合 SP {combined_txt}
      <div class="odds-sub">100 元约返 {payout_txt} 元 · 隐含过关 {implied_txt}</div>
    </div>
    {legs_html}
    <div class="explain-box">
      <div class="explain-title">串关说明</div>
      <div class="explain-p">{headline}</div>
      {f'<ul class="reason-list">{reasons_html}</ul>' if reasons_html else ''}
      {f'<div class="explain-p">{paragraph}</div>' if paragraph and paragraph != headline else ''}
      {f'<div class="stake-line">💡 {stake}</div>' if stake else ''}
    </div>
    {ai_box}
  </div>
  <div class="footer">公益体彩 量力而行 · 仅供参考 不构成投注建议 · {generated}</div>
</div>

<script>
async function savePng() {{
  const btn = document.querySelector('.btn-save');
  btn.disabled = true;
  btn.textContent = '生成中…';
  try {{
    const el = document.getElementById('share-wrap');
    const canvas = await html2canvas(el, {{
      scale: 2,
      useCORS: true,
      backgroundColor: null,
      logging: false,
    }});
    const a = document.createElement('a');
    a.download = '{_e(fname)}.png';
    a.href = canvas.toDataURL('image/png');
    a.click();
  }} catch (e) {{
    alert('生成失败，请截屏保存：' + e);
  }} finally {{
    btn.disabled = false;
    btn.textContent = '📷 保存 PNG（发朋友圈）';
  }}
}}
</script>
</body></html>"""
