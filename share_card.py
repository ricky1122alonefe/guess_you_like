"""Single-match share card for WeChat Moments (HTML + browser export)."""

from __future__ import annotations

import html
import re
from datetime import datetime, timedelta
from typing import Any

from daily_picks import load_kickoff_map
from jingcai_pick import final_recommendation_cn
from time_utils import format_beijing, to_beijing

_WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


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
    """Reusable browser-side long PNG export for a page section."""
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
</script>"""


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
