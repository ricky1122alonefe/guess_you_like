"""Single-match share card for WeChat Moments (HTML + browser export)."""

from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timedelta
from typing import Any

from pathlib import Path

from daily_picks import load_kickoff_map
from jingcai_pick import (
    KEY_FROM_SP_CN,
    NO_JINGCAI,
    final_pick_key,
    final_recommendation_cn,
    handicap_label,
    jingcai_market_mode,
    market_label,
)
from time_utils import format_beijing, to_beijing
from ui_theme import poster_batch_page_css, poster_css, share_match_page_css

log = logging.getLogger(__name__)

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


_GAMBLING_TERM_PATTERNS: list[tuple[str, str]] = [
    (r"博彩(?:公司|平台|行业|用语)?|赌博|赌球|赌钱|彩票(?:站)?|足彩|购彩|洗码|追号", ""),
    (r"投注|下注|庄家|滚球|仓位|Kelly", ""),
    (r"竞彩(?:足球|可购|推荐|SP|方向)?|公益体彩|体彩", ""),
    (r"串关|可串|可单关|单关|[23]串1|2串1", ""),
    (r"SP(?:\s*[\d.]+)?", ""),
    (r"[\d.]+\s*倍(?:赔率)?", ""),
    (r"胜平负", "走势"),
    (r"赔率|欧赔|亚盘|盘口|水位|让球|大小球|上盘|下盘|降水|升水|诱盘|走盘|封盘|初盘|临盘", "走势"),
    (r"购彩建议|不构成(?:任何)?投注建议", ""),
    (r"公益体彩[^。]*", ""),
]


def _strip_gambling_terms(text: str) -> str:
    """Remove or neutralize gambling/lottery jargon for social export."""
    if not text:
        return ""
    out = str(text)
    for pat, repl in _GAMBLING_TERM_PATTERNS:
        out = re.sub(pat, repl, out, flags=re.IGNORECASE)
    out = re.sub(r"[（(]\s*[）)]", "", out)
    return out


def _sanitize_export_text(text: str) -> str:
    """Strip betting/lottery terms for social-media PNG export."""
    if not text:
        return ""
    out = _strip_gambling_terms(text)
    out = re.sub(r"推荐", "分析", out)
    out = re.sub(r"\s{2,}", " ", out)
    return out.strip()


def _sanitize_personal_note(text: str, *, max_len: int = 500) -> str:
    """Personal note for PNG — tactical fan tone only."""
    out = _strip_viewing_compliance_terms(str(text or ""))
    out = re.sub(r"\s{2,}", " ", out).strip()
    return out[:max_len]


_VIEWING_COMPLIANCE_PATTERNS: list[tuple[str, str]] = [
    (r"\d+(?:\.\d+)?\s*[%％]", ""),
    (r"(?:胜率|赢率|概率|机会概率|走势倾向|一致程度)", ""),
    (r"看好(?:主队|客队|主|客|巴西|日本)?|主机会|客队机会", ""),
    (r"主胜|客胜|预测(?:平局|主胜|客胜|胜负)?", ""),
    (r"综合倾向|胜负推荐|投注引导|购彩|买(?:主|客|平|球)", ""),
    (r"分流资金|盘赔|阈值|\bEV\b|\bedge\b", ""),
    (r"临盘|走势|方向|拿捏|稳(?:胆|单)?", ""),
    (r"赢球|必赢|必胜|稳赢|必出", ""),
    (r"购彩|体彩|下注|投注|串关|Kelly|赔率|盘口|水位|亚盘|欧赔|让球|竞彩|博彩|赌博|彩票|足彩|庄家", ""),
]


def _strip_viewing_compliance_terms(text: str) -> str:
    """Douyin-safe viewing poster — drop win/loss bias and platform-sensitive words."""
    if not text:
        return ""
    out = _strip_gambling_terms(text)
    for pat, repl in _VIEWING_COMPLIANCE_PATTERNS:
        out = re.sub(pat, repl, out, flags=re.IGNORECASE)
    out = re.sub(r"[（(]\s*[）)]", "", out)
    out = re.sub(r"\s{2,}", " ", out)
    return out.strip(" ·，,。；;")


def _pick_to_trend_cn(pick: str) -> str:
    pick = (pick or "").strip()
    if pick in ("主胜", "胜") or pick.endswith(" 胜"):
        return "主队"
    if pick in ("客胜", "负") or pick.endswith(" 负"):
        return "客队"
    if pick in ("平局", "平") or pick.endswith(" 平"):
        return "均衡"
    if pick in ("—", "", NO_JINGCAI, "观望"):
        return "观望"
    return _sanitize_export_text(pick) or "观望"


def _is_no_pick(pick: str) -> bool:
    return (pick or "").strip() in ("—", "", NO_JINGCAI, "观望", "待定", "skip")


def _pick_row_key_extended(pick: str) -> str | None:
    key = _pick_row_key(pick)
    if key:
        return key
    p = (pick or "").strip()
    if p in KEY_FROM_SP_CN and KEY_FROM_SP_CN[p] != "skip":
        return KEY_FROM_SP_CN[p]
    if "客" in p or p.endswith("负"):
        return "away"
    if "平" in p:
        return "draw"
    if "主" in p or p.endswith("胜"):
        return "home"
    return None


def _resolve_export_trend(ctx: dict[str, Any]) -> tuple[str, str]:
    """Headline trend for safe PNG — never leave a blank when models already picked."""
    trend_map = {"home": "主队", "draw": "均衡", "away": "客队"}
    exp_key = str(ctx.get("export_pick_key") or "").strip()
    if exp_key in trend_map:
        return trend_map[exp_key], exp_key

    rec = ctx.get("recommend") or ""
    if not _is_no_pick(rec):
        key = _pick_row_key_extended(rec)
        if key:
            return _pick_to_trend_cn(rec), key

    ref = ctx.get("reference") or ""
    if not _is_no_pick(ref):
        key = _pick_row_key_extended(ref)
        if key:
            return _pick_to_trend_cn(ref), key

    votes: dict[str, int] = {}
    order: list[str] = []
    for m in ctx.get("ai_models") or []:
        pick = m.get("pick") or ""
        if _is_no_pick(pick):
            continue
        key = _pick_row_key_extended(pick)
        if not key:
            continue
        votes[key] = votes.get(key, 0) + 1
        if key not in order:
            order.append(key)

    if votes:
        max_v = max(votes.values())
        leaders = {k for k, v in votes.items() if v == max_v}
        best = next((k for k in order if k in leaders), next(iter(leaders)))
        return trend_map[best], best

    key = _pick_row_key_extended(rec)
    if key:
        return _pick_to_trend_cn(rec), key
    return "观望", ""


def _tier_to_safe_cn(tier_cn: str) -> str:
    return {
        "可串": "一致性强",
        "可单关": "中等把握",
        "仅参考": "低把握",
    }.get((tier_cn or "").strip(), tier_cn or "")


def _confidence_to_safe_cn(conf: str) -> str:
    conf = (conf or "").strip()
    if conf in ("高", "中", "低"):
        return f"把握 · {conf}"
    return conf


def _decision_to_safe_cn(decision: str) -> str:
    d = str(decision or "").strip()
    for key, label in (
        ("A 可串", "一致性强"),
        ("B 可单关", "中等把握"),
        ("C 仅参考", "低把握参考"),
        ("skip", "建议跳过"),
        ("观望", "观望"),
    ):
        if key in d:
            return label
    safe = _tier_to_safe_cn(d)
    if safe and safe != d:
        return safe
    cleaned = _sanitize_export_text(d)
    return cleaned or "待更新"


def _risk_to_safe_cn(risk: str) -> str:
    r = str(risk or "").strip()
    if r in ("高", "中", "低"):
        return f"波动 · {r}"
    return _sanitize_export_text(r) or ""


def _contains_market_terms(text: str) -> bool:
    bad = (
        "博彩", "赌博", "赌球", "彩票", "足彩", "购彩",
        "看好", "主胜", "客胜", "预测", "走势", "方向", "拿捏",
        "水位", "盘口", "亚盘", "欧赔", "让球", "竞彩", "上盘", "下盘", "大小球",
        "降水", "升水", "诱盘", "走盘", "封盘", "初盘", "临盘", "SP", "Kelly", "串关",
        "购彩", "体彩", "下注", "投注", "赔率", "庄家", "滚球", "EV", "edge", "阈值",
    )
    blob = str(text or "")
    return any(x in blob for x in bad)


def _sanitize_agent_export_text(text: str) -> str:
    """Stronger sanitizer for multi-agent Douyin export — motivation/result only."""
    out = _sanitize_export_text(text)
    extra = [
        (r"\bAgent\b", ""),
        (r"Chief|证据板|Pipeline|工作台|智能模块", ""),
        (r"硬风险闸门?", ""),
        (r"串关|可串|可单关|仅参考|可跟|可单关", ""),
        (r"入手|仓位|Kelly|购彩|体彩|下注|投注|购彩", ""),
        (r"让球(?:\([+\-]?\d+\))?", ""),
        (r"盘口|亚盘|欧赔|水位|竞彩|上盘|下盘|大小球|降水|升水|诱盘|走盘|封盘|初盘|临盘", ""),
        (r"SP(?:\s*[\d.]+)?", ""),
        (r"数据面|走势", ""),
        (r"欧亚(?:数据|一致性)?", "赛果方向"),
    ]
    for pat, repl in extra:
        out = re.sub(pat, repl, out, flags=re.IGNORECASE)
    out = re.sub(r"[（(]\s*[）)]", "", out)
    out = re.sub(r"\s{2,}", " ", out).strip(" ·，,。；;")
    return out


_MOTIVATION_TOPIC_RE = re.compile(
    r"出线|小组|积分|排名第|净胜球|战意|晋级|淘汰|第三|同组|末轮|"
    r"默契|轮换|已锁|已达|争夺|打平|平局|战绩|交手|相互|对头|"
    r"进球数|胜场|负场|平场|积分榜|轮次|出线状态|出线形势|杯赛小组|"
    r"双方|必须赢|保平|拿分|全取|胜负关系|出线后",
)


def _is_standings_motivation_line(text: str) -> bool:
    """Only group standings / points / H2H motivation — no market wording."""
    raw = str(text or "").strip()
    if len(raw) < 4 or _contains_market_terms(raw):
        return False
    clean = _sanitize_agent_export_text(raw)
    if len(clean) < 4 or _contains_market_terms(clean):
        return False
    return bool(_MOTIVATION_TOPIC_RE.search(clean))


def _motivation_clean_lines(text: str, *, limit: int = 4) -> list[str]:
    lines: list[str] = []
    for chunk in re.split(r"[。\n；;]", str(text or "")):
        clean = _sanitize_agent_export_text(chunk.strip())
        if not _is_standings_motivation_line(clean):
            continue
        if clean not in lines:
            lines.append(clean)
        if len(lines) >= limit:
            break
    return lines


def _social_clean_lines(text: str, *, limit: int = 4) -> list[str]:
    lines: list[str] = []
    for chunk in re.split(r"[。\n；;]", str(text or "")):
        clean = _sanitize_agent_export_text(chunk.strip())
        if len(clean) < 4 or _contains_market_terms(clean):
            continue
        if clean not in lines:
            lines.append(clean)
        if len(lines) >= limit:
            break
    return lines


def _extract_motivation_judgment(
    agent_board: dict[str, Any] | None,
    *,
    match_name: str = "",
) -> dict[str, Any]:
    """小组出线 / 积分 / 胜负关系 — strictly no handicap or lottery terms."""
    lines: list[str] = []
    motiv_ids = ("cup_standing", "motivation", "scenario_simulator", "cross_group_path")
    for agent in (agent_board or {}).get("agents") or []:
        if str(agent.get("agent_id") or "") not in motiv_ids:
            continue
        for ev in agent.get("evidence") or []:
            clean = _sanitize_agent_export_text(str(ev))
            if _is_standings_motivation_line(clean) and clean not in lines:
                lines.append(clean[:160])
    if not lines and match_name:
        try:
            from group_stage_model import analyze_match_from_name

            ma = analyze_match_from_name(match_name)
            if ma:
                mt = ma.get("match_type_cn") or ma.get("match_type")
                if mt:
                    line = _sanitize_agent_export_text(f"战意类型：{mt}")
                    if _is_standings_motivation_line(line) and line not in lines:
                        lines.append(line)
                for bit in (ma.get("reasoning") or [])[:4]:
                    clean = _sanitize_agent_export_text(str(bit))
                    if _is_standings_motivation_line(clean) and clean not in lines:
                        lines.append(clean[:160])
        except Exception:
            pass
    headline = lines[0] if lines else "暂无小组出线/积分/胜负关系分析，请先运行多智能体分析"
    return {"headline": headline[:120], "lines": lines[:4]}


def build_agent_workbench_social_ctx(
    *,
    index: dict | None = None,
    prediction: dict | None = None,
    agent_board: dict | None = None,
    chief_report: dict | None = None,
) -> dict[str, Any]:
    """Build Douyin-safe summary context from multi-agent workbench data."""
    from match_agents.board import merge_result_and_scores, resolve_best_list_verdict

    index = index or {}
    match_name = str(
        index.get("match_name")
        or (prediction or {}).get("match")
        or (chief_report or {}).get("match_name")
        or ""
    ).strip()
    home, away = split_teams(match_name)
    verdict = resolve_best_list_verdict(chief_report, board=agent_board, match=prediction)
    picks = merge_result_and_scores(chief_report, board=agent_board, match=prediction)
    analysis = (chief_report or {}).get("analysis") or {}

    result_cn = str(picks.get("result_1x2_cn") or analysis.get("result_1x2_cn") or "").strip()
    top_scores = [str(x).strip() for x in (picks.get("top_scores") or []) if str(x).strip()][:2]
    motiv = _extract_motivation_judgment(agent_board, match_name=match_name)

    summary_raw = str(verdict.get("summary") or analysis.get("summary") or "").strip()
    summary_lines = _motivation_clean_lines(summary_raw, limit=2)
    if not summary_lines:
        summary_lines = _social_clean_lines(summary_raw, limit=2)
        summary_lines = [x for x in summary_lines if _is_standings_motivation_line(x) or "胜" in x or "平" in x or "负" in x][:2]
    if not summary_lines:
        summary_lines = [x for x in motiv.get("lines") or [] if x != motiv.get("headline")][:2]
    summary = "。".join(summary_lines)
    if summary and not summary.endswith("。"):
        summary += "。"
    if not summary and not result_cn:
        summary = "请先运行含 Chief 的流式分析，或等待定时任务生成专家板。"

    watch: list[str] = []
    for item in (analysis.get("watch_points") or [])[:4]:
        clean = _sanitize_agent_export_text(str(item))
        if clean and clean not in watch and _is_standings_motivation_line(clean):
            watch.append(clean)

    return {
        "match_name": match_name,
        "home": home or match_name,
        "away": away or "",
        "result_1x2_cn": result_cn if result_cn in ("主胜", "平局", "客胜") else _sanitize_agent_export_text(result_cn) or result_cn,
        "top_scores": top_scores,
        "motivation_headline": motiv.get("headline") or "",
        "motivation_lines": motiv.get("lines") or [],
        "certainty": str(verdict.get("certainty_label") or verdict.get("confidence") or "—"),
        "summary": summary,
        "watch_points": watch,
        "ready": bool(
            (motiv.get("lines") or result_cn or top_scores)
            and summary != "请先运行含 Chief 的流式分析，或等待定时任务生成专家板。"
        ),
    }


def html_agent_workbench_social_card(ctx: dict[str, Any]) -> str:
    """Douyin-safe poster: motivation + result only (no handicap/market terms)."""
    home = _e(ctx.get("home") or "主队")
    away = _e(ctx.get("away") or "客队")
    result = _e(ctx.get("result_1x2_cn") or "待更新")
    scores = ctx.get("top_scores") or []
    scores_txt = " / ".join(_e(s) for s in scores[:2]) if scores else "—"
    certainty = _e(ctx.get("certainty") or "—")
    summary = _e(ctx.get("summary") or "暂无总结，请先完成多智能体分析。")
    motiv_head = _e(ctx.get("motivation_headline") or "战意信息待更新")
    motiv_lines = ctx.get("motivation_lines") or []
    motiv_html = ""
    extra_lines = [x for x in motiv_lines if x != ctx.get("motivation_headline")][:3]
    if extra_lines:
        motiv_html = "<ul class='jc-agent-motiv-list'>" + "".join(f"<li>{_e(x)}</li>" for x in extra_lines) + "</ul>"

    pick_key = {"主胜": "home", "平局": "draw", "客胜": "away"}.get(str(ctx.get("result_1x2_cn") or ""), "")
    pills_html = ""
    for key, lbl, active_cls in (
        ("home", "主", "jc-safe-pill-home"),
        ("draw", "平", "jc-safe-pill-draw"),
        ("away", "客", "jc-safe-pill-away"),
    ):
        on = " is-on" if pick_key == key else ""
        pills_html += f'<span class="jc-safe-pill {active_cls}{on}">{lbl}</span>'

    watch_html = ""
    for w in ctx.get("watch_points") or []:
        watch_html += f"<li>{_e(w)}</li>"
    watch_block = ""
    if watch_html:
        watch_block = f'<div class="jc-safe-watch"><div class="jc-safe-watch-hd">赛前关注</div><ul>{watch_html}</ul></div>'

    return f"""
<div class="jc-poster jc-poster-safe agent-douyin-poster">
  <div class="jc-safe-top">
    <div class="jc-safe-brand">FIFA WORLD CUP · 战意与赛果研判</div>
  </div>
  <div class="jc-hero-match jc-agent-match-title">{home} <span class="jc-vs-inline">VS</span> {away}</div>
  <div class="jc-agent-block jc-agent-motiv">
    <div class="jc-agent-block-hd">战意分析 · 小组出线 / 积分 / 胜负关系</div>
    <p class="jc-agent-block-lead">{motiv_head}</p>
    {motiv_html}
  </div>
  <div class="jc-agent-block jc-agent-result">
    <div class="jc-agent-block-hd">胜负判断</div>
    <div class="jc-agent-result-row">
      <div class="jc-hero-score">{result}</div>
      <div class="jc-safe-pills">{pills_html}</div>
    </div>
    <div class="jc-agent-score-row">
      <span class="jc-agent-score-label">可能比分</span>
      <strong>{scores_txt}</strong>
    </div>
  </div>
  <div class="jc-safe-synth">
    <div class="jc-safe-synth-hd">综合说明</div>
    <p>{summary}</p>
  </div>
  {watch_block}
  <div class="jc-safe-meta-row"><span class="jc-safe-meta-chip">确认度 · {certainty}</span></div>
  <div class="jc-safe-foot">世界杯数据研判 · 仅供交流参考 · #世界杯 #战意分析 #足球数据</div>
</div>"""


def html_agent_workbench_social_panel(ctx: dict[str, Any], *, slug: str = "agent-douyin") -> str:
    """Export module with Douyin-safe poster + save button."""
    poster = html_agent_workbench_social_card(ctx)
    btn = (
        '<button type="button" class="btn-poster-save export-hide" '
        'onclick="saveModuleImage(this)">📷 保存抖音总结图</button>'
    )
    hint = (
        '<p class="meta agent-douyin-hint export-hide">'
        "存图版只展示<strong>战意分析（小组出线·积分·胜负关系）</strong>与<strong>胜负判断</strong>，不含水位/盘口/竞彩等词。"
        "</p>"
    )
    return (
        f'<div class="export-module export-module-poster agent-douyin-module" data-export-slug="{_e(slug)}">'
        f'<div class="export-poster-actions">{btn}{hint}</div>'
        f'<div class="export-poster export-poster-screen export-hide">{poster}</div>'
        f'<div class="export-poster export-poster-safe">{poster}</div>'
        f"</div>"
    )


VIEWING_NOTES_FONT = (
    '<link rel="preconnect" href="https://fonts.googleapis.com"/>'
    '<link href="https://fonts.googleapis.com/css2?family=Ma+Shan+Zheng&family=Noto+Sans+SC:wght@400;700;900&display=swap" rel="stylesheet"/>'
)


def viewing_notes_poster_css() -> str:
    return """
.vn-poster.vn-cute {
  width: 430px; max-width: 100%; margin: 0 auto; padding: 22px 18px 24px;
  background: linear-gradient(145deg, #fff5f8 0%, #f3f0ff 42%, #eef9ff 100%);
  color: #5a4a6a;
  font-family: "Noto Sans SC", "PingFang SC", "Hiragino Sans GB", sans-serif;
  border: 3px solid #ffc8dd;
  border-radius: 28px;
  box-shadow: 0 10px 28px rgba(255, 143, 171, .22), 0 2px 0 #fff inset;
  position: relative; overflow: hidden;
}
.vn-poster.vn-cute::before {
  content: ""; position: absolute; inset: 10px; border: 2px dashed rgba(255, 182, 193, .45);
  border-radius: 22px; pointer-events: none;
}
.vn-deco {
  position: absolute; z-index: 2; font-size: 18px; line-height: 1; opacity: .85;
  filter: drop-shadow(0 1px 2px rgba(255, 143, 171, .35));
}
.vn-deco-tl { top: 12px; left: 14px; }
.vn-deco-tr { top: 12px; right: 14px; }
.vn-deco-bl { bottom: 14px; left: 16px; font-size: 16px; }
.vn-deco-br { bottom: 14px; right: 16px; font-size: 16px; }
.vn-title {
  position: relative; z-index: 1; text-align: center; margin: 0 0 12px;
  font-size: 22px; line-height: 1.35; font-weight: 900; letter-spacing: .02em;
  color: #ff6b9d;
  text-shadow: 0 2px 0 #fff, 0 0 12px rgba(255, 143, 171, .35);
}
.vn-title small {
  display: block; font-size: 13px; font-weight: 700; color: #9b8ab8; margin-top: 4px;
}
.vn-chars {
  position: relative; z-index: 1; display: grid; grid-template-columns: 1fr auto 1fr auto 1fr;
  align-items: end; gap: 6px; margin: 10px 0 14px;
}
.vn-char { text-align: center; }
.vn-char-avatar {
  width: 56px; height: 56px; margin: 0 auto 6px; border-radius: 50%;
  border: 3px solid #fff; background: linear-gradient(135deg, #ffe3ef, #dceeff);
  font-size: 28px; line-height: 50px;
  box-shadow: 0 4px 10px rgba(255, 143, 171, .25);
}
.vn-char-name { font-size: 11px; font-weight: 800; color: #7a6a8a; }
.vn-vs-mini {
  font-weight: 900; color: #ff8fab; font-size: 12px; padding-bottom: 20px;
  background: #fff; border-radius: 999px; padding: 4px 8px 20px; line-height: 1;
}
.vn-match {
  position: relative; z-index: 1; text-align: center; margin-bottom: 12px;
  padding: 12px 10px; background: rgba(255,255,255,.72);
  border: 2px solid #ffd6e7; border-radius: 20px;
  box-shadow: 0 4px 12px rgba(255, 182, 193, .18);
}
.vn-match-teams { font-size: 21px; font-weight: 900; line-height: 1.35; color: #4a3a5a; }
.vn-vs-pill {
  display: inline-block; margin: 0 4px; padding: 2px 10px; border-radius: 999px;
  background: linear-gradient(90deg, #ffb3c6, #c9b6ff); color: #fff; font-size: 14px;
  vertical-align: middle; box-shadow: 0 2px 6px rgba(255, 143, 171, .35);
}
.vn-match-meta { font-size: 11px; color: #9b8ab8; margin-top: 6px; line-height: 1.5; }
.vn-compliance {
  position: relative; z-index: 1; margin-bottom: 10px; padding: 10px 12px;
  background: linear-gradient(180deg, #fff9db, #fff3bf);
  border: 2px solid #f5d565; border-radius: 16px;
  font-size: 9px; line-height: 1.55; font-weight: 700; color: #7a5a00;
  box-shadow: 0 2px 8px rgba(245, 213, 101, .25);
}
.vn-predict-row {
  position: relative; z-index: 1; display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 12px;
}
.vn-predict-card {
  background: #fff; border: 2px solid #e8d9ff; border-radius: 16px;
  padding: 10px 6px; text-align: center; min-height: 74px;
  box-shadow: 0 3px 8px rgba(201, 182, 255, .15);
}
.vn-predict-card strong { display: block; font-size: 11px; font-weight: 900; color: #6a5a8a; }
.vn-predict-card span { display: block; font-size: 10px; color: #5a4a6a; margin-top: 5px; line-height: 1.45; }
.vn-grid {
  position: relative; z-index: 1; display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; margin-bottom: 10px;
}
.vn-section {
  background: rgba(255,255,255,.78); border: 2px solid #d4eaff; border-radius: 16px;
  padding: 10px 8px; min-height: 96px;
}
.vn-section-hd {
  font-size: 12px; font-weight: 900; margin-bottom: 6px; color: #6a5a8a;
  border-bottom: 2px dotted rgba(201, 182, 255, .45); padding-bottom: 4px;
}
.vn-section ul { margin: 0; padding-left: 16px; font-size: 10px; line-height: 1.45; color: #5a4a6a; }
.vn-section li { margin-bottom: 3px; }
.vn-form-bar {
  position: relative; z-index: 1; background: linear-gradient(90deg, #d4f1ff, #e8d9ff);
  border: 2px solid #b8e0ff; border-radius: 16px; padding: 10px 12px;
  font-size: 10px; line-height: 1.5; color: #4a5a7a; margin-bottom: 10px;
}
.vn-recent-form {
  position: relative; z-index: 1; display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 10px;
}
.vn-recent-col {
  background: rgba(255,255,255,.82); border: 2px solid #ffd6e7; border-radius: 16px; padding: 8px 6px;
}
.vn-recent-hd { font-size: 11px; font-weight: 900; color: #6a5a8a; margin-bottom: 4px; text-align: center; }
.vn-recent-summary {
  font-size: 9px; font-weight: 700; color: #9b8ab8; text-align: center; margin-bottom: 6px;
  padding-bottom: 4px; border-bottom: 1px dashed rgba(201, 182, 255, .35);
}
.vn-recent-list { list-style: none; margin: 0; padding: 0; }
.vn-recent-row {
  display: grid; grid-template-columns: 38px 14px 1fr 32px 14px; gap: 2px; align-items: center;
  font-size: 8px; line-height: 1.3; color: #5a4a6a; padding: 2px 0;
  border-bottom: 1px dotted rgba(201, 182, 255, .25);
}
.vn-recent-row:last-child { border-bottom: none; }
.vn-recent-badge {
  display: inline-block; width: 13px; height: 13px; border-radius: 999px;
  font-size: 8px; font-weight: 900; text-align: center; line-height: 13px; color: #fff;
}
.vn-recent-badge.r-win { background: #7ed6a5; }
.vn-recent-badge.r-draw { background: #ffd166; }
.vn-recent-badge.r-loss { background: #ff9eb5; }
.vn-recent-src { font-size: 8px; color: #b0a0c0; text-align: center; margin-top: 6px; grid-column: 1 / -1; }
.vn-h2h {
  position: relative; z-index: 1; background: rgba(212, 241, 255, .55); border: 2px solid #b8e0ff;
  border-radius: 14px; padding: 8px 10px; font-size: 9px; color: #4a5a7a; margin-bottom: 10px; line-height: 1.45;
}
.vn-choice {
  position: relative; z-index: 1; text-align: center; padding: 12px 10px 8px;
  background: #fff; border: 2px solid #ffc8dd; border-radius: 22px;
  box-shadow: 0 4px 14px rgba(255, 143, 171, .16);
}
.vn-choice-label { font-size: 13px; font-weight: 900; color: #8a7a9a; }
.vn-choice-val {
  display: inline-block; margin-top: 8px; font-size: 26px; font-weight: 900; color: #ff6b9d;
  border: 2px dashed #ffb3c6; border-radius: 16px; padding: 6px 18px; min-width: 120px;
  background: linear-gradient(180deg, #fff, #fff5f8);
}
.vn-choice-sub { font-size: 11px; color: #9b8ab8; margin-top: 8px; }
.vn-foot {
  position: relative; z-index: 1; text-align: center; margin-top: 12px;
  font-size: 15px; font-weight: 800; color: #ff8fab;
}
.vn-tips {
  position: relative; z-index: 1; display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 10px;
}
.vn-tip-box {
  font-size: 9px; line-height: 1.4; color: #8a7a9a; background: rgba(255,255,255,.65);
  border: 1px dashed rgba(255, 182, 193, .55); border-radius: 12px; padding: 8px;
}
.vn-tip-box strong { display: block; font-size: 10px; margin-bottom: 2px; color: #ff8fab; }
.vn-module .export-poster { background: linear-gradient(180deg, #fff0f5, #f3f0ff); padding: 14px 0; border-radius: 20px; }
.vn-teammods { position: relative; z-index: 1; display: flex; flex-direction: column; gap: 10px; margin-bottom: 10px; }
.vn-teammod {
  background: rgba(255,255,255,.78); border: 2px solid #e8d9ff; border-radius: 18px; padding: 10px 8px 8px;
}
.vn-teammod-hd {
  font-size: 12px; font-weight: 900; color: #6a5a8a; margin-bottom: 8px; text-align: center;
  border-bottom: 2px dotted rgba(201, 182, 255, .4); padding-bottom: 5px;
}
.vn-teammod-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.vn-teammod-col {
  background: #fff; border: 2px solid #f0e6ff; border-radius: 14px;
  padding: 8px 6px; min-height: 52px;
}
.vn-teammod-col.is-home { border-top: 4px solid #8ecae6; }
.vn-teammod-col.is-away { border-top: 4px solid #ff9eb5; }
.vn-teammod-team { font-size: 10px; font-weight: 900; color: #6a5a8a; margin-bottom: 5px; text-align: center; }
.vn-teammod-list { margin: 0; padding-left: 14px; font-size: 9px; line-height: 1.42; color: #5a4a6a; }
.vn-teammod-list li { margin-bottom: 2px; }
.vn-teammod-empty { font-size: 9px; color: #b0a0c0; text-align: center; line-height: 1.4; padding: 4px 2px; }
.vn-lineup-row { margin-bottom: 5px; }
.vn-lineup-row:last-child { margin-bottom: 0; }
.vn-lineup-label { font-size: 8px; font-weight: 900; color: #9b8ab8; margin-bottom: 2px; }
.vn-lineup-players { display: flex; flex-wrap: wrap; gap: 4px; }
.vn-lineup-chip {
  font-size: 8px; line-height: 1.2; padding: 3px 6px; border-radius: 999px;
  background: #fff5f8; border: 1px solid #ffc8dd; color: #6a5a8a;
}
.vn-teammod-src { font-size: 8px; color: #b0a0c0; text-align: center; margin-top: 5px; }
.vn-personal-note {
  position: relative; z-index: 1; background: #fff9c4;
  border: 2px solid #ffe066; border-radius: 4px 18px 18px 18px;
  padding: 12px 12px 10px; margin-bottom: 12px;
  box-shadow: 3px 4px 0 rgba(255, 209, 102, .35);
  transform: rotate(-.6deg);
}
.vn-personal-note-off { display: none !important; }
.vn-personal-note::before {
  content: "📌"; position: absolute; top: -8px; left: 14px; font-size: 16px;
}
.vn-personal-note-hd { font-size: 12px; font-weight: 900; color: #c47f17; margin-bottom: 6px; }
.vn-personal-note-body { font-size: 11px; line-height: 1.6; color: #5a4a2a; white-space: pre-wrap; min-height: 1.2em; }
.vn-note-form {
  margin: 10px 0 0; padding: 12px; background: rgba(255,255,255,.72);
  border-radius: 16px; border: 2px dashed rgba(255, 182, 193, .45);
}
.vn-note-form label { display: block; font-size: 12px; font-weight: 700; margin-bottom: 6px; color: #8a7a9a; }
.vn-note-form textarea {
  width: 100%; box-sizing: border-box; border: 2px solid #ffd6e7; border-radius: 14px;
  padding: 10px; font-size: 13px; resize: vertical; min-height: 72px; background: #fff;
}
.vn-note-form-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; align-items: center; }
"""


VIEWING_NOTES_POSTER_CSS = viewing_notes_poster_css()

_BAD_VIEWING_LINE_RE = re.compile(
    r"http|github|Contribute to|伤停名单：.*球探|"
    r"已尝试\s*500|暂无可靠结构化|未解析到|情报页|网页搜索|"
    r"查询[：:]|500\.com|DuckDuckGo|命中\s*\d+\s*条|数据查询",
    re.I,
)
_INJURY_LINE_RE = re.compile(
    r"伤停|缺阵|受伤|复出|怀疑|停赛|红牌|黄牌累积|injur|doubtful|ruled out|suspend|unavail|miss(?:ing)?",
    re.I,
)
_VERDICT_ONLY_RE = re.compile(
    r"^(当前(?:分析|推荐)|主胜|客胜|平局|胜|平|负|待研判)[：:\s]*.*$",
    re.I,
)
_VENUE_LINE_RE = re.compile(
    r"Super Bowl|NFL|MLS|主场馆|球场.*(?:19|20)\d{2}|opened in|Host City|"
    r"体育场.*(?:举办|主办|opened)|赛事主办",
    re.I,
)


def _strip_score_snippets(text: str) -> str:
    out = _SCORE_SNIP_RE.sub("", str(text or ""))
    out = re.sub(r"\d+\s*[-:：]\s*\d+", "", out)
    out = re.sub(r"\s{2,}", " ", out)
    return out.strip(" ·，,；;。 ")


def _normalize_1x2_cn(raw: str | None) -> str:
    r = str(raw or "").strip()
    if r in ("主胜", "平局", "客胜"):
        return r
    if "平" in r:
        return "平局"
    if "客" in r or r.endswith("负"):
        return "客胜"
    if "主" in r or (r.endswith("胜") and "客" not in r):
        return "主胜"
    return "待研判"


def _verdict_to_fan_cn(raw: str | None) -> str:
    """Legacy helper — viewing poster no longer shows win/loss labels."""
    _ = raw
    return ""


def _viewing_oracle_topic(label: str, idx: int) -> str:
    label = str(label or "").strip()
    if label in ("综合", "Chief", "chief"):
        return "综合观察"
    topics = ("战术风格", "阵容观察", "临场要点")
    if "战意" in label or "积分" in label:
        return "战意背景"
    return topics[idx % len(topics)]


def _viewing_oracle_fallback(home: str, away: str, idx: int) -> str:
    home = home or "主队"
    away = away or "客队"
    fallbacks = (
        f"关注{home}与{away}在中前场的风格碰撞",
        "可从压迫强度与转换速度切入观察",
        "阵容深度与轮换值得赛前留意",
    )
    return fallbacks[idx % len(fallbacks)]


def _viewing_oracle_comment(raw: str, *, home: str = "", away: str = "", idx: int = 0) -> str:
    clean = _sanitize_viewing_notes_text(raw)
    if clean:
        return clean[:72]
    return _viewing_oracle_fallback(home, away, idx)


def _is_verdict_only_line(text: str) -> bool:
    clean = str(text or "").strip()
    if not clean:
        return True
    if _VERDICT_ONLY_RE.match(clean):
        return True
    if clean in ("主胜", "客胜", "平局", "胜", "平", "负", "待研判"):
        return True
    if re.fullmatch(r"当前(?:分析|推荐)[：:]\s*(主胜|客胜|平局|胜|平|负)", clean):
        return True
    return False


def _is_venue_or_stadium_line(text: str) -> bool:
    clean = str(text or "").strip()
    if not clean:
        return False
    if _VENUE_LINE_RE.search(clean):
        return True
    if "体育场" in clean and any(x in clean for x in ("举办", "主办", "opened", "NFL", "Texans")):
        return True
    return False


def _is_internal_agent_log(text: str) -> bool:
    return bool(_BAD_VIEWING_LINE_RE.search(str(text or "")))


def _sanitize_viewing_notes_text(text: str) -> str:
    """Strip scores, betting jargon, and venue noise for Douyin OCR safety."""
    if _is_internal_agent_log(text):
        return ""
    out = _strip_score_snippets(_strip_viewing_compliance_terms(_sanitize_agent_export_text(str(text or ""))))
    extra = [
        (r"Agent(?:\s*研判)?", "综合"),
        (r"推荐", "观察"),
        (r"反方观点[：:]", "需注意："),
    ]
    for pat, repl in extra:
        out = re.sub(pat, repl, out, flags=re.IGNORECASE)
    out = re.sub(r"\s{2,}", " ", out).strip(" ·，,。；;")
    if _is_venue_or_stadium_line(out):
        return ""
    if _is_verdict_only_line(out):
        return ""
    if _contains_market_terms(out):
        return ""
    if len(out) < 4:
        return ""
    return out[:120]


def _viewing_notes_line_ok(text: str) -> bool:
    clean = _sanitize_viewing_notes_text(text)
    return len(clean) >= 6


def _viewing_notes_kickoff_line(index: dict | None, prediction: dict | None) -> str:
    """Only trusted kickoff — never agent-scraped venue/stadium."""
    ko = str((index or {}).get("kickoff_at") or (prediction or {}).get("kickoff_at") or "").strip()
    if not ko:
        return "开赛时间以官方赛程为准"
    try:
        bj = to_beijing(ko)
        if bj:
            return f"北京时间 {format_beijing(bj, '%m-%d %H:%M')} 开球"
    except Exception:
        pass
    return f"开球 {ko[:16]}"


def _agent_evidence_lines(agent_board: dict | None, agent_id: str, *, limit: int = 3) -> list[str]:
    lines: list[str] = []
    for agent in (agent_board or {}).get("agents") or []:
        if str(agent.get("agent_id") or "") != agent_id:
            continue
        for ev in agent.get("evidence") or []:
            clean = _sanitize_viewing_notes_text(str(ev))
            if clean and clean not in lines:
                lines.append(clean)
            if len(lines) >= limit:
                return lines
    return lines


def _agent_warning_lines(agent_board: dict | None, agent_id: str, *, limit: int = 3) -> list[str]:
    lines: list[str] = []
    for agent in (agent_board or {}).get("agents") or []:
        if str(agent.get("agent_id") or "") != agent_id:
            continue
        for w in agent.get("warnings") or []:
            clean = _sanitize_viewing_notes_text(str(w))
            if clean and clean not in lines:
                lines.append(clean)
            if len(lines) >= limit:
                return lines
    return lines


def _injury_evidence_lines(agent_board: dict | None, *, limit: int = 8) -> list[str]:
    lines: list[str] = []
    for agent in (agent_board or {}).get("agents") or []:
        if str(agent.get("agent_id") or "") not in ("intel", "external_context", "late_confirmation"):
            continue
        for ev in agent.get("evidence") or []:
            raw = str(ev)
            if not _INJURY_LINE_RE.search(raw):
                continue
            clean = _sanitize_viewing_notes_text(raw)
            if not clean:
                continue
            if clean not in lines:
                lines.append(clean[:120])
            if len(lines) >= limit:
                return lines
    return lines


def _assign_injury_lines(
    lines: list[str],
    *,
    home_cn: str,
    away_cn: str,
) -> tuple[list[str], list[str]]:
    try:
        from fifa_preview import team_en_name

        home_en = team_en_name(home_cn)
        away_en = team_en_name(away_cn)
    except Exception:
        home_en = away_en = ""
    home_out: list[str] = []
    away_out: list[str] = []
    for line in lines:
        low = line.lower()
        home_hit = home_cn in line or (home_en and home_en.lower() in low)
        away_hit = away_cn in line or (away_en and away_en.lower() in low)
        if home_hit and not away_hit:
            home_out.append(line)
        elif away_hit and not home_hit:
            away_out.append(line)
        elif not home_hit and not away_hit:
            if _is_internal_agent_log(line):
                continue
            continue
    return home_out[:4], away_out[:4]


def _apply_sporttery_side(side: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = dict(side)
    if patch.get("injuries"):
        out["injuries"] = list(patch["injuries"])
        out["has_injuries"] = True
    if patch.get("key_players"):
        out["key_players"] = list(patch["key_players"])
        out["has_key_players"] = True
    if patch.get("tactics_lines"):
        out["tactics_lines"] = list(patch["tactics_lines"])
        out["has_tactics"] = True
    return out


def _build_team_modules(
    *,
    home_cn: str,
    away_cn: str,
    fifa_overlay: dict[str, Any],
    sporttery_overlay: dict[str, Any] | None = None,
    agent_board: dict | None,
) -> dict[str, Any]:
    empty_side = {
        "team": "",
        "key_players": [],
        "tactics_lines": [],
        "lineup_rows": [],
        "injuries": [],
        "has_lineup": False,
        "has_key_players": False,
        "has_tactics": False,
        "has_injuries": False,
    }
    fifa_tm = (fifa_overlay or {}).get("team_modules") or {}
    home_mod = dict(fifa_tm.get("home") or empty_side)
    away_mod = dict(fifa_tm.get("away") or empty_side)
    home_mod["team"] = home_mod.get("team") or home_cn
    away_mod["team"] = away_mod.get("team") or away_cn

    st_tm = (sporttery_overlay or {}).get("team_modules") or {}
    home_mod = _apply_sporttery_side(home_mod, st_tm.get("home") or {})
    away_mod = _apply_sporttery_side(away_mod, st_tm.get("away") or {})

    if not (st_tm.get("home") or {}).get("injuries") and not (st_tm.get("away") or {}).get("injuries"):
        inj_home, inj_away = _assign_injury_lines(
            _injury_evidence_lines(agent_board),
            home_cn=home_cn,
            away_cn=away_cn,
        )
        inj_home = [x for x in inj_home if not _is_internal_agent_log(x)]
        inj_away = [x for x in inj_away if not _is_internal_agent_log(x)]
        try:
            from fifa_translate import translate_en_to_zh, needs_zh_translate

            inj_home = [translate_en_to_zh(x) if needs_zh_translate(x) else x for x in inj_home]
            inj_away = [translate_en_to_zh(x) if needs_zh_translate(x) else x for x in inj_away]
        except Exception:
            pass
        inj_home = [x for x in inj_home if x.strip() and not _is_internal_agent_log(x)]
        inj_away = [x for x in inj_away if x.strip() and not _is_internal_agent_log(x)]
        if inj_home and not home_mod.get("has_injuries"):
            home_mod["injuries"] = inj_home
            home_mod["has_injuries"] = True
        if inj_away and not away_mod.get("has_injuries"):
            away_mod["injuries"] = inj_away
            away_mod["has_injuries"] = True

    modules = {"home": home_mod, "away": away_mod}
    has_any = any(
        side.get("has_lineup") or side.get("has_key_players") or side.get("has_tactics") or side.get("has_injuries")
        for side in modules.values()
    )
    return {
        "available": has_any,
        "home": home_mod,
        "away": away_mod,
        "sporttery_source_url": (sporttery_overlay or {}).get("source_url") or "",
    }


def _viewing_notes_team_side_col(side: dict[str, Any], *, css_class: str) -> str:
    team = _e(side.get("team") or "—")
    body = ""
    if side.get("has_key_players"):
        lis = "".join(f"<li>{_e(x)}</li>" for x in (side.get("key_players") or [])[:4])
        body += f'<ul class="vn-teammod-list">{lis}</ul>'
    else:
        body += '<div class="vn-teammod-empty">暂无核心球员描述</div>'
    return f'<div class="vn-teammod-col {css_class}"><div class="vn-teammod-team">{team}</div>{body}</div>'


def _viewing_notes_lineup_col(side: dict[str, Any], *, css_class: str) -> str:
    team = _e(side.get("team") or "—")
    rows_html = ""
    for row in side.get("lineup_rows") or []:
        chips = "".join(
            f'<span class="vn-lineup-chip">{_e(p)}</span>'
            for p in (row.get("players") or [])[:8]
        )
        rows_html += (
            f'<div class="vn-lineup-row">'
            f'<div class="vn-lineup-label">{_e(row.get("label") or "位置")}</div>'
            f'<div class="vn-lineup-players">{chips}</div></div>'
        )
    if not rows_html:
        rows_html = '<div class="vn-teammod-empty">暂无 FIFA 预测首发</div>'
    return f'<div class="vn-teammod-col {css_class}"><div class="vn-teammod-team">{team}</div>{rows_html}</div>'


def _viewing_notes_injury_col(side: dict[str, Any], *, css_class: str) -> str:
    team = _e(side.get("team") or "—")
    if side.get("has_injuries"):
        lis = "".join(f"<li>{_e(x)}</li>" for x in (side.get("injuries") or [])[:4])
        body = f'<ul class="vn-teammod-list">{lis}</ul>'
    else:
        body = '<div class="vn-teammod-empty">暂无可靠伤停情报</div>'
    return f'<div class="vn-teammod-col {css_class}"><div class="vn-teammod-team">{team}</div>{body}</div>'


def _viewing_notes_tactics_col(side: dict[str, Any], *, css_class: str) -> str:
    team = _e(side.get("team") or "—")
    if side.get("has_tactics"):
        lis = "".join(f"<li>{_e(x)}</li>" for x in (side.get("tactics_lines") or [])[:3])
        body = f'<ul class="vn-teammod-list">{lis}</ul>'
    else:
        body = '<div class="vn-teammod-empty">暂无战术描述</div>'
    return f'<div class="vn-teammod-col {css_class}"><div class="vn-teammod-team">{team}</div>{body}</div>'


def _viewing_notes_team_modules_block(
    modules: dict[str, Any] | None,
    *,
    fifa_source: str = "",
    sporttery_source: str = "",
) -> str:
    tm = modules or {}
    if not tm.get("available"):
        return ""
    home = tm.get("home") or {}
    away = tm.get("away") or {}
    src_bits: list[str] = []
    if fifa_source:
        src_bits.append(f'FIFA · <a href="{_e(fifa_source)}" target="_blank" rel="noopener">预览</a>')
    st_src = sporttery_source or str(tm.get("sporttery_source_url") or "")
    if st_src:
        src_bits.append(f'官方 · <a href="{_e(st_src)}" target="_blank" rel="noopener">伤停/射手</a>')
    src = f'<div class="vn-teammod-src">{" · ".join(src_bits)}</div>' if src_bits else ""

    blocks = [
        (
            "⭐ 核心球员",
            _viewing_notes_team_side_col(home, css_class="is-home")
            + _viewing_notes_team_side_col(away, css_class="is-away"),
        ),
        (
            "📋 预计首发",
            _viewing_notes_lineup_col(home, css_class="is-home")
            + _viewing_notes_lineup_col(away, css_class="is-away"),
        ),
        (
            "⚔️ 风格数据",
            _viewing_notes_tactics_col(home, css_class="is-home")
            + _viewing_notes_tactics_col(away, css_class="is-away"),
        ),
        (
            "🏥 伤停信息",
            _viewing_notes_injury_col(home, css_class="is-home")
            + _viewing_notes_injury_col(away, css_class="is-away"),
        ),
    ]
    html_parts = ['<div class="vn-teammods">']
    for title, cols in blocks:
        html_parts.append(
            f'<div class="vn-teammod"><div class="vn-teammod-hd">{_e(title)}</div>'
            f'<div class="vn-teammod-grid">{cols}</div></div>'
        )
    if src:
        html_parts.append(src)
    html_parts.append("</div>")
    return "".join(html_parts)


def _latest_ai_rows(prediction: dict | None, ai_records: list | None) -> list[dict[str, str]]:
    latest = (ai_records or [None])[0] or {}
    analyses = latest.get("analyses") or {}
    if not analyses:
        analyses = (prediction or {}).get("ai_analyses") or {}
    rows: list[dict[str, str]] = []
    for pid, analysis in analyses.items():
        row = analysis.get("predict_row") or {}
        result = _normalize_1x2_cn(analysis.get("result_1x2_cn") or row.get("胜平负") or "")
        reason = _strip_score_snippets(
            _sanitize_agent_export_text(analysis.get("actuary_reasoning") or analysis.get("summary") or "")
        )[:48]
        rows.append({
            "label": str(analysis.get("label") or analysis.get("ai_provider_label") or pid),
            "result": result,
            "comment": reason or result or "待补充",
        })
    return rows


VIEWING_COMPLIANCE_TEXT = (
    "纯足球爱好者赛前观赛笔记，仅交流球队战术、球员技术、赛事历史数据，"
    "无任何投注引导、胜负推荐，理性欣赏足球赛事，请勿过度解读数据。"
)


def _build_viewing_oracles(
    *,
    picks: dict,
    chief_report: dict | None,
    ai_rows: list[dict[str, str]],
    home: str = "",
    away: str = "",
) -> list[dict[str, str]]:
    analysis = (chief_report or {}).get("analysis") or {}
    agent_comment = _viewing_oracle_comment(
        analysis.get("summary") or "",
        home=home,
        away=away,
        idx=0,
    )
    avatars = ("🧑‍💻", "👩", "🤖")
    oracles: list[dict[str, str]] = [{
        "label": "综合",
        "avatar": avatars[0],
        "topic": _viewing_oracle_topic("综合", 0),
        "comment": agent_comment,
    }]
    for i, row in enumerate(ai_rows[:2]):
        oracles.append({
            "label": row["label"][:8],
            "avatar": avatars[i + 1],
            "topic": _viewing_oracle_topic(row.get("label") or "", i + 1),
            "comment": _viewing_oracle_comment(
                row.get("comment") or "",
                home=home,
                away=away,
                idx=i + 1,
            ),
        })
    while len(oracles) < 3:
        idx = len(oracles)
        oracles.append({
            "label": "待分析",
            "avatar": avatars[idx],
            "topic": _viewing_oracle_topic("", idx),
            "comment": _viewing_oracle_fallback(home, away, idx),
        })
    return oracles[:3]


def _viewing_notes_form_block(team_form: dict | None) -> str:
    tf = team_form or {}
    if not tf.get("available"):
        return (
            '<div class="vn-recent-form">'
            '<div class="vn-recent-col" style="grid-column:1/-1">'
            '<div class="vn-recent-hd">双方近期战绩</div>'
            '<p class="vn-recent-summary">暂无近10场记录（本地库与搜索均未命中）</p>'
            "</div></div>"
        )

    def _badge(res: str) -> str:
        cls = {"胜": "r-win", "平": "r-draw", "负": "r-loss"}.get(res, "r-draw")
        letter = {"胜": "W", "平": "D", "负": "L"}.get(res, "?")
        return f'<span class="vn-recent-badge {cls}">{letter}</span>'

    def _col(side: dict) -> str:
        rows = ""
        for m in (side.get("matches") or [])[:10]:
            rows += (
                f'<li class="vn-recent-row">'
                f'<span>{_e(m.get("date"))}</span>'
                f"<span>{_e(m.get('venue'))}</span>"
                f'<span>{_e(m.get("opponent"))}</span>'
                f'<span>{_e(m.get("score"))}</span>'
                f"{_badge(str(m.get('result') or ''))}"
                f"</li>"
            )
        if not rows:
            rows = '<li class="vn-recent-row"><span colspan>暂无明细</span></li>'
        return (
            f'<div class="vn-recent-col">'
            f'<div class="vn-recent-hd">{_e(side.get("team"))} · 近10场</div>'
            f'<div class="vn-recent-summary">{_e(side.get("summary"))}</div>'
            f'<ul class="vn-recent-list">{rows}</ul>'
            f"</div>"
        )

    h2h = tf.get("head_to_head") or []
    h2h_html = ""
    if h2h:
        bits = " · ".join(_e(h.get("match") or "") for h in h2h[:2] if h.get("match"))
        if bits:
            h2h_html = f'<div class="vn-h2h"><strong>交锋</strong> {bits}</div>'

    src = _e(tf.get("data_source") or "")
    return (
        f'{h2h_html}<div class="vn-recent-form">'
        f'{_col(tf.get("home") or {})}{_col(tf.get("away") or {})}'
        f'<div class="vn-recent-src">数据来源：{src}</div>'
        f"</div>"
    )


def build_viewing_notes_ctx(
    *,
    index: dict | None = None,
    prediction: dict | None = None,
    agent_board: dict | None = None,
    chief_report: dict | None = None,
    ai_records: list | None = None,
    output_root: str | Path | None = None,
    fixture_id: str | None = None,
    fifa_preview: dict | None = None,
) -> dict[str, Any]:
    """Comic-style viewing notes poster — filled from agent + AI analysis."""
    from match_agents.board import merge_result_and_scores, resolve_best_list_verdict

    index = index or {}
    match_name = str(
        index.get("match_name")
        or (prediction or {}).get("match")
        or (chief_report or {}).get("match_name")
        or ""
    ).strip()
    home, away = split_teams(match_name)
    verdict = resolve_best_list_verdict(chief_report, board=agent_board, match=prediction)
    picks = merge_result_and_scores(chief_report, board=agent_board, match=prediction)
    ai_rows = _latest_ai_rows(prediction, ai_records)
    motiv = _extract_motivation_judgment(agent_board, match_name=match_name)

    ko = str(index.get("kickoff_at") or (prediction or {}).get("kickoff_at") or "")
    day_note = ""
    if len(ko) >= 10:
        try:
            dt = datetime.strptime(ko[:10], "%Y-%m-%d")
            day_note = f"{dt.month}月{dt.day}日"
        except ValueError:
            day_note = ko[:10]

    fifa_overlay: dict[str, Any] = {}
    if fifa_preview is None and output_root and fixture_id and home and away:
        try:
            from fifa_preview import load_fifa_preview, viewing_notes_fifa_overlay

            fifa_preview = load_fifa_preview(output_root, fixture_id)
            if fifa_preview:
                fifa_overlay = viewing_notes_fifa_overlay(
                    fifa_preview,
                    home_cn=home,
                    away_cn=away,
                    output_root=output_root,
                    fixture_id=fixture_id,
                )
        except Exception as exc:
            log.debug("FIFA preview load skipped: %s", exc)
    elif fifa_preview and home and away:
        try:
            from fifa_preview import viewing_notes_fifa_overlay

            fifa_overlay = viewing_notes_fifa_overlay(
                fifa_preview,
                home_cn=home,
                away_cn=away,
                output_root=output_root,
                fixture_id=fixture_id,
            )
        except Exception as exc:
            log.debug("FIFA preview overlay skipped: %s", exc)

    sporttery_overlay: dict[str, Any] = {}
    if output_root and fixture_id and home and away:
        try:
            from sporttery_intel import build_viewing_overlay, load_sporttery_intel

            st_intel = load_sporttery_intel(output_root, fixture_id)
            if st_intel:
                sporttery_overlay = build_viewing_overlay(st_intel)
        except Exception as exc:
            log.debug("sporttery intel load skipped: %s", exc)

    team_modules = _build_team_modules(
        home_cn=home,
        away_cn=away,
        fifa_overlay=fifa_overlay,
        sporttery_overlay=sporttery_overlay,
        agent_board=agent_board,
    )

    has_fifa_modules = bool(team_modules.get("available"))
    if has_fifa_modules:
        raw_sections = [
            ("① 临场风险", _agent_warning_lines(agent_board, "contrarian", limit=3)),
            ("② 战意观察", (motiv.get("lines") or [motiv.get("headline") or ""])[:3]),
        ]
        fifa_section_override: dict[str, list[str]] = {}
    else:
        raw_sections = [
            ("① 核心球员", _agent_evidence_lines(agent_board, "intel", limit=3)),
            ("② 战术风格", _agent_evidence_lines(agent_board, "scenario_simulator", limit=2)),
            ("③ 临场风险", _agent_warning_lines(agent_board, "contrarian", limit=3)),
            ("④ 战意观察", (motiv.get("lines") or [motiv.get("headline") or ""])[:3]),
        ]
        fifa_section_override = {}
    sections = []
    for title, lines in raw_sections:
        clean = []
        fifa_lines = fifa_section_override.get(title) or []
        if fifa_lines:
            clean = [_sanitize_viewing_notes_text(str(x)) for x in fifa_lines if str(x).strip()][:3]
            clean = [x for x in clean if x]
        if not clean:
            for x in lines:
                if title.endswith("战意观察"):
                    bit = _sanitize_viewing_notes_text(_strip_score_snippets(_sanitize_agent_export_text(x)))
                    if _is_standings_motivation_line(bit) and bit not in clean:
                        clean.append(bit[:100])
                else:
                    bit = _sanitize_viewing_notes_text(str(x))
                    if bit and bit not in clean:
                        clean.append(bit[:100])
                if len(clean) >= 3:
                    break
        sections.append({"title": title, "lines": clean or ["暂无补充"]})

    personal_note = ""
    if output_root and fixture_id:
        try:
            from viewing_note_store import load_viewing_note

            personal_note = load_viewing_note(output_root, fixture_id)
        except Exception as exc:
            log.debug("viewing note load skipped: %s", exc)

    result_cn = _normalize_1x2_cn(picks.get("result_1x2_cn"))
    motiv_line = _strip_score_snippets(motiv.get("headline") or "")
    if not _is_standings_motivation_line(motiv_line):
        motiv_line = ""

    team_form: dict[str, Any] = {}
    if home and away:
        try:
            from team_form_search import build_viewing_notes_team_form

            team_form = build_viewing_notes_team_form(
                home,
                away,
                limit=10,
                use_search=True,
                reference_date=ko or None,
            )
        except Exception as exc:
            log.debug("viewing notes team form skipped: %s", exc)

    kickoff_line = _viewing_notes_kickoff_line(index, prediction)
    kickoff_extra = str(fifa_overlay.get("kickoff_extra") or "")
    if kickoff_extra and "球馆" not in kickoff_line and "球场" not in kickoff_line:
        kickoff_line = f"{kickoff_line}{kickoff_extra}"

    return {
        "match_name": match_name,
        "home": home or "主队",
        "away": away or "客队",
        "day_note": day_note,
        "kickoff_line": kickoff_line,
        "oracles": _build_viewing_oracles(
            picks=picks,
            chief_report=chief_report,
            ai_rows=ai_rows,
            home=home or "主队",
            away=away or "客队",
        ),
        "sections": sections,
        "motiv_line": motiv_line[:120],
        "team_form": team_form,
        "team_modules": team_modules,
        "personal_note": personal_note,
        "fixture_id": str(fixture_id or index.get("fixture_id") or ""),
        "fifa_preview": fifa_preview,
        "fifa_source_url": fifa_overlay.get("source_url") or "",
        "sporttery_source_url": sporttery_overlay.get("source_url") or team_modules.get("sporttery_source_url") or "",
        "ready": bool(result_cn != "待研判" or motiv.get("lines") or ai_rows or fifa_overlay or personal_note),
    }


def html_viewing_notes_poster(ctx: dict[str, Any]) -> str:
    home = _e(ctx.get("home") or "主队")
    away = _e(ctx.get("away") or "客队")
    day_note = _e(ctx.get("day_note") or "")
    kickoff = _e(ctx.get("kickoff_line") or "")
    oracles = ctx.get("oracles") or []
    oracle_html = ""
    for i, o in enumerate(oracles[:3]):
        if i:
            oracle_html += '<div class="vn-vs-mini">VS</div>'
        oracle_html += (
            f'<div class="vn-char"><div class="vn-char-avatar">{_e(o.get("avatar") or "🙂")}</div>'
            f'<div class="vn-char-name">{_e(o.get("label") or "—")}</div></div>'
        )

    predict_html = ""
    for o in oracles[:3]:
        predict_html += (
            f'<div class="vn-predict-card"><strong>{_e(o.get("topic") or "战术观察")}</strong>'
            f'<span>{_e(o.get("comment") or "")}</span></div>'
        )

    section_html = ""
    for sec in ctx.get("sections") or []:
        lis = "".join(f"<li>{_e(x)}</li>" for x in (sec.get("lines") or [])[:3])
        section_html += (
            f'<div class="vn-section"><div class="vn-section-hd">{_e(sec.get("title") or "")}</div>'
            f"<ul>{lis or '<li>待补充分析</li>'}</ul></div>"
        )

    motiv_line = _e(ctx.get("motiv_line") or "")
    motiv_block = ""
    if motiv_line:
        motiv_block = f'<div class="vn-form-bar">{motiv_line}</div>'
    form_block = _viewing_notes_form_block(ctx.get("team_form"))
    team_mod_block = _viewing_notes_team_modules_block(
        ctx.get("team_modules"),
        fifa_source=str(ctx.get("fifa_source_url") or ""),
        sporttery_source=str(ctx.get("sporttery_source_url") or ""),
    )
    personal = _sanitize_personal_note(str(ctx.get("personal_note") or ""))
    note_cls = "" if personal else " vn-personal-note-off"
    compliance = f'<div class="vn-compliance">{_e(VIEWING_COMPLIANCE_TEXT)}</div>'
    personal_block = (
        f"{compliance}"
        f'<div class="vn-personal-note{note_cls}">'
        f'<div class="vn-personal-note-hd">📝 我的个人看法</div>'
        f'<div class="vn-personal-note-body">{_e(personal)}</div>'
        f"</div>"
    )
    title_main = f"{home} vs {away}"
    title_sub = f"世界杯战术观赛笔记{(' · ' + day_note) if day_note else ''}"

    return f"""
<div class="vn-poster vn-cute">
  <div class="vn-deco vn-deco-tl">✨</div>
  <div class="vn-deco vn-deco-tr">🌸</div>
  <div class="vn-deco vn-deco-bl">⚽</div>
  <div class="vn-deco vn-deco-br">💫</div>
  <h1 class="vn-title">{title_main}<small>{title_sub}</small></h1>
  <div class="vn-chars">{oracle_html}</div>
  <div class="vn-match">
    <div class="vn-match-teams">{home} <span class="vn-vs-pill">VS</span> {away}</div>
    <div class="vn-match-meta">{kickoff}</div>
  </div>
  {personal_block}
  <div class="vn-predict-row">{predict_html}</div>
  {team_mod_block}
  {form_block}
  <div class="vn-grid">{section_html}</div>
  {motiv_block}
  <div class="vn-tips">
    <div class="vn-tip-box"><strong>小贴士</strong>多聊战术与球员，少做胜负预判。</div>
    <div class="vn-tip-box"><strong>温馨提示</strong>理性看球，享受比赛本身。</div>
  </div>
  <div class="vn-foot">仅业余球迷复盘分享，不构成任何参考建议 · 世界杯，因你更精彩 ♡</div>
</div>"""


def viewing_notes_panel_script() -> str:
    return """
<script>
function _sanitizeNoteForExport(text) {
  if (!text) return '';
  var out = String(text);
  var pats = [
    [/博彩|赌博|赌球|彩票|足彩|购彩|投注|下注|庄家|滚球|竞彩|体彩|串关|可串|单关|Kelly/gi, ''],
    [/盘口|亚盘|欧赔|水位|让球|大小球|赔率|2串1|3串1/gi, ''],
    [/看好|主胜|客胜|预测|走势|方向|拿捏|稳胆|稳单|稳赢|赢球|必赢/gi, ''],
    [/\\d+(?:\\.\\d+)?\\s*[%％]/g, '']
  ];
  for (var i = 0; i < pats.length; i++) {
    out = out.replace(pats[i][0], pats[i][1]);
  }
  return out.replace(/\\s{2,}/g, ' ').trim().slice(0, 500);
}
function _syncViewingPersonalNote(mod) {
  if (!mod || !mod.classList.contains('vn-module')) return '';
  const ta = mod.querySelector('.vn-note-input');
  const text = _sanitizeNoteForExport((ta && ta.value || '').trim());
  const box = mod.querySelector('.vn-personal-note-body');
  const wrap = mod.querySelector('.vn-personal-note');
  if (box && wrap) {
    if (text) {
      box.textContent = text;
      wrap.classList.remove('vn-personal-note-off');
    } else {
      box.textContent = '';
      wrap.classList.add('vn-personal-note-off');
    }
  }
  return text;
}
async function _persistViewingNote(mod, text) {
  const fid = mod && mod.dataset ? mod.dataset.fixtureId : '';
  if (!fid || !text) return;
  try {
    const resp = await fetch('/api/match/' + encodeURIComponent(fid) + '/viewing-note', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({personal_note: text}),
    });
    if (!resp.ok) throw new Error('save failed');
  } catch (e) { /* still allow save image */ }
}
async function applyViewingNoteAndSave(btn, fid) {
  const mod = btn && btn.closest ? btn.closest('.export-module') : null;
  const ta = mod && mod.querySelector('.vn-note-input');
  const text = _sanitizeNoteForExport((ta && ta.value || '').trim());
  if (!text) {
    alert('请先填写个人看法（勿含敏感词）');
    return;
  }
  const oldLabel = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.textContent = '写入并生成…'; }
  try {
    const fidUse = (mod && mod.dataset && mod.dataset.fixtureId) || fid || '';
    if (fidUse) {
      const resp = await fetch('/api/match/' + encodeURIComponent(fidUse) + '/viewing-note', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({personal_note: text}),
      });
      let data = {};
      try { data = await resp.json(); } catch (e) { /* ignore */ }
      if (!resp.ok || data.ok === false) {
        alert('看法保存失败：' + (data.error || ('HTTP ' + resp.status)));
      }
    }
    _syncViewingPersonalNote(mod);
    await saveModuleImage(btn);
  } catch (e) {
    alert('存图失败：' + e);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = oldLabel || '📝 写入个人看法并保存图'; }
  }
}
function _clonePosterForExport(mod) {
  const poster = _exportPosterNode(mod);
  if (!poster) return null;
  _syncViewingPersonalNote(mod);
  const ta = mod.querySelector('.vn-note-input');
  const text = _sanitizeNoteForExport((ta && ta.value || '').trim());
  const clone = poster.cloneNode(true);
  clone.style.cssText = 'position:fixed;left:-99999px;top:0;z-index:-1;margin:0;transform:none;overflow:visible;';
  const noteWrap = clone.querySelector('.vn-personal-note');
  const noteBody = clone.querySelector('.vn-personal-note-body');
  if (noteWrap && noteBody) {
    if (text) {
      noteBody.textContent = text;
      noteWrap.classList.remove('vn-personal-note-off');
      noteWrap.style.transform = 'none';
      noteWrap.style.display = 'block';
    } else {
      noteWrap.classList.add('vn-personal-note-off');
    }
  }
  document.body.appendChild(clone);
  return clone;
}
function _exportPosterNode(mod) {
  const safe = mod.querySelector('.export-poster-safe');
  if (safe && safe.querySelector('.vn-poster')) return safe.querySelector('.vn-poster');
  return mod.querySelector('.vn-poster') || safe || mod.querySelector('.export-poster') || mod;
}
async function _ensureHtml2Canvas() {
  if (typeof html2canvas === 'function') return;
  await new Promise(function(resolve, reject) {
    var s = document.createElement('script');
    s.src = 'https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js';
    s.onload = resolve;
    s.onerror = function() { reject(new Error('html2canvas 加载失败')); };
    document.head.appendChild(s);
  });
}
</script>
"""


def html_viewing_notes_panel(
    ctx: dict[str, Any],
    *,
    slug: str = "viewing-notes",
    extra_actions: str = "",
) -> str:
    poster = html_viewing_notes_poster(ctx)
    fid = _e(str(ctx.get("fixture_id") or ""))
    saved = _e(str(ctx.get("personal_note") or ""))
    btn = (
        '<button type="button" class="btn-poster-save export-hide" '
        'onclick="saveModuleImage(this)">📷 仅保存图片</button>'
    )
    apply_btn = (
        f'<button type="button" class="btn btn-sm export-hide" style="margin-left:8px" '
        f"onclick=\"applyViewingNoteAndSave(this, '{fid}')\">📝 写入个人看法并保存图</button>"
    )
    if extra_actions:
        btn = f"{btn}{extra_actions}{apply_btn}"
    else:
        btn = f"{btn}{apply_btn}"
    note_form = (
        f'<div class="vn-note-form export-hide">'
        f'<label for="vn-note-input-{fid}">我的个人看法（存图时自动净化敏感词）</label>'
        f'<textarea id="vn-note-input-{fid}" class="vn-note-input" rows="3" maxlength="500" '
        f'placeholder="例：森保一擅长低位防反，巴西边路压迫值得重点观察…">{saved}</textarea>'
        f'<div class="vn-note-form-actions">'
        f'<span class="meta">先填看法 → 点「写入个人看法并保存图」</span>'
        f"</div></div>"
    )
    fifa_meta = ""
    if ctx.get("fifa_source_url") or ctx.get("sporttery_source_url"):
        bits = []
        if ctx.get("fifa_source_url"):
            bits.append(
                f'FIFA <a href="{_e(ctx.get("fifa_source_url"))}" target="_blank" rel="noopener">预览</a>'
            )
        if ctx.get("sporttery_source_url"):
            bits.append(
                f'体彩 <a href="{_e(ctx.get("sporttery_source_url"))}" target="_blank" rel="noopener">伤停</a>'
            )
        fifa_meta = f'<span class="meta"> · {" · ".join(bits)}</span>'
    hint = (
        '<p class="meta vn-hint export-hide">'
        "粉彩风 · FIFA 首发/预览 + 体彩伤停射手/风格数据；填看法后存图。"
        f"{fifa_meta}"
        "</p>"
    )
    return (
        f'<div class="export-module export-module-poster vn-module" '
        f'data-export-slug="{_e(slug)}" data-fixture-id="{fid}" data-export-bg="#fff5f8">'
        f'<div class="export-poster-actions">{btn}{hint}</div>'
        f"{note_form}"
        f'<div class="export-poster export-poster-safe">{poster}</div>'
        f"</div>"
    )


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
        "export_pick_key": pick_key if pick_key not in ("skip", "") else "",
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


def html_ai_summary_card_safe(ctx: dict[str, Any]) -> str:
    """Social-media safe poster — no lottery/betting surface; used only in PNG export."""
    home = _e(ctx.get("home"))
    away = _e(ctx.get("away"))
    kickoff_full = _e(ctx.get("kickoff_full") or "—")
    kickoff_line = _e(ctx.get("kickoff_line") or "—")
    num = _e(ctx.get("match_num") or "—")
    trend, pick_key = _resolve_export_trend(ctx)

    pills_html = ""
    for key, lbl, active_cls in (
        ("home", "主", "jc-safe-pill-home"),
        ("draw", "平", "jc-safe-pill-draw"),
        ("away", "客", "jc-safe-pill-away"),
    ):
        on = " is-on" if pick_key == key else ""
        pills_html += f'<span class="jc-safe-pill {active_cls}{on}">{lbl}</span>'

    tier_cn = _tier_to_safe_cn(ctx.get("buy_tier_cn") or "")
    tier_html = ""
    if tier_cn:
        tier_css = {"一致性强": "a", "中等把握": "b", "低把握": "c", "观望": "c"}.get(tier_cn, "c")
        reason = _sanitize_export_text(ctx.get("buy_tier_reason") or "")
        tier_html = (
            f'<div class="jc-safe-tier jc-safe-tier-{tier_css}">'
            f'<strong>{_e(tier_cn)}</strong>'
            f'{f"<span>{_e(reason)}</span>" if reason else ""}'
            f"</div>"
        )

    synth = _sanitize_export_text(ctx.get("summary_text") or "")
    synth_html = ""
    if synth:
        synth_html = (
            f'<div class="jc-safe-synth">'
            f'<div class="jc-safe-synth-hd">AI 综合总结</div>'
            f"<p>{_e(synth[:260])}</p></div>"
        )
    elif ctx.get("ai_models"):
        synth_html = (
            '<div class="jc-safe-synth is-muted">'
            '<div class="jc-safe-synth-hd">AI 综合总结</div>'
            f"<p>模型综合倾向 {_e(trend)}，详见下方各模型分析。</p></div>"
        )

    ai_models = ctx.get("ai_models") or []
    models_agree = ctx.get("models_agree")
    agree_html = ""
    if len(ai_models) > 1:
        agree_txt = "多模型一致" if models_agree else "模型存在分歧"
        agree_cls = "is-ok" if models_agree else "is-warn"
        agree_html = f'<div class="jc-safe-agree {agree_cls}">{_e(agree_txt)}</div>'

    models_html = ""
    for m in ai_models[:3]:
        pick = m.get("pick") or "—"
        trend_m = _pick_to_trend_cn(pick)
        pick_cls = "jc-safe-model-pick"
        if trend_m == "观望":
            pick_cls += " is-muted"
        conf = _confidence_to_safe_cn(m.get("confidence") or "")
        conf_tag = f'<span class="jc-safe-model-conf">{_e(conf)}</span>' if conf and conf != "—" else ""
        summ = _sanitize_export_text(m.get("summary") or "")
        summ_block = (
            f'<p class="jc-safe-model-sum">{_e(summ[:180])}</p>'
            if summ else '<p class="jc-safe-model-sum is-muted">暂无文字总结</p>'
        )
        models_html += (
            f'<div class="jc-safe-model-card">'
            f'<div class="jc-safe-model-head">'
            f'<strong class="jc-safe-model-name">{_e(m.get("label", "AI"))}</strong>'
            f'<span class="{pick_cls}">倾向 · {_e(trend_m)}</span>'
            f'{conf_tag}'
            f"</div>{summ_block}</div>"
        )
    if not models_html:
        models_html = (
            '<div class="jc-safe-model-card is-empty">'
            "<p>请先生成 AI 分析后再存图。</p></div>"
        )

    conf = ctx.get("confidence") or ""
    conf_html = ""
    if conf and conf != "—":
        conf_html = f'<span class="jc-safe-meta-chip">{_e(_confidence_to_safe_cn(conf))}</span>'

    return f"""
<div class="jc-poster jc-poster-safe">
  <div class="jc-safe-top">
    <div class="jc-safe-brand">FIFA WORLD CUP · AI 分析</div>
    <div class="jc-safe-num">{num}</div>
  </div>
  <div class="jc-hero-layout">
    <div class="jc-hero-left">
      <div class="jc-hero-kicker">用 AI 和数据，算这场世界杯</div>
      <div class="jc-hero-match">{home} <span class="jc-vs-inline">VS</span> {away}</div>
      <div class="jc-hero-pills">
        <div class="jc-glass-pill"><span class="jc-pill-lbl">北京时间</span><strong>{kickoff_line}</strong></div>
        <div class="jc-glass-pill"><span class="jc-pill-lbl">开赛</span><strong>{kickoff_full}</strong></div>
      </div>
    </div>
    <div class="jc-hero-right">
      <div class="jc-hero-score">{_e(trend)}</div>
      <div class="jc-safe-pills">{pills_html}</div>
    </div>
  </div>
  {tier_html}
  {synth_html}
  <div class="jc-safe-ai-section">
    <div class="jc-safe-ai-hd">各模型 AI 分析 · 总结</div>
    {agree_html}
    <div class="jc-safe-model-list">{models_html}</div>
  </div>
  <div class="jc-safe-meta-row">{conf_html}</div>
  <div class="jc-safe-foot">数据模型输出 · 仅供交流参考</div>
</div>"""


AI_SUMMARY_POSTER_CSS = poster_css()
POSTER_BATCH_PAGE_CSS = poster_batch_page_css()


def html_ai_summary_panel(ctx: dict[str, Any], *, slug: str = "ai-summary") -> str:
    """Poster + prominent save button (button hidden inside saved PNG)."""
    poster = html_ai_summary_card(ctx)
    safe_poster = html_ai_summary_card_safe(ctx)
    btn = (
        '<button type="button" class="btn-poster-save export-hide" '
        'onclick="saveModuleImage(this)">📷 保存推荐图（发抖音）</button>'
    )
    return (
        f'<div class="export-module export-module-poster" data-export-slug="{_e(slug)}">'
        f'<div class="export-poster-actions">{btn}</div>'
        f'<div class="export-poster export-poster-screen">{poster}</div>'
        f'<div class="export-poster export-poster-safe" hidden>{safe_poster}</div>'
        f"</div>"
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
{share_match_page_css()}
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
function _swapPosterForExport(mod) {{
  const screen = mod.querySelector('.export-poster-screen');
  const safe = mod.querySelector('.export-poster-safe');
  if (!safe) return {{ target: mod.querySelector('.export-poster') || mod, state: null }};
  const state = {{
    screenHidden: screen ? screen.hidden : false,
    screenDisplay: screen ? screen.style.display : '',
    safeHidden: safe.hidden,
    safeDisplay: safe.style.display,
  }};
  if (screen) {{
    screen.hidden = true;
    screen.style.display = 'none';
  }}
  safe.hidden = false;
  safe.style.display = 'block';
  return {{ target: safe, state }};
}}
function _restorePosterSwap(state) {{
  if (!state) return;
  const mod = state.mod;
  if (!mod) return;
  const screen = mod.querySelector('.export-poster-screen');
  const safe = mod.querySelector('.export-poster-safe');
  if (screen) {{
    screen.hidden = state.screenHidden;
    screen.style.display = state.screenDisplay;
  }}
  if (safe) {{
    safe.hidden = state.safeHidden;
    safe.style.display = state.safeDisplay;
  }}
}}
function _exportBgColor(el) {{
  const root = (el && el.closest) ? el.closest('[data-export-bg]') : null;
  const byId = document.getElementById('{_e(root_id)}');
  const node = root || byId;
  return (node && node.dataset.exportBg) || '#0a0c18';
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
  if (mod.classList.contains('vn-module') && typeof _syncViewingPersonalNote === 'function') {{
    _syncViewingPersonalNote(mod);
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
  let target = mod.querySelector('.export-poster-screen') || mod.querySelector('.export-poster') || mod;
  let canvasBackups = [];
  let posterSwap = null;
  let exportClone = null;
  try {{
    if (typeof _ensureHtml2Canvas === 'function') await _ensureHtml2Canvas();
    else if (typeof html2canvas !== 'function') throw new Error('html2canvas 未加载');
    const swapped = _swapPosterForExport(mod);
    if (swapped.target) target = swapped.target;
    posterSwap = swapped.state;
    if (posterSwap) posterSwap.mod = mod;
    if (mod.classList.contains('vn-module') && typeof _clonePosterForExport === 'function') {{
      exportClone = _clonePosterForExport(mod);
      if (exportClone) target = exportClone;
    }} else if (typeof _exportPosterNode === 'function' && mod.classList.contains('vn-module')) {{
      target = _exportPosterNode(mod);
    }}
    canvasBackups = _freezeCanvases(target);
    await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
    const canvas = await html2canvas(target, {{
      scale: Math.min(2, window.devicePixelRatio || 1.5),
      useCORS: true,
      backgroundColor: _exportBgColor(target),
      logging: false,
      scrollY: 0,
      scrollX: 0,
      windowWidth: target.scrollWidth,
      windowHeight: target.scrollHeight + 32,
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
    if (exportClone && exportClone.parentNode) exportClone.parentNode.removeChild(exportClone);
    _restorePosterSwap(posterSwap);
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
      backgroundColor: _exportBgColor(root),
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
  display: inline-block; padding: 9px 18px; color: #fff !important;
  border: none; border-radius: 999px; cursor: pointer; font-size: 14px;
  font-weight: 700; text-decoration: none;
  background: linear-gradient(90deg, #ff4b8b 0%, #ff6b4a 100%);
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
