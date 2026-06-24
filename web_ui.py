"""HTML pages for dashboard and match detail (hourly trends)."""

from __future__ import annotations

import html
import json
import re
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote

from jingcai_pick import final_recommendation_cn
from product_focus import score_prediction_enabled as _score_enabled
from eu_odds_chart import build_eu_multi_chart_data
from share_card import (
    AI_SUMMARY_POSTER_CSS,
    build_ai_summary_context,
    html_ai_summary_panel,
    long_image_export_script,
)
from time_utils import beijing_date, chart_time_label, format_beijing, format_ts, now_beijing_str


def _e(s) -> str:
    return html.escape(str(s) if s is not None else "")


def _json_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


_AI_BTN_JS = """
function showToast(msg, isErr) {
  let t = document.getElementById('ai-toast');
  if (!t) {
    t = document.createElement('div');
    t.id = 'ai-toast';
    document.body.appendChild(t);
  }
  t.className = 'toast' + (isErr ? ' toast-err' : '');
  t.textContent = msg;
  t.style.display = 'block';
  clearTimeout(window._toastTimer);
  window._toastTimer = setTimeout(() => { t.style.display = 'none'; }, isErr ? 6000 : 2500);
}

function aiRecommend(fid, btn) {
  if (!confirm('对该场比赛调用 AI 分析？\\n多模型模式下已配置的模型各跑一次（DeepSeek / 豆包），约 1–2 分钟。')) return;
  const b = btn || (typeof event !== 'undefined' && event.target);
  if (b) { b.disabled = true; b.textContent = '分析中…'; }
  fetch('/api/match/' + fid + '/recommend', {method:'POST'})
    .then(r => r.json())
    .then(d => {
      if (!d.ok) {
        showToast(d.error || '分析失败', true);
        if (b) { b.disabled = false; b.textContent = b.dataset.label || '✨ AI 推荐本场'; }
        return;
      }
      const n = (d.ai_providers && d.ai_providers.length) || (d.ai_analyses ? Object.keys(d.ai_analyses).length : 1);
      showToast('✅ 已保存 ' + n + ' 个模型分析，刷新页面…');
      document.querySelectorAll('.btn-deep').forEach(el => {
        el.disabled = false;
        el.title = '';
        el.onclick = () => aiDeepAnalyze(fid, el);
        el.textContent = el.dataset.label || '🔍 AI 深度分析';
      });
      document.querySelectorAll('.deep-gate-hint').forEach(el => { el.remove(); });
      setTimeout(() => location.reload(), 900);
    })
    .catch(e => {
      showToast('请求失败: ' + e, true);
      if (b) { b.disabled = false; b.textContent = b.dataset.label || '✨ AI 推荐本场'; }
    });
}

function aiDeepAnalyze(fid, btn) {
  if (!confirm('AI 深度分析：若尚未跑过首轮，会先自动做 AI 推荐，再二次综合研判。\\n多模型约 1–3 分钟，请稍候。')) return;
  const b = btn || (typeof event !== 'undefined' && event.target);
  if (b) { b.disabled = true; b.textContent = '分析中…'; }
  fetch('/api/match/' + fid + '/deep-analyze', {method:'POST'})
    .then(r => r.json())
    .then(d => {
      if (!d.ok) {
        showToast(d.error || '深度分析失败', true);
        if (b) { b.disabled = false; b.textContent = b.dataset.label || '🔍 AI 深度分析'; }
        return;
      }
      showToast('✅ ' + (d.headline || '深度分析完成') + (d.auto_first_pass ? '（含自动首轮 AI）' : '') + '，刷新页面…');
      setTimeout(() => location.reload(), 900);
    })
    .catch(e => {
      showToast('请求失败: ' + e, true);
      if (b) { b.disabled = false; b.textContent = b.dataset.label || '🔍 AI 深度分析'; }
    });
}

function escHtmlSim(s) {
  const d = document.createElement('div');
  d.textContent = s == null ? '' : String(s);
  return d.innerHTML;
}

function renderSimilarityAi(d) {
  const ev = (d.key_evidence || []).map(x => '<li>' + escHtmlSim(x) + '</li>').join('');
  return '<div class="similar-ai-box">'
    + '<div class="similar-ai-top"><strong>' + escHtmlSim(d.headline || '相似盘口解读') + '</strong>'
    + '<span class="tag">' + escHtmlSim(d.confidence_cn || '—') + '</span></div>'
    + '<p class="similar-ai-pick"><strong>胜平负</strong> ' + escHtmlSim(d.result_pick_cn || '—')
    + ' · <strong>亚盘</strong> ' + escHtmlSim(d.handicap_pick_cn || '—')
    + ' · <strong>比分</strong> ' + escHtmlSim(d.likely_scores || '—') + '</p>'
    + '<p>' + escHtmlSim(d.summary || '') + '</p>'
    + (d.sample_reliability ? '<p class="meta">' + escHtmlSim(d.sample_reliability) + '</p>' : '')
    + (ev ? '<ul class="similar-ai-ev">' + ev + '</ul>' : '')
    + '<p class="meta"><strong>风险</strong> ' + escHtmlSim(d.risk || '—') + '</p>'
    + (d.vs_baseline ? '<p class="meta"><strong>对比规则推荐</strong> ' + escHtmlSim(d.vs_baseline) + '</p>' : '')
    + (d.action ? '<p class="similar-ai-action">' + escHtmlSim(d.action) + '</p>' : '')
    + '</div>';
}

function aiSimilarityAnalyze(fid, source, btn) {
  const out = document.getElementById('sim-ai-' + fid + '-' + source);
  if (btn) { btn.disabled = true; btn.textContent = '分析中…'; }
  if (out) out.innerHTML = '<p class="meta">正在解读相似盘口样本…</p>';
  fetch('/api/match/' + fid + '/similarity-ai', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({source: source, force: true})
  })
    .then(r => r.json())
    .then(d => {
      if (btn) { btn.disabled = false; btn.textContent = btn.dataset.label || '✨ AI盘口解读'; }
      if (!out) return;
      if (!d.ok) {
        out.innerHTML = '<p class="meta similar-ai-err">' + escHtmlSim(d.error || '分析失败') + '</p>';
        return;
      }
      out.innerHTML = renderSimilarityAi(d);
    })
    .catch(e => {
      if (btn) { btn.disabled = false; btn.textContent = btn.dataset.label || '✨ AI盘口解读'; }
      if (out) out.innerHTML = '<p class="meta similar-ai-err">请求失败: ' + escHtmlSim(e) + '</p>';
    });
}

function runSettle(opts) {
  opts = opts || {};
  const body = {};
  if (opts.resettle) body.resettle = true;
  if (opts.fixture_id) body.fixture_id = String(opts.fixture_id);
  if (opts.fixture_ids) body.fixture_ids = opts.fixture_ids;
  return fetch('/api/settle', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  }).then(r => r.json());
}

function manualSettle(btn, opts) {
  opts = opts || {};
  const tip = opts.resettle
    ? '重新抓取终场比分并覆盖已有赛果？'
    : '从 live.500 / 世界杯 API 抓取已完场比分并写入结算？';
  if (!confirm(tip)) return;
  if (btn) { btn.disabled = true; btn.textContent = '抓取中…'; }
  runSettle(opts).then(d => {
    if (btn) {
      btn.disabled = false;
      btn.textContent = btn.dataset.label || '抓取完赛赛果';
    }
    if (!d.ok) {
      showToast(d.error || d.message || '结算失败', true);
      return;
    }
    const names = (d.settled_matches || []).slice(0, 3).map(x => x.score_text ? x.match_name + ' ' + x.score_text : x.match_name).filter(Boolean);
    let msg = `结算 ${d.settled || 0} 场`;
    if (d.skipped_live) msg += ` · 跳过进行中 ${d.skipped_live}`;
    if (d.skipped_no_score) msg += ` · 暂无比分 ${d.skipped_no_score}`;
    if (names.length) msg += '\\n' + names.join('\\n');
    showToast(msg, false);
    if ((d.settled || 0) > 0) setTimeout(() => location.reload(), 900);
  }).catch(e => {
    if (btn) {
      btn.disabled = false;
      btn.textContent = btn.dataset.label || '抓取完赛赛果';
    }
    showToast('请求失败: ' + e, true);
  });
}
"""

_AI_CHAT_JS = """
function startAiChat(scope, fid) {
  const boxId = scope === 'match' ? 'match-ai-chat' : 'dashboard-ai-chat';
  const box = document.getElementById(boxId);
  if (!box) return;
  const input = box.querySelector('.ai-chat-input');
  const provider = box.querySelector('.ai-chat-provider');
  const out = box.querySelector('.ai-chat-output');
  const btn = box.querySelector('.ai-chat-send');
  const prompt = (input && input.value || '').trim();
  if (!prompt) { showToast('先输入你的判断或问题', true); return; }
  if (window._aiChatSource) window._aiChatSource.close();
  out.textContent = '';
  if (btn) { btn.disabled = true; btn.textContent = '分析中…'; }
  const params = new URLSearchParams({prompt, provider: provider.value || 'deepseek'});
  const url = scope === 'match'
    ? '/api/match/' + encodeURIComponent(fid) + '/chat-stream?' + params.toString()
    : '/api/dashboard/chat-stream?' + params.toString();
  const es = new EventSource(url);
  window._aiChatSource = es;
  es.addEventListener('chunk', ev => { out.textContent += ev.data; out.scrollTop = out.scrollHeight; });
  es.addEventListener('error', ev => {
    out.textContent += '\\n[连接结束或出错]';
    es.close();
    if (btn) { btn.disabled = false; btn.textContent = '发送给AI'; }
  });
  es.addEventListener('done', ev => {
    es.close();
    if (btn) { btn.disabled = false; btn.textContent = '发送给AI'; }
  });
}

function fillAiChat(scope, text) {
  const box = document.getElementById(scope === 'match' ? 'match-ai-chat' : 'dashboard-ai-chat');
  if (!box) return;
  const input = box.querySelector('.ai-chat-input');
  if (input) input.value = text;
}

async function initAiProviderSelects() {
  const byRole = new Map();
  document.querySelectorAll('[data-ai-provider-role]').forEach(sel => {
    const role = sel.getAttribute('data-ai-provider-role') || 'chat';
    if (!byRole.has(role)) byRole.set(role, []);
    byRole.get(role).push(sel);
  });
  for (const [role, elements] of byRole.entries()) {
    try {
      const r = await fetch('/api/ai/providers?role=' + encodeURIComponent(role) + '&configured=1');
      const d = await r.json();
      const providers = d.providers || [];
      elements.forEach(sel => {
        sel.innerHTML = '';
        providers.forEach(p => {
          const opt = document.createElement('option');
          opt.value = p.id;
          opt.textContent = p.label;
          sel.appendChild(opt);
        });
        if (!sel.options.length) {
          const opt = document.createElement('option');
          opt.value = 'deepseek';
          opt.textContent = '未配置 AI';
          sel.appendChild(opt);
        }
      });
    } catch (e) { /* keep empty select */ }
  }
}
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initAiProviderSelects);
} else {
  initAiProviderSelects();
}
"""

_DASH_FILTER_JS = """
function filterDashRows(mode) {
  document.querySelectorAll('.dash-row').forEach(tr => {
    if (mode === 'sweet') {
      tr.style.display = tr.dataset.sweet === '1' ? '' : 'none';
    } else if (mode === 'solid') {
      const g = tr.dataset.accGrade || '';
      tr.style.display = (g === '稳胆甜区' || g === '稳胆') ? '' : 'none';
    } else {
      tr.style.display = '';
    }
  });
}
function onDashFilter(el) {
  if (el && el.checked) {
    const solid = document.getElementById('dash-filter-solid');
    if (solid) solid.checked = false;
  }
  filterDashRows(el && el.checked ? 'sweet' : 'all');
}
function onDashSolidFilter(el) {
  if (el && el.checked) {
    const sweet = document.getElementById('dash-filter-sweet');
    if (sweet) sweet.checked = false;
    filterDashRows('solid');
  } else {
    filterDashRows('all');
  }
}
"""

_PARLAY_JS = """
const parlaySelected = new Map();
const PICK_MAX = 20;

function toggleParlayPick(el) {
  const fid = el.dataset.fid;
    if (el.checked) {
    if (parlaySelected.size >= PICK_MAX) {
      el.checked = false;
      showToast('最多选 ' + PICK_MAX + ' 场', true);
      return;
    }
    const tier = el.dataset.tier || '';
    const sweet = el.dataset.sweet === '1';
    const grade = el.dataset.accGrade || '';
    if (tier && tier !== 'A') {
      const label = tier === 'B' ? '可单关' : '仅参考';
      showToast('该场档位为「' + label + '」，串关建议优先选「可串」', true);
    }
    if (!sweet && grade !== '稳胆甜区' && grade !== '稳胆') {
      showToast('非 SP 1.3–1.6 甜区，重正确率可单关，串关请优先「稳胆甜区」', true);
    }
    parlaySelected.set(fid, el.dataset.name || fid);
  } else {
    parlaySelected.delete(fid);
  }
  updateParlayToolbar();
}

function updateParlayToolbar() {
  const n = parlaySelected.size;
  const countEl = document.getElementById('parlay-count');
  const btn = document.getElementById('parlay-analyze-btn');
  const aiBtn = document.getElementById('parlay-ai-btn');
  const posterBtn = document.getElementById('poster-batch-btn');
  if (countEl) countEl.textContent = n + ' 场 · 串关需 2';
  const ready = n === 2;
  if (btn) btn.disabled = !ready;
  if (aiBtn) aiBtn.disabled = !ready;
  if (posterBtn) posterBtn.disabled = n === 0;
}

function openSelectedPosters() {
  const ids = [...parlaySelected.keys()];
  if (!ids.length) { showToast('请先勾选场次', true); return; }
  window.open('/share/posters?ids=' + encodeURIComponent(ids.join(',')), '_blank', 'noopener');
}

function escHtml(s) {
  const d = document.createElement('div');
  d.textContent = s == null ? '' : String(s);
  return d.innerHTML;
}

function renderParlayResult(d) {
  window._lastParlay = d;
  const el = document.getElementById('parlay-result');
  if (!el) return;
  if (d.options && d.options.length) {
    const cards = d.options.map((opt, idx) => {
      const verdictCls = opt.verdict === '可串' ? 'verdict-ok' : (opt.verdict === '不建议' ? 'verdict-bad' : 'verdict-warn');
      const legs = (opt.legs || []).map((leg, i) => {
        const sp = leg.odds_used || leg.jingcai_sp || '—';
        return '<div class="leg-block"><p class="match-line"><span class="leg-num">' + (i+1) + '</span>'
          + '<a href="/match/' + escHtml(leg.fixture_id) + '"><strong>' + escHtml(leg.match) + '</strong></a></p>'
          + '<p class="pick-line"><strong class="pick">' + escHtml(leg.pick_cn) + '</strong>'
          + ' · SP ' + escHtml(sp)
          + ' · 置信 ' + escHtml(leg.confidence_cn)
          + (leg.jingcai_market_label && leg.jingcai_market_label !== '—' ? ' · ' + escHtml(leg.jingcai_market_label) : '')
          + '</p></div>';
      }).join('');
      const risks = opt.ai_risk_notes || [];
      const combined = opt.combined_odds ? ('组合 SP ≈ ' + opt.combined_odds) : '赔率不完整';
      const payout = opt.payout_per_100 ? (' · 100 元约返 ' + opt.payout_per_100 + ' 元') : '';
      const shareIds = (opt.legs || []).map(l => l.fixture_id).filter(Boolean).join(',');
      const shareBtn = shareIds
        ? '<a class="btn btn-sm" href="/share/parlay?ids=' + encodeURIComponent(shareIds) + '" target="_blank" rel="noopener">📷 保存成图</a>'
        : '';
      return '<div class="parlay-option">'
        + '<h3>' + escHtml(opt.ai_label || ('方案' + (idx + 1))) + ' · <span class="' + verdictCls + '">' + escHtml(opt.verdict) + '</span></h3>'
        + '<p class="meta">' + escHtml(opt.ai_provider_label || 'AI') + ' · 比赛日 ' + escHtml(opt.match_date || '—') + ' · ' + combined + payout + '</p>'
        + legs
        + '<div class="parlay-ai-brief"><p><strong>' + escHtml(opt.ai_headline || '') + '</strong></p>'
        + (opt.ai_reason ? '<p class="meta">' + escHtml(opt.ai_reason) + '</p>' : '')
        + (risks.length ? '<ul class="parlay-reasons">' + risks.map(r => '<li>' + escHtml(r) + '</li>').join('') + '</ul>' : '')
        + (opt.ai_stake_advice ? '<p class="parlay-stake">' + escHtml(opt.ai_stake_advice) + '</p>' : '')
        + '</div>'
        + '<div class="parlay-actions">' + shareBtn + '</div>'
        + '</div>';
    }).join('');
    el.innerHTML = '<h3>AI自动选2串1 · ' + escHtml(d.ai_provider_label || '') + '</h3>'
      + '<p class="meta">默认给两组：稳健一组、提赔一组；每组内部同一天，不跨天。</p>'
      + cards;
    el.style.display = 'block';
    el.scrollIntoView({behavior: 'smooth', block: 'nearest'});
    return;
  }
  const verdictCls = d.verdict === '可串' ? 'verdict-ok' : (d.verdict === '不建议' ? 'verdict-bad' : 'verdict-warn');
  let legsHtml = '';
  (d.legs || []).forEach((leg, i) => {
    const sp = leg.odds_used || leg.jingcai_sp || '—';
    let legReason = '';
    const expl = d.explanation || {};
    (expl.leg_reasons || []).forEach(lr => {
      if (lr.match === leg.match) legReason = lr.text || '';
    });
    legsHtml += '<div class="leg-block"><p class="match-line"><span class="leg-num">' + (i+1) + '</span>'
      + '<a href="/match/' + escHtml(leg.fixture_id) + '"><strong>' + escHtml(leg.match) + '</strong></a></p>'
      + '<p class="pick-line"><strong class="pick">' + escHtml(leg.pick_cn) + '</strong>'
      + ' · SP ' + escHtml(sp)
      + ' · 置信 ' + escHtml(leg.confidence_cn)
      + (leg.jingcai_market_label && leg.jingcai_market_label !== '—' ? ' · ' + escHtml(leg.jingcai_market_label) : '')
      + '</p>'
      + (legReason ? '<p class="leg-reason-text">' + escHtml(legReason) + '</p>' : '')
      + '</div>';
  });
  let explainHtml = '';
  const ex = d.explanation || {};
  if (ex.headline || ex.paragraph) {
    explainHtml += '<div class="parlay-explain-box"><h4>串关说明</h4>'
      + '<p class="parlay-explain">' + escHtml(ex.paragraph || ex.headline) + '</p>';
    if (ex.reasons && ex.reasons.length) {
      explainHtml += '<ul class="parlay-reasons">' + ex.reasons.map(r => '<li>' + escHtml(r) + '</li>').join('') + '</ul>';
    }
    if (ex.stake_advice) {
      explainHtml += '<p class="parlay-stake">💡 ' + escHtml(ex.stake_advice) + '</p>';
    }
    explainHtml += '</div>';
  }
  let warnHtml = '';
  const warns = (d.warnings || []).concat(d.blockers || []);
  if (warns.length) {
    warnHtml = '<ul class="parlay-warns">' + warns.map(w => '<li>' + escHtml(w) + '</li>').join('') + '</ul>';
  }
  let aiHtml = '';
  if (d.ai_headline || d.ai_reason) {
    const risks = d.ai_risk_notes || [];
    aiHtml = '<div class="parlay-ai-brief"><p><strong>AI 选串：</strong>' + escHtml(d.ai_headline || '') + '</p>'
      + (d.ai_reason ? '<p class="meta">' + escHtml(d.ai_reason) + '</p>' : '')
      + (risks.length ? '<ul class="parlay-reasons">' + risks.map(r => '<li>' + escHtml(r) + '</li>').join('') + '</ul>' : '')
      + (d.ai_stake_advice ? '<p class="parlay-stake">' + escHtml(d.ai_stake_advice) + '</p>' : '')
      + '</div>';
  } else if (d.ai_brief) {
    const b = d.ai_brief;
    aiHtml = '<div class="parlay-ai-brief"><p><strong>AI 简评：</strong>' + escHtml(b.headline || b.brief || '') + '</p>'
      + (b.stake_advice ? '<p class="meta">' + escHtml(b.stake_advice) + '</p>' : '') + '</div>';
  } else if (d.ai_error) {
    aiHtml = '<p class="meta">AI 简评失败：' + escHtml(d.ai_error) + '</p>';
  }
  const combined = d.combined_odds ? ('组合 SP ≈ ' + d.combined_odds) : '赔率不完整';
  const payout = d.payout_per_100 ? (' · 100 元约返 ' + d.payout_per_100 + ' 元') : '';
  const dateTxt = d.match_date ? (' · 比赛日 ' + d.match_date) : '';
  const shareIds = (d.legs || []).map(l => l.fixture_id).filter(Boolean).join(',');
  const shareBtn = shareIds
    ? '<a class="btn btn-sm" href="/share/parlay?ids=' + encodeURIComponent(shareIds) + '" target="_blank" rel="noopener">📷 保存成图</a>'
    : '';
  const title = d.ai_provider_label ? ('AI 自动选 2串1 · ' + d.ai_provider_label) : '自选 2串1';
  el.innerHTML = '<h3>' + escHtml(title) + ' · <span class="' + verdictCls + '">' + escHtml(d.verdict) + '</span></h3>'
    + '<p class="meta">' + escHtml(d.verdict_detail) + ' · ' + combined + payout + escHtml(dateTxt) + '</p>'
    + legsHtml + explainHtml + warnHtml + aiHtml
    + '<div class="parlay-actions">' + shareBtn + '</div>'
    + '<p class="meta">本地分析 · ' + escHtml(d.generated_at || '') + '</p>';
  el.style.display = 'block';
  el.scrollIntoView({behavior: 'smooth', block: 'nearest'});
}

function analyzeParlay(useAi) {
  const ids = [...parlaySelected.keys()];
  if (ids.length !== 2) { showToast('请勾选 2 场', true); return; }
  const btn = useAi ? document.getElementById('parlay-ai-btn') : document.getElementById('parlay-analyze-btn');
  const label = useAi ? 'AI 简评' : '2串1 分析';
  if (btn) { btn.disabled = true; btn.textContent = '分析中…'; }
  const url = '/api/parlay/analyze' + (useAi ? '?ai=1' : '');
  fetch(url, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({fixture_ids: ids})
  })
    .then(r => r.json())
    .then(d => {
      updateParlayToolbar();
      if (btn) btn.textContent = label;
      if (!d.ok) { showToast(d.error || '分析失败', true); return; }
      renderParlayResult(d);
      showToast('✅ 2串1 分析完成');
    })
    .catch(e => {
      updateParlayToolbar();
      if (btn) { btn.textContent = label; }
      showToast('请求失败: ' + e, true);
    });
}

function analyzeListParlayAi() {
  const providerEl = document.getElementById('list-parlay-provider');
  const provider = providerEl ? providerEl.value : 'deepseek';
  const btn = document.getElementById('list-parlay-ai-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'AI选串中…'; }
  fetch('/api/list-parlay/ai', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({provider})
  })
    .then(r => r.json())
    .then(d => {
      if (btn) { btn.disabled = false; btn.textContent = 'AI自动选2串1'; }
      if (!d.ok) { showToast(d.error || 'AI选串失败', true); return; }
      renderParlayResult(d);
      showToast('✅ AI已选出2串1');
    })
    .catch(e => {
      if (btn) { btn.disabled = false; btn.textContent = 'AI自动选2串1'; }
      showToast('请求失败: ' + e, true);
    });
}
"""

_TOAST_CSS = """
.toast {{
  display: none; position: fixed; bottom: 24px; right: 24px; z-index: 9999;
  background: #059669; color: #fff; padding: 12px 20px; border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0,0,0,.15); font-size: 14px; max-width: 360px;
}}
.toast-err {{ background: #dc2626; }}
"""

_BTN_CSS = """
.btn {{ display: inline-block; padding: 8px 16px; background: #2563eb; color: #fff !important;
        border-radius: 6px; border: none; cursor: pointer; font-size: 14px; text-decoration: none; }}
.btn-sm {{ padding: 4px 10px; font-size: 12px; }}
.btn:disabled {{ opacity: 0.6; cursor: wait; }}
.btn-ai {{ background: #7c3aed; }}
.btn-deep {{ background: #0d9488; }}
.btn-deep:disabled {{ background: #94a3b8; opacity: 0.7; cursor: not-allowed; }}
.deep-card {{ border-left: 4px solid #0d9488; }}
.deep-headline {{ font-size: 1.2rem; font-weight: 600; color: #0f766e; margin: 0 0 8px; }}
.deep-section {{ margin: 10px 0; }}
.deep-section h4 {{ margin: 0 0 4px; font-size: 13px; color: #475569; }}
.deep-list {{ margin: 4px 0 0 16px; padding: 0; }}
.deep-list li {{ margin: 2px 0; font-size: 13px; color: #334155; }}
"""

_FOLD_CSS = """
details.fold {{
  background: #fff; border-radius: 10px; margin-bottom: 10px;
  border: 1px solid #e2e8f0; box-shadow: 0 1px 3px rgba(0,0,0,.04);
}}
details.fold > summary {{
  padding: 14px 18px; cursor: pointer; font-weight: 600; font-size: 14px;
  color: #334155; list-style: none; user-select: none;
}}
details.fold > summary::-webkit-details-marker {{ display: none; }}
details.fold > summary::before {{
  content: '▸'; display: inline-block; margin-right: 8px; color: #94a3b8;
  transition: transform .15s;
}}
details.fold[open] > summary::before {{ transform: rotate(90deg); }}
details.fold-muted > summary {{ font-weight: 500; color: #64748b; }}
details.fold-open {{ border-color: #bfdbfe; }}
details.fold-open > summary {{ color: #1e40af; }}
.fold-body {{ padding: 0 16px 16px; }}
.fold-body > .card:first-child {{ margin-top: 0; }}
.fold-body .card {{ box-shadow: none; border: 1px solid #eef2f6; margin-bottom: 10px; }}
.fold-stack {{ display: flex; flex-direction: column; gap: 10px; margin-bottom: 16px; }}
.fold-summary-line {{ display: flex; align-items: center; gap: 8px; width: 100%; }}
.fold-summary-line > span:first-child {{ flex: 1; min-width: 0; }}
.export-module {{ position: relative; background: #fff; }}
.export-module:not(details) {{ border: 1px solid #e2e8f0; border-radius: 10px; margin-bottom: 12px; }}
.export-module-toolbar {{ position: absolute; top: 8px; right: 8px; z-index: 5; }}
.export-module-inner {{ padding-top: 2px; }}
.export-module:not(details) .export-module-inner {{ padding: 36px 12px 12px; }}
.export-module:not(details) .export-module-inner > .card:first-child {{ margin-top: 0; margin-bottom: 0; }}
.btn-export-mod {{ font-size: 11px; padding: 3px 10px; border-radius: 6px; border: 1px solid #cbd5e1;
  background: #fff; color: #475569; cursor: pointer; white-space: nowrap; line-height: 1.4; }}
.btn-export-mod:hover {{ background: #f1f5f9; border-color: #94a3b8; }}
.btn-export-mod:disabled {{ opacity: 0.6; cursor: wait; }}
"""

_LAYOUT_CSS = """
*, *::before, *::after {{ box-sizing: border-box; }}
html {{ -webkit-text-size-adjust: 100%; }}
body {{ font-family: system-ui, -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
       margin: 0 auto; padding: 16px clamp(12px, 3vw, 24px) 32px; background: #f0f2f5; color: #1a1a1a;
       max-width: min(1200px, 100%); width: 100%; min-height: 100vh; overflow-x: clip; }}
.card {{ background: #fff; border-radius: 10px; padding: 18px clamp(14px, 3vw, 22px); margin-bottom: 16px;
         box-shadow: 0 1px 4px rgba(0,0,0,.06); max-width: 100%; }}
h1 {{ margin: 0 0 10px; font-size: clamp(1.15rem, 4vw, 1.35rem); line-height: 1.3; }}
h2 {{ margin: 0 0 12px; font-size: clamp(1rem, 3.2vw, 1.08rem); line-height: 1.35; }}
h3 {{ margin: 0 0 12px; font-size: clamp(.95rem, 3vw, 1rem); color: #334155; line-height: 1.35; }}
.back {{ margin-bottom: 12px; }}
.back a {{ color: #2563eb; text-decoration: none; }}
.meta {{ color: #64748b; font-size: 13px; line-height: 1.55; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border-bottom: 1px solid #eee; padding: 10px 8px; text-align: left; font-size: 14px; vertical-align: top; }}
th {{ background: #fafafa; font-weight: 600; white-space: nowrap; }}
a {{ color: #2563eb; text-decoration: none; word-break: break-word; }}
.tag {{ display: inline-block; background: #eff6ff; color: #1d4ed8; padding: 2px 8px;
        border-radius: 4px; font-size: 12px; margin: 2px 4px 2px 0; max-width: 100%; }}
.tag-live {{ background: #fef3c7; color: #b45309; }}
.tag-qual-div {{ background: #fff7ed; color: #c2410c; border: 1px solid #fdba74; font-weight: 700; }}
.tag-buy-tier-a {{ background: #ecfdf5; color: #047857; border: 1px solid #6ee7b7; font-weight: 700; }}
.tag-buy-tier-b {{ background: #eff6ff; color: #1d4ed8; border: 1px solid #93c5fd; font-weight: 700; }}
.tag-buy-tier-c {{ background: #f3f4f6; color: #6b7280; border: 1px solid #d1d5db; font-weight: 600; }}
.tag-acc-sweet {{ background: #fff7ed; color: #c2410c; border: 1px solid #fdba74; font-weight: 700; }}
.tag-acc-solid {{ background: #ecfdf5; color: #047857; border: 1px solid #6ee7b7; font-weight: 700; }}
.tag-acc-ok {{ background: #eff6ff; color: #1d4ed8; border: 1px solid #93c5fd; }}
.tag-acc-warn {{ background: #fef2f2; color: #b91c1c; border: 1px solid #fecaca; }}
.sweet-teaser {{ background: linear-gradient(135deg,#fff7ed,#ffedd5); border: 1px solid #fdba74;
  border-radius: 12px; padding: 12px 16px; margin: 0 0 14px; }}
.sweet-teaser h3 {{ margin: 0 0 8px; font-size: 15px; color: #c2410c; }}
.sweet-teaser ul {{ margin: 0; padding-left: 18px; line-height: 1.55; }}
.meta.warn {{ color: #b45309; font-weight: 600; }}
.qual-div-banner {{ background: linear-gradient(135deg,#fff7ed,#ffedd5); border: 1px solid #fdba74;
  border-radius: 12px; padding: 14px 16px; margin: 12px 0 16px; }}
.qual-div-banner p {{ margin: 8px 0 0; font-size: 14px; line-height: 1.55; }}
.buy-tier-banner {{ border-radius: 10px; padding: 12px 16px; margin: 12px 0; border: 1px solid #e5e7eb; }}
.buy-tier-banner h3 {{ margin: 0 0 6px; font-size: 16px; }}
.buy-tier-banner p {{ margin: 0; font-size: 14px; line-height: 1.5; color: #374151; }}
.buy-tier-tier-a {{ background: linear-gradient(135deg,#ecfdf5,#d1fae5); border-color: #6ee7b7; }}
.buy-tier-tier-a h3 {{ color: #047857; }}
.buy-tier-tier-b {{ background: linear-gradient(135deg,#eff6ff,#dbeafe); border-color: #93c5fd; }}
.buy-tier-tier-b h3 {{ color: #1d4ed8; }}
.buy-tier-tier-c {{ background: linear-gradient(135deg,#f9fafb,#f3f4f6); border-color: #d1d5db; }}
.buy-tier-tier-c h3 {{ color: #6b7280; }}
.tag-ok {{ background: #ecfdf5; color: #047857; }}
.tag-miss {{ background: #fef2f2; color: #b91c1c; }}
.tag-active {{ background: #1d4ed8; color: #fff; }}
code {{ word-break: break-word; }}
canvas {{ max-width: 100% !important; height: auto !important; }}
img {{ max-width: 100%; height: auto; }}
"""

_RESPONSIVE_CSS = """
.page-nav, .back { display: flex; flex-wrap: wrap; gap: 6px 8px; align-items: center; line-height: 1.65; }
.page-nav a, .back a { white-space: nowrap; }
.action-bar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 16px; }
.card:has(> table), .fold-body:has(> table), .similar-block {
  overflow-x: auto; -webkit-overflow-scrolling: touch; max-width: 100%;
}
.card > table:not(.mini), .fold-body > table:not(.mini) { min-width: 560px; }
.card > table.dashboard-table { min-width: 680px; }
table.mini { width: 100%; min-width: 0; }
.stat-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 118px), 1fr));
  gap: 10px; margin-bottom: 12px;
}
.stat {
  background: #f8fafc; border-radius: 8px; padding: 10px 12px; border: 1px solid #e2e8f0;
  text-align: center; min-width: 0;
}
.stat-val { font-size: clamp(1.05rem, 3.5vw, 1.35rem); font-weight: 700; line-height: 1.25; word-break: break-word; }
.stat-lbl { font-size: 11px; color: #64748b; margin-top: 4px; line-height: 1.35; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr)); gap: 12px; }
.match-row { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.2fr); gap: 8px 16px; align-items: start; }
.match-side { justify-self: end; text-align: right; font-size: 12px; color: #475569; line-height: 1.65; min-width: 0; }
.hero-card { max-width: 100%; }
@media (max-width: 900px) {
  .strategy-grid, .path-grid, .rec-grid, .quant-score-grid, .kelly-grid, .gs-grid, .conc-grid,
  .watch-grid, .ai-watch-cols, .ai-match-grid, .match-ai-grid, .watch-stats {
    grid-template-columns: 1fr !important;
  }
  .match-row { grid-template-columns: 1fr !important; }
  .match-side { justify-self: stretch !important; text-align: left !important; }
}
@media (max-width: 640px) {
  body { padding: 12px 10px 24px; }
  .card { padding: 14px 12px; margin-bottom: 12px; border-radius: 8px; }
  th, td { padding: 8px 6px; font-size: 13px; }
  .btn { padding: 8px 12px; font-size: 13px; }
  .toast { left: 10px; right: 10px; bottom: 10px; max-width: none; }
  details.fold > summary { padding: 12px 14px; font-size: 13px; }
  .fold-body { padding: 0 12px 12px; }
  .parlay-toolbar { flex-direction: column; align-items: stretch; }
  .parlay-toolbar .btn, .parlay-toolbar select, .parlay-toolbar .ai-chat-provider { width: 100%; max-width: 100%; }
  .ai-chat-toolbar { flex-direction: column; align-items: stretch; }
  .ai-chat-toolbar .btn, .ai-chat-toolbar select { width: 100%; max-width: 100%; }
  .toolbar { flex-direction: column; align-items: stretch; }
  .toolbar .btn { width: 100%; text-align: center; }
}
"""


def _shared_css(*extra: str) -> str:
    chat_css = """
.ai-chat-card { border-left: 4px solid #7c3aed; }
.ai-chat-toolbar { display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin:8px 0; }
.ai-chat-provider { padding:7px 10px; border:1px solid #cbd5e1; border-radius:8px; }
.ai-chat-quick { display:flex; gap:8px; flex-wrap:wrap; margin:8px 0; }
.ai-chat-input { width:100%; box-sizing:border-box; border:1px solid #cbd5e1; border-radius:8px; padding:10px; font-size:14px; }
.ai-chat-output { min-height:90px; max-height:360px; overflow:auto; white-space:pre-wrap; background:#0f172a; color:#e2e8f0;
                  border-radius:8px; padding:12px; line-height:1.55; font-size:13px; }
"""
    raw = _LAYOUT_CSS + _RESPONSIVE_CSS + _FOLD_CSS + _TOAST_CSS + _BTN_CSS + chat_css + "".join(extra)
    return raw.replace("{{", "{").replace("}}", "}")


def _export_module_btn() -> str:
    return (
        '<button type="button" class="btn-export-mod" '
        'onclick="event.preventDefault(); event.stopPropagation(); saveModuleImage(this)" '
        'title="保存本模块为图片（适合抖音分条发）">📷 存图</button>'
    )


def _wrap_export_module(slug: str, html: str, *, extra_class: str = "") -> str:
    if not html or not str(html).strip():
        return ""
    cls = "export-module"
    if extra_class:
        cls += f" {extra_class}"
    return (
        f'<div class="{cls}" data-export-slug="{_e(slug)}">'
        f'<div class="export-module-toolbar export-hide">{_export_module_btn()}</div>'
        f'<div class="export-module-inner">{html}</div></div>'
    )


def _fold(
    summary: str,
    body: str,
    *,
    open: bool = False,
    muted: bool = False,
    css_class: str = "",
    export_slug: str = "",
) -> str:
    """Collapsible section — secondary data hidden until expanded."""
    if not body or not body.strip():
        return ""
    open_attr = " open" if open else ""
    extra = css_class.strip()
    cls = "fold"
    if muted:
        cls += " fold-muted"
    if open:
        cls += " fold-open"
    if extra:
        cls += f" {extra}"
    export_btn = ""
    mod_attr = ""
    if export_slug:
        cls += " export-module"
        mod_attr = f' data-export-slug="{_e(export_slug)}"'
        export_btn = _export_module_btn()
    return (
        f'<details class="{cls}"{open_attr}{mod_attr}>'
        f'<summary><span class="fold-summary-line"><span>{summary}</span>{export_btn}</span></summary>'
        f'<div class="fold-body">{body}</div>'
        f"</details>"
    )


def _ai_chat_card(*, scope: str, fid: str = "") -> str:
    box_id = "match-ai-chat" if scope == "match" else "dashboard-ai-chat"
    quicks = [
        "只站在反方风控角度，找最强不买理由",
        "只分析欧亚互转暗线，判断是否诱盘",
        "如果我要人工干预，应该改成什么策略",
        "这场/这些比赛适不适合进保底2串1",
    ]
    btns = "".join(
        f'<button type="button" class="btn btn-sm" onclick="fillAiChat(\'{scope}\', \'{_e(q)}\')">{_e(q[:10])}</button>'
        for q in quicks
    )
    return f"""
<div class="card ai-chat-card" id="{box_id}">
  <h3>人工干预 AI 对话 <span class="tag">SSE</span></h3>
  <p class="meta">只用于复核与人工干预；下拉列表来自 <code>/api/ai/providers</code>（密钥仍在 .env）。</p>
  <div class="ai-chat-toolbar export-hide">
    <select class="ai-chat-provider" data-ai-provider-role="chat">
      <option value="deepseek">加载中…</option>
    </select>
    <button type="button" class="btn ai-chat-send" onclick="startAiChat('{scope}', '{_e(fid)}')">发送给AI</button>
  </div>
  <div class="ai-chat-quick export-hide">{btns}</div>
  <textarea class="ai-chat-input export-hide" rows="3" placeholder="输入你的人工判断或问题，例如：欧亚互转偏浅，是不是诱主？"></textarea>
  <pre class="ai-chat-output"></pre>
</div>"""



def _display_pick(m: dict, *, row: dict | None = None) -> str:
    row = row if row is not None else (m.get("predict_row") or {})
    if m.get("recommendation_source") == "pending" and not row.get("胜平负"):
        return "待分析"
    return final_recommendation_cn(m)


def _format_dual_pick(m: dict) -> str:
    analyses = m.get("ai_analyses") or {}
    if analyses:
        parts = []
        for pid, p in analyses.items():
            row = p.get("predict_row") or {}
            label = (p.get("ai_provider_label") or pid).replace(" 精算师", "")
            pick = _display_pick(p, row=row)
            parts.append(f"{label}:{pick}")
        return " | ".join(parts)
    return _display_pick(m)


def _hit_badge(hit) -> str:
    if hit is True:
        return '<span class="tag tag-ok">✓</span>'
    if hit is False:
        return '<span class="tag tag-miss">✗</span>'
    return '<span class="meta">—</span>'


def _closing_odds_txt(settled: dict) -> str:
    eu_h = settled.get("closing_eu_home")
    eu_d = settled.get("closing_eu_draw")
    eu_a = settled.get("closing_eu_away")
    ah = settled.get("closing_ah_line")
    parts = []
    if eu_h is not None:
        parts.append(f"欧 {eu_h}/{eu_d}/{eu_a}")
    if ah is not None:
        parts.append(f"亚 {ah}")
    ts = settled.get("closing_captured_at")
    if ts:
        parts.append(format_ts(ts))
    return " · ".join(parts) if parts else "—"


def _tier_badge_html(m: dict, row: dict | None = None) -> str:
    row = row or {}
    cn = m.get("buy_tier_cn") or row.get("购买档位") or ""
    if not cn:
        return ""
    css = {"可串": "tier-a", "可单关": "tier-b", "仅参考": "tier-c"}.get(cn, "tier-c")
    tip = m.get("buy_tier_reason") or row.get("档位说明") or ""
    title = f' title="{_e(tip)}"' if tip else ""
    return f' <span class="tag tag-buy-{css}"{title}>{_e(cn)}</span>'


def _accuracy_badge_html(m: dict, row: dict | None = None) -> str:
    row = row or {}
    grade = m.get("accuracy_grade_cn") or row.get("稳胆评级") or ""
    if not grade or grade in ("跳过", "—"):
        return ""
    css = {
        "稳胆甜区": "acc-sweet",
        "稳胆": "acc-solid",
        "可跟": "acc-ok",
        "慎跟": "acc-warn",
    }.get(grade, "acc-warn")
    sp = m.get("accuracy_jingcai_sp") or row.get("稳胆SP") or row.get("竞彩SP")
    tip = m.get("accuracy_reason") or ""
    if sp:
        tip = f"SP {sp}" + (f"；{tip}" if tip and tip != "—" else "")
    title = f' title="{_e(tip)}"' if tip else ""
    return f' <span class="tag tag-acc-{css}"{title}>{_e(grade)}</span>'


def _enrich_dashboard_match(m: dict) -> dict:
    """Attach buy tier + accuracy / sweet-spot analysis for dashboard rows."""
    from jingcai_pick import ensure_match_jingcai

    out = ensure_match_jingcai(dict(m))
    try:
        from analysis.rules.output import attach_post_recommendation

        attach_post_recommendation(out)
    except Exception:
        pass
    return out


def _sweet_spot_teaser(
    matches: list[dict],
    kickoff_map: dict | None = None,
    *,
    match_date: str = "",
) -> str:
    """Homepage block: SP 1.3–1.6 for the current 比赛日 / 收益周期 only."""
    from accuracy_pick import build_sweet_spot_analysis
    from daily_picks import _kickoff_label

    kickoff_map = kickoff_map or {}
    rows: list[tuple[int, dict, dict]] = []
    for m in matches:
        sa = m.get("sweet_spot_analysis")
        if not sa:
            try:
                sa = build_sweet_spot_analysis(m)
            except Exception:
                continue
        if not sa.get("ok") or not sa.get("sweet_spot"):
            continue
        grade = sa.get("accuracy_grade") or ""
        rank = {"稳胆甜区": 0, "稳胆": 1, "可跟": 2}.get(grade, 9)
        rows.append((rank, m, sa))

    if not rows:
        import config as app_cfg

        lo = getattr(app_cfg, "ACCURACY_SP_MIN", 1.30)
        hi = getattr(app_cfg, "ACCURACY_SP_MAX", 1.60)
        return f"""
<div class="card sweet-teaser muted">
  <h3>🎯 SP 甜区 {lo:g}–{hi:g} · 比赛日 {_e(match_date or '—')}（0 场）</h3>
  <p class="meta" style="margin:0">本比赛日暂无 SP 落在甜区的可跟场次。</p>
</div>"""

    rows.sort(key=lambda x: (x[0], -(x[2].get("accuracy_score") or 0)))
    lo = rows[0][2].get("sp_target_min", 1.30)
    hi = rows[0][2].get("sp_target_max", 1.60)
    items = ""
    for _, m, sa in rows[:8]:
        fid = str(m.get("fixture_id") or "")
        row = m.get("predict_row") or m
        name = row.get("比赛") or m.get("match") or fid
        ko = _kickoff_label(m, kickoff_map)
        pick = sa.get("pick_cn") or "—"
        sp = sa.get("sp") or "—"
        grade = sa.get("accuracy_grade") or "—"
        passed = sa.get("checklist_passed")
        total = sa.get("checklist_total")
        chk = f"{passed}/{total}" if passed is not None and total else "—"
        items += (
            f"<li><span class='meta'>{_e(ko)}</span> "
            f"<a href=\"/match/{_e(fid)}\"><strong>{_e(name)}</strong></a>"
            f" · {_e(pick)} · SP {_e(str(sp))} · {_e(grade)}"
            f" · 清单 {_e(str(chk))}"
            f"<br><span class='meta'>{_e(sa.get('edge_note') or sa.get('band_note') or '')}</span></li>"
        )

    return f"""
<div class="card sweet-teaser">
  <h3>🎯 SP 甜区 {lo:g}–{hi:g} · 比赛日 {_e(match_date)}（{len(rows)} 场）</h3>
  <p class="meta" style="margin:0 0 8px">本页仅展示<strong>同一比赛日</strong>场次，与当日 2串1 / 收益复盘周期一致。</p>
  <ul>{items}</ul>
</div>"""


def _match_day_switcher(available: list[str], cycle_day: str) -> str:
    """Switcher for SP sweet-spot card only — main match table stays full window."""
    if not available:
        return ""
    if len(available) == 1:
        return (
            f'<p class="meta cycle-day-bar">甜区收益周期 · 比赛日 <strong>{_e(cycle_day)}</strong>'
            f"（下方列表仍显示 {len(available)} 天内全部场次）</p>"
        )
    parts = []
    for d in available:
        if d == cycle_day:
            parts.append(f"<strong>{_e(d)}</strong>")
        else:
            parts.append(f'<a href="/?date={_e(d)}">{_e(d)}</a>')
    return (
        f'<p class="meta cycle-day-bar">甜区收益周期 · 比赛日 {" · ".join(parts)}'
        f" · 仅影响上方甜区卡片，下方列表不变</p>"
    )


def _sweet_spot_panel(prediction: dict | None) -> str:
    if not prediction:
        return ""
    from accuracy_pick import build_sweet_spot_analysis

    import config as app_cfg

    sa = prediction.get("sweet_spot_analysis") or build_sweet_spot_analysis(prediction)
    lo = sa.get("sp_target_min") or getattr(app_cfg, "ACCURACY_SP_MIN", 1.30)
    hi = sa.get("sp_target_max") or getattr(app_cfg, "ACCURACY_SP_MAX", 1.60)
    band_txt = f"{lo:g}–{hi:g}"
    if not sa.get("ok"):
        reason = sa.get("reason") or "暂无数据"
        return f"""
<div class="card sweet-spot-card muted">
  <h3>🎯 SP 甜区分析 <span class="tag">{_e(band_txt)}</span></h3>
  <p class="meta">{_e(reason)}</p>
</div>"""

    sweet = sa.get("sweet_spot")
    band_cls = "sweet-in" if sweet else ("sweet-below" if sa.get("band") == "below_sweet" else "sweet-above")
    grade = sa.get("accuracy_grade") or "—"
    grade_css = {
        "稳胆甜区": "acc-sweet",
        "稳胆": "acc-solid",
        "可跟": "acc-ok",
        "慎跟": "acc-warn",
    }.get(grade, "acc-warn")

    checklist_rows = ""
    for c in sa.get("checklist") or []:
        mark = "✓" if c.get("ok") else "✗"
        cls = "chk-ok" if c.get("ok") else "chk-bad"
        checklist_rows += (
            f"<tr class='{cls}'><td>{mark}</td><td>{_e(c.get('label'))}</td>"
            f"<td class='meta'>{_e(c.get('detail'))}</td></tr>"
        )

    prob_line = ""
    if sa.get("sp_implied_pct") is not None:
        prob_line = f"SP 隐含 {sa['sp_implied_pct']}%"
        if sa.get("model_prob_pct") is not None:
            prob_line += f" · 欧赔去水 {sa['model_prob_pct']}%"
            if sa.get("prob_gap_pct") is not None:
                prob_line += f"（差 {sa['prob_gap_pct']:+.1f}pp）"

    fid = prediction.get("fixture_id") or ""
    api_link = ""
    if fid:
        api_link = (
            f'<p class="meta"><a href="/api/match/{_e(str(fid))}/sweet-spot" '
            f'target="_blank" rel="noopener">JSON API</a></p>'
        )

    sweet_tag = ' <span class="tag tag-acc-sweet">甜区</span>' if sweet else ""
    return f"""
<div class="card sweet-spot-card {band_cls}">
  <h3>🎯 SP 甜区分析 <span class="tag">重正确率</span>{sweet_tag}
     <span class="tag tag-acc-{grade_css}">{_e(grade)}</span></h3>
  <p class="sweet-headline"><strong>{_e(sa.get('band_headline') or '—')}</strong>
     · 推荐 <strong>{_e(sa.get('pick_cn') or '—')}</strong></p>
  <p class="meta">{_e(sa.get('band_note') or '')}</p>
  {f'<p class="meta">{_e(prob_line)} · {_e(sa.get("edge_note") or "")}</p>' if prob_line or sa.get("edge_note") else ''}
  <table class="mini sweet-check-table">
    <tr><th></th><th>对齐项</th><th>说明</th></tr>
    {checklist_rows}
  </table>
  <p class="meta">清单 {sa.get('checklist_passed', '—')}/{sa.get('checklist_total', '—')}
     · 参考 {_e(sa.get('reference_cn') or '—')} · 初盘 {_e(sa.get('open_cn') or '—')}
     · 置信 {_e(sa.get('confidence_cn') or '—')}</p>
  {f'<p class="meta">比分主推 <strong>{_e(sa.get("score_headline") or "—")}</strong> · 赛果轨 {_e(sa.get("score_pick_1x2_cn") or "—")}</p>' if _score_enabled() else ''}
  <p class="sweet-verdict"><strong>{_e(sa.get('verdict') or '—')}</strong> — {_e(sa.get('stake_hint') or '')}</p>
  <p class="meta">{_e(sa.get('reasons') or '')}</p>
  {api_link}
</div>"""


def _alert_tags_html(m: dict, row: dict | None = None) -> str:
    tags = list(m.get("alert_tags") or [])
    row = row or {}
    extra = row.get("特殊标注") or ""
    if extra:
        tags.extend(t for t in str(extra).split("、") if t and t not in tags)
    if not tags:
        return ""
    return "".join(f' <span class="tag tag-qual-div">{_e(t)}</span>' for t in tags)


def _dashboard_active_row(
    m: dict,
    indexes: dict,
    kickoff_map: dict | None = None,
) -> str:
    from daily_picks import _kickoff_date

    kickoff_map = kickoff_map or {}
    row = m.get("predict_row") or m
    fid = str(m.get("fixture_id") or "")
    name = row.get("比赛") or m.get("match") or "—"
    pick = _format_dual_pick(m)
    jc_play = row.get("竞彩玩法") or ""
    pick_cell = _e(pick)
    if jc_play and jc_play not in ("—", "胜平负"):
        pick_cell = f"{pick_cell}<br><span class='meta'>{_e(jc_play)}</span>"
    elif jc_play == "胜平负":
        pick_cell = f"{pick_cell}<br><span class='meta'>竞彩 SP</span>"
    scores = row.get("推荐比分") or "、".join(m.get("likely_scores_detail") or [])
    ah = row.get("亚盘") or m.get("asian_handicap_cn") or "—"
    conf = row.get("置信度") or m.get("confidence_cn") or "—"
    tier_cn = m.get("buy_tier_cn") or row.get("购买档位") or "—"
    n_pts = (indexes.get(fid) or {}).get("point_count", 0)
    phase = m.get("match_phase") or "upcoming"
    phase_tag = ""
    if phase == "live":
        score = (m.get("live_score") or "").strip()
        minute = (m.get("live_status_label") or "").strip()
        if score and minute and minute != "进行中":
            live_txt = f"进行中 {score} · {minute}"
        elif score:
            live_txt = f"进行中 {score}"
        elif minute and minute != "进行中":
            live_txt = f"进行中 · {minute}"
        else:
            live_txt = "进行中"
        phase_tag = f' <span class="tag tag-live">{_e(live_txt)}</span>'
    alert_tag = _alert_tags_html(m, row)
    tier_tag = _tier_badge_html(m, row)
    acc_tag = _accuracy_badge_html(m, row)
    sp_val = row.get("竞彩SP") or m.get("accuracy_jingcai_sp") or ""
    sweet = m.get("sweet_spot") or (
        m.get("accuracy_pick") or {}
    ).get("sweet_spot")
    grade = m.get("accuracy_grade") or (m.get("accuracy_pick") or {}).get("accuracy_grade") or ""
    sweet_flag = "1" if sweet else "0"
    match_day = _kickoff_date(m, kickoff_map) or ""
    detail = f'<a href="/match/{_e(fid)}">趋势 ({n_pts})</a>' if fid else "—"
    ai_btn = (
        f'<button type="button" class="btn btn-sm btn-ai" '
        f'onclick="aiRecommend(\'{_e(fid)}\', this)">AI推荐</button>'
        if fid else "—"
    )
    cb = (
        f'<input type="checkbox" class="parlay-cb" data-fid="{_e(fid)}" '
        f'data-tier="{_e(m.get("buy_tier") or "")}" '
        f'data-sweet="{sweet_flag}" '
        f'data-match-date="{_e(match_day)}" '
        f'data-acc-grade="{_e(grade)}" '
        f'data-name="{_e(name)}" onchange="toggleParlayPick(this)" title="勾选：2串1 / 批量推荐图">'
        if fid else "—"
    )
    sp_cell = _e(sp_val) if sp_val else "—"
    return (
        f"<tr class='dash-row' data-sweet='{sweet_flag}' "
        f"data-acc-grade='{_e(grade)}' data-tier='{_e(m.get('buy_tier') or '')}'>"
        f"<td class='parlay-pick'>{cb}</td>"
        f"<td><a href=\"/match/{_e(fid)}\">{_e(name)}</a>{phase_tag}{tier_tag}{acc_tag}{alert_tag}</td>"
        f"<td>{_e(tier_cn)}</td>"
        f"<td>{pick_cell}<br><span class='meta'>SP {sp_cell}</span></td><td>{_e(scores)}</td>"
        f"<td>{_e(ah)}</td><td>{_e(conf)}</td><td>{detail}</td>"
        f"<td>{ai_btn}</td></tr>\n"
    )


def _dashboard_finished_row(m: dict, indexes: dict) -> str:
    settled = m.get("settled") or {}
    fid = str(m.get("fixture_id") or settled.get("external_id") or "")
    row = m.get("predict_row") or m
    name = row.get("比赛") or m.get("match") or settled.get("match_name") or "—"
    if not settled:
        pick = _format_dual_pick(m) if row else "—"
        n_pts = (indexes.get(fid) or {}).get("point_count", 0)
        detail = f'<a href="/match/{_e(fid)}">复盘 ({n_pts})</a>' if fid else "—"
        return (
            f"<tr><td><a href=\"/match/{_e(fid)}\">{_e(name)}</a></td>"
            f"<td colspan='2'><span class='meta'>待抓取赛果</span></td>"
            f"<td>{_e(pick)}</td><td class='meta'>—</td><td>{detail}</td></tr>\n"
        )
    score = settled.get("score_text") or "—"
    result_cn = settled.get("result_1x2_cn") or "—"
    pick = settled.get("pick_jingcai_cn") or _format_dual_pick(m) if m.get("predict_row") else "—"
    from recommendation_review import _compare_summary

    cmp_txt = _compare_summary(
        pick_cn=str(pick or ""),
        result_cn=str(result_cn),
        hit=settled.get("hit_1x2"),
    )
    cmp_cls = "cmp-ok" if settled.get("hit_1x2") is True else ("cmp-bad" if settled.get("hit_1x2") is False else "meta")
    closing = _closing_odds_txt(settled)
    hit_1x2 = _hit_badge(settled.get("hit_1x2"))
    hit_sc = _hit_badge(settled.get("hit_score"))
    n_pts = (indexes.get(fid) or {}).get("point_count", 0)
    detail = f'<a href="/match/{_e(fid)}">复盘 ({n_pts})</a>' if fid else "—"
    return (
        f"<tr><td><a href=\"/match/{_e(fid)}\">{_e(name)}</a></td>"
        f"<td><strong>{_e(score)}</strong> {_e(result_cn)}</td>"
        f"<td class='{cmp_cls}'>{_e(cmp_txt)}</td>"
        f"<td class='meta'>{_e(closing)}</td>"
        f"<td>{_e(pick)}</td>"
        f"<td>{hit_1x2} 1X2 · {hit_sc} 比分</td>"
        f"<td>{detail} · <a href='/review'>复盘表</a></td></tr>\n"
    )


def html_dashboard(
    state: dict,
    latest: dict | None,
    *,
    output_root: Path,
    within_days: float | None = None,
    match_date: str | None = None,
) -> str:
    import config as app_cfg
    from ai_schedule import format_ai_interval
    from daily_picks import (
        filter_matches_by_day,
        list_available_match_days,
        load_dashboard_matches,
        load_kickoff_map,
        load_live_status_map,
        resolve_match_day,
    )
    from match_settlement import classify_matches, load_settled_map
    from match_timeline import list_match_indexes

    window = within_days if within_days is not None else app_cfg.SERVICE_WITHIN_DAYS
    matches = load_dashboard_matches(output_root, within_days=window)
    indexes = {x.get("fixture_id"): x for x in list_match_indexes(output_root)}
    settled_map = load_settled_map(output_root)
    kickoff_map = load_kickoff_map(within_days=window)
    live_status_map = load_live_status_map(within_days=window)
    upcoming, live, finished = classify_matches(
        matches, kickoff_map=kickoff_map, settled_map=settled_map,
        live_status_map=live_status_map,
    )
    all_active = upcoming + live
    available_days = list_available_match_days(all_active, kickoff_map)
    cycle_day = resolve_match_day(all_active, kickoff_map, match_date=match_date)
    sweet_day_matches = filter_matches_by_day(all_active, kickoff_map, cycle_day)

    all_active_enriched = [_enrich_dashboard_match(m) for m in all_active]
    sweet_day_enriched = [_enrich_dashboard_match(m) for m in sweet_day_matches]
    n_live = sum(1 for m in all_active_enriched if m.get("match_phase") == "live")
    n_upcoming = len(all_active_enriched) - n_live
    if n_live:
        active_title = f"未开赛 {n_upcoming} · 进行中 {n_live} · 共 {len(all_active)} 场"
    else:
        active_title = f"未开赛 / 进行中 · {len(all_active)} 场"

    active_rows = "".join(
        _dashboard_active_row(m, indexes, kickoff_map) for m in all_active_enriched
    )
    if not active_rows:
        active_rows = "<tr><td colspan='8'>暂无未开赛/进行中比赛</td></tr>"

    finished_rows = "".join(_dashboard_finished_row(m, indexes) for m in finished)
    if not finished_rows:
        finished_rows = "<tr><td colspan='7'>暂无已结算完场（开球 105 分钟后自动抓取赛果）</td></tr>"

    wc_teaser = _worldcup_teaser(output_root)
    div_teaser = _divergence_teaser(output_root)
    sweet_teaser = _sweet_spot_teaser(
        sweet_day_enriched, kickoff_map, match_date=cycle_day,
    )
    day_switcher = _match_day_switcher(available_days, cycle_day)

    import config as app_cfg
    from ai_schedule import format_ai_interval

    sweet_lo = getattr(app_cfg, "ACCURACY_SP_MIN", 1.30)
    sweet_hi = getattr(app_cfg, "ACCURACY_SP_MAX", 1.60)
    sweet_band_txt = f"{sweet_lo:g}–{sweet_hi:g}"

    lr = state.get("last_run") or {}
    run_status = "运行中" if state.get("running") else "空闲"
    if app_cfg.AI_AUTO_ENABLED:
        ai_schedule_txt = f"定时 AI 每 {format_ai_interval()}"
    else:
        ai_schedule_txt = "定时 AI 已关闭 · 请手动点「AI 推荐本场」"
    service_body = f"""
  <p>状态：<strong>{run_status}</strong>
     · 上次成功 <code>{_e(format_ts(state.get('last_success_at')))}</code>
     · 下次整点 <code>{_e(format_ts(state.get('next_scheduled_at')))}</code></p>
  <p>最近任务 <code>{_e(lr.get('run_id') or '—')}</code>
     · 下载 {lr.get('download_ok', 0)} · 分析 {lr.get('predict_ok', 0)}
     · AI {lr.get('ai_called', 0)} 次
     {'· 结算 ' + str(lr.get('settled_count', 0)) + ' 场' if lr.get('settled_count') else ''}</p>
  <p class="meta">{ai_schedule_txt} · 仅 <strong>24h 内</strong>开赛 · poll 窗口 {window:g} 天</p>
  <p class="meta" id="db-line">数据库：加载中…</p>
  <p class="meta">
    <button type="button" class="btn btn-sm" style="background:#059669" data-label="抓取完赛赛果"
      onclick="manualSettle(this)">抓取完赛赛果</button>
    <button type="button" class="btn btn-sm" onclick="manualSettle(this, {{resettle:true}})">重算赛果</button>
    <span id="settle-line">赛果：加载中…</span>
  </p>
  <script>
  fetch('/api/db/status').then(r=>r.json()).then(d=>{{
    const el = document.getElementById('db-line');
    if (!d.ok) {{ el.textContent = '数据库：未连接'; return; }}
    const s = d.stats || {{}};
    el.textContent = `数据库：${{s.fixtures||0}} 场 · ${{s.ticks||0}} tick · ${{s.last_tick_at||'—'}}`;
  }}).catch(()=>{{ document.getElementById('db-line').textContent='数据库：未连接'; }});
  fetch('/api/settle').then(r=>r.json()).then(d=>{{
    const el = document.getElementById('settle-line');
    if (!el) return;
    if (!d.ok) {{ el.textContent = d.error || '赛果：不可用'; return; }}
    el.textContent = `待结算 ${{d.pending_count||0}} 场 · 已结算 ${{d.settled_count||0}} 场`;
  }}).catch(()=>{{ const el=document.getElementById('settle-line'); if(el) el.textContent='赛果：加载失败'; }});
  </script>"""

    finished_fold = _fold(
        f"已完场（{len(finished)} 场）",
        f"""<p class="meta">开球约 105 分钟后抓取赛果 · <a href="/review"><strong>推荐复盘表</strong></a> 对照全部完场</p>
<table>
<tr><th>比赛</th><th>赛果</th><th>对照</th><th>终盘</th><th>预测</th><th>命中</th><th>详情</th></tr>
{finished_rows}
</table>""",
        open=len(finished) <= 4 and len(finished) > 0,
        muted=True,
    )

    dash_css = _shared_css(
        ".pred-card { border-left: 4px solid #7c3aed; }"
        ".parlay-toolbar { display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-bottom:12px; }"
        ".parlay-result { display:none; margin-top:16px; border-left:4px solid #2563eb; }"
        ".parlay-pick { text-align:center; width:36px; }"
        ".parlay-cb { width:16px; height:16px; cursor:pointer; }"
        ".verdict-ok { color:#059669; } .verdict-warn { color:#d97706; } .verdict-bad { color:#dc2626; }"
        ".parlay-warns { margin:8px 0 0; padding-left:20px; color:#92400e; font-size:13px; }"
        ".parlay-ai-brief { margin-top:10px; padding:10px; background:#f0f9ff; border-radius:6px; }"
        ".parlay-explain-box { margin-top:12px; padding:12px; background:#f8fafc; border-radius:8px; border:1px solid #e2e8f0; }"
        ".parlay-explain-box h4 { margin:0 0 8px; font-size:14px; color:#334155; }"
        ".parlay-explain { font-size:14px; line-height:1.6; color:#334155; margin:0 0 8px; }"
        ".parlay-reasons { margin:0 0 8px; padding-left:20px; font-size:13px; color:#475569; line-height:1.5; }"
        ".parlay-stake { margin:8px 0 0; font-weight:700; color:#1d4ed8; font-size:14px; }"
        ".leg-reason-text { font-size:13px; color:#64748b; margin:4px 0 0; line-height:1.5; }"
        ".parlay-actions { margin-top:12px; }"
        ".parlay-option { border:1px solid #e2e8f0; border-radius:10px; padding:12px; margin:12px 0; background:#fff; }"
        ".cmp-ok { color: #047857; font-weight: 700; }"
        ".cmp-bad { color: #b91c1c; font-weight: 700; }"
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<meta http-equiv="refresh" content="120"/>
<title>盘口分析服务</title>
<style>
{dash_css}
</style>
<script>{_AI_BTN_JS}{_AI_CHAT_JS}{_DASH_FILTER_JS}{_PARLAY_JS}</script>
</head><body>
<h1>⚽ 盘口分析</h1>
<nav class="page-nav meta" style="margin-bottom:14px">
  <a href="/daily">📋 当日 2串1</a> · <a href="/worldcup">🏆 开盘套路</a>
  · <a href="/worldcup/groups">⚔️ 小组战意</a>
  · <a href="/handicap">📊 亚盘赢盘</a>
  · <a href="/divergence">⚡ 欧亚分歧</a>
  · <a href="/quant">📈 量化回测</a>
  · <a href="/review"><strong>📋 推荐复盘</strong></a>
  · <a href="/settings/ai">🤖 AI 设置</a>
  · <a href="/kelly">🧮 Kelly</a>
  · 状态 <strong>{run_status}</strong>
</nav>
<button class="btn" style="margin-bottom:14px" onclick="fetch('/api/run',{{method:'POST'}}).then(r=>r.json()).then(d=>showToast(d.message||d.error||'已触发', !d.ok))">立即执行一次</button>
<a class="btn" href="/review" style="margin-bottom:14px;background:#ca8a04">📋 推荐复盘</a>
{div_teaser}
{day_switcher}
{sweet_teaser}
{wc_teaser}
{_ai_chat_card(scope="dashboard")}
<div class="card">
  <h2>{_e(active_title)}</h2>
  <div class="parlay-toolbar">
    <span class="meta">已选 <strong id="parlay-count">0 场 · 串关需 2</strong></span>
    <button type="button" class="btn btn-sm" style="background:#dc2626" id="poster-batch-btn" disabled
            onclick="openSelectedPosters()">📷 批量推荐图</button>
    <button type="button" class="btn btn-sm" id="parlay-analyze-btn" disabled
            onclick="analyzeParlay(false)">2串1 分析</button>
    <button type="button" class="btn btn-sm btn-ai" id="parlay-ai-btn" disabled
            onclick="analyzeParlay(true)">AI 简评（可选）</button>
    <select id="list-parlay-provider" class="ai-chat-provider" data-ai-provider-role="parlay">
      <option value="deepseek">加载中…</option>
    </select>
    <button type="button" class="btn btn-sm btn-ai" id="list-parlay-ai-btn"
            onclick="analyzeListParlayAi()">AI自动选2串1</button>
    <span class="meta">勾选后可「批量推荐图」（每场一张 PNG，可跨天）；2串1 须恰好选 2 场且同一比赛日</span>
  </div>
  <div class="card parlay-result" id="parlay-result"></div>
  <p class="meta" style="margin-bottom:8px">
    <label><input type="checkbox" id="dash-filter-sweet" onchange="onDashFilter(this)"> 仅 SP {_e(sweet_band_txt)} 甜区</label>
    &nbsp;·&nbsp;
    <label><input type="checkbox" id="dash-filter-solid" onchange="onDashSolidFilter(this)"> 仅稳胆 / 稳胆甜区</label>
  </p>
  <table class="dashboard-table">
    <tr><th title="勾选场次">选</th><th>比赛</th><th>档位</th><th>竞彩推荐</th><th>比分</th><th>亚盘</th><th>置信</th><th>详情</th><th>AI</th></tr>
    {active_rows}
  </table>
</div>
<div class="fold-stack">
{finished_fold}
{_fold("服务状态 · 任务日志", service_body, muted=True)}
</div>
</body></html>"""


def _daily_source_line(payload: dict) -> str:
    if payload.get("source") == "ai":
        prov = payload.get("ai_provider") or "AI"
        return f'<span class="tag tag-active">{_e(prov)} 每小时精选</span>'
    return "规则引擎"


def _tier_card(tier: dict | None, *, css_class: str) -> str:
    if not tier:
        return f"""
<div class="card tier-card {css_class} tier-empty">
  <h3>暂无合适组合</h3>
  <p class="meta">当日没有满足该档条件的 2串1，或模型均为观望。</p>
</div>"""

    legs = tier.get("legs") or []
    # backward compat: old single-match payload
    if not legs and tier.get("fixture_id"):
        legs = [tier]

    parlay_type = tier.get("parlay_type") or "2串1"
    combined = tier.get("combined_odds") or tier.get("eu_odds")
    combined_txt = f" · 组合赔率约 {combined}" if combined else ""

    leg_html = ""
    for i, leg in enumerate(legs, 1):
        fid = leg.get("fixture_id") or ""
        eu = leg.get("eu_odds")
        eu_txt = f" · 欧赔 {eu}" if eu else ""
        leg_html += f"""
  <div class="leg-block">
    <p class="match-line">
      <span class="leg-num">{i}</span>
      <a href="/match/{_e(fid)}"><strong>{_e(leg.get('match'))}</strong></a>
      <span class="tag">{_e(leg.get('kickoff'))}</span>
    </p>
    <p class="pick-line">
      <strong class="pick">{_e(leg.get('pick_cn'))}</strong>
      · 比分 {_e(leg.get('scores'))}
      · 亚盘 {_e(leg.get('asian_handicap_cn'))}
      · 置信 {_e(leg.get('confidence_cn'))}{eu_txt}
    </p>
    <p class="meta">{_e(leg.get('model_note'))}</p>
  </div>"""

    summary = tier.get("reason") or ""
    reason_html = ""
    if summary:
        reason_html = _fold("选场理由", f'<p class="reason">{_e(summary)}</p>', muted=True)

    return f"""
<div class="card tier-card {css_class}">
  <h3>{_e(tier.get('tier_label'))} · {parlay_type}
    <span class="tier-score">评分 {_e(tier.get('score'))}{combined_txt}</span></h3>
  {leg_html}
  {reason_html}
</div>"""


def _fallback_safe_card(tier: dict | None, *, target: str) -> str:
    if not tier:
        return ""
    card = _tier_card(tier, css_class="tier-floor")
    share = (
        f'<p><a class="btn btn-share" href="/share/daily-safe?date={quote(target)}">'
        '📷 保存保底 2串1 成图</a></p>'
    )
    note = (
        '<p class="meta floor-note">保底候选：只在同日可售竞彩中选“相对最稳”的两场，'
        '用于观望较多时参考，仍建议小仓位。</p>'
    )
    return f'<section class="floor-section"><h2>🛟 最保底 2串1</h2>{note}{share}{card}</section>'


def html_daily_picks(payload: dict) -> str:
    target = payload.get("date") or ""
    dates = payload.get("available_dates") or []
    date_links = ""
    for d in dates:
        cls = "tag tag-active" if d == target else "tag"
        date_links += f'<a class="{cls}" href="/daily?date={quote(d)}">{_e(d)}</a> '

    tiers = payload.get("tiers") or {}
    safe = _tier_card(tiers.get("safe"), css_class="tier-safe")
    balanced = _tier_card(tiers.get("balanced"), css_class="tier-balanced")
    upset = _tier_card(tiers.get("upset"), css_class="tier-upset")
    fallback_safe = _fallback_safe_card(payload.get("fallback_safe"), target=target)

    msg = payload.get("message") or ""
    ai_err = payload.get("ai_error") or ""
    if ai_err and not msg:
        msg = f"AI 推荐失败：{ai_err}"
    msg_html = f'<p class="meta">{_e(msg)}</p>' if msg else ""
    policy_note = ""
    note = payload.get("pick_policy_note") or ""
    if note:
        policy_note = f'<p class="meta">{_e(note)}</p>'
    elif payload.get("pick_policy", "").startswith("胜平负优先"):
        rq = payload.get("rqsp_actionable_count") or 0
        el = payload.get("rqsp_eligible_count") or 0
        if rq and not el:
            policy_note = (
                f'<p class="meta">优先胜平负；{rq} 场仅让球未达极高置信门槛</p>'
            )
        elif el:
            policy_note = (
                f'<p class="meta">含 {el} 场极高置信让球候选'
                f'（另有 {rq - el} 场让球未入选）</p>'
            )

    ai_note = ""
    if payload.get("ai_run_at"):
        n = len(payload.get("ai_analyzed") or [])
        ai_note = f'<p class="meta">最近 AI 运行：{_e(format_ts(payload.get("ai_run_at")))} · 分析 {n} 场</p>'
    elif payload.get("source") == "ai":
        prov = payload.get("ai_provider") or "AI"
        ai_note = f'<p class="meta">由 {_e(prov)} 生成三档推荐</p>'

    tier_help = _fold(
        "档位说明",
        """<p><strong>稳健 2串1</strong>：较稳组合，多模型一致、赔率偏低。</p>
<p><strong>折中 2串1</strong>：收益与胜率平衡。</p>
<p><strong>博冷门 2串1</strong>：偏冷门高赔，小注为宜。</p>
<p class="meta">2串1 优先胜平负；仅让球场次需「高置信 + 多模型一致或正EV」才纳入候选。</p>
<p class="meta">也可点上方「AI 分析当日」手动触发；整点任务开启 AI 时自动更新。</p>""",
        muted=True,
    )

    daily_css = _shared_css("""
.tier-card { border-top: 4px solid #94a3b8; }
.tier-safe { border-top-color: #059669; }
.tier-balanced { border-top-color: #2563eb; }
.tier-upset { border-top-color: #dc2626; }
.tier-floor { border-top-color: #7c3aed; }
.floor-section { margin: 18px 0; }
.floor-section h2 { margin-bottom: 8px; }
.floor-note { background: #f5f3ff; border: 1px solid #ddd6fe; padding: 10px 12px; border-radius: 10px; }
.btn-share { background: #7c3aed; color: white; text-decoration: none; display: inline-block; }
.tier-empty { opacity: 0.85; }
.tier-score { font-size: 12px; color: #64748b; font-weight: normal; }
.pick { font-size: 1.2rem; color: #0f172a; }
.pick-line { margin: 8px 0; }
.leg-block { border-left: 3px solid #e2e8f0; padding-left: 12px; margin: 12px 0; }
.leg-num { display: inline-block; background: #334155; color: #fff; width: 22px; height: 22px;
            border-radius: 50%; text-align: center; line-height: 22px; font-size: 12px; margin-right: 8px; }
.reason { white-space: pre-wrap; line-height: 1.55; margin: 0; }
""")

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>当日推荐 · {_e(target)}</title>
<style>
{daily_css}
</style>
<script>
function showToast(msg, isErr) {{
  let t = document.getElementById('ai-toast');
  if (!t) {{ t = document.createElement('div'); t.id = 'ai-toast'; document.body.appendChild(t); }}
  t.className = 'toast' + (isErr ? ' toast-err' : '');
  t.textContent = msg;
  t.style.display = 'block';
  clearTimeout(window._toastTimer);
  window._toastTimer = setTimeout(() => {{ t.style.display = 'none'; }}, isErr ? 8000 : 4000);
}}
function runDailyAi(date) {{
  if (!confirm('对「' + date + '」全部场次运行 AI 分析，并生成三档 2串1？\\n逐场约 1–2 分钟，请稍候。')) return;
  const btn = document.getElementById('dailyAiBtn');
  if (btn) {{ btn.disabled = true; btn.textContent = 'AI 分析中…'; }}
  const t0 = Date.now();
  fetch('/api/daily/ai?date=' + encodeURIComponent(date), {{method:'POST'}})
    .then(r => r.json())
    .then(d => {{
      if (!d.ok) {{
        showToast(d.error || '启动失败', true);
        if (btn) {{ btn.disabled = false; btn.textContent = '✨ AI 分析当日'; }}
        return;
      }}
      showToast(d.message || '已启动');
      const poll = setInterval(() => {{
        fetch('/api/daily-picks?date=' + encodeURIComponent(date))
          .then(r => r.json())
          .then(p => {{
            if (p.source === 'ai' || p.ai_run_at) {{
              clearInterval(poll);
              showToast('AI 推荐已更新，正在刷新…');
              setTimeout(() => location.reload(), 800);
            }}
          }}).catch(() => {{}});
        if (Date.now() - t0 > 600000) {{
          clearInterval(poll);
          if (btn) {{ btn.disabled = false; btn.textContent = '✨ AI 分析当日'; }}
          showToast('耗时较长，请手动刷新页面查看', true);
        }}
      }}, 8000);
    }})
    .catch(e => {{
      showToast('请求失败: ' + e, true);
      if (btn) {{ btn.disabled = false; btn.textContent = '✨ AI 分析当日'; }}
    }});
}}
{_AI_CHAT_JS}
</script>
</head><body>
<p class="back page-nav"><a href="/">← 返回首页</a> · <a href="/worldcup">开盘套路</a> · <a href="/handicap">亚盘赢盘</a> · <a href="/quant">量化回测</a> · <a href="/kelly">Kelly</a></p>
<h1>📋 当日 2串1 · {_e(target)}</h1>
<p class="meta">{payload.get('match_count', 0)} 场 · 可推 {payload.get('actionable_count', 0)} 场
  · {_daily_source_line(payload)} · {_e(format_ts(payload.get('generated_at')))}
  · {_e(payload.get('pick_policy') or '胜平负优先')}</p>
{policy_note}
<p>{date_links or '<span class="meta">暂无日期</span>'}
  <button type="button" class="btn btn-ai" id="dailyAiBtn"
    onclick="runDailyAi('{_e(target)}')">✨ AI 分析当日</button></p>
{ai_note}
{msg_html}
{_ai_chat_card(scope="dashboard")}
<div class="grid">
  {safe}
  {balanced}
  {upset}
</div>
{fallback_safe}
{tier_help}
</body></html>"""


def _implied_card(implied: dict | None, *, prediction: dict | None = None) -> str:
    imp = implied or (prediction or {}).get("eu_implied")
    if not imp:
        return ""
    level = imp.get("anomaly_level") or "ok"
    warn_cls = " tag-warn" if imp.get("is_anomaly") else ""
    reason = imp.get("reason") or ""
    return f"""
<div class="card implied-card">
  <h3>欧赔隐含概率 <span class="tag{warn_cls}">{'异常' if imp.get('is_anomaly') else '正常'}</span></h3>
  <p class="meta">100÷赔率 得隐含胜率；<strong>原始三项之和</strong>通常 102%–110%（机构抽水），<strong>去水后=100%</strong></p>
  <table>
    <tr><th></th><th>原始隐含</th><th>去水概率</th></tr>
    <tr><td>主胜</td><td>{_e(imp.get('raw_home_pct'))}%</td><td>{_e(imp.get('fair_home_pct'))}%</td></tr>
    <tr><td>平局</td><td>{_e(imp.get('raw_draw_pct'))}%</td><td>{_e(imp.get('fair_draw_pct'))}%</td></tr>
    <tr><td>客胜</td><td>{_e(imp.get('raw_away_pct'))}%</td><td>{_e(imp.get('fair_away_pct'))}%</td></tr>
    <tr><td><strong>合计</strong></td><td><strong>{_e(imp.get('raw_sum_pct'))}%</strong></td><td>100%</td></tr>
  </table>
  <p class="meta">抽水 { _e(imp.get('overround_pct')) }pp · { _e(reason) }</p>
</div>"""


def _jingcai_card(jc: dict, prediction: dict | None = None) -> str:
    if not jc or (not jc.get("has_sp") and not jc.get("has_rqsp")):
        return """
<div class="card">
  <h3>竞彩 SP</h3>
  <p class="meta">暂无竞彩数据（下一轮 poll 会自动抓取，或该场未开售胜平负/让球玩法）</p>
</div>"""

    rec_html = ""
    if prediction:
        row = prediction.get("predict_row") or {}
        rec = row.get("竞彩推荐") or (prediction.get("jingcai_pick_info") or {}).get("jingcai_pick_display")
        if rec and rec not in ("—", ""):
            sp = row.get("竞彩SP") or (prediction.get("jingcai_pick_info") or {}).get("jingcai_sp")
            sp_txt = f" · SP {_e(sp)}" if sp else ""
            reason = (prediction.get("jingcai_pick_info") or {}).get("jingcai_reason") or ""
            rec_html = f"<p><strong>推荐购买：{_e(rec)}</strong>{sp_txt}</p>"
            if reason:
                rec_html += f"<p class='meta'>{_e(reason)}</p>"
            rq_rate = row.get("让球参考胜率")
            if rq_rate:
                rec_html += f"<p class='meta'>国外参考胜率：{_e(rq_rate)}</p>"
            match_ref = row.get("赛果参考")
            if match_ref:
                rec_html += f"<p class='meta'>赛果参考（非竞彩购买项）：{_e(match_ref)}</p>"
        elif not jc.get("has_sp") and jc.get("has_rqsp"):
            rec_html = (
                "<p class='meta'>本场仅开售让球胜平负；"
                "让球方向单独参考国外欧赔/相似样本胜率，与胜平负 SP 无关</p>"
            )

    num = _e(jc.get("match_num") or "—")
    hcap = jc.get("handicap_label") or jc.get("handicap") or "—"
    rows = ""
    if jc.get("has_sp"):
        rows += (
            f"<tr><td>胜平负</td>"
            f"<td>{_e(jc.get('sp_home'))}</td>"
            f"<td>{_e(jc.get('sp_draw'))}</td>"
            f"<td>{_e(jc.get('sp_away'))}</td></tr>"
        )
    if jc.get("has_rqsp"):
        label = f"让球({hcap})" if hcap != "—" else "让球胜平负"
        rows += (
            f"<tr><td>{label}</td>"
            f"<td>{_e(jc.get('rqsp_home'))}</td>"
            f"<td>{_e(jc.get('rqsp_draw'))}</td>"
            f"<td>{_e(jc.get('rqsp_away'))}</td></tr>"
        )
    return f"""
<div class="card">
  <h3>竞彩 SP <span class="tag">{num}</span></h3>
  <table>
    <tr><th>玩法</th><th>胜</th><th>平</th><th>负</th></tr>
    {rows}
  </table>
  <p class="meta">数据来源：500.com liveOddsList / 竞彩足球，每 5 分钟更新</p>
  {rec_html}
</div>"""


def _latest_jingcai(timeline: list) -> dict:
    for p in reversed(timeline):
        jc = (p.get("odds") or {}).get("jingcai")
        if jc and (jc.get("has_sp") or jc.get("has_rqsp")):
            return jc
    return {}


def _latest_betfair(timeline: list) -> dict:
    for p in reversed(timeline):
        bf = (p.get("odds") or {}).get("betfair")
        if bf and bf.get("has_data"):
            return bf
    return {}


def _fmt_vol(n) -> str:
    if n is None:
        return "—"
    try:
        v = int(n)
    except (TypeError, ValueError):
        return str(n)
    if v >= 1_000_000:
        return f"{v / 1_000_000:.2f}M"
    if v >= 10_000:
        return f"{v / 10_000:.1f}万"
    return f"{v:,}"


def _betfair_card(bf: dict) -> str:
    if not bf or not bf.get("has_data"):
        return """
<div class="card">
  <h3>必发指数 / 成交量</h3>
  <p class="meta">暂无必发数据（下一轮 poll 会自动抓取，或该场交易所无成交）</p>
</div>"""

    oc = bf.get("outcomes") or {}
    home = oc.get("home") or {}
    draw = oc.get("draw") or {}
    away = oc.get("away") or {}
    pct = bf.get("volume_pct") or {}

    rows = ""
    for key, o in (("home", home), ("draw", draw), ("away", away)):
        p = pct.get(key)
        rows += (
            f"<tr><td>{_e(o.get('label') or key)}</td>"
            f"<td>{_fmt_vol(o.get('volume'))}</td>"
            f"<td><strong>{_e(p)}%</strong></td>"
            f"<td>{_e(o.get('trade_price'))}</td>"
            f"<td>{_e(o.get('bf_index'))}</td>"
            f"<td>{_e(o.get('hot_cold'))}</td></tr>"
        )

    summary = bf.get("summary") or ""
    summary_p = f'<p class="meta">{_e(summary)}</p>' if summary else ""

    return f"""
<div class="card">
  <h3>必发指数 / 成交量</h3>
  <p class="meta">总成交 {_fmt_vol(bf.get('volume_total'))} · 数据来源 500.com 投注分析</p>
  <table>
    <tr><th>选项</th><th>成交量</th><th>占比</th><th>成交价</th><th>必发指数</th><th>冷热</th></tr>
    {rows}
  </table>
  {summary_p}
</div>"""


def _betfair_chart_data(timeline: list, bf: dict) -> dict:
    """Build datasets for volume line charts."""
    labels_poll = []
    vol_h, vol_d, vol_a = [], [], []
    for p in timeline:
        b = (p.get("odds") or {}).get("betfair") or {}
        if not b.get("has_data"):
            continue
        pct = b.get("volume_pct") or {}
        if pct.get("home") is None and pct.get("away") is None:
            continue
        labels_poll.append(chart_time_label(p.get("ts") or p.get("hour")))
        vol_h.append(pct.get("home"))
        vol_d.append(pct.get("draw"))
        vol_a.append(pct.get("away"))

    trend = (bf or {}).get("trend") or {}
    return {
        "poll_labels": labels_poll,
        "poll_home": vol_h,
        "poll_draw": vol_d,
        "poll_away": vol_a,
        "trend_labels": trend.get("labels") or [],
        "trend_home": trend.get("home_pct") or [],
        "trend_draw": trend.get("draw_pct") or [],
        "trend_away": trend.get("away_pct") or [],
    }


def _pred_card(pred: dict, *, title: str = "最新推荐") -> str:
    if not pred:
        return ""
    row = pred.get("predict_row") or pred
    src = pred.get("recommendation_source", "")
    if pred.get("ai_provider_label"):
        src_label = pred["ai_provider_label"]
    elif "ai" in src or pred.get("manual_ai"):
        src_label = "精算师"
    else:
        src_label = "规则"
    reasoning = pred.get("actuary_reasoning") or ""
    meta = (pred.get("summary") or "")[:500]
    if reasoning and reasoning not in meta:
        meta = f"{reasoning}\n{meta}" if meta else reasoning
    scores = "—"
    if _score_enabled():
        scores = row.get("推荐比分") or "、".join(pred.get("likely_scores_detail") or pred.get("likely_scores") or []) or "—"
    pick = final_recommendation_cn(pred)
    ref = pred.get("reference_result_1x2_cn") or row.get("赛果预测") or pred.get("match_result_1x2_cn") or ""
    jc_play = row.get("竞彩玩法") or ""
    jc_sp = row.get("竞彩SP")
    sp_txt = f" · SP {jc_sp}" if jc_sp else ""
    ref_line = ""
    if ref and ref not in (pick, "—", ""):
        ref_line = f"<p class='meta'><strong>参考研判：</strong>{_e(ref)} <span class='meta'>(欧亚盘口)</span></p>"
    buy_line = f"<p class='meta'><strong>竞彩可购：</strong>{_e(pick)}{sp_txt}"
    if jc_play and jc_play != "—":
        buy_line += f" · {_e(jc_play)}"
    buy_line += "</p>"
    div = pred.get("jingcai_divergence") or {}
    div_line = f"<p class='meta warn'>{_e(div.get('note') or '')}</p>" if div.get("divergence") else ""
    meta_block = _fold("分析逻辑", f"<p class='meta'>{_e(meta)}</p>", muted=True) if meta else ""
    market_summary = pred.get("market_pattern_summary") or ""
    market_names = pred.get("market_pattern_names") or []
    market_lines = ""
    if market_summary:
        market_lines += f"<p class='meta'><strong>欧亚转换：</strong>{_e(market_summary)}</p>"
    if market_names:
        market_lines += f"<p class='meta'><strong>识别套路：</strong>{_e('、'.join(str(x) for x in market_names))}</p>"
    market_block = _fold("欧亚转换 / 盘赔对照", market_lines, muted=True) if market_lines else ""
    alert_tags = pred.get("alert_tags") or []
    alert_html = "".join(f' <span class="tag tag-qual-div">{_e(t)}</span>' for t in alert_tags)
    tier_tag = _tier_badge_html(pred, row)
    tier_reason = pred.get("buy_tier_reason") or row.get("档位说明") or ""
    tier_line = ""
    if tier_tag:
        tier_line = f"<p class='meta'><strong>购买档位：</strong>{tier_tag}"
        if tier_reason:
            tier_line += f" <span class='meta'>{_e(tier_reason)}</span>"
        tier_line += "</p>"
    odds_w = pred.get("odds_blend_summary") or pred.get("pattern_reference_cn") or ""
    odds_line = f"<p class='meta'><strong>权重：</strong>{_e(odds_w)}</p>" if odds_w else ""
    return f"""
<div class="card pred-card">
  <h3>{_e(title)} <span class="tag">{_e(src_label)}</span>{alert_html}</h3>
  <p><strong class="pick">{_e(pick)}</strong>{sp_txt}
     {f"<span class='tag'>{_e(jc_play)}</span>" if jc_play and jc_play != "—" else ""}</p>
  {ref_line}
  {tier_line}
  {buy_line}
  {div_line}
  {f"<p>比分 {_e(scores)} · 亚盘 {_e(row.get('亚盘') or pred.get('asian_handicap_cn'))} · 置信 {_e(row.get('置信度') or pred.get('confidence_cn'))}</p>" if _score_enabled() else f"<p>亚盘 {_e(row.get('亚盘') or pred.get('asian_handicap_cn'))} · 置信 {_e(row.get('置信度') or pred.get('confidence_cn'))}</p>"}
  {odds_line}
  {market_block}
  {meta_block}
</div>"""


def _build_pred_cards(prediction: dict | None) -> str:
    if not prediction:
        return ""
    analyses = prediction.get("ai_analyses") or {}
    if analyses:
        picks = {
            pid: _display_pick(p, row=p.get("predict_row") or {})
            for pid, p in analyses.items()
        }
        unique = {v for v in picks.values() if v}
        disagree = len(unique) > 1
        cards = ""
        if prediction.get("ai_disagreement"):
            n = len(analyses)
            tag = "多模型" if n > 2 else "双模型"
            cards += f'<p class="meta dual-hint">⚠️ {tag}分歧，综合为「观望」——请分别参考各模型卡片</p>'
        elif disagree:
            cards += '<p class="meta dual-hint">⚠️ 各模型结论不一致，请分别参考下方卡片</p>'
        for pid, p in analyses.items():
            label = p.get("ai_provider_label") or pid
            cards += _pred_card(p, title=f"{label} 推荐")
        return cards
    if prediction.get("final_pick_cn") or (prediction.get("predict_row") or {}).get("竞彩推荐"):
        return _pred_card(prediction)
    return ""


def _score_pills(scores: list[dict] | None) -> str:
    if not scores:
        return "<span class='meta'>暂无比分分布</span>"
    return " ".join(
        f"<span class='tag'>{_e(x.get('score'))} · {_e(x.get('pct'))}%</span>"
        for x in scores[:8]
    )


def _rate_pct(v) -> str:
    """Format 0–1 rate or already-percent value for display."""
    if v is None:
        return "—"
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    if 0 <= x <= 1:
        return f"{x * 100:.1f}%"
    return f"{x:.1f}%"


def _similar_ai_card_html(data: dict | None) -> str:
    if not data or not data.get("ok"):
        return ""
    ev_items = data.get("key_evidence") or []
    ev_html = ""
    if ev_items:
        ev_html = "<ul class='similar-ai-ev'>" + "".join(
            f"<li>{_e(x)}</li>" for x in ev_items[:6]
        ) + "</ul>"
    rel = data.get("sample_reliability")
    rel_html = f"<p class='meta'>{_e(rel)}</p>" if rel else ""
    vs = data.get("vs_baseline")
    vs_html = (
        f"<p class='meta'><strong>对比规则推荐</strong> {_e(vs)}</p>" if vs else ""
    )
    action = data.get("action")
    action_html = f"<p class='similar-ai-action'>{_e(action)}</p>" if action else ""
    return f"""
<div class="similar-ai-box">
  <div class="similar-ai-top">
    <strong>{_e(data.get('headline') or '相似盘口解读')}</strong>
    <span class="tag">{_e(data.get('confidence_cn') or '—')}</span>
  </div>
  <p class="similar-ai-pick">
    <strong>胜平负</strong> {_e(data.get('result_pick_cn') or '—')}
    · <strong>亚盘</strong> {_e(data.get('handicap_pick_cn') or '—')}
    · <strong>比分</strong> {_e(data.get('likely_scores') or '—')}
  </p>
  <p>{_e(data.get('summary') or '')}</p>
  {rel_html}
  {ev_html}
  <p class="meta"><strong>风险</strong> {_e(data.get('risk') or '—')}</p>
  {vs_html}
  {action_html}
</div>"""


def _similar_block(
    block: dict,
    *,
    fixture_id: str = "",
    ai_cache: dict | None = None,
) -> str:
    samples = block.get("samples") or []
    source = str(block.get("source") or "")
    ai_btn = ""
    ai_panel = ""
    if fixture_id and source and block.get("count"):
        cached = (ai_cache or {}).get(source)
        panel_body = _similar_ai_card_html(cached) if cached else ""
        ai_btn = (
            f'<button type="button" class="btn btn-sm btn-ai similar-ai-btn" '
            f'data-label="✨ AI盘口解读" '
            f'onclick="aiSimilarityAnalyze(\'{_e(fixture_id)}\', \'{_e(source)}\', this)">'
            f'✨ AI盘口解读</button>'
        )
        ai_panel = (
            f'<div id="sim-ai-{_e(fixture_id)}-{_e(source)}" class="similar-ai-out">'
            f'{panel_body}</div>'
        )
    if not block or not block.get("count"):
        return (
            f"<div class='card inner similar-block'><div class='similar-head'>"
            f"<h4>{_e(block.get('title') or '相似样本')}</h4>{ai_btn}</div>"
            f"<p class='meta'>暂无足够相似样本</p>{ai_panel}</div>"
        )
    rows = "".join(
        "<tr>"
        f"<td>{i}</td>"
        f"<td>{_e(s.get('date'))}</td>"
        f"<td>{_e(s.get('match'))}</td>"
        f"<td><strong>{_e(s.get('score'))}</strong></td>"
        f"<td>{_e(s.get('result_cn'))}</td>"
        f"<td>{_e(s.get('ah'))}</td>"
        f"<td>{_e(s.get('ah_water'))}</td>"
        f"<td>{_e(s.get('eu'))}</td>"
        f"<td>{_e(s.get('similarity'))}</td>"
        f"<td class='meta'>{_e(s.get('source'))}</td>"
        "</tr>"
        for i, s in enumerate(samples[:10], 1)
    )
    if not rows:
        rows = "<tr><td colspan='10'>暂无明细</td></tr>"
    avg = block.get("avg_total_goals")
    avg_txt = f" · 场均进球 {float(avg):.2f}" if avg is not None else ""
    ah_line = ""
    if block.get("ah_rate_text"):
        ah_line = f"<p><strong>赢盘率</strong> {_e(block.get('ah_rate_text'))}</p>"
        breakdown = []
        for label, key in (
            ("上盘全赢", "ah_home_full_win"),
            ("上盘半赢", "ah_home_half_win"),
            ("走水", "ah_home_push"),
            ("上盘半输", "ah_home_half_loss"),
            ("上盘全输", "ah_home_full_loss"),
        ):
            val = block.get(key)
            if val is not None:
                breakdown.append(f"{label} {_rate_pct(val)}")
        if breakdown:
            ah_line += f"<p class='meta'>分布：{' · '.join(breakdown)}</p>"
    return f"""
<div class="card inner similar-block">
  <div class="similar-head">
    <h4>{_e(block.get('title'))} <span class="tag">{_e(block.get('count'))} 场</span></h4>
    {ai_btn}
  </div>
  <p><strong>{_e(block.get('rate_text'))}</strong>{avg_txt}</p>
  {ah_line}
  <p class="meta">Top比分：{_score_pills(block.get('top_scores'))}</p>
  {ai_panel}
  <table>
    <tr><th>#</th><th>日期</th><th>比赛</th><th>比分</th><th>结果</th><th>亚盘</th><th>水位</th><th>欧赔</th><th>差值</th><th>来源</th></tr>
    {rows}
  </table>
</div>"""


def _build_similarity_html(
    prediction: dict | None,
    *,
    fixture_id: str = "",
    output_root: Path | None = None,
) -> str:
    sim = (prediction or {}).get("similarity_analysis") or {}
    if not sim:
        return ""
    ai_cache: dict = {}
    if fixture_id and output_root:
        try:
            from similarity_ai import load_cached_analyses

            ai_cache = load_cached_analyses(output_root, fixture_id)
        except Exception:
            ai_cache = {}
    kw = {"fixture_id": fixture_id, "ai_cache": ai_cache}
    open_blocks = "".join(_similar_block(b, **kw) for b in (sim.get("open") or []))
    live_blocks = "".join(_similar_block(b, **kw) for b in (sim.get("live") or []))
    note = "严格匹配无样本后已自动放宽条件" if sim.get("auto_relaxed") else "按当前容差选取距离最近样本"
    total = sim.get("history_total")
    total_txt = f" · 历史库 {total} 场" if total else ""
    return f"""
<p class="meta">展示当前比赛初盘、实时盘口分别匹配到的历史样本 Top10{total_txt} · 历史侧为终盘/收盘口径 · {note}</p>
<h4>初盘类似盘口</h4>
<div class="grid similar-grid">{open_blocks}</div>
<h4>实时盘口 vs 历史终盘</h4>
<div class="grid similar-grid">{live_blocks}</div>"""


def _build_ai_history_html(ai_records: list[dict] | None) -> str:
    if not ai_records:
        return ""
    rows = ""
    for rec in ai_records:
        ts = format_ts(rec.get("ts"))
        tag = "手动" if rec.get("manual_ai") else "定时"
        analyses = rec.get("analyses") or {}
        for pid, a in analyses.items():
            label = a.get("label") or pid
            reason = (a.get("actuary_reasoning") or "")[:200]
            pick_disp = _display_pick(a, row=a.get("predict_row") or {})
            rows += (
                f"<tr><td>{_e(ts)}</td><td><span class='tag'>{_e(tag)}</span></td>"
                f"<td>{_e(label)}</td>"
                f"<td><strong>{_e(pick_disp)}</strong></td>"
                f"<td>{_e(a.get('likely_scores'))}</td>"
                f"<td>{_e(a.get('asian_handicap_cn'))}</td>"
                f"<td>{_e(a.get('confidence_cn'))}</td>"
                f"<td class='meta'>{_e(reason)}</td></tr>\n"
            )
    return f"""
  <p class="meta">国内竞彩可购方向（胜平负 SP 或让球胜平负）。</p>
  <table>
    <tr><th>时间</th><th>来源</th><th>模型</th><th>竞彩推荐</th><th>比分</th><th>亚盘</th><th>置信</th><th>摘要</th></tr>
    {rows}
  </table>"""


def _score_outlook_html(outlook: dict | None) -> str:
    if not outlook or not isinstance(outlook, dict):
        return "—"
    parts = []
    for key, label in (
        ("primary", "最可能"),
        ("secondary", "备选"),
        ("upset_watch", "冷门关注"),
    ):
        items = outlook.get(key) or []
        if items:
            txt = "、".join(str(x) for x in items[:4])
            parts.append(f"{label} {txt}")
    return " · ".join(parts) if parts else "—"


def _deep_analysis_card(record: dict | None) -> str:
    if not record:
        return ""
    a = record.get("analysis") or {}
    if not a.get("headline"):
        return ""
    ts = format_ts(record.get("ts"))
    outlook = _score_outlook_html(a.get("score_outlook"))
    watch = a.get("pre_match_watchlist") or []
    watch_html = ""
    if watch:
        items = "".join(f"<li>{_e(w)}</li>" for w in watch[:4])
        watch_html = f"""<div class="deep-section"><h4>赛前关注</h4><ul class="deep-list">{items}</ul></div>"""
    risks = a.get("key_risks") or []
    risk_html = ""
    if risks:
        items = "".join(f"<li>{_e(r)}</li>" for r in risks[:3])
        risk_html = f"""<div class="deep-section"><h4>关键风险</h4><ul class="deep-list">{items}</ul></div>"""
    layers = a.get("analysis_layers") or []
    layers_fold = ""
    if layers:
        body = "".join(f"<p class='meta' style='margin:4px 0'>{_e(x)}</p>" for x in layers[:8])
        layers_fold = _fold("推理层次", body, muted=True)
    synthesis = a.get("model_synthesis") or ""
    synthesis_block = ""
    if synthesis:
        synthesis_block = f"""<div class="deep-section"><h4>模型综合</h4><p class="meta">{_e(synthesis)}</p></div>"""
    return f"""
<div class="card deep-card">
  <h3>🔍 AI 深度研判 <span class="tag">{_e(ts)}</span></h3>
  <p class="deep-headline">{_e(a.get('headline'))}</p>
  <p><strong class="pick">{_e(a.get('final_pick'))}</strong>
     · 置信 {_e(a.get('confidence_level'))}
     · {_e(a.get('stake_advice') or '')}</p>
  <p class="meta">{_e(a.get('final_pick_reason') or '')}</p>
  <p>比分 outlook · {_e(outlook)}</p>
  {synthesis_block}
  {_fold('深度结论', f"<p class='meta'>{_e(a.get('deep_verdict') or '')}</p>", open=True)}
  <div class="deep-section"><h4>翻车场景</h4><p class="meta">{_e(a.get('contrarian_case') or '—')}</p></div>
  <div class="deep-section"><h4>亚盘</h4><p class="meta">{_e(a.get('handicap_deep') or '—')}</p></div>
  <div class="deep-section"><h4>大小球</h4><p class="meta">{_e(a.get('over_under_deep') or '—')}</p></div>
  {watch_html}
  {risk_html}
  {layers_fold}
</div>"""


def _build_deep_history_html(deep_records: list[dict] | None) -> str:
    if not deep_records or len(deep_records) <= 1:
        return ""
    rows = ""
    for rec in deep_records[1:]:
        a = rec.get("analysis") or {}
        rows += (
            f"<tr><td>{_e(format_ts(rec.get('ts')))}</td>"
            f"<td><strong>{_e(a.get('headline'))}</strong></td>"
            f"<td>{_e(a.get('final_pick'))}</td>"
            f"<td>{_e(a.get('confidence_level'))}</td>"
            f"<td>{_e(a.get('stake_advice'))}</td></tr>\n"
        )
    return f"""
  <table>
    <tr><th>时间</th><th>结论</th><th>推荐</th><th>置信</th><th>仓位</th></tr>
    {rows}
  </table>"""


def _pct(v) -> str:
    if v is None:
        return "—"
    return f"{v}%"


def _worldcup_teaser(output_root: Path) -> str:
    """One-line WC opening conclusion on dashboard."""
    import json
    path = output_root / "worldcup" / "ledger.json"
    if not path.is_file():
        return ""
    try:
        ledger = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ""
    pat = ledger.get("opening_patterns") or {}
    acc = ledger.get("accuracy") or {}
    conc = pat.get("conclusions") or {}
    headline = conc.get("headline") or pat.get("summary") or ""
    n = pat.get("sample_size") or 0
    purchase = acc.get("purchase_jingcai") or {}
    if not headline and not n and not purchase.get("judged"):
        return ""
    action = (conc.get("actionable") or [None])[0] or ""
    extra = f"<p class='meta' style='margin:8px 0 0'>{_e(action)}</p>" if action else ""
    tier_line = ""
    if purchase.get("judged"):
        bits = []
        for key, label in (("tier_a", "可串"), ("tier_b", "可单关"), ("tier_c", "仅参考")):
            t = purchase.get(key) or {}
            if t.get("total"):
                bits.append(f"{label} {t.get('hit', 0)}/{t.get('total')} ({_pct(t.get('rate_pct'))})")
        tier_bits = " · ".join(bits)
        tier_line = (
            f"<p class='meta' style='margin:8px 0 0'>"
            f"竞彩购买 {_e(str(purchase.get('hit', 0)))}/{_e(str(purchase.get('judged', 0)))} "
            f"({_pct(purchase.get('rate_pct'))})"
            f"{(' · ' + _e(tier_bits)) if tier_bits else ''}"
            f" · <a href='/review'>复盘详情</a></p>"
        )
    headline_line = f"<p style='margin:6px 0 0;font-size:15px'>{_e(headline)}</p>" if headline else ""
    return f"""
<div class="card" style="border-left:4px solid #2563eb">
  <p style="margin:0"><a href="/worldcup"><strong>🏆 开盘套路</strong></a>
  · <a href="/worldcup/groups"><strong>⚔️ 小组战意</strong></a>
  · <a href="/review"><strong>📋 推荐复盘</strong></a>
  · <a href="/handicap"><strong>📊 亚盘赢盘</strong></a>
  · <a href="/quant"><strong>📈 量化回测</strong></a>
  · <a href="/kelly"><strong>🧮 Kelly</strong></a>
     <span class="meta"> · {n} 场完赛</span></p>
  {headline_line}
  {tier_line}
  {extra}
</div>"""


def _stat_grid(items: list[tuple[str, str]]) -> str:
    cells = "".join(
        f'<div class="stat"><div class="stat-val">{_e(v)}</div><div class="stat-lbl">{_e(k)}</div></div>'
        for k, v in items
    )
    return f'<div class="stat-grid">{cells}</div>'


def _fmt_ledger_triplet(a, b, c) -> str:
    if a is None and b is None and c is None:
        return "—"
    return f"{a or '—'}/{b or '—'}/{c or '—'}"


def _fmt_ledger_ah(odds: dict) -> str:
    if not odds:
        return "—"
    line = odds.get("ah_line")
    hw = odds.get("ah_home_water")
    aw = odds.get("ah_away_water")
    if line is None and hw is None and aw is None:
        return "—"
    return f"{line if line is not None else '—'} · {hw if hw is not None else '—'}/{aw if aw is not None else '—'}"


def _ledger_record_row_compact(r: dict) -> str:
    fid = r.get("fixture_id") or ""
    name = r.get("match_name") or fid
    score = r.get("score_text") or "—"
    result = r.get("result_1x2_cn") or "—"
    takeaway = r.get("takeaway") or "—"
    grp = r.get("group")
    grp_tag = f'<span class="chip chip-grp">{_e(grp)}组</span>' if grp else ""
    pick = r.get("pick_jingcai_cn")
    pick_bit = ""
    if pick and pick not in ("—", "观望", ""):
        hit = _hit_badge(r.get("hit_1x2"))
        tier_cn = r.get("buy_tier_cn") or ""
        tier_bit = f' <span class="tag tag-buy-{"tier-a" if tier_cn == "可串" else "tier-b" if tier_cn == "可单关" else "tier-c"}">{_e(tier_cn)}</span>' if tier_cn and tier_cn != "未分级" else ""
        pick_bit = f'<span class="meta">预测 {_e(pick)} {hit}{tier_bit}</span>'
    link = f'<a href="/match/{_e(fid)}">详情</a>' if fid else ""
    op = r.get("opening_odds") or {}
    cl = r.get("closing_odds") or {}
    open_eu = _fmt_ledger_triplet(op.get("eu_home"), op.get("eu_draw"), op.get("eu_away"))
    close_eu = _fmt_ledger_triplet(cl.get("eu_home"), cl.get("eu_draw"), cl.get("eu_away"))
    open_ah = _fmt_ledger_ah(op)
    close_ah = _fmt_ledger_ah(cl)
    pred_score = r.get("recommended_scores") or "—"
    conf = r.get("confidence_cn") or "—"
    ah_pick = r.get("asian_handicap_cn") or "—"
    fav = r.get("opening_favorite_cn") or "—"
    return (
        f'<div class="match-row">'
        f'<div class="match-left">'
        f'<div class="match-main"><strong>{_e(name)}</strong> {grp_tag}'
        f'<span class="score">{_e(score)}</span> {_e(result)}</div>'
        f'<div class="match-take">{_e(takeaway)} {pick_bit}</div>'
        f'<div class="match-link">{link}</div></div>'
        f'<div class="match-side">'
        f'<div><span class="side-label">预测</span><strong>{_e(pick or "—")}</strong> · 置信 {_e(conf)} · 比分 {_e(pred_score)}</div>'
        f'<div><span class="side-label">亚盘</span>初 {_e(open_ah)} → 终 {_e(close_ah)} · 推荐 {_e(ah_pick)}</div>'
        f'<div><span class="side-label">欧赔</span>初 {_e(open_eu)} → 终 {_e(close_eu)} · 初盘热门 {_e(fav)}</div>'
        f'</div></div>\n'
    )


def _conclusion_card_html(card: dict) -> str:
    tone = card.get("tone") or "neutral"
    return f"""
<div class="conc-card tone-{tone}">
  <div class="conc-head">
    <span class="conc-title">{_e(card.get('title'))}</span>
    <span class="conc-verdict">{_e(card.get('verdict'))}</span>
  </div>
  <p class="conc-liner">{_e(card.get('one_liner'))}</p>
  <p class="conc-advice">{_e(card.get('advice'))}</p>
</div>"""


def _pattern_block(patterns: dict) -> str:
    conc = patterns.get("conclusions") or {}
    sample = patterns.get("sample_size", 0)
    headline = conc.get("headline") or patterns.get("summary") or "完场后自动归纳开盘套路"
    conf = conc.get("confidence") or "low"
    conf_note = conc.get("confidence_note") or ""
    conf_labels = {"low": "观察期", "medium": "参考期", "high": "较可靠"}
    actions = conc.get("actionable") or []
    cards = conc.get("cards") or []

    action_html = "".join(f"<li>{_e(x)}</li>" for x in actions)
    cards_html = "".join(_conclusion_card_html(c) for c in cards)

    if not cards_html and sample == 0:
        cards_html = '<p class="meta empty-hint">暂无完场样本，小组赛推进后将自动生成结论卡片。</p>'

    return f"""
<div class="hero-card">
  <div class="hero-top">
    <h2 class="hero-headline">{_e(headline)}</h2>
    <span class="conf-badge conf-{conf}">{conf_labels.get(conf, conf)} · {sample} 场</span>
  </div>
  <p class="conf-note">{_e(conf_note)}</p>
</div>

<div class="card">
  <h3>投注参考</h3>
  <ul class="action-list">{action_html or '<li class="meta">样本积累中…</li>'}</ul>
</div>

<div class="card">
  <h3>开盘套路判断</h3>
  <div class="conc-grid">{cards_html}</div>
</div>"""


def _upcoming_watch_html(watch: dict | None) -> str:
    if not watch:
        return ""
    matches = watch.get("matches") or []
    notes = "".join(f"<li>{_e(x)}</li>" for x in (watch.get("notes") or []))
    if not matches:
        rows = "<p class='meta'>未来24小时暂无可分析比赛</p>"
    else:
        rows = ""
        for m in matches:
            lvl = m.get("level") or "neutral"
            pats = "、".join(str(x) for x in (m.get("pattern_names") or [])) or m.get("consistency_cn") or "—"
            reason = m.get("conversion_summary") or "—"
            if m.get("routine_notes"):
                reason += "；" + "；".join(str(x) for x in m.get("routine_notes")[:2])
            sim = m.get("similar_open") or m.get("similar_live") or "—"
            group_chip = ""
            if m.get("group"):
                label = f"{m.get('group')}组"
                if m.get("group_archetype"):
                    label += f" · {m.get('group_archetype')}"
                group_chip = f'<span class="chip chip-grp">{_e(label)}</span>'
            strategy_hint = m.get("group_strategy_hint") or ""
            state = m.get("group_state_context") or {}
            motivation_notes = state.get("motivation_notes") or []
            motivation_hint = motivation_notes[0] if state.get("played_matches") and motivation_notes else ""
            secondary = state.get("secondary_signals") or {}
            secondary_hint = ""
            collusion = secondary.get("collusion_watch") or {}
            if collusion.get("hint"):
                secondary_hint = collusion["hint"]
            elif secondary.get("opponent_picking_notes"):
                secondary_hint = secondary["opponent_picking_notes"][0]
            elif secondary.get("notes"):
                secondary_hint = secondary["notes"][0]
            ctx_items = []
            if strategy_hint:
                ctx_items.append(("结构", strategy_hint))
            if motivation_hint:
                ctx_items.append(("战意", motivation_hint))
            if secondary_hint:
                ctx_items.append(("次要", secondary_hint))
            ctx_html = ""
            if ctx_items:
                ctx_li = "".join(
                    f'<li><span class="watch-ctx-label">{_e(label)}</span>{_e(text[:100])}</li>'
                    for label, text in ctx_items
                )
                ctx_html = f"""
<details class="watch-fold">
  <summary>小组背景 · {len(ctx_items)} 条</summary>
  <ul class="watch-ctx-list">{ctx_li}</ul>
</details>"""
            rows += f"""
<div class="watch-item watch-{_e(lvl)}" id="watch-card-{_e(m.get('fixture_id'))}">
  <div class="watch-item-head">
    <div class="watch-head-main">
      <div class="watch-time">{_e(m.get('kickoff'))}</div>
      <div class="watch-title-row">
        <a class="watch-match" href="/match/{_e(m.get('fixture_id'))}">{_e(m.get('match'))}</a>
        {group_chip}
      </div>
    </div>
    <span class="watch-badge watch-badge-{_e(lvl)}">{_e(m.get('level_cn'))}</span>
  </div>
  <div class="watch-pick-strip">
    <span class="watch-pick-main">{_e(m.get('pick'))}</span>
    <span class="watch-pick-meta">置信 {_e(m.get('confidence'))}</span>
    <span class="watch-pattern">{_e(pats)}</span>
  </div>
  <p class="watch-reason">{_e(reason[:120])}{'…' if len(reason) > 120 else ''}</p>
  {ctx_html}
  <div class="watch-stats">
    <div class="watch-stat">
      <div class="watch-stat-label">亚盘</div>
      <div class="watch-stat-line">初 {_e(m.get('open_ah'))}</div>
      <div class="watch-stat-line sub">实 {_e(m.get('live_ah'))}</div>
    </div>
    <div class="watch-stat watch-stat-wide">
      <div class="watch-stat-label">历史相似</div>
      <div class="watch-stat-line small">{_e(sim[:120])}{'…' if len(sim) > 120 else ''}</div>
    </div>
  </div>
  <div class="watch-foot">
    <button type="button" class="btn btn-sm btn-ai" onclick="analyzeWorldcupMatch('{_e(m.get('fixture_id'))}', this)">AI分析本场</button>
    <div class="match-ai-result" id="match-ai-{_e(m.get('fixture_id'))}"></div>
  </div>
</div>"""
    return f"""
<div class="hero-card upcoming-watch">
  <div class="hero-top">
    <h2 class="hero-headline">{_e(watch.get('headline') or '未来24小时开盘套路观察')}</h2>
    <span class="conf-badge conf-medium">赛前 · {watch.get('count', 0)} 场</span>
  </div>
  <p class="conf-note">基于当前抓取盘口、初盘→实时盘变化、欧亚互转与历史相似样本，本地汇总生成，不调用 AI。</p>
</div>
<div class="card">
  <h3>未来24小时投注参考</h3>
  <ul class="action-list">{notes}</ul>
</div>
<div class="card watch-card">
  <h3>未来24小时重点场次</h3>
  <div class="watch-grid">{rows}</div>
</div>"""


def _upcoming_ai_watch_html(ai: dict | None) -> str:
    if not ai:
        return ""
    if ai.get("ok") is False:
        return f"""
<div class="card ai-watch-card">
  <h3>AI 盘路总结 <span class="tag">每小时缓存</span></h3>
  <p class="meta">暂不可用：{_e(ai.get('error') or 'AI总结失败')}</p>
</div>"""
    group_notes = "".join(f"<li>{_e(x)}</li>" for x in (ai.get("group_notes") or [])[:4])
    betting_notes = "".join(f"<li>{_e(x)}</li>" for x in (ai.get("betting_notes") or [])[:5])
    match_cards = ""
    for m in (ai.get("match_notes") or [])[:8]:
        fid = m.get("fixture_id") or ""
        match = m.get("match") or fid
        match_cards += f"""
<div class="ai-match-note">
  <div class="ai-match-head">
    <a href="/match/{_e(fid)}"><strong>{_e(match)}</strong></a>
    <span class="tag">{_e(m.get('verdict') or '复核')}</span>
  </div>
  <p>{_e(m.get('action') or '')}</p>
  <p class="meta">{_e(m.get('reason') or '')}</p>
  <p class="meta"><strong>风险：</strong>{_e(m.get('risk') or '—')}</p>
</div>"""
    return f"""
<div class="card ai-watch-card">
  <h3>AI 盘路总结 <span class="tag">{_e(ai.get('ai_provider_label') or 'AI')}</span></h3>
  <p class="ai-headline">{_e(ai.get('headline') or '')}</p>
  <p class="meta">{_e(ai.get('overview') or '')}</p>
  <div class="ai-watch-cols">
    <div><h4>小组/强弱</h4><ul>{group_notes or '<li class="meta">—</li>'}</ul></div>
    <div><h4>投注风控</h4><ul>{betting_notes or '<li class="meta">—</li>'}</ul></div>
  </div>
  <div class="ai-match-grid">{match_cards}</div>
  <p class="meta">生成 {_e(ai.get('generated_at'))} · 每小时最多自动刷新一次</p>
</div>"""


def _ledger_details_block(records: list[dict], acc: dict, patterns: dict) -> str:
    """Collapsible raw data — hidden by default."""
    record_rows = "".join(_ledger_record_row_compact(r) for r in records)
    if not record_rows:
        record_rows = '<p class="meta">暂无完场记录</p>'

    pred_section = ""
    with_rec = acc.get("with_recommendation") or 0
    purchase = acc.get("purchase_jingcai") or {}
    if with_rec:
        stats = _stat_grid([
            ("有推荐", str(with_rec)),
            ("竞彩购买胜率", _pct(purchase.get("rate_pct") or acc.get("rate_1x2_pct"))),
            ("比分命中", _pct(acc.get("rate_score_pct"))),
        ])
        by_src = _source_table(acc.get("by_source") or {})
        by_tier = _buy_tier_table(acc.get("by_buy_tier") or {})
        pred_section = _fold(
            f"预测复盘（{with_rec} 场）",
            f"{stats}<h4>购买档位胜率</h4>{by_tier}<h4>按来源</h4>{by_src}",
            muted=True,
        )

    st = patterns.get("stats") or {}
    raw_bits = []
    for k, label in (
        ("favorite_hit_rate_pct", "热门打出率"),
        ("draw_rate_pct", "平局占比"),
        ("shallow_home_win_pct", "偏浅主胜率"),
        ("aligned_fav_hit_pct", "一致盘低赔打出率"),
    ):
        v = st.get(k)
        if v is not None:
            raw_bits.append(f"{label} {v}%")
    raw_line = " · ".join(raw_bits) if raw_bits else "统计随样本更新"

    return f"""
<div class="fold-stack">
{pred_section}
{_fold(f"完场一览（{len(records)} 场）", f'<div class="match-list">{record_rows}</div>', muted=True)}
{_fold("原始统计", f'<p class="meta">{_e(raw_line)}</p>', muted=True)}
</div>"""


def _source_table(by_source: dict) -> str:
    if not by_source:
        return "<p class='meta'>暂无分来源统计</p>"
    rows = ""
    for src, v in by_source.items():
        rows += (
            f"<tr><td>{_e(src)}</td><td>{v.get('total', 0)}</td>"
            f"<td>{v.get('hit', 0)}</td><td>{_pct(v.get('rate_pct'))}</td></tr>\n"
        )
    return f"""<table class="mini">
<tr><th>来源</th><th>场次</th><th>命中</th><th>命中率</th></tr>
{rows}</table>"""


def _buy_tier_table(by_tier: dict) -> str:
    if not by_tier:
        return "<p class='meta'>暂无分档位统计（需 poll 后带「购买档位」再 settle）</p>"
    rows = ""
    css = {"A": "tier-a", "B": "tier-b", "C": "tier-c", "unknown": "tier-c"}
    for tier, v in by_tier.items():
        label = v.get("label_cn") or tier
        cls = css.get(tier, "tier-c")
        rows += (
            f"<tr><td><span class='tag tag-buy-{cls}'>{_e(label)}</span></td>"
            f"<td>{v.get('total', 0)}</td><td>{v.get('hit', 0)}</td>"
            f"<td><strong>{_pct(v.get('rate_pct'))}</strong></td></tr>\n"
        )
    return f"""<table class="mini buy-tier-stats">
<tr><th>购买档位</th><th>场次</th><th>命中</th><th>胜率</th></tr>
{rows}</table>"""


def html_worldcup_ledger(ledger: dict) -> str:
    acc = ledger.get("accuracy") or {}
    purchase = acc.get("purchase_jingcai") or {}
    patterns = ledger.get("opening_patterns") or {}
    upcoming_watch = ledger.get("upcoming_opening_watch") or {}
    upcoming_ai = ledger.get("upcoming_ai_watch") or {}
    records = ledger.get("records") or []
    updated = ledger.get("updated_at") or now_beijing_str()

    upcoming_ai_html = _upcoming_ai_watch_html(upcoming_ai)
    upcoming_html = _upcoming_watch_html(upcoming_watch)
    pattern_html = _pattern_block(patterns)
    details_html = _ledger_details_block(records, acc, patterns)

    wc_css = _shared_css("""
.card, .hero-card { border-radius: 12px; padding: clamp(14px, 3vw, 20px) clamp(14px, 3vw, 24px); }
.hero-card { background: linear-gradient(135deg, #eff6ff 0%, #fff 60%); border: 1px solid #dbeafe; box-shadow: 0 1px 4px rgba(0,0,0,.06); margin-bottom: 16px; }
h2.hero-headline { margin: 0; font-size: clamp(1.05rem, 3.5vw, 1.25rem); line-height: 1.45; color: #0f172a; flex: 1; }
.hero-top { display: flex; flex-wrap: wrap; align-items: flex-start; gap: 12px; }
.conf-badge { font-size: 12px; font-weight: 600; padding: 6px 12px; border-radius: 20px; white-space: nowrap; }
.conf-low { background: #fef3c7; color: #92400e; }
.conf-medium { background: #dbeafe; color: #1e40af; }
.conf-high { background: #d1fae5; color: #065f46; }
.conf-note { margin: 10px 0 0; }
.action-list { margin: 0; padding-left: 20px; line-height: 1.75; font-size: 15px; }
.conc-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr)); gap: 12px; }
.conc-card { border-radius: 10px; padding: 14px 16px; border: 1px solid #e2e8f0; }
.conc-card.tone-warn { border-color: #fecaca; background: #fffbeb; }
.conc-card.tone-ok { border-color: #bbf7d0; background: #f0fdf4; }
.conc-card.tone-neutral { background: #f8fafc; }
.conc-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.conc-title { font-weight: 700; font-size: 14px; }
.conc-verdict { font-size: 12px; font-weight: 600; padding: 2px 10px; border-radius: 12px; background: rgba(0,0,0,.06); }
.tone-warn .conc-verdict { background: #fee2e2; color: #b91c1c; }
.tone-ok .conc-verdict { background: #dcfce7; color: #15803d; }
.conc-liner { margin: 0 0 6px; font-size: 14px; line-height: 1.5; }
.conc-advice { margin: 0; font-size: 13px; color: #475569; }
.match-list { display: flex; flex-direction: column; gap: 8px; }
.match-row { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.15fr); gap: 8px 18px; padding: 12px 0; border-bottom: 1px solid #f1f5f9; align-items:start; }
.match-left { min-width: 0; }
.match-take { font-size: 13px; color: #64748b; margin-top: 4px; }
.score { font-weight: 700; margin-left: 8px; }
.match-side { justify-self: end; text-align: right; font-size: 12px; color: #475569; line-height: 1.65; }
.side-label { display:inline-block; color:#64748b; margin-right:6px; font-weight:700; }
.match-link { margin-top: 4px; }
.chip-grp { display:inline-flex; align-items:center; background:#eff6ff; color:#1d4ed8; font-size:10px; font-weight:700; padding:2px 8px; border-radius:999px; border:1px solid #dbeafe; white-space:nowrap; }
.toolbar { display: flex; gap: 10px; flex-wrap: wrap; }
table.mini { font-size: 13px; }
.watch-grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 300px), 1fr)); gap:14px; align-items:stretch; }
.watch-item { display:flex; flex-direction:column; gap:10px; border:1px solid #e2e8f0; border-radius:14px; padding:14px 14px 12px; background:#fff; box-shadow:0 1px 2px rgba(15,23,42,.04); }
.watch-item.watch-warn { border-color:#fdba74; background:linear-gradient(180deg,#fff7ed 0%,#fff 36%); }
.watch-item-head { display:flex; align-items:flex-start; justify-content:space-between; gap:10px; }
.watch-head-main { min-width:0; flex:1; }
.watch-title-row { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.watch-time { font-size:11px; color:#64748b; letter-spacing:.02em; margin-bottom:4px; }
.watch-match { font-size:16px; font-weight:800; color:#1d4ed8; line-height:1.25; text-decoration:none; }
.watch-match:hover { text-decoration:underline; }
.watch-pick-strip { display:flex; align-items:center; gap:8px; flex-wrap:wrap; padding:8px 10px; background:#f8fafc; border-radius:10px; border:1px solid #eef2f7; }
.watch-pick-main { font-size:15px; font-weight:800; color:#0f172a; }
.watch-pick-meta { font-size:12px; color:#64748b; }
.watch-pattern { background:#e0f2fe; color:#0369a1; border-radius:999px; padding:2px 9px; font-size:11px; font-weight:700; }
.watch-reason { margin:0; color:#475569; font-size:12px; line-height:1.55; min-height:2.8em; }
.watch-fold { border:1px dashed #e2e8f0; border-radius:10px; padding:0 10px; background:#fcfdff; }
.watch-fold summary { cursor:pointer; font-size:12px; font-weight:700; color:#64748b; padding:8px 0; list-style:none; }
.watch-fold summary::-webkit-details-marker { display:none; }
.watch-fold[open] summary { color:#334155; border-bottom:1px solid #eef2f7; margin-bottom:6px; }
.watch-ctx-list { margin:0 0 8px; padding:0; list-style:none; }
.watch-ctx-list li { font-size:11px; line-height:1.5; color:#64748b; padding:4px 0; border-top:1px solid #f1f5f9; }
.watch-ctx-list li:first-child { border-top:none; }
.watch-ctx-label { display:inline-block; min-width:2.2em; margin-right:6px; padding:1px 6px; border-radius:999px; background:#eef2ff; color:#4338ca; font-weight:700; font-size:10px; }
.watch-stats { display:grid; grid-template-columns: minmax(110px,.75fr) 1.25fr; gap:8px; }
.watch-stat { background:#f8fafc; border:1px solid #eef2f7; border-radius:10px; padding:8px 10px; min-width:0; }
.watch-stat-wide { grid-column:auto; }
.watch-stat-label { font-size:10px; font-weight:800; color:#64748b; text-transform:uppercase; letter-spacing:.04em; margin-bottom:4px; }
.watch-stat-line { font-size:12px; color:#334155; line-height:1.45; word-break:break-word; }
.watch-stat-line.sub { color:#64748b; margin-top:2px; }
.watch-stat-line.small { font-size:11px; color:#475569; }
.watch-foot { margin-top:auto; display:flex; flex-direction:column; gap:8px; }
.match-ai-result { width:100%; }
.match-ai-box { border:1px solid #c4b5fd; border-left:4px solid #7c3aed; background:#faf5ff; border-radius:12px; padding:10px 12px; }
.match-ai-top { display:flex; align-items:flex-start; justify-content:space-between; gap:8px; margin-bottom:6px; }
.match-ai-title { font-size:14px; line-height:1.35; color:#4c1d95; }
.match-ai-action { font-size:13px; font-weight:700; color:#1e293b; margin-bottom:8px; line-height:1.45; }
.match-ai-grid { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:6px; }
.match-ai-cell { background:rgba(255,255,255,.72); border-radius:8px; padding:7px 8px; min-width:0; }
.match-ai-cell .lbl { display:block; font-size:10px; font-weight:800; color:#7c3aed; margin-bottom:3px; letter-spacing:.03em; }
.match-ai-cell p { margin:0; font-size:11px; line-height:1.45; color:#475569; }
.match-ai-points { margin:0; padding-left:16px; color:#475569; line-height:1.45; font-size:11px; }
.match-ai-foot { display:flex; justify-content:space-between; gap:8px; flex-wrap:wrap; margin-top:6px; padding-top:6px; border-top:1px solid #ede9fe; font-size:10px; color:#64748b; }
.match-ai-stake { font-weight:700; color:#6d28d9; }
.watch-badge { font-size: 11px; font-weight: 800; padding: 4px 9px; border-radius: 999px; white-space: nowrap; flex-shrink:0; }
.watch-badge-warn { background: #fee2e2; color: #be123c; }
.watch-badge-ok { background: #dcfce7; color: #15803d; }
.watch-badge-neutral { background: #e0f2fe; color: #0369a1; }
.ai-watch-card { border-left:4px solid #7c3aed; }
.ai-headline { font-size:17px; font-weight:700; color:#4c1d95; margin:4px 0 8px; }
.ai-watch-cols { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin:12px 0; }
.ai-watch-cols ul { margin:4px 0 0; padding-left:18px; line-height:1.6; }
.ai-match-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; margin-top:12px; }
.ai-match-note { background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; padding:10px; }
.ai-match-head { display:flex; justify-content:space-between; gap:8px; align-items:center; }
.ai-match-note p { margin:6px 0 0; line-height:1.5; }
.export-hero { margin-bottom: 14px; }
.export-hero h1 { margin: 0 0 6px; font-size: 1.45rem; }
.export-footer { margin-top: 16px; padding-top: 10px; border-top: 1px dashed #cbd5e1; text-align: center; font-size: 11px; color: #64748b; }
#worldcup-export-root { background: #f8fafc; padding: 4px 0 8px; }
""")

    export_fname = f"worldcup-ledger-{updated[:10].replace('-', '')}"
    export_script = long_image_export_script(root_id="worldcup-export-root", filename=export_fname)

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<meta http-equiv="refresh" content="180"/>
<title>世界杯 · 开盘套路总结</title>
<style>
{wc_css}
</style>
{export_script}
<script>{_AI_BTN_JS}</script>
<script>
function refreshLedger() {{
  fetch('/api/worldcup/refresh', {{method:'POST'}})
    .then(r=>r.json())
    .then(d=>{{ if(d.ok) location.reload(); else alert(d.error||'刷新失败'); }})
    .catch(e=>alert(e));
}}
function escHtmlLocal(s) {{
  const d = document.createElement('div');
  d.textContent = s == null ? '' : String(s);
  return d.innerHTML;
}}
function analyzeWorldcupMatch(fid, btn) {{
  const out = document.getElementById('match-ai-' + fid);
  if (btn) {{ btn.disabled = true; btn.textContent = 'AI分析中…'; }}
  if (out) out.innerHTML = '<p class="meta">AI 正在综合本届赛果、小组强弱和盘口套路…</p>';
  fetch('/api/worldcup/match-ai', {{
    method:'POST',
    headers: {{'Content-Type':'application/json'}},
    body: JSON.stringify({{fixture_id: fid, force: true}})
  }})
    .then(r=>r.json())
    .then(d=>{{
      if (btn) {{ btn.disabled = false; btn.textContent = 'AI分析本场'; }}
      if (!out) return;
      if (!d.ok) {{
        out.innerHTML = '<p class="meta">AI分析失败：' + escHtmlLocal(d.error || '未知错误') + '</p>';
        return;
      }}
      const points = (d.watch_points || []).map(x => '<li>' + escHtmlLocal(x) + '</li>').join('');
      out.innerHTML = '<div class="match-ai-box">'
        + '<div class="match-ai-top"><strong class="match-ai-title">' + escHtmlLocal(d.headline || d.match || 'AI分析') + '</strong>'
        + '<span class="tag">' + escHtmlLocal(d.verdict || '复核') + '</span></div>'
        + '<div class="match-ai-action">' + escHtmlLocal(d.action || '') + '</div>'
        + '<div class="match-ai-grid">'
        + '<div class="match-ai-cell"><span class="lbl">理由</span><p>' + escHtmlLocal(d.reason || '—') + '</p></div>'
        + '<div class="match-ai-cell"><span class="lbl">风险</span><p>' + escHtmlLocal(d.risk || '—') + '</p></div>'
        + '</div>'
        + (points ? '<ul class="match-ai-points">' + points + '</ul>' : '')
        + '<div class="match-ai-foot">'
        + '<span class="match-ai-stake">' + escHtmlLocal(d.stake_advice || '') + '</span>'
        + '<span>' + escHtmlLocal(d.generated_at || '') + ' · ' + escHtmlLocal(d.ai_provider_label || 'AI') + '</span>'
        + '</div></div>';
    }})
    .catch(e=>{{
      if (btn) {{ btn.disabled = false; btn.textContent = 'AI分析本场'; }}
      if (out) out.innerHTML = '<p class="meta">请求失败：' + escHtmlLocal(e) + '</p>';
    }});
}}
</script>
</head><body>
<p class="back page-nav"><a href="/">← 返回首页</a> · <a href="/daily">当日推荐</a> · <a href="/handicap">亚盘赢盘</a> · <a href="/quant">量化回测</a> · <a href="/kelly">Kelly</a></p>

<div class="card toolbar">
  <button class="btn" onclick="refreshLedger()">刷新</button>
  <button class="btn" style="background:#059669" data-label="抓取赛果"
    onclick="manualSettle(this)">抓取赛果</button>
  <button class="btn" style="background:#7c3aed" onclick="savePageLongImage(this)">📷 保存长图</button>
</div>
<p class="meta">长图会展开折叠内容并打包当前页面主要模块；单场/2串1 仍可用详情页「保存成图」。</p>

<div id="worldcup-export-root">
  <div class="export-hero">
    <h1>🏆 本届世界杯 · 开盘套路</h1>
    <p class="meta">结论由完场赛果 + 初/终盘自动归纳 · 更新 {_e(updated)}</p>
    <p><a class="btn" href="/worldcup/groups">⚔️ 小组战意 · 默契球/拼命球</a></p>
  </div>

{upcoming_html}

{upcoming_ai_html}

{pattern_html}

<div class="card">
  <h3>竞彩购买胜率 · 三档</h3>
  <p class="meta">按结算时「购买档位」统计竞彩可购方向的 1X2 命中（非模型内参胜平负）</p>
  {_buy_tier_table(acc.get("by_buy_tier") or {})}
  <p class="meta">整体 {_e(str(purchase.get('hit', acc.get('hit_1x2') or 0)))}/{_e(str(purchase.get('judged', acc.get('judged_1x2') or 0)))} · {_pct(purchase.get('rate_pct') or acc.get('rate_1x2_pct'))}</p>
</div>

{details_html}

  <p class="export-footer">公益体彩 量力而行 · 仅供参考 不构成投注建议 · {_e(updated)}</p>
</div>
</body></html>"""


def _ah_pattern_table(rows: list[dict], *, title: str) -> str:
    if not rows:
        return f"<p class='meta'>{_e(title)}：暂无足够样本</p>"
    body = ""
    for r in rows:
        push = f" · 走水 {_pct(r.get('push_pct'))}" if r.get("push_pct") is not None else ""
        body += (
            f"<tr><td>{_e(r.get('label'))}</td>"
            f"<td>{r.get('count', 0)}</td>"
            f"<td>{_pct(r.get('upper_win_pct'))}</td>"
            f"<td>{_pct(r.get('lower_win_pct'))}</td>"
            f"<td class='meta'>{push.lstrip(' · ')}</td></tr>\n"
        )
    return f"""
<h4>{_e(title)}</h4>
<table class="mini">
  <tr><th>分组</th><th>场次</th><th>上盘赢</th><th>下盘赢</th><th>备注</th></tr>
  {body}
</table>"""


def _ah_record_row(r: dict) -> str:
    fid = r.get("fixture_id") or ""
    link = f'<a href="/match/{_e(fid)}">{_e(r.get("match_name") or fid)}</a>' if fid else _e(r.get("match_name"))
    pick = r.get("asian_handicap_cn") or r.get("pick_ah_cn") or "—"
    hit = _hit_badge(r.get("hit_ah"))
    line = _closing_odds_txt({
        "closing_ah_line": (r.get("closing_odds") or {}).get("ah_line") or r.get("closing_ah_line"),
    })
    return f"""
<div class="match-row">
  <div class="match-left">
    <div>{link} <span class="score">{_e(r.get('score_text'))}</span></div>
    <div class="match-take">{_e(r.get('result_1x2_cn'))} · 终盘 {_e(line)}</div>
  </div>
  <div class="match-side">
    <div><span class="side-label">推荐</span>{_e(pick)} {hit}</div>
    <div class="meta">{_e(r.get('asian_handicap_reason') or r.get('takeaway') or '')[:80]}</div>
  </div>
</div>"""


def html_ah_analytics(ledger: dict) -> str:
    acc = ledger.get("accuracy") or {}
    patterns = ledger.get("patterns") or {}
    records = ledger.get("records") or []
    updated = ledger.get("updated_at") or now_beijing_str()

    stats = _stat_grid([
        ("完场样本", str(acc.get("total_settled") or len(records))),
        ("有亚盘推荐", str(acc.get("with_ah_pick") or 0)),
        ("推荐赢盘率", _pct(acc.get("rate_ah_pct"))),
        ("净收益", str(acc.get("net_units") if acc.get("net_units") is not None else "—")),
    ])
    side_table = _source_table({
        {"home": "上盘", "away": "下盘"}.get(k, k): v
        for k, v in (acc.get("by_side") or {}).items()
    })
    conf_table = _source_table(acc.get("by_confidence") or {})

    pattern_html = (
        _ah_pattern_table(patterns.get("by_line_bucket") or [], title="按终盘盘口区间")
        + _ah_pattern_table(patterns.get("by_line_move") or [], title="按初→终盘变动")
        + _ah_pattern_table(patterns.get("by_consistency") or [], title="按欧亚一致性")
    )

    with_pick = [r for r in records if r.get("asian_handicap_pick") in ("home", "away")]
    pick_rows = "".join(_ah_record_row(r) for r in reversed(with_pick[-40:]))
    if not pick_rows:
        pick_rows = '<p class="meta">暂无带亚盘推荐的完场记录；有推荐且完场后会自动纳入回测。</p>'

    ah_css = _shared_css("""
.hero-card { background: linear-gradient(135deg, #f5f3ff 0%, #fff 60%); border: 1px solid #ddd6fe; }
.match-list { display: flex; flex-direction: column; gap: 8px; }
.match-row { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 8px 16px;
             padding: 12px 0; border-bottom: 1px solid #f1f5f9; }
.match-take { font-size: 13px; color: #64748b; margin-top: 4px; }
.score { font-weight: 700; margin-left: 8px; }
.side-label { display:inline-block; color:#64748b; margin-right:6px; font-weight:700; }
""")

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>亚盘赢盘分析</title>
<style>
{ah_css}
</style>
</head><body>
<p class="back page-nav"><a href="/">← 返回首页</a> · <a href="/worldcup">开盘套路</a> · <a href="/daily">当日推荐</a> · <a href="/kelly">Kelly</a></p>

<div class="card hero-card">
  <h1>📊 亚盘赢盘分析</h1>
  <p class="meta">基于完场赛果 + 终盘盘口统计历史赢盘规律，并回测系统亚盘推荐 · 更新 {_e(updated)}</p>
  {stats}
</div>

<div class="card">
  <h2>推荐回测</h2>
  <p class="meta">判定 {acc.get('judged_ah', 0)} 场 · 命中 {acc.get('hit_ah', 0)} · 未中 {acc.get('miss_ah', 0)} · 走水 {acc.get('push_ah', 0)}</p>
  <h4>按上下盘方向</h4>
  {side_table}
  <h4>按置信度</h4>
  {conf_table}
</div>

<div class="card">
  <h2>历史赢盘规律（{patterns.get('sample_count', 0)} 场有终盘）</h2>
  <p class="meta">不依赖推荐，仅看同类盘口在历史上的上/下盘打出频率。</p>
  {pattern_html}
</div>

<div class="card">
  <h2>亚盘推荐复盘（最近 {min(len(with_pick), 40)} 场）</h2>
  <div class="match-list">{pick_rows}</div>
</div>

<p class="meta" style="margin-top:20px">公益体彩 量力而行 · 仅供参考 不构成投注建议</p>
</body></html>"""


def html_kelly_calculator(
    prefill: dict | None = None,
    *,
    initial_result: dict | None = None,
) -> str:
    pre = prefill or {}
    init = initial_result or {}
    pre_json = json.dumps(pre, ensure_ascii=False, default=_json_default)
    init_json = json.dumps(init, ensure_ascii=False, default=_json_default)

    match_hint = ""
    if pre.get("available"):
        probs = []
        if pre.get("historical_probability_pct") is not None:
            probs.append(f"历史 {pre['historical_probability_pct']}%")
        if pre.get("market_probability_pct") is not None:
            probs.append(f"市场 {pre['market_probability_pct']}%")
        prob_txt = " · ".join(probs) if probs else ""
        fid = pre.get("fixture_id") or ""
        link = f' · <a href="/match/{_e(fid)}">返回单场</a>' if fid else ""
        match_hint = (
            f'<div class="card prefill-card">'
            f'<strong>{_e(pre.get("match"))}</strong> · 推荐 {_e(pre.get("pick_cn"))}'
            f'{(" · " + _e(prob_txt)) if prob_txt else ""}'
            f'{link}</div>'
        )

    kelly_css = _shared_css("""
.kelly-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 300px), 1fr)); gap: 16px; }
.kelly-form label { display: block; font-size: 13px; color: #475569; margin: 10px 0 4px; }
.kelly-form input, .kelly-form select { width: 100%; max-width: 100%; padding: 8px 10px;
  border: 1px solid #cbd5e1; border-radius: 8px; font-size: 14px; }
.prefill-card { background: #eff6ff; border: 1px solid #bfdbfe; margin-bottom: 14px; }
.result-card { border-left: 4px solid #2563eb; }
.result-card.tone-negative { border-left-color: #dc2626; }
.result-card.tone-warn { border-left-color: #d97706; }
.result-card.tone-ok { border-left-color: #059669; }
.kelly-val { font-size: 1.6rem; font-weight: 700; margin: 4px 0; }
.kelly-sub { font-size: 13px; color: #64748b; }
.kelly-metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 120px), 1fr)); gap: 10px; margin-top: 12px; }
.metric { background: #f8fafc; border-radius: 8px; padding: 10px 12px; }
.metric .lbl { font-size: 11px; color: #64748b; }
.metric .num { font-size: 1.1rem; font-weight: 700; }
.formula { background: #f1f5f9; padding: 10px 12px; border-radius: 8px; font-family: ui-monospace, monospace;
  font-size: 13px; margin: 12px 0; }
.quick-btns { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; }
.quick-btns button { padding: 4px 10px; font-size: 12px; border: 1px solid #cbd5e1; background: #fff;
  border-radius: 6px; cursor: pointer; }
""")

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Kelly 仓位计算器</title>
<style>
{kelly_css}
</style>
</head><body>
<p class="back page-nav"><a href="/">← 返回首页</a> · <a href="/handicap">亚盘赢盘</a> · <a href="/quant">量化回测</a> · <a href="/daily">当日推荐</a> · <a href="/worldcup">开盘套路</a></p>

<h1>🧮 Kelly 仓位计算器</h1>
<p class="meta">根据胜率与赔率计算最优下注比例 · 公式 f* = (p×D − 1) / (D − 1)</p>

{match_hint}

<div class="kelly-grid">
  <div class="card kelly-form">
    <h2>输入参数</h2>
    <label>预估胜率 (%)</label>
    <input type="number" id="kProb" min="0.1" max="99.9" step="0.1" placeholder="例如 55"/>
    <div class="quick-btns" id="probQuick"></div>

    <label>赔率类型</label>
    <select id="kOddsType">
      <option value="decimal">欧赔（小数）</option>
      <option value="water">亚盘水位</option>
    </select>

    <label>赔率 / 水位</label>
    <input type="number" id="kOdds" min="0.01" step="0.01" placeholder="欧赔 2.05 或水位 0.95"/>

    <label>Kelly 分数（风控）</label>
    <select id="kFraction">
      <option value="1">全 Kelly（100%）</option>
      <option value="0.5" selected>半 Kelly（50%）</option>
      <option value="0.25">四分之一 Kelly（25%）</option>
    </select>

    <label>本金（可选，元）</label>
    <input type="number" id="kBankroll" min="0" step="100" placeholder="例如 10000"/>

    <p style="margin-top:14px">
      <button class="btn" type="button" onclick="calcKelly()">计算</button>
    </p>
    <p class="formula">f* = (p×D − 1) / (D − 1) · D = 1 + 水位（亚盘）</p>
  </div>

  <div class="card result-card" id="kResult">
    <h2>计算结果</h2>
    <p class="meta">填写左侧参数后自动计算</p>
  </div>
</div>

<div class="card" style="margin-top:16px">
  <h3>说明</h3>
  <ul class="meta" style="line-height:1.7">
    <li><strong>全 Kelly</strong>：理论最优比例，波动极大，长期易回撤。</li>
    <li><strong>半 Kelly / 四分之一 Kelly</strong>：实战常用，牺牲少量 EV 换稳定性。</li>
    <li>胜率可填：历史相似样本频率、修正概率，或你自己的判断。</li>
    <li>Kelly ≤ 0 表示无正 EV，不应下注；本工具上限默认 25% 本金。</li>
  </ul>
</div>

<p class="meta" style="margin-top:20px">公益体彩 量力而行 · 仅供参考 不构成投注建议</p>

<script>
const PREFILL = {pre_json};
const INITIAL = {init_json};

function esc(s) {{
  return String(s == null ? '' : s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}}

function decimalOdds(type, raw) {{
  const v = parseFloat(raw);
  if (!isFinite(v)) return null;
  if (type === 'water') return 1 + v;
  return v;
}}

function calcKellyLocal() {{
  const p = parseFloat(document.getElementById('kProb').value) / 100;
  const type = document.getElementById('kOddsType').value;
  const oddsRaw = document.getElementById('kOdds').value;
  const fraction = parseFloat(document.getElementById('kFraction').value);
  const bankrollRaw = document.getElementById('kBankroll').value;
  const bankroll = bankrollRaw ? parseFloat(bankrollRaw) : null;
  const D = decimalOdds(type, oddsRaw);

  if (!isFinite(p) || p <= 0 || p >= 1) return {{ ok: false, error: '胜率须在 0–100% 之间' }};
  if (!D || D <= 1) return {{ ok: false, error: '赔率无效' }};

  const b = D - 1;
  const fullKelly = (p * D - 1) / b;
  const implied = 1 / D;
  const edge = p - implied;
  const ev = p * D - 1;
  const frac = Math.max(0, Math.min(fraction, 1));
  const adjusted = fullKelly * frac;
  const maxPct = 0.25;
  const capped = adjusted > 0 ? Math.min(adjusted, maxPct) : adjusted;
  const stake = (bankroll && bankroll > 0 && capped > 0) ? Math.round(bankroll * capped * 100) / 100 : null;

  let verdict = '有正 EV';
  let tone = 'ok';
  if (fullKelly <= 0) {{ verdict = '无正 EV，不建议下注'; tone = 'negative'; }}
  else if (fullKelly < 0.02) {{ verdict = '边缘极薄，建议观望'; tone = 'warn'; }}
  else if (frac < 1) {{ verdict = '建议采用分数 Kelly 控风险'; }}

  return {{
    ok: true, probability_pct: p * 100, decimal_odds: D, implied_probability_pct: implied * 100,
    edge_pp: edge * 100, ev_pct: ev * 100, full_kelly_pct: fullKelly * 100,
    adjusted_kelly_pct: adjusted * 100, capped_kelly_pct: capped > 0 ? capped * 100 : 0,
    half_kelly_pct: fullKelly > 0 ? fullKelly * 50 : 0,
    quarter_kelly_pct: fullKelly > 0 ? fullKelly * 25 : 0,
    stake_amount: stake, verdict, tone, fraction: frac
  }};
}}

function renderResult(r) {{
  const box = document.getElementById('kResult');
  if (!r.ok) {{
    box.className = 'card result-card tone-negative';
    box.innerHTML = '<h2>计算结果</h2><p class="meta">' + esc(r.error) + '</p>';
    return;
  }}
  box.className = 'card result-card tone-' + (r.tone || 'ok');
  const stakeLine = r.stake_amount != null
    ? '<p class="kelly-val">建议下注 ' + esc(r.stake_amount) + ' 元</p>'
      + '<p class="kelly-sub">约 ' + esc(r.capped_kelly_pct.toFixed(2)) + '% 本金（上限 25%）</p>'
    : '<p class="kelly-sub">填写本金可换算建议金额</p>';
  box.innerHTML = `
    <h2>计算结果</h2>
    <p class="meta">${{esc(r.verdict)}}</p>
    <p class="kelly-val">${{esc(r.adjusted_kelly_pct.toFixed(2))}}%</p>
    <p class="kelly-sub">分数 Kelly（${{esc((r.fraction * 100).toFixed(0))}}%）· 全 Kelly ${{esc(r.full_kelly_pct.toFixed(2))}}%</p>
    ${{stakeLine}}
    <div class="kelly-metrics">
      <div class="metric"><div class="lbl">隐含胜率</div><div class="num">${{esc(r.implied_probability_pct.toFixed(1))}}%</div></div>
      <div class="metric"><div class="lbl">Edge</div><div class="num">${{esc(r.edge_pp.toFixed(2))}} pp</div></div>
      <div class="metric"><div class="lbl">EV / 单位</div><div class="num">${{esc(r.ev_pct.toFixed(2))}}%</div></div>
      <div class="metric"><div class="lbl">半 Kelly</div><div class="num">${{esc(r.half_kelly_pct.toFixed(2))}}%</div></div>
      <div class="metric"><div class="lbl">¼ Kelly</div><div class="num">${{esc(r.quarter_kelly_pct.toFixed(2))}}%</div></div>
      <div class="metric"><div class="lbl">欧赔 D</div><div class="num">${{esc(r.decimal_odds.toFixed(3))}}</div></div>
    </div>`;
}}

function calcKelly() {{
  renderResult(calcKellyLocal());
}}

function applyPrefill() {{
  if (!PREFILL || !PREFILL.available) return;
  if (PREFILL.probability_pct != null)
    document.getElementById('kProb').value = PREFILL.probability_pct;
  if (PREFILL.odds_type)
    document.getElementById('kOddsType').value = PREFILL.odds_type;
  if (PREFILL.odds_value != null)
    document.getElementById('kOdds').value = PREFILL.odds_value;

  const q = document.getElementById('probQuick');
  if (PREFILL.historical_probability_pct != null) {{
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = '历史 ' + PREFILL.historical_probability_pct + '%';
    b.onclick = () => {{ document.getElementById('kProb').value = PREFILL.historical_probability_pct; calcKelly(); }};
    q.appendChild(b);
  }}
  if (PREFILL.market_probability_pct != null) {{
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = '市场 ' + PREFILL.market_probability_pct + '%';
    b.onclick = () => {{ document.getElementById('kProb').value = PREFILL.market_probability_pct; calcKelly(); }};
    q.appendChild(b);
  }}
}}

['kProb','kOddsType','kOdds','kFraction','kBankroll'].forEach(id => {{
  document.getElementById(id).addEventListener('input', calcKelly);
  document.getElementById(id).addEventListener('change', calcKelly);
}});

applyPrefill();
if (INITIAL && INITIAL.ok) renderResult(INITIAL);
else calcKelly();
</script>
</body></html>"""


def _motivation_tag(match_type: str) -> str:
    cls = {
        "collusion_watch": "tag-warn",
        "must_win": "tag-miss",
        "draw_friendly": "tag-active",
        "open_race": "tag-active",
        "gd_race": "tag",
        "conservative_favorite": "tag-warn",
        "dead_rubber": "meta",
    }.get(match_type, "tag")
    return cls


def _group_standings_table(table: list[dict]) -> str:
    if not table:
        return "<p class='meta'>暂无积分</p>"
    rows = ""
    for r in table:
        rows += (
            f"<tr><td>{r.get('rank')}</td><td><strong>{_e(r.get('team'))}</strong></td>"
            f"<td>{r.get('played')}</td><td>{r.get('won')}/{r.get('drawn')}/{r.get('lost')}</td>"
            f"<td>{r.get('gf')}-{r.get('ga')}</td><td>{r.get('gd'):+d}</td>"
            f"<td><strong>{r.get('points')}</strong></td></tr>\n"
        )
    return f"""<table class="mini">
<tr><th>#</th><th>球队</th><th>赛</th><th>胜/平/负</th><th>进失</th><th>净</th><th>分</th></tr>
{rows}</table>"""


def _fixture_prediction_row(p: dict) -> str:
    fid = p.get("fixture_id") or ""
    name = p.get("match_name") or f"{p.get('home')}VS{p.get('away')}"
    link = f'<a href="/match/{_e(fid)}">{_e(name)}</a>' if fid else _e(name)
    mt = p.get("match_type") or "normal"
    tag_cls = _motivation_tag(mt)
    reasons = " · ".join(p.get("reasoning") or [])[:180]
    ah = p.get("ah_hint") or "—"
    return f"""
<div class="gs-fixture">
  <div class="gs-fix-head">
    {link}
    <span class="tag {tag_cls}">{_e(p.get('match_type_cn'))}</span>
    <span class="meta">R{p.get('round')} · {_e(p.get('kickoff'))}</span>
  </div>
  <p><strong>倾向</strong> {_e(p.get('likely_direction_cn'))} · 亚盘提示 {_e(ah)}</p>
  <p class="meta">{_e(reasons)}</p>
</div>"""


def html_group_stage(report: dict) -> str:
    if not report.get("ok"):
        err = report.get("error") or "无法拉取积分榜"
        return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>小组战意</title></head><body>
<p class="back page-nav"><a href="/">← 返回</a></p>
<p>加载失败：{_e(err)}</p></body></html>"""

    rs = report.get("round_summary") or {}
    cutoff = report.get("best_third_cutoff") or {}
    thirds = report.get("best_third_ranking") or []
    updated = report.get("updated_at") or now_beijing_str()

    third_rows = ""
    for t in thirds:
        zone = "✓" if t.get("in_best8_zone") else "—"
        third_rows += (
            f"<tr><td>{t.get('third_rank')}</td><td>{_e(t.get('group'))}组</td>"
            f"<td>{_e(t.get('team'))}</td><td>{t.get('points')}</td>"
            f"<td>{t.get('gd'):+d}</td><td>{t.get('gf')}</td><td>{zone}</td></tr>\n"
        )

    highlight_html = ""
    for label, key in (("默契球观察", "collusion_watch"), ("拼命球", "must_win")):
        items = (report.get("highlights") or {}).get(key) or []
        if not items:
            continue
        cards = "".join(_fixture_prediction_row(p) for p in items)
        highlight_html += f"<div class='card'><h3>{_e(label)} · {len(items)} 场</h3>{cards}</div>"

    groups_html = ""
    for g in report.get("groups") or []:
        upcoming = g.get("upcoming") or []
        pred_block = "".join(_fixture_prediction_row(p) for p in upcoming) or "<p class='meta'>暂无待赛</p>"
        groups_html += f"""
<div class="card gs-group-card">
  <h3>{g.get('group')} 组 <span class="meta">{_e(g.get('archetype') or '')}</span></h3>
  <p class="meta">{_e(g.get('strategy_hint') or '')}</p>
  {_group_standings_table(g.get('standings') or [])}
  <h4>待赛场次 · 战意预测</h4>
  {pred_block}
</div>"""

    type_counts = report.get("type_counts") or {}
    type_txt = " · ".join(f"{k} {v}场" for k, v in sorted(type_counts.items(), key=lambda x: -x[1]))

    gs_css = _shared_css("""
.gs-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 1fr)); gap: 14px; }
.gs-fixture { border-top: 1px solid #f1f5f9; padding: 10px 0; }
.gs-fix-head { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 4px; }
.gs-group-card h4 { margin: 14px 0 6px; font-size: 13px; color: #475569; }
.hero-gs { background: linear-gradient(135deg, #ecfdf5 0%, #fff 55%); border: 1px solid #bbf7d0; }
""")

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>世界杯小组战意 · 默契球/拼命球</title>
<style>{gs_css}</style>
</head><body>
<p class="back page-nav"><a href="/">← 返回首页</a> · <a href="/worldcup">开盘套路</a> · <a href="/handicap">亚盘赢盘</a> · <a href="/quant">量化回测</a> · <a href="/kelly">Kelly</a></p>

<div class="card hero-gs">
  <h1>⚔️ 小组战意分析 · 48队赛制</h1>
  <p class="meta">{_e(rs.get('stage_label'))} · 更新 {_e(updated)}</p>
  <p>{_e(report.get('advance_rule_cn') or '')}</p>
  <p class="meta">最佳8小组第三参考线：≥ <strong>{cutoff.get('points', '—')}</strong> 分 · 净胜球 ≥ <strong>{cutoff.get('gd', '—')}</strong></p>
  <p class="meta">待赛分类：{_e(type_txt or '—')}</p>
  <button class="btn" onclick="location.reload()">刷新积分榜</button>
</div>

<div class="card">
  <h2>12组第三名排名（争8席）</h2>
  <table class="mini">
    <tr><th>#</th><th>组</th><th>球队</th><th>分</th><th>净</th><th>进</th><th>晋级区</th></tr>
    {third_rows}
  </table>
</div>

{highlight_html}

<div class="gs-grid">
{groups_html}
</div>

<p class="meta" style="margin-top:20px">战意模型已接入规则引擎推荐与 AI 分析上下文 · 仅供参考</p>
<p><a class="btn" href="/worldcup/groups/final">📋 末轮出线形势文案（按小组 · 基于 AI）</a></p>
</body></html>"""


def _group_picker_chip(g: dict, *, checked: bool = False) -> str:
    group = g.get("group") or "?"
    m_n = g.get("match_count") or 0
    u_n = g.get("user_ai_match_count") or 0
    disabled = "" if m_n else " disabled"
    chk = " checked" if checked else ""
    meta = f"末轮{m_n}场 · 你已AI {u_n}场" if m_n else "暂无末轮"
    warn = ' <span class="tag tag-warn">待AI</span>' if m_n and u_n < m_n else ""
    ok = ' <span class="tag tag-acc-sweet">可生成</span>' if u_n else ""
    return (
        f'<label class="gfc-pick{" is-off" if not m_n else ""}">'
        f'<input type="checkbox" class="gfc-group-cb" value="{_e(group)}"{chk}{disabled}/> '
        f'<strong>{_e(group)}组</strong> <span class="meta">{meta}</span>{ok}{warn}</label>'
    )


def _group_scenario_form_rows(selected: list[dict]) -> str:
    rows = ""
    for g in selected:
        group = g.get("group") or "?"
        for m in g.get("matches") or []:
            if m.get("is_finished"):
                continue
            fid = m.get("fixture_id") or ""
            home = m.get("home") or ""
            away = m.get("away") or ""
            name = m.get("match_name") or f"{home}VS{away}"
            ai_pick = m.get("jingcai_pick") if m.get("jingcai_pick") not in ("—", "", "观望", "暂无竞彩") else "—"
            locked = m.get("user_locked") or {}
            if locked.get("locked"):
                rows += f"""
<div class="gsc-match gsc-locked" data-fixture-id="{_e(fid)}" data-group="{_e(group)}"
  data-home="{_e(home)}" data-away="{_e(away)}" data-locked="1">
  <div class="gsc-match-hd">
    <strong>{_e(group)}组</strong> · {_e(name)}
    <span class="tag tag-acc-sweet">已定稿 {_e(locked.get('pick_cn') or '—')}</span>
    <span class="meta">{_e(locked.get('locked_at') or '')}</span>
  </div>
  <p class="meta">AI倾向 {_e(ai_pick)} · 定稿后不可修改，赛后见 <a href="/review">推荐复盘</a></p>
</div>"""
                continue
            rows += f"""
<div class="gsc-match" data-fixture-id="{_e(fid)}" data-group="{_e(group)}"
  data-home="{_e(home)}" data-away="{_e(away)}" data-match-name="{_e(name)}">
  <div class="gsc-match-hd">
    <strong>{_e(group)}组</strong> · {_e(name)}
    <span class="meta">AI倾向 {_e(ai_pick)}</span>
  </div>
  <div class="gsc-pick-row">
    <label class="gsc-pick-opt"><input type="radio" name="gsc-{_e(fid or name)}" class="gsc-pick" value="home"/> 主胜</label>
    <label class="gsc-pick-opt"><input type="radio" name="gsc-{_e(fid or name)}" class="gsc-pick" value="draw"/> 平</label>
    <label class="gsc-pick-opt"><input type="radio" name="gsc-{_e(fid or name)}" class="gsc-pick" value="away"/> 客胜</label>
  </div>
</div>"""
    if not rows:
        return '<p class="meta gsc-empty">所选小组暂无未踢完的末轮场次。</p>'
    return f'<div class="gsc-grid">{rows}</div>'


def _render_locked_compare_html(locked_compare: dict) -> str:
    if not locked_compare or not locked_compare.get("groups"):
        return ""
    blocks = ""
    for g in locked_compare.get("groups") or []:
        blocks += _group_scenario_compare_block(g)
    summary = locked_compare.get("summary") or ""
    return f"""
<div class="card hero-gsc gsc-result">
  <h3>📊 已定稿 · 比对总结</h3>
  <p>{_e(summary)}</p>
</div>
{blocks}"""


def _group_scenario_compare_block(g: dict) -> str:
    group = g.get("group") or "?"
    narrative = g.get("narrative") or ""
    matches = g.get("matches") or []
    changes = g.get("team_changes") or []
    stats = g.get("stats") or {}

    match_rows = ""
    for m in matches:
        ai_cls = "gsc-yes" if m.get("ai_agrees") is True else ("gsc-no" if m.get("ai_agrees") is False else "gsc-na")
        rule_cls = "gsc-yes" if m.get("rule_aligns") is True else ("gsc-no" if m.get("rule_aligns") is False else "gsc-na")
        match_rows += (
            f"<tr><td>{_e(m.get('match_name') or '—')}</td>"
            f"<td>{_e(m.get('user_pick_cn') or m.get('user_outcome_cn') or '—')}</td>"
            f"<td class='{ai_cls}'>{_e(m.get('ai_pick') or '—')}</td>"
            f"<td class='{rule_cls}'>{_e(m.get('rule_motivation_cn') or '—')} · {_e(m.get('rule_direction_cn') or '—')}</td>"
            f"<td class='meta'>{_e(m.get('verdict_cn') or '—')}</td></tr>"
        )

    change_bits = ""
    for ch in changes:
        change_bits += (
            f"<li>{_e(ch.get('team') or '—')}："
            f"第{_e(ch.get('before_rank'))}→第{_e(ch.get('after_rank'))} · "
            f"{_e(ch.get('before_status_cn'))} → {_e(ch.get('after_status_cn'))}</li>"
        )
    change_html = f"<ul class='gsc-changes meta'>{change_bits}</ul>" if change_bits else "<p class='meta'>出线状态与当前形势一致。</p>"

    return f"""
<div class="card gsc-group" id="gsc-group-{_e(group)}">
  <div class="gsc-head">
    <h3>{_e(group)} 组 · 比对结果</h3>
    <span class="meta">AI一致 {stats.get('ai_agree', 0)} · 不同 {stats.get('ai_disagree', 0)} · 规则 {stats.get('rule_align', 0)}</span>
  </div>
  <p class="meta">{_e(g.get('standings_line_before') or '—')} → {_e(g.get('standings_line_after') or '—')}</p>
  <table class="gsc-table"><thead><tr>
    <th>场次</th><th>你的定稿</th><th>AI</th><th>规则战意</th><th>结论</th>
  </tr></thead><tbody>{match_rows or '<tr><td colspan="5" class="meta">暂无</td></tr>'}</tbody></table>
  {change_html}
  <details class="gsc-fold"><summary>展开文字总结</summary>
    <pre class="gfc-copy gsc-narrative" id="gsc-narr-{_e(group)}">{_e(narrative)}</pre>
    <button type="button" class="btn btn-sm" onclick="copyGroupText('gsc-narr-{_e(group)}', this)">复制总结</button>
  </details>
</div>"""


def _group_final_copy_block(g: dict) -> str:
    group = g.get("group") or "?"
    race = g.get("race") or {}
    chaos = race.get("chaos") or {}
    chaos_cls = {"high": "tag-warn", "medium": "tag-live", "low": "tag"}.get(chaos.get("chaos_level") or "", "tag")
    u_n = g.get("user_ai_match_count") or 0
    m_n = g.get("match_count") or 0
    narrative = g.get("narrative") or ""
    ai_narrative = g.get("ai_narrative") or ""
    ai_at = g.get("ai_narrative_at") or ""

    match_bits = ""
    for m in g.get("matches") or []:
        fid = m.get("fixture_id") or ""
        link = f'<a href="/match/{_e(fid)}">{_e(m.get("match_name") or "—")}</a>' if fid else _e(m.get("match_name") or "—")
        ai_tag = '<span class="tag tag-acc-sweet">已AI</span>' if m.get("has_user_ai") else '<span class="meta">未AI</span>'
        match_bits += (
            f'<li>{link} · {_e(m.get("motivation_type_cn") or "—")} · '
            f'倾向 {_e(m.get("jingcai_pick") if m.get("jingcai_pick") not in ("—", "", "观望", "暂无竞彩") else "—")} {ai_tag}</li>'
        )

    ai_block = ""
    if ai_narrative:
        ai_block = f"""
<div class="gfc-ai-box">
  <div class="gfc-ai-hd">✨ 工程师口吻 · AI 润色版 <span class="meta">{_e(ai_at)}</span></div>
  <pre class="gfc-copy gfc-ai-copy" id="gfc-ai-{_e(group)}">{_e(ai_narrative)}</pre>
  <button type="button" class="btn btn-sm" onclick="copyGroupText('gfc-ai-{_e(group)}', this)">复制 AI 文案</button>
</div>"""

    return f"""
<div class="card gfc-group" id="group-{_e(group)}">
  <div class="gfc-head">
    <h3>{_e(group)} 组 · 数据复盘</h3>
    <span class="tag {chaos_cls}">{_e(chaos.get('chaos_level_cn') or '—')}</span>
    <span class="meta">末轮 {m_n} 场 · 你的 AI {u_n}/{m_n}</span>
  </div>
  <ul class="gfc-matches meta">{match_bits or '<li>暂无末轮场次</li>'}</ul>
  <div class="gfc-rule-box">
    <div class="gfc-copy-hd">👨‍💻 数据研发工程师 · 抖音发文版（已隐藏 SP/赔率）</div>
    <pre class="gfc-copy" id="gfc-rule-{_e(group)}">{_e(narrative)}</pre>
    <div class="gfc-actions">
      <button type="button" class="btn btn-sm" onclick="copyGroupText('gfc-rule-{_e(group)}', this)">复制发抖音</button>
      <button type="button" class="btn btn-sm btn-ai" data-group="{_e(group)}"
        onclick="aiGroupCopy('{_e(group)}', this)">✨ 工程师口吻润色</button>
    </div>
  </div>
  {ai_block}
</div>"""


def html_group_final_copy(report: dict) -> str:
    from analysis.tournament.group_final_prompt import GROUP_FINAL_DOUYIN_SYSTEM_PROMPT

    if not report.get("ok"):
        err = report.get("error") or "无法生成文案"
        return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"/>
<title>末轮出线文案</title></head><body>
<p><a href="/worldcup/groups">← 返回小组战意</a></p>
<p>加载失败：{_e(err)}</p></body></html>"""

    rs = report.get("round_summary") or {}
    stats = report.get("stats") or {}
    updated = report.get("updated_at") or now_beijing_str()
    selected_keys = report.get("selected_groups") or []
    selected_set = set(selected_keys)
    all_groups = report.get("groups") or []
    selected = report.get("selected") or []

    picker = "".join(
        _group_picker_chip(g, checked=g.get("group") in selected_set) for g in all_groups
    )
    blocks = "".join(_group_final_copy_block(g) for g in selected) if selected else ""

    empty_hint = ""
    if not selected:
        empty_hint = """
<div class="card gfc-empty">
  <p>请勾选上方小组，再点「生成出线文案」。</p>
  <p class="meta">只会汇总你在列表/详情页点过「AI推荐」的场次；未 AI 的末轮场不会写入文案。</p>
</div>"""

    gfc_css = _shared_css("""
.gfc-pick-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr)); gap:10px; margin:12px 0; }
.gfc-pick {
  display:flex; align-items:flex-start; gap:8px; padding:10px 12px; border:1px solid #e2e8f0;
  border-radius:10px; background:#fff; cursor:pointer;
}
.gfc-pick.is-off { opacity:.55; cursor:not-allowed; }
.gfc-pick input { margin-top:3px; }
.gfc-pick strong { min-width:2em; }
.gfc-toolbar { display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin-top:12px; }
.gfc-head { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-bottom:10px; }
.gfc-head h3 { margin:0; flex:1; min-width:160px; }
.gfc-matches { margin:0 0 12px; padding-left:18px; line-height:1.6; }
.gfc-copy-hd, .gfc-ai-hd { font-size:13px; font-weight:700; color:#475569; margin-bottom:6px; }
.gfc-copy {
  white-space: pre-wrap; word-break: break-word; font-family: inherit; font-size: 13px; line-height: 1.65;
  background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px; margin: 0 0 10px;
  max-height: 420px; overflow: auto;
}
.gfc-ai-box { margin-top: 14px; padding-top: 14px; border-top: 1px dashed #e2e8f0; }
.gfc-ai-copy { background: #faf5ff; border-color: #ddd6fe; }
.gfc-actions { display:flex; gap:8px; flex-wrap:wrap; }
.hero-gfc { background: linear-gradient(135deg, #eff6ff 0%, #fff 55%); border: 1px solid #bfdbfe; }
.gfc-empty { text-align:center; color:#64748b; }
.gfc-prompt-pre { max-height: 360px; font-size: 12px; }
.gfc-prompt-fold > summary { cursor:pointer; font-weight:600; padding:4px 0; }
.gsc-grid { display:grid; gap:12px; margin-top:12px; }
.gsc-match { border:1px solid #e2e8f0; border-radius:10px; padding:12px; background:#fff; }
.gsc-match-hd { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-bottom:8px; font-size:13px; }
.gsc-pick-row { display:flex; gap:12px; flex-wrap:wrap; }
.gsc-pick-opt {
  display:inline-flex; align-items:center; gap:6px; padding:8px 12px;
  border:1px solid #cbd5e1; border-radius:999px; background:#fff; cursor:pointer; font-size:13px;
}
.gsc-pick-opt:has(input:checked) { border-color:#059669; background:#ecfdf5; font-weight:700; }
.gsc-match.gsc-locked { background:#f8fafc; border-color:#cbd5e1; }
.gsc-score-row { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.gsc-result { margin-top:16px; }
.gsc-table { width:100%; border-collapse:collapse; font-size:13px; margin:10px 0; }
.gsc-table th, .gsc-table td { border-bottom:1px solid #e2e8f0; padding:8px 6px; text-align:left; vertical-align:top; }
.gsc-yes { color:#15803d; font-weight:600; }
.gsc-no { color:#b91c1c; font-weight:600; }
.gsc-na { color:#64748b; }
.gsc-changes { margin:8px 0 0; padding-left:18px; }
.gsc-fold > summary { cursor:pointer; font-weight:600; margin-top:8px; }
.gsc-narrative { max-height:280px; }
.hero-gsc { background: linear-gradient(135deg, #f0fdf4 0%, #fff 60%); border:1px solid #bbf7d0; margin-top:16px; }
""")

    js = """
function selectedGroupIds() {
  return [...document.querySelectorAll('.gfc-group-cb:checked')].map(el => el.value);
}
function generateGroupCopy() {
  const ids = selectedGroupIds();
  if (!ids.length) { alert('请先勾选至少 1 个小组'); return; }
  const url = '/worldcup/groups/final?groups=' + encodeURIComponent(ids.join(','));
  window.location.href = url;
}
function copyGroupText(id, btn) {
  const el = document.getElementById(id);
  if (!el) return;
  const text = el.textContent || '';
  navigator.clipboard.writeText(text).then(() => {
    const label = btn.textContent;
    btn.textContent = '已复制';
    setTimeout(() => { btn.textContent = label; }, 1500);
  }).catch(() => {
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    btn.textContent = '已复制';
  });
}
function aiGroupCopy(group, btn) {
  const label = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'AI生成中…';
  fetch('/api/worldcup/groups/final-copy/ai', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({groups: [group], user_ai_only: true})
  }).then(r => r.json()).then(d => {
    btn.disabled = false;
    btn.textContent = label;
    if (!d.ok) { alert(d.error || 'AI 文案失败'); return; }
    location.reload();
  }).catch(e => {
    btn.disabled = false;
    btn.textContent = label;
    alert('请求失败: ' + e);
  });
}
function aiAllGroupCopy(btn) {
  const ids = selectedGroupIds();
  if (!ids.length) { alert('请先勾选小组'); return; }
  const label = btn.textContent;
  btn.disabled = true;
  btn.textContent = '批量生成中…';
  fetch('/api/worldcup/groups/final-copy/ai', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({groups: ids, user_ai_only: true})
  }).then(r => r.json()).then(d => {
    btn.disabled = false;
    btn.textContent = label;
    if (!d.ok) { alert(d.error || '部分失败'); }
    location.reload();
  }).catch(e => {
    btn.disabled = false;
    btn.textContent = label;
    alert('请求失败: ' + e);
  });
}
function collectScenarioPicks() {
  const results = [];
  document.querySelectorAll('.gsc-match:not([data-locked="1"])').forEach(el => {
    const checked = el.querySelector('.gsc-pick:checked');
    if (!checked) return;
    const item = {
      pick: checked.value,
      group: el.dataset.group || '',
      home: el.dataset.home || '',
      away: el.dataset.away || '',
      match_name: el.dataset.matchName || '',
    };
    if (el.dataset.fixtureId) item.fixture_id = el.dataset.fixtureId;
    results.push(item);
  });
  return results;
}
function renderScenarioCompare(data) {
  const box = document.getElementById('gsc-result');
  if (!box) return;
  if (!data.ok) {
    box.innerHTML = '<div class="card"><p class="gsc-no">' + (data.error || '定稿失败') + '</p></div>';
    return;
  }
  let html = '<div class="card hero-gsc gsc-result"><h3>📊 定稿比对总结</h3><p>' + (data.summary || '') + '</p></div>';
  (data.groups || []).forEach(g => {
    const stats = g.stats || {};
    let rows = '';
    (g.matches || []).forEach(m => {
      const aiCls = m.ai_agrees === true ? 'gsc-yes' : (m.ai_agrees === false ? 'gsc-no' : 'gsc-na');
      const ruleCls = m.rule_aligns === true ? 'gsc-yes' : (m.rule_aligns === false ? 'gsc-no' : 'gsc-na');
      rows += '<tr><td>' + (m.match_name || '—') + '</td>'
        + '<td>' + (m.user_pick_cn || m.user_outcome_cn || '—') + '</td>'
        + '<td class="' + aiCls + '">' + (m.ai_pick || '—') + '</td>'
        + '<td class="' + ruleCls + '">' + (m.rule_motivation_cn || '—') + ' · ' + (m.rule_direction_cn || '—') + '</td>'
        + '<td class="meta">' + (m.verdict_cn || '—') + '</td></tr>';
    });
    let changes = '';
    (g.team_changes || []).forEach(ch => {
      changes += '<li>' + ch.team + '：第' + ch.before_rank + '→第' + ch.after_rank
        + ' · ' + ch.before_status_cn + ' → ' + ch.after_status_cn + '</li>';
    });
    const changeHtml = changes
      ? '<ul class="gsc-changes meta">' + changes + '</ul>'
      : '<p class="meta">出线状态与当前形势一致。</p>';
    html += '<div class="card gsc-group"><div class="gsc-head"><h3>' + g.group + ' 组 · 比对结果</h3>'
      + '<span class="meta">AI一致 ' + (stats.ai_agree || 0) + ' · 不同 ' + (stats.ai_disagree || 0)
      + ' · 规则 ' + (stats.rule_align || 0) + '</span></div>'
      + '<p class="meta">' + (g.standings_line_before || '—') + ' → ' + (g.standings_line_after || '—') + '</p>'
      + '<p class="meta">积分榜按胜平负最小比分推演（1-0/1-1/0-1），净胜球 tie 时仅供参考。</p>'
      + '<table class="gsc-table"><thead><tr><th>场次</th><th>你的定稿</th><th>AI</th><th>规则战意</th><th>结论</th></tr></thead><tbody>'
      + (rows || '<tr><td colspan="5" class="meta">暂无</td></tr>') + '</tbody></table>' + changeHtml
      + '<details class="gsc-fold"><summary>展开文字总结</summary><pre class="gfc-copy gsc-narrative">'
      + (g.narrative || '') + '</pre></details></div>';
  });
  box.innerHTML = html;
  document.querySelectorAll('.gsc-match:not([data-locked="1"])').forEach(el => {
    el.querySelectorAll('input').forEach(inp => { inp.disabled = true; });
    el.classList.add('gsc-locked');
  });
  box.scrollIntoView({behavior: 'smooth', block: 'start'});
}
function finalizeUserPicks(btn) {
  const ids = selectedGroupIds();
  const picks = collectScenarioPicks();
  if (!picks.length) { alert('请至少选择一场的胜平负'); return; }
  if (!confirm('定稿后不可修改。确定锁定这 ' + picks.length + ' 场吗？')) return;
  const label = btn.textContent;
  btn.disabled = true;
  btn.textContent = '定稿中…';
  fetch('/api/worldcup/groups/scenario-compare', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({groups: ids, picks: picks, finalize: true, user_ai_only: true})
  }).then(r => r.json()).then(d => {
    btn.disabled = false;
    btn.textContent = label;
    if (!d.ok) { alert(d.error || (d.errors && d.errors[0]) || '定稿失败'); return; }
    renderScenarioCompare(d);
  }).catch(e => {
    btn.disabled = false;
    btn.textContent = label;
    alert('请求失败: ' + e);
  });
}
"""

    ai_btn_disabled = " disabled" if not selected else ""

    scenario_section = ""
    if selected:
        scenario_form = _group_scenario_form_rows(selected)
        locked_html = _render_locked_compare_html(report.get("locked_compare") or {})
        has_unlocked = "gsc-pick" in scenario_form
        finalize_btn = ""
        if has_unlocked:
            finalize_btn = (
                '<button type="button" class="btn" style="background:#059669" '
                'onclick="finalizeUserPicks(this)">🔒 定稿锁定（不可修改）</button>'
            )
        scenario_section = f"""
<div class="card hero-gsc" id="gsc-form">
  <h2>🎯 2. 我的末轮胜平负 · 定稿后不可改</h2>
  <p class="meta">只选主胜/平/客胜，不用填比分。点「定稿锁定」后写入本地归档，防止临场改作业；赛后与 AI、实际赛果一起在 <a href="/review">推荐复盘</a> 对照。</p>
  {scenario_form}
  <div class="gfc-toolbar">
    {finalize_btn}
  </div>
  <div id="gsc-result">{locked_html}</div>
</div>"""

    prompt_fold = f"""
<details class="card gfc-prompt-fold">
  <summary>📝 Prompt 模板 · 数据研发工程师 · 抖音（改代码见 analysis/tournament/group_final_prompt.py）</summary>
  <p class="meta">点「工程师口吻润色」即走此 System Prompt + 你的小组数据 JSON。可复制到 ChatGPT / Cursor 手动调。</p>
  <pre class="gfc-copy gfc-prompt-pre" id="gfc-system-prompt">{_e(GROUP_FINAL_DOUYIN_SYSTEM_PROMPT)}</pre>
  <button type="button" class="btn btn-sm" onclick="copyGroupText('gfc-system-prompt', this)">复制 System Prompt</button>
  <a class="btn btn-sm" style="background:#64748b" href="/api/worldcup/groups/final-copy/prompt" target="_blank" rel="noopener">JSON API</a>
</details>"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>末轮出线形势文案 · 按小组</title>
<style>{gfc_css}</style>
<script>{js}</script>
</head><body>
<p class="back page-nav">
  <a href="/">← 返回首页</a> · <a href="/worldcup/groups">⚔️ 小组战意</a> · <a href="/worldcup">🏆 开盘套路</a>
</p>

<div class="card hero-gfc">
  <h1>👨‍💻 数据研发 · 抖音出线文案</h1>
  <p class="meta">{_e(rs.get('stage_label'))} · 更新 {_e(updated)}</p>
  <p>{_e(report.get('advance_rule_cn') or '')}</p>
  <p class="meta">全库末轮 {stats.get('match_count', 0)} 场 · 你已跑模型 {stats.get('user_ai_match_count', 0)} 场</p>
  <p class="meta"><strong>人设：数据研发工程师</strong> — 用「积分榜引擎 + 战意规则 + 多模型 AI」的口吻写抖音，自动去掉 SP/赔率等敏感词，文末带话题标签。</p>

  <h3 style="margin:16px 0 0;font-size:15px">1. 选择小组</h3>
  <div class="gfc-pick-grid">{picker}</div>
  <div class="gfc-toolbar">
    <button type="button" class="btn" style="background:#dc2626" onclick="generateGroupCopy()">生成出线文案</button>
    <button class="btn" onclick="location.href='/worldcup/groups/final'">重新选择</button>
    <button class="btn" onclick="location.reload()">刷新 AI 状态</button>
    <button type="button" class="btn btn-ai" onclick="aiAllGroupCopy(this)"{ai_btn_disabled}>✨ 工程师口吻润色已选组</button>
  </div>
</div>

{prompt_fold}

{scenario_section}

{empty_hint}
{blocks}

  <p class="meta">流程：跑模型 → 勾选小组 → 生成文案 → 选定胜平负并定稿 → 赛后复盘 · 定稿后不可修改</p>
</body></html>"""


def _team_form_fold_html(match_name: str) -> str:
    try:
        from team_recent_form import build_team_recent_form_from_match
        from style_clash import build_style_clash_from_form
        form = build_team_recent_form_from_match(match_name)
        clash = build_style_clash_from_form(form)
    except Exception:
        return ""
    if not form.get("available"):
        return ""

    clash_html = ""
    if clash.get("available"):
        hs = clash.get("home_style") or {}
        aws = clash.get("away_style") or {}
        lvl = clash.get("variance_cn") or "—"
        lvl_cls = "tag-warn" if clash.get("variance_level") == "high" else "tag"
        clash_html = f"""
<p class="style-clash-banner">
  <span class="tag {lvl_cls}">战术变数 { _e(lvl) }</span>
  <strong>{ _e(clash.get('headline')) }</strong>
</p>
<p class="meta">{ _e(clash.get('detail')) }</p>
<p class="meta">主队 · {_e(hs.get('style_cn'))} — {_e(hs.get('reason'))}<br/>
客队 · {_e(aws.get('style_cn'))} — {_e(aws.get('reason'))}</p>
<p class="meta">关注：{_e(clash.get('watch'))} · {_e(clash.get('note'))}</p>
<hr style="border:none;border-top:1px dashed #e2e8f0;margin:12px 0"/>"""

    rows = clash_html
    for side_key, label in (("home", "主队"), ("away", "客队")):
        block = form.get(side_key) or {}
        rows += f"<p><strong>{label} { _e(block.get('team')) }</strong> · {_e(block.get('summary'))}</p>"
        rows += "<table><tr><th>日期</th><th>对手</th><th>主客</th><th>比分</th><th>赛果</th><th>欧赔</th></tr>"
        for m in (block.get("recent_matches") or [])[:6]:
            rows += (
                f"<tr><td>{_e(m.get('date'))}</td><td>{_e(m.get('opponent'))}</td>"
                f"<td>{_e(m.get('venue'))}</td><td>{_e(m.get('score'))}</td>"
                f"<td>{_e(m.get('result'))}</td><td class='meta'>{_e(m.get('eu_odds'))}</td></tr>"
            )
        rows += "</table>"
    h2h = form.get("head_to_head") or []
    if h2h:
        rows += "<p class='meta'><strong>近一年交锋</strong> " + " · ".join(
            _e(h.get("match")) for h in h2h
        ) + "</p>"
    rows += f"<p class='meta'>{_e(form.get('note'))}</p>"
    return _fold(
        "战术变数 · 双方近期国际赛（近1年）",
        rows,
        muted=True,
        export_slug="team-form",
    )


def _settled_card(settled: dict | None) -> str:
    if not settled or not settled.get("score_text"):
        return ""
    score = settled.get("score_text") or "—"
    result_cn = settled.get("result_1x2_cn") or "—"
    closing = _closing_odds_txt(settled)
    pick = settled.get("pick_jingcai_cn") or "—"
    hit_1x2 = _hit_badge(settled.get("hit_1x2"))
    hit_sc = _hit_badge(settled.get("hit_score"))
    settled_at = format_ts(settled.get("settled_at"))
    return f"""
<div class="card settled-card">
  <h3>已完场复盘</h3>
  <p><strong>赛果 { _e(score) }</strong> · {_e(result_cn)} · 结算 {_e(settled_at)}</p>
  <p class="meta">终盘 {_e(closing)}</p>
  <p>预测 {_e(pick)} · 命中 {hit_1x2} 1X2 · {hit_sc} 比分</p>
  <p class="meta">亚盘 {_e(settled.get('pick_ah_cn') or '—')} · 赢盘 {_hit_badge(settled.get('hit_ah'))}</p>
</div>"""


def _ah_stats_row(label: str, block: dict | None) -> str:
    if not block or not block.get("count"):
        return f"<tr><td>{_e(label)}</td><td colspan='3' class='meta'>样本不足</td></tr>"
    return (
        f"<tr><td>{_e(label)}</td>"
        f"<td>{block.get('count')} 场</td>"
        f"<td>{_rate_pct(block.get('ah_upper_win_rate'))}</td>"
        f"<td>{_rate_pct(block.get('ah_lower_win_rate'))}</td></tr>"
    )


def _build_ah_analysis_card(prediction: dict | None, timeline: list[dict] | None = None) -> str:
    from ah_analytics import ah_card_from_prediction

    data = ah_card_from_prediction(prediction, timeline)
    if not data:
        return ""

    open_line = data.get("open_line")
    live_line = data.get("live_line")
    line_txt = "—"
    if open_line is not None or live_line is not None:
        line_txt = f"初 {_e(open_line)} → 临 {_e(live_line)}"
    water_txt = ""
    if data.get("open_water") or data.get("live_water"):
        water_txt = f" · 水位 初 {_e(data.get('open_water'))} → 临 {_e(data.get('live_water'))}"

    pick_cn = data.get("pick_cn") or "观望"
    reason = data.get("reason") or ""
    stats_rows = _ah_stats_row("初盘相似", data.get("open_stats"))
    stats_rows += _ah_stats_row("临盘相似", data.get("live_stats"))

    return f"""
<div class="card ah-card">
  <h3>📊 亚盘赢盘分析</h3>
  <p><strong class="pick">{_e(pick_cn)}</strong>{(' · ' + _e(reason)) if reason else ''}</p>
  <p class="meta">盘口 {line_txt}{water_txt}</p>
  <table class="mini ah-stats-table">
    <tr><th>样本层</th><th>场次</th><th>上盘赢盘率</th><th>下盘赢盘率</th></tr>
    {stats_rows}
  </table>
  <p class="meta">赢盘率来自相似历史样本的亚盘结算统计；推荐方向由历史净收益 + 临盘水位综合得出。
  · <a href="/kelly?fixture_id={_e(prediction.get('fixture_id') if prediction else '')}">Kelly 仓位 →</a></p>
</div>"""


def _path_block(team: str, pick: dict) -> str:
    from knockout_path import bracket_flow_steps

    paths = pick.get("paths") or {}
    preferred = pick.get("easiest_path_rank") or 1
    pref_key = {1: "first", 2: "second", 3: "third"}.get(preferred, "first")
    pref_path = paths.get(pref_key) or {}
    pref_steps = bracket_flow_steps(pref_path)
    lane = ""
    for i, step in enumerate(pref_steps):
        if i:
            lane += "<div class='bracket-connector'>↓</div>"
        cls = f"bracket-node {step.get('stage', '')}"
        lane += f"<div class='{cls}'>{_e(step.get('label'))}</div>"

    rows = ""
    for key, label in (("first", "若夺头名"), ("second", "若拿第二"), ("third", "若第三(最佳8)")):
        p = paths.get(key) or {}
        summary = p.get("r32_summary") or p.get("r32_label") or "—"
        preview = p.get("opponent_preview") or ""
        if preview:
            summary = f"{summary}<br><span class='meta'>潜在对手：{_e(preview)}</span>"
        r16 = p.get("r16_hint") or ""
        extra = f"<br><span class='meta'>{_e(r16)}</span>" if r16 and r16 != "—" else ""
        highlight = " class='path-row-preferred'" if key == pref_key else ""
        rows += (
            f"<tr{highlight}><td>{label}</td>"
            f"<td>{_e(summary)}{extra}</td>"
            f"<td>{p.get('difficulty_score', '—')}</td></tr>\n"
        )
    notes = pick.get("notes") or []
    note_html = "".join(f"<li>{_e(x)}</li>" for x in notes[:4])
    race = pick.get("race") or {}
    race_html = ""
    if race.get("status_cn"):
        race_cls = {
            "locked_1st": "race-lock",
            "locked_top2": "race-lock",
            "out": "race-out",
            "fight_1st": "race-fight",
        }.get(race.get("status"), "race-normal")
        race_html = (
            f"<p class='race-badge {race_cls}'>"
            f"<strong>{_e(race.get('status_cn'))}</strong>"
            f" · 可达成名次 {', '.join(str(x) for x in (race.get('possible_ranks') or []))}"
            f"</p>"
        )
    likely = pick.get("likely_r32") or {}
    likely_html = ""
    if likely.get("summary"):
        likely_html = f"<p class='meta likely-r32'><strong>32强前瞻</strong> {_e(likely.get('summary'))}</p>"
    opp_rows = ""
    for o in likely.get("opponents") or []:
        teams = " / ".join(o.get("teams") or []) or o.get("current") or "—"
        opp_rows += (
            f"<tr><td>{_e(o.get('label') or o.get('slot'))}</td>"
            f"<td>{_e(teams)}</td>"
            f"<td class='meta'>{_e(o.get('note') or '')}</td></tr>"
        )
    opp_table = ""
    if opp_rows:
        opp_table = f"""
  <table class="mini likely-opp-table">
    <tr><th>签位</th><th>潜在对手</th><th>说明</th></tr>
    {opp_rows}
  </table>"""
    return f"""
<div class="path-block">
  <h4>{_e(team)} · 淘汰赛路径</h4>
  {race_html}
  {likely_html}
  <p class="meta">挑对手风险：<span class="tag">{_e(pick.get('picking_level_cn'))}</span>
     · 相对更优路径：<strong>{_e(pick.get('preferred_path_cn'))}</strong></p>
  <div class="bracket-lane" aria-label="潜在对阵图">
    <div class="lane-title">更优路径示意</div>
    {lane}
  </div>
  <table class="mini">
    <tr><th>名次</th><th>32强可能对阵</th><th>难度</th></tr>
    {rows}
  </table>
  <ul class="meta path-notes">{note_html or '<li>—</li>'}</ul>
  {opp_table}
</div>"""


def _quant_score_tags(scores: list, *, detail: list | None = None) -> str:
    if detail:
        return " ".join(f"<span class='tag'>{_e(str(x))}</span>" for x in detail[:5])
    if not scores:
        return "<span class='meta'>—</span>"
    return " ".join(f"<span class='tag'>{_e(str(x))}</span>" for x in scores[:5])


def _quant_panel(prediction: dict | None) -> str:
    if not prediction:
        return ""
    quant = prediction.get("quant") or {}
    sm = quant.get("score_model") or {}
    ev = quant.get("jingcai_ev") or prediction.get("jingcai_ev")
    elo = quant.get("elo")
    mc = quant.get("group_mc")
    if not sm and not ev and not elo and not mc:
        return ""

    hist_detail = prediction.get("likely_scores_detail") or []
    hist_scores = prediction.get("likely_scores") or []
    model_detail = prediction.get("model_likely_scores_detail") or sm.get("likely_scores_detail") or []
    model_scores = prediction.get("model_likely_scores") or sm.get("likely_scores") or []
    stretch = prediction.get("model_stretch_scores") or [
        s.get("score") for s in (sm.get("stretch_scores") or []) if s.get("score")
    ]

    score_grid = ""
    if hist_scores or model_scores:
        stretch_txt = ""
        if stretch:
            stretch_txt = f"<p class='meta'>模型延伸：{' · '.join(_e(str(x)) for x in stretch[:2])}</p>"
        score_grid = f"""
<div class="quant-score-grid">
  <div class="quant-track">
    <h4>历史相似 Top3</h4>
    {_quant_score_tags(hist_scores, detail=hist_detail)}
  </div>
  <div class="quant-track model-track">
    <h4>Dixon-Coles 模型 Top3</h4>
    {_quant_score_tags(model_scores, detail=model_detail)}
    {stretch_txt}
  </div>
</div>"""

    model_meta = ""
    if sm:
        probs = sm.get("prob_1x2_pct") or {}
        ah_cov = sm.get("ah_home_cover_pct")
        model_meta = (
            f"<p class='meta'>λ 主 {sm.get('lambda_home')} · 客 {sm.get('lambda_away')}"
            f" · 总进球 {sm.get('avg_total_goals')}"
            f" · 模型 1X2 {probs.get('home')}/{probs.get('draw')}/{probs.get('away')}%"
            f"{f' · 模型上盘 {ah_cov}%' if ah_cov is not None else ''}</p>"
        )

    elo_block = ""
    if elo:
        elo_block = (
            f"<p class='meta'><strong>Elo</strong> {_e(elo.get('home'))} {elo.get('home_elo')}"
            f" vs {_e(elo.get('away'))} {elo.get('away_elo')}"
            f" · 差 {elo.get('elo_diff'):+.0f}"
            f" · 主胜 {elo.get('home_win_prob_pct')}%</p>"
        )

    ev_block = ""
    if ev:
        vb = "value-yes" if ev.get("value_bet") else "value-no"
        ev_block = f"""
<div class="quant-ev {vb}">
  <strong>{_e(ev.get('pick_cn') or '—')}</strong>
  · SP {ev.get('jingcai_sp')} · 公平 {ev.get('fair_prob_pct')}% · 边际 {ev.get('edge_pp'):+.2f}pp
  · EV {ev.get('ev_pct'):+.2f}% · {_e(ev.get('label') or '')}
</div>"""

    mc_block = ""
    if mc and mc.get("teams"):
        mc_rows = ""
        for t in mc.get("teams") or []:
            mc_rows += (
                f"<tr><td>{_e(t.get('team'))}</td>"
                f"<td>{t.get('p_top2_pct')}%</td>"
                f"<td>{t.get('p_best3_pct')}%</td>"
                f"<td>{t.get('p_out_pct')}%</td></tr>"
            )
        mc_block = f"""
<div class="quant-mc">
  <h4>小组出线 MC · {_e(mc.get('group'))} 组 · {mc.get('simulations')} 次</h4>
  <table class="mini">
    <tr><th>球队</th><th>前二</th><th>最佳第三</th><th>出局</th></tr>
    {mc_rows}
  </table>
</div>"""

    return f"""
<div class="card quant-card">
  <h3>📈 量化分析 <span class="tag">Poisson · Elo · EV</span></h3>
  {score_grid}
  {model_meta}
  {elo_block}
  {ev_block}
  {mc_block}
  <p class="meta">历史轨来自相似样本；模型轨由去水欧赔拟合 λ，Dixon-Coles 修正低比分相关。</p>
</div>"""


def _score_recommend_panel(prediction: dict | None) -> str:
    if not _score_enabled() or not prediction:
        return ""
    from score_recommend import build_score_recommendation

    sr = prediction.get("score_recommend") or build_score_recommendation(prediction)
    if not sr.get("ok"):
        reason = sr.get("reason") or "暂无数据"
        return f"""
<div class="card score-rec-card muted">
  <h3>⚽ 比分推荐 <span class="tag">基础分析</span></h3>
  <p class="meta">{_e(reason)}</p>
</div>"""

    primary = sr.get("primary") or []
    rows = ""
    for i, p in enumerate(primary):
        rank = "主推" if i == 0 else ("备选" if i == 1 else "延伸")
        align = "✓" if p.get("aligned") else "—"
        prob = f"{p['prob_pct']}%" if p.get("prob_pct") is not None else "—"
        rows += (
            f"<tr><td><strong>{rank}</strong></td>"
            f"<td class='score-cell'><strong>{_e(p.get('score'))}</strong></td>"
            f"<td>{prob}</td>"
            f"<td>{_e(p.get('outcome_cn') or '—')}</td>"
            f"<td>{align}</td>"
            f"<td class='meta'>{_e(p.get('source') or '—')}</td></tr>"
        )

    stretch = sr.get("stretch") or []
    stretch_line = ""
    if stretch:
        stretch_line = f"<p class='meta'>模型延伸：{' · '.join(_e(str(x)) for x in stretch)}</p>"

    track_summary = sr.get("track_summary") or {}
    hist_txt = track_summary.get("historical") or "—"
    model_txt = track_summary.get("model") or "—"

    meta = sr.get("model_meta") or {}
    meta_line = ""
    if meta.get("lambda_home") is not None:
        probs = meta.get("prob_1x2_pct") or {}
        meta_line = (
            f"<p class='meta'>Poisson λ 主 {meta.get('lambda_home')} · 客 {meta.get('lambda_away')}"
            f" · 模型 1X2 {probs.get('home')}/{probs.get('draw')}/{probs.get('away')}%</p>"
        )

    fid = prediction.get("fixture_id") or ""
    api_link = ""
    if fid:
        api_link = (
            f'<p class="meta"><a href="/api/match/{_e(str(fid))}/score-recommend" '
            f'target="_blank" rel="noopener">JSON API</a></p>'
        )

    return f"""
<div class="card score-rec-card">
  <h3>⚽ 比分推荐 <span class="tag">基础分析</span></h3>
  <p class="score-headline">参考赛果 <strong>{_e(sr.get('pick_1x2_cn') or '—')}</strong>
     · 主推 <strong>{_e(sr.get('headline') or '—')}</strong></p>
  <p class="meta">{_e(sr.get('summary') or '')}</p>
  <table class="mini score-rec-table">
    <tr><th>档位</th><th>比分</th><th>概率</th><th>赛果</th><th>一致</th><th>来源</th></tr>
    {rows}
  </table>
  {stretch_line}
  <div class="score-track-row">
    <div><span class="side-label">历史轨</span> {_e(hist_txt)}</div>
    <div><span class="side-label">模型轨</span> {_e(model_txt)}</div>
  </div>
  <p class="meta">总进球 {_e(sr.get('total_goals_hint') or '—')} · 大小球 {_e(sr.get('over_under_cn') or '—')} · 置信 {_e(sr.get('confidence_cn') or '—')}</p>
  {meta_line}
  {api_link}
</div>"""


def _format_review_kickoff(kickoff_at: str | None) -> str:
    """Show MM-DD HH:MM for review table (full value kept in data-kickoff)."""
    ko = str(kickoff_at or "").strip()
    if not ko:
        return "—"
    if len(ko) >= 16 and ko[4] == "-" and ko[7] == "-":
        return ko[5:16]
    if len(ko) >= 10:
        return ko[:10]
    return ko


def _review_row(r: dict) -> str:
    fid = r.get("fixture_id") or ""
    name = r.get("match_name") or fid
    link = f'<a href="/match/{_e(fid)}">{_e(name)}</a>' if fid else _e(name)
    tier_cn = r.get("buy_tier_cn") or "—"
    tier_css = {"可串": "tier-a", "可单关": "tier-b", "仅参考": "tier-c"}.get(tier_cn, "tier-c")
    tier_tag = f'<span class="tag tag-buy-{tier_css}">{_e(tier_cn)}</span>' if tier_cn != "—" else "—"
    hit_1x2 = _hit_badge(r.get("hit_1x2"))
    hit_sc = _hit_badge(r.get("hit_score")) if _score_enabled() else "—"
    hit_ah = _hit_badge(r.get("hit_ah"))
    cmp_txt = r.get("compare_summary") or "—"
    cmp_cls = "cmp-ok" if r.get("hit_1x2") is True else ("cmp-bad" if r.get("hit_1x2") is False else "")
    ref = r.get("reference_result_1x2_cn") or "—"
    open_cn = r.get("open_result_1x2_cn") or "—"
    rec_scores = (r.get("recommended_scores") or "—")[:36] if _score_enabled() else "—"
    ko_raw = str(r.get("kickoff_at") or "")
    ko = _format_review_kickoff(ko_raw)
    user_pick = r.get("user_pick_cn") or "—"
    user_hit = _hit_badge(r.get("user_hit_1x2")) if r.get("user_pick_cn") else "—"
    user_locked = r.get("user_locked_at") or ""
    user_cell = f"<strong>{_e(user_pick)}</strong>"
    if user_locked:
        user_cell += f"<br/><span class='meta'>定稿 {_e(user_locked[:16])}</span>"
    return (
        f"<tr data-tier='{_e(r.get('buy_tier') or '')}' data-hit='{_e(str(r.get('hit_1x2')))}'"
        f" data-kickoff='{_e(ko_raw)}'>"
        f"<td>{_e(ko)}</td><td>{link}</td>"
        f"<td>{user_cell}</td>"
        f"<td><strong>{_e(r.get('pick_jingcai_cn') or '—')}</strong></td>"
        f"<td><strong>{_e(r.get('score_text') or '—')}</strong> {_e(r.get('result_1x2_cn') or '—')}</td>"
        f"<td class='{cmp_cls}'>{_e(cmp_txt)}</td>"
        f"<td>{tier_tag}</td>"
        f"<td>{_e(r.get('confidence_cn') or '—')}</td>"
        f"<td class='meta'>{_e(ref)}</td>"
        f"<td class='meta'>{_e(open_cn)}</td>"
        f"<td class='meta'>{_e(rec_scores)}</td>"
        f"<td>{user_hit}</td><td>{hit_1x2}</td><td>{hit_sc}</td><td>{hit_ah}</td>"
        f"<td class='meta'>{_e(r.get('recommendation_source') or '—')}</td>"
        f"</tr>\n"
    )


def html_recommendation_review(report: dict) -> str:
    report = report or {}
    updated = report.get("updated_at") or now_beijing_str()
    acc = report.get("accuracy") or {}
    purchase = acc.get("purchase_jingcai") or {}
    records = report.get("records") or []
    misses = report.get("miss_patterns") or []

    stats = _stat_grid([
        ("已结算", str(report.get("total_settled") or 0)),
        ("有竞彩推荐", str(report.get("with_recommendation") or 0)),
        ("购买胜率", _pct(purchase.get("rate_pct") or acc.get("rate_1x2_pct"))),
        ("A 可串", _pct((purchase.get("tier_a") or {}).get("rate_pct"))),
        ("B 可单关", _pct((purchase.get("tier_b") or {}).get("rate_pct"))),
        ("C 仅参考", _pct((purchase.get("tier_c") or {}).get("rate_pct"))),
    ])
    tier_table = _buy_tier_table(acc.get("by_buy_tier") or {})
    rows = "".join(_review_row(r) for r in records) or "<tr><td colspan='16'>暂无已结算场次</td></tr>"

    user_acc = report.get("user_pick_accuracy") or {}
    user_locked_n = report.get("user_locked_count") or 0
    user_stats = ""
    if user_locked_n:
        user_stats = f"""
<div class="card" style="border-color:#bbf7d0;background:#f0fdf4">
  <h2>🔒 我的定稿 vs 赛果</h2>
  <p class="meta">末轮定稿 {user_locked_n} 场 · 已结算对照 {user_acc.get('judged') or 0} 场</p>
  <p><strong>定稿命中率</strong> {_pct(user_acc.get('rate_pct'))} ·
  <strong>与 AI 同向</strong> {_pct(user_acc.get('vs_ai_rate_pct'))}
  （{user_acc.get('vs_ai_same') or 0}/{user_acc.get('vs_ai_judged') or 0}）</p>
  <p class="meta">定稿在 <a href="/worldcup/groups/final">末轮出线文案</a> 页锁定，此处与工具推荐、实际赛果并列复盘。</p>
</div>"""

    miss_li = "".join(
        f"<li><strong>{_e(m.get('pattern'))}</strong> × {m.get('count', 0)}</li>"
        for m in misses
    ) or "<li class='meta'>暂无足够样本</li>"

    review_css = _shared_css("""
.hero-card { background: linear-gradient(135deg, #fefce8 0%, #fff 55%); border: 1px solid #fde047; }
.cmp-ok { color: #047857; font-weight: 700; }
.cmp-bad { color: #b91c1c; font-weight: 700; }
.review-toolbar { display:flex; gap:8px; flex-wrap:wrap; margin:12px 0; align-items:center; }
.review-toolbar .review-sort-label { margin-left: auto; font-size: 12px; color: #64748b; }
@media (max-width: 640px) {
  .review-toolbar .review-sort-label { margin-left: 0; width: 100%; }
}
.review-toolbar button { padding:6px 12px; border-radius:8px; border:1px solid #e2e8f0; background:#fff; cursor:pointer; }
.review-toolbar button.active { background:#2563eb; color:#fff; border-color:#2563eb; }
.review-table-wrap { overflow-x:auto; }
table.review-table { font-size: 13px; min-width: 960px; }
table.review-table th { white-space: nowrap; }
""")

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>推荐复盘</title>
<style>
{review_css}
</style>
<script>
let reviewFilter = 'all';
let reviewSort = 'kickoff_desc';

function applyReviewFilter() {{
  document.querySelectorAll('.review-table tbody tr').forEach(tr => {{
    const tier = tr.dataset.tier || '';
    const hit = tr.dataset.hit || '';
    let show = true;
    if (reviewFilter === 'A') show = tier === 'A';
    else if (reviewFilter === 'B') show = tier === 'B';
    else if (reviewFilter === 'C') show = tier === 'C';
    else if (reviewFilter === 'hit') show = hit === 'True';
    else if (reviewFilter === 'miss') show = hit === 'False';
    tr.style.display = show ? '' : 'none';
  }});
}}

function filterReview(kind) {{
  reviewFilter = kind;
  document.querySelectorAll('.review-toolbar button[data-filter]').forEach(b => {{
    b.classList.toggle('active', b.dataset.filter === kind);
  }});
  applyReviewFilter();
}}

function sortReview(kind) {{
  reviewSort = kind;
  document.querySelectorAll('.review-toolbar button[data-sort]').forEach(b => {{
    b.classList.toggle('active', b.dataset.sort === kind);
  }});
  const tbody = document.querySelector('.review-table tbody');
  if (!tbody) return;
  const rows = Array.from(tbody.querySelectorAll('tr'));
  rows.sort((a, b) => {{
    const ka = a.dataset.kickoff || '';
    const kb = b.dataset.kickoff || '';
    if (reviewSort === 'kickoff_asc') return ka.localeCompare(kb);
    return kb.localeCompare(ka);
  }});
  rows.forEach(r => tbody.appendChild(r));
  applyReviewFilter();
}}
</script>
</head><body>
<p class="back page-nav"><a href="/">← 返回首页</a> · <a href="/review">推荐复盘</a> · <a href="/worldcup">开盘套路</a> · <a href="/quant">量化回测</a></p>

<div class="card hero-card">
  <h1>📋 推荐复盘</h1>
  <p class="meta">对照「开球前最后一次竞彩推荐」与「实际赛果」· 更新 {_e(updated)}</p>
  {stats}
</div>

{user_stats}

<div class="card">
  <h2>购买档位胜率</h2>
  {tier_table}
</div>

<div class="card">
  <h2>常见失误模式</h2>
  <ul>{miss_li}</ul>
  <p class="meta">格式：竞彩推荐→实际赛果；样本越多越有参考价值。</p>
</div>

<div class="card">
  <h2>逐场对照（{len(records)} 场）</h2>
  <div class="review-toolbar">
    <button type="button" class="active" data-filter="all" onclick="filterReview('all')">全部</button>
    <button type="button" data-filter="A" onclick="filterReview('A')">A 可串</button>
    <button type="button" data-filter="B" onclick="filterReview('B')">B 可单关</button>
    <button type="button" data-filter="C" onclick="filterReview('C')">C 仅参考</button>
    <button type="button" data-filter="hit" onclick="filterReview('hit')">只看命中</button>
    <button type="button" data-filter="miss" onclick="filterReview('miss')">只看失误</button>
    <span class="review-sort-label">排序</span>
    <button type="button" class="active" data-sort="kickoff_desc" onclick="sortReview('kickoff_desc')">开球↓最新</button>
    <button type="button" data-sort="kickoff_asc" onclick="sortReview('kickoff_asc')">开球↑最早</button>
  </div>
  <div class="review-table-wrap">
  <table class="review-table">
    <thead>
      <tr>
        <th>开球</th><th>比赛</th><th>我的定稿</th><th>竞彩推荐</th><th>实际</th><th>对照</th>
        <th>档位</th><th>置信</th><th>参考研判</th><th>初盘</th><th>比分</th>
        <th>定稿</th><th>1X2</th><th>比分</th><th>亚盘</th><th>来源</th>
      </tr>
    </thead>
    <tbody>
    {rows}
    </tbody>
  </table>
  </div>
  <p class="meta">推荐取自 settle 时归档的开球前预测（runs/latest + payload）；点击比赛名可看盘口演变与 AI 记录。</p>
</div>
</body></html>"""


def html_quant_analytics(report: dict) -> str:
    acc = report or {}
    updated = acc.get("updated_at") or now_beijing_str()
    elo_sample = acc.get("elo_ratings_sample") or {}

    purchase = acc.get("purchase_jingcai") or {}
    stats = _stat_grid([
        ("完场样本", str(acc.get("total_settled") or 0)),
        ("竞彩购买胜率", _pct(purchase.get("rate_pct") or acc.get("rate_1x2_pct"))),
        ("A 可串", _pct((purchase.get("tier_a") or {}).get("rate_pct"))),
        ("B 可单关", _pct((purchase.get("tier_b") or {}).get("rate_pct"))),
        ("C 仅参考", _pct((purchase.get("tier_c") or {}).get("rate_pct"))),
        ("亚盘推荐赢盘", _pct((acc.get("ah_settled") or {}).get("rate_pct"))),
    ])

    hist = acc.get("hist_score") or {}
    model = acc.get("model_score") or {}
    ah = acc.get("ah_settled") or {}
    evp = acc.get("ev_positive") or {}

    detail_rows = [
        ("竞彩购买 整体", purchase.get("judged") or acc.get("judged_1x2"), purchase.get("hit") or acc.get("hit_1x2"), purchase.get("rate_pct") or acc.get("rate_1x2_pct")),
        ("A 可串", (purchase.get("tier_a") or {}).get("total"), (purchase.get("tier_a") or {}).get("hit"), (purchase.get("tier_a") or {}).get("rate_pct")),
        ("B 可单关", (purchase.get("tier_b") or {}).get("total"), (purchase.get("tier_b") or {}).get("hit"), (purchase.get("tier_b") or {}).get("rate_pct")),
        ("C 仅参考", (purchase.get("tier_c") or {}).get("total"), (purchase.get("tier_c") or {}).get("hit"), (purchase.get("tier_c") or {}).get("rate_pct")),
        ("历史比分 Top3", hist.get("judged"), hist.get("hit_top3"), hist.get("rate_pct")),
        ("Dixon-Coles Top3", model.get("judged"), model.get("hit_top3"), model.get("rate_pct")),
        ("亚盘推荐", ah.get("judged"), ah.get("hit"), ah.get("rate_pct")),
        ("EV&gt;3% 场次 1X2", evp.get("judged"), evp.get("hit_1x2"), evp.get("rate_pct")),
    ]
    detail_table = ""
    for label, judged, hit, rate in detail_rows:
        detail_table += (
            f"<tr><td>{label}</td><td>{judged or 0}</td><td>{hit or 0}</td><td>{_pct(rate)}</td></tr>"
        )

    source_table = _source_table(acc.get("by_source") or {})
    conf_table = _source_table(acc.get("by_confidence") or {})
    tier_table = _buy_tier_table(acc.get("by_buy_tier") or {})

    elo_rows = ""
    for team, rating in sorted(elo_sample.items(), key=lambda x: -x[1])[:12]:
        elo_rows += f"<tr><td>{_e(team)}</td><td>{rating:.0f}</td></tr>"
    if not elo_rows:
        elo_rows = "<tr><td colspan='2'>暂无 Elo 快照（完赛后自动更新）</td></tr>"

    quant_css = _shared_css("""
.hero-card { background: linear-gradient(135deg, #ecfdf5 0%, #fff 60%); border: 1px solid #bbf7d0; }
.quant-card { border-left: 4px solid #059669; }
.quant-score-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 240px), 1fr)); gap: 12px; margin: 10px 0; }
.quant-track { background: #f8fafc; border-radius: 8px; padding: 10px; border: 1px solid #e2e8f0; }
.quant-track.model-track { background: #ecfdf5; border-color: #bbf7d0; }
.quant-ev { margin: 10px 0; padding: 10px 12px; border-radius: 8px; font-size: 14px; }
.quant-ev.value-yes { background: #ecfdf5; border: 1px solid #86efac; color: #166534; }
.quant-ev.value-no { background: #f8fafc; border: 1px solid #e2e8f0; color: #475569; }
.quant-mc { margin-top: 12px; }
""")

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>量化回测</title>
<style>
{quant_css}
</style>
</head><body>
<p class="back page-nav"><a href="/">← 返回首页</a> · <a href="/worldcup">开盘套路</a> · <a href="/daily">当日推荐</a> · <a href="/handicap">亚盘赢盘</a> · <a href="/quant">量化回测</a> · <a href="/kelly">Kelly</a></p>

<div class="card hero-card">
  <h1>📈 量化回测</h1>
  <p class="meta">Dixon-Coles 比分 · Elo 强度 · 竞彩 EV · 小组 MC · 更新 {_e(updated)}</p>
  {stats}
</div>

<div class="card">
  <h2>回测明细</h2>
  <table>
    <tr><th>维度</th><th>样本</th><th>命中</th><th>命中率</th></tr>
    {detail_table}
  </table>
  <p class="meta">历史比分取推荐时 likely_scores 前三；模型比分取 Dixon-Coles Top3；正 EV 阈值为 EV&gt;3%。</p>
</div>

<div class="card">
  <h2>1X2 按购买档位</h2>
  {tier_table}
  <p class="meta">A=可串 · B=可单关 · C=仅参考；统计对象为竞彩可购方向。</p>
</div>

<div class="card">
  <h2>1X2 按来源 / 置信度</h2>
  <h4>按推荐来源</h4>
  {source_table}
  <h4>按置信度</h4>
  {conf_table}
</div>

<div class="card">
  <h2>Elo 强度（样本）</h2>
  <table>
    <tr><th>球队</th><th>Rating</th></tr>
    {elo_rows}
  </table>
  <p class="meta">种子来自 wc2026 档位，完场后自动迭代更新。</p>
</div>

<p class="meta" style="margin-top:20px">公益体彩 量力而行 · 仅供参考 不构成投注建议</p>
</body></html>"""


def _divergence_teaser(output_root: Path) -> str:
    try:
        from eu_ah_divergence import build_divergence_report

        report = build_divergence_report(output_root)
        rows = report.get("matches") or []
        if not rows:
            return ""
        huge = sum(1 for r in rows if r.get("severity") == "extreme")
        top = rows[0]
        hint = (
            f"最大分歧：{_e(top.get('match'))}（{top.get('divergence_score')} 分，"
            f"{_e(top.get('severity_cn'))}）"
        )
        return f"""
<div class="card" style="border-left:4px solid #dc2626;margin-bottom:14px">
  <p style="margin:0"><a href="/divergence"><strong>⚡ 欧亚分歧</strong></a>
     <span class="meta"> · {len(rows)} 场需关注 · {huge} 场巨大分歧</span></p>
  <p class="meta" style="margin:6px 0 0">{hint}</p>
</div>"""
    except Exception:
        return ""


def html_eu_ah_divergence(report: dict) -> str:
    rows_data = report.get("matches") or []
    notes = "".join(f"<li>{_e(x)}</li>" for x in (report.get("notes") or []))
    min_score = report.get("min_score", 45)
    updated = report.get("updated_at") or now_beijing_str()

    if not rows_data:
        table = "<p class='meta empty-hint'>当前窗口内暂无达到阈值的欧亚分歧场次。</p>"
    else:
        trs = ""
        for r in rows_data:
            sev = r.get("severity") or "major"
            sev_cls = {"extreme": "sev-extreme", "major": "sev-major", "moderate": "sev-mod"}.get(sev, "")
            sigs = " · ".join(_e(x) for x in (r.get("signals") or [])[:3]) or "—"
            fid = r.get("fixture_id") or ""
            trs += f"""
<tr class="{sev_cls}">
  <td><span class="score-badge">{r.get('divergence_score', 0)}</span><br><span class="meta">{_e(r.get('severity_cn'))}</span></td>
  <td><a href="/match/{_e(fid)}">{_e(r.get('match'))}</a><br><span class="meta">{_e(r.get('kickoff'))}</span></td>
  <td>{_e(r.get('consistency_cn'))}<br><span class="meta">gap {_e(r.get('line_gap'))}</span></td>
  <td><span class="meta">欧→亚</span> {_e(r.get('eu_to_ah_line_cn'))}<br><span class="meta">实际</span> {_e(r.get('ah_line_cn'))}</td>
  <td><span class="meta">初欧</span> {_e(r.get('open_eu'))}<br><span class="meta">临欧</span> {_e(r.get('live_eu'))}</td>
  <td><span class="meta">初亚</span> {_e(r.get('open_ah'))}<br><span class="meta">临亚</span> {_e(r.get('live_ah'))}</td>
  <td class="sig-cell">{sigs}<p class="meta advice">{_e(r.get('advice') or '')}</p></td>
</tr>"""
        table = f"""<table>
<tr><th>分歧分</th><th>比赛</th><th>类型</th><th>盘口对照</th><th>欧赔</th><th>亚盘</th><th>信号 / 建议</th></tr>
{trs}
</table>"""

    div_css = _shared_css("""
.hero-card { background: linear-gradient(135deg, #fef2f2 0%, #fff 55%); border: 1px solid #fecaca; }
.sev-extreme td:first-child { background: #fef2f2; }
.sev-major td:first-child { background: #fff7ed; }
.score-badge { font-size: 1.25rem; font-weight: 800; color: #b91c1c; }
.sig-cell { font-size: 13px; line-height: 1.5; max-width: 280px; }
.sig-cell .advice { margin: 6px 0 0; color: #475569; }
""")

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>欧亚分歧扫描</title>
<style>
{div_css}
</style>
</head><body>
<p class="back page-nav"><a href="/">← 返回首页</a> · <a href="/worldcup">开盘套路</a> · <a href="/daily">当日推荐</a> · <a href="/handicap">亚盘赢盘</a> · <a href="/quant">量化回测</a> · <a href="/kelly">Kelly</a></p>

<div class="card hero-card">
  <h1>⚡ 欧亚分歧扫描</h1>
  <p class="meta">{_e(report.get('headline') or '')} · 阈值 ≥{min_score} 分 · 更新 {_e(updated)}</p>
  <p class="meta">扫描 {report.get('scanned', 0)} 场赛程 · 本地计算，不调用 AI</p>
</div>

<div class="card">
  <h2>分歧场次（按分数降序）</h2>
  {table}
</div>

<div class="card">
  <h3>说明</h3>
  <ul class="meta">{notes or '<li>—</li>'}</ul>
</div>

<p class="meta" style="margin-top:20px">公益体彩 量力而行 · 仅供参考 不构成投注建议</p>
</body></html>"""


def html_ai_settings(config: dict) -> str:
    import json as _json

    cfg_json = _json.dumps(config, ensure_ascii=False)
    cfg_path = config.get("config_path") or "（将写入 output/service/ai_config.json）"
    settings_css = _shared_css("""
.hero-card { background: linear-gradient(135deg, #eef2ff 0%, #fff 55%); border: 1px solid #c7d2fe; }
.ai-global { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 220px), 1fr)); gap: 12px; }
.ai-global label { display:block; font-size:13px; color:#475569; margin-bottom:4px; }
.ai-global select { width:100%; padding:8px 10px; border:1px solid #cbd5e1; border-radius:8px; }
.provider-grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 340px), 1fr)); gap:12px; }
.provider-card { border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; background:#fff; }
.provider-card.off { opacity:.72; background:#f8fafc; }
.provider-head { display:flex; justify-content:space-between; align-items:center; gap:8px; margin-bottom:10px; }
.provider-head h3 { margin:0; font-size:1rem; }
.status-pill { font-size:11px; font-weight:700; padding:3px 10px; border-radius:999px; }
.status-ok { background:#dcfce7; color:#166534; }
.status-bad { background:#fee2e2; color:#991b1b; }
.field { margin:8px 0; }
.field label { display:block; font-size:12px; color:#64748b; margin-bottom:3px; }
.field input[type=text] { width:100%; padding:7px 9px; border:1px solid #cbd5e1; border-radius:8px; font-size:13px; }
.roles { display:flex; flex-wrap:wrap; gap:8px 12px; margin-top:6px; }
.roles label { font-size:12px; color:#334155; }
.toolbar { display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin:16px 0; }
#save-status { font-size:13px; color:#64748b; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size:12px; }
""")

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>AI 模型设置</title>
<style>{settings_css}</style>
</head><body>
<p class="back page-nav"><a href="/">← 返回首页</a> · <a href="/daily">当日推荐</a> · <a href="/divergence">欧亚分歧</a></p>

<div class="card hero-card">
  <h1>🤖 AI 模型设置</h1>
  <p class="meta">在此调整启用状态、模型 ID、用途角色；<strong>API Key 仍在 .env / local_secrets.py</strong>，不会写入配置文件。</p>
  <p class="meta">当前配置来源：<code class="mono">{_e(cfg_path)}</code></p>
</div>

<div class="card">
  <h2>全局</h2>
  <div class="ai-global">
    <div>
      <label for="primary-id">主模型 primary_id</label>
      <select id="primary-id"></select>
    </div>
    <div>
      <label for="predict-mode">预测模式 predict_mode</label>
      <select id="predict-mode">
        <option value="multi">multi — 全部已启用模型</option>
        <option value="single">single — 仅主模型</option>
        <option value="primary_only">primary_only — 同 single</option>
      </select>
    </div>
  </div>
</div>

<div class="card">
  <h2>Provider 列表</h2>
  <div id="provider-grid" class="provider-grid"></div>
</div>

<div class="toolbar">
  <button type="button" class="btn" id="save-btn">保存配置</button>
  <button type="button" class="btn" style="background:#64748b" onclick="location.reload()">重新加载</button>
  <span id="save-status"></span>
</div>

<div class="card">
  <h3>说明</h3>
  <ul class="meta">
    <li><code>predict</code>：单场 AI 推荐 / 整点分析</li>
    <li><code>chat</code>：首页/单场人工对话</li>
    <li><code>parlay</code>：列表 AI 2串1</li>
    <li>Kimi 需在配置中启用且设置 <code>AI_ENABLE_KIMI=1</code></li>
    <li>保存后写入 <code>output/service/ai_config.json</code>，立即对新请求生效（无需重启）</li>
  </ul>
</div>

<script>
let AI_CFG = {cfg_json};

const ALL_ROLES = ['predict', 'chat', 'parlay', 'daily', 'watch'];

function esc(s) {{
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;');
}}

function renderProviders() {{
  const grid = document.getElementById('provider-grid');
  const primary = document.getElementById('primary-id');
  grid.innerHTML = '';
  primary.innerHTML = '';
  (AI_CFG.providers || []).sort((a,b) => (a.order||999)-(b.order||999)).forEach(p => {{
    const opt = document.createElement('option');
    opt.value = p.id;
    opt.textContent = p.label || p.id;
    primary.appendChild(opt);
    const roles = p.roles || [];
    const roleChecks = ALL_ROLES.map(r => {{
      const checked = roles.includes(r) ? 'checked' : '';
      return `<label><input type="checkbox" data-role="${{r}}" data-pid="${{esc(p.id)}}" ${{checked}}/> ${{r}}</label>`;
    }}).join('');
    const card = document.createElement('div');
    card.className = 'provider-card' + (p.enabled ? '' : ' off');
    card.innerHTML = `
      <div class="provider-head">
        <h3>${{esc(p.label || p.id)}} <span class="meta">(${{esc(p.id)}})</span></h3>
        <span class="status-pill ${{p.configured ? 'status-ok' : 'status-bad'}}">${{p.configured ? '密钥已配置' : '未配置密钥'}}</span>
      </div>
      <label><input type="checkbox" class="en-check" data-pid="${{esc(p.id)}}" ${{p.enabled ? 'checked' : ''}}/> 启用</label>
      <div class="field"><label>model</label><input type="text" class="model-inp" data-pid="${{esc(p.id)}}" value="${{esc(p.model||'')}}"/></div>
      <div class="field"><label>base_url</label><input type="text" class="url-inp" data-pid="${{esc(p.id)}}" value="${{esc(p.base_url||'')}}"/></div>
      <div class="field"><label>api_key_env</label><input type="text" class="env-inp" data-pid="${{esc(p.id)}}" value="${{esc(p.api_key_env||'')}}"/></div>
      <div class="roles">${{roleChecks}}</div>
      <button type="button" class="btn btn-sm test-btn" data-pid="${{esc(p.id)}}" style="margin-top:10px">测试连通</button>
      <span class="meta test-out" data-pid="${{esc(p.id)}}"></span>`;
    grid.appendChild(card);
  }});
  primary.value = AI_CFG.primary_id || (AI_CFG.providers[0] && AI_CFG.providers[0].id) || '';
  document.getElementById('predict-mode').value = AI_CFG.predict_mode || 'multi';
}}

function collectConfig() {{
  const providers = (AI_CFG.providers || []).map(p => {{
    const pid = p.id;
    const roles = [];
    document.querySelectorAll(`input[data-role][data-pid="${{pid}}"]`).forEach(el => {{
      if (el.checked) roles.push(el.getAttribute('data-role'));
    }});
    const enabledEl = document.querySelector(`.en-check[data-pid="${{pid}}"]`);
    const modelEl = document.querySelector(`.model-inp[data-pid="${{pid}}"]`);
    const urlEl = document.querySelector(`.url-inp[data-pid="${{pid}}"]`);
    const envEl = document.querySelector(`.env-inp[data-pid="${{pid}}"]`);
    return {{
      ...p,
      enabled: enabledEl ? enabledEl.checked : p.enabled,
      model: modelEl ? modelEl.value.trim() : p.model,
      base_url: urlEl ? urlEl.value.trim() : p.base_url,
      api_key_env: envEl ? envEl.value.trim() : p.api_key_env,
      roles,
    }};
  }});
  return {{
    version: AI_CFG.version || 1,
    primary_id: document.getElementById('primary-id').value,
    predict_mode: document.getElementById('predict-mode').value,
    multi: AI_CFG.multi || {{ on_disagreement: 'skip' }},
    providers,
  }};
}}

document.getElementById('save-btn').addEventListener('click', async () => {{
  const status = document.getElementById('save-status');
  status.textContent = '保存中…';
  try {{
    const body = collectConfig();
    const r = await fetch('/api/ai/config', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify(body),
    }});
    const d = await r.json();
    if (!d.ok) throw new Error((d.errors && d.errors.join('; ')) || d.error || '保存失败');
    AI_CFG = d.config || body;
    renderProviders();
    status.textContent = '已保存 → ' + (d.path || '');
  }} catch (e) {{
    status.textContent = '失败: ' + e.message;
  }}
}});

document.getElementById('provider-grid').addEventListener('click', async ev => {{
  const btn = ev.target.closest('.test-btn');
  if (!btn) return;
  const pid = btn.getAttribute('data-pid');
  const out = document.querySelector(`.test-out[data-pid="${{pid}}"]`);
  out.textContent = ' 测试中…';
  try {{
    const r = await fetch('/api/ai/test', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ provider_id: pid }}),
    }});
    const d = await r.json();
    out.textContent = d.ok ? (' ✓ ' + (d.sample || 'OK')) : (' ✗ ' + (d.error || '失败'));
  }} catch (e) {{
    out.textContent = ' ✗ ' + e.message;
  }}
}});

renderProviders();
</script>
</body></html>"""


def _build_match_strategy_panel(match_name: str, prediction: dict | None = None) -> str:
    from knockout_path import build_match_knockout_context

    ctx = build_match_knockout_context(match_name)
    if not ctx or not ctx.get("same_group"):
        return ""

    group = ctx.get("group")
    standings = ctx.get("standings") or []
    st_rows = ""
    for r in standings:
        st_rows += (
            f"<tr><td>{r.get('rank')}</td><td><strong>{_e(r.get('team'))}</strong></td>"
            f"<td>{r.get('points')}</td><td>{r.get('gd'):+d}</td><td>{r.get('played')}</td></tr>"
        )

    home = (ctx.get("home_knockout") or {}).get("team") or ""
    away = (ctx.get("away_knockout") or {}).get("team") or ""
    if not home or not away:
        from share_card import split_teams
        from wc_standings_fetch import normalize_team
        hr, ar = split_teams(match_name)
        home, away = normalize_team(hr), normalize_team(ar)

    home_path = _path_block(home, ctx.get("home_knockout") or {})
    away_path = _path_block(away, ctx.get("away_knockout") or {})

    sc_rows = ""
    for s in ctx.get("scenarios") or []:
        sc_rows += (
            f"<tr><td>{_e(s.get('label'))}</td>"
            f"<td>{_e(s.get('score_effect'))}</td>"
            f"<td class='meta'>{_e(s.get('note'))}</td></tr>"
        )

    hint = ctx.get("prediction_hint") or {}
    mot = ctx.get("motivation") or {}
    mt = hint.get("match_type_cn") or mot.get("match_type_cn") or "—"
    tag_cls = _motivation_tag(mot.get("match_type") or "normal")

    pred_1x2 = {"home": "主胜", "away": "客胜", "draw": "平局", "none": "观望"}.get(
        hint.get("model_1x2_hint") or "none", "—",
    )

    notes = hint.get("notes") or []
    note_p = "".join(f"<p class='meta' style='margin:4px 0'>{_e(x)}</p>" for x in notes[:4])

    bracket_notes = "".join(f"<li>{_e(x)}</li>" for x in (ctx.get("bracket_notes") or [])[:2])

    from knockout_path import build_group_bracket_overview

    go = build_group_bracket_overview(group)
    g1, g2 = go.get("first") or {}, go.get("second") or {}
    group_strip = f"""
<div class="group-bracket-strip">
  <span class="meta">{_e(group)}组固定签位：</span>
  <span class="bracket-chip r32">头名 → {_e(g1.get('r32_summary') or '—')}</span>
  <span class="bracket-chip r32">第二 → {_e(g2.get('r32_summary') or '—')}</span>
  <span class="meta">（同组两队末轮可能为争/让名次而控分）</span>
</div>"""

    home_pref = (ctx.get("home_knockout") or {}).get("preferred_path_cn") or "—"
    away_pref = (ctx.get("away_knockout") or {}).get("preferred_path_cn") or "—"
    pick_compare = ""
    if home_pref != away_pref and ctx.get("picking_level") in ("watch", "medium", "high"):
        pick_compare = (
            f"<p class='meta picking-warn'>⚠ 同组路径分化：{_e(home)} 更优为<strong>{_e(home_pref)}</strong>，"
            f"{_e(away)} 更优为<strong>{_e(away_pref)}</strong>——平局或小胜可能同时满足双方「挑对手」动机。</p>"
        )

    rs = ctx.get("round_summary") or {}
    stage = rs.get("stage_label") or ""
    gr = ctx.get("group_race") or {}
    chaos = gr.get("chaos") or {}
    chaos_banner = ""
    if chaos.get("summary"):
        cls = "chaos-high" if chaos.get("chaos_level") == "high" else "chaos-med"
        chaos_banner = (
            f"<div class='group-chaos-banner {cls}'>"
            f"<strong>{_e(chaos.get('chaos_level_cn') or '小组形势')}</strong> "
            f"{_e(chaos.get('summary'))}</div>"
        )

    return f"""
<div class="card strategy-card">
  <div class="strategy-head">
    <h3>⚔️ 小组形势 · 淘汰赛路径</h3>
    <span class="chip chip-grp">{_e(group)} 组</span>
    <span class="meta">{_e(stage)}</span>
    <a class="btn btn-sm" href="/worldcup/groups">全组看板 →</a>
  </div>
{chaos_banner}

  <div class="strategy-grid">
    <div class="strategy-col">
      <h4>{_e(group)} 组积分榜</h4>
      <table class="mini">
        <tr><th>#</th><th>球队</th><th>分</th><th>净</th><th>赛</th></tr>
        {st_rows}
      </table>
    </div>
    <div class="strategy-col prediction-col">
      <h4>战意预测</h4>
      <p><span class="tag {tag_cls}">{_e(mt)}</span>
         <span class="tag">挑对手 {_e(ctx.get('picking_level_cn'))}</span></p>
      <p><strong>倾向</strong> {_e(hint.get('likely_direction_cn'))}
         · <strong>模型方向</strong> {_e(pred_1x2)}
         · <strong>亚盘</strong> {_e(hint.get('ah_hint') or '—')}</p>
      {note_p}
      {pick_compare}
      <p class="meta picking-warn">{_e(hint.get('picking_note') or '')}</p>
    </div>
  </div>

  {group_strip}

  <div class="path-grid">
    {home_path}
    {away_path}
  </div>

  <h4>本场赛果推演（积分）</h4>
  <table class="mini">
    <tr><th>赛果</th><th>赛后积分</th><th>战意解读</th></tr>
    {sc_rows}
  </table>

  <details class="bracket-notes">
    <summary>32强签位说明（FIFA 固定路径 + 第三待定）</summary>
    <ul class="meta">{bracket_notes}</ul>
  </details>
</div>"""


def _qualification_divergence_banner(prediction: dict | None) -> str:
    if not prediction:
        return ""
    qd = prediction.get("qualification_divergence") or {}
    if not qd.get("tag"):
        return ""
    signals = qd.get("signals") or []
    sig_txt = "；".join(signals[:3])
    return f"""
<div class="qual-div-banner">
  <strong>{_e(qd.get('tag'))}</strong>
  <span class="meta">{_e(qd.get('group_context_cn'))} · {_e(qd.get('consistency_cn'))} · {_e(qd.get('divergence_score'))} 分</span>
  <p>{_e(qd.get('advice'))}</p>
  {f"<p class='meta'>{_e(sig_txt)}</p>" if sig_txt else ""}
</div>"""


def _buy_tier_banner(prediction: dict | None) -> str:
    if not prediction:
        return ""
    row = prediction.get("predict_row") or {}
    cn = prediction.get("buy_tier_cn") or row.get("购买档位") or ""
    if not cn:
        return ""
    reason = prediction.get("buy_tier_reason") or row.get("档位说明") or ""
    css = {"可串": "tier-a", "可单关": "tier-b", "仅参考": "tier-c"}.get(cn, "tier-c")
    parlay_hint = " · 可加入 2串1" if prediction.get("parlay_eligible") else " · 串关请优先选「可串」"
    return f"""
<div class="card buy-tier-banner buy-tier-{css}">
  <h3>购买档位 · {_e(cn)}{_e(parlay_hint)}</h3>
  <p>{_e(reason) if reason else '—'}</p>
</div>"""


def html_match_detail(
    index: dict,
    *,
    prediction: dict | None = None,
    ai_records: list[dict] | None = None,
    deep_records: list[dict] | None = None,
    settled: dict | None = None,
    output_root: Path | None = None,
) -> str:
    fid = index.get("fixture_id", "")
    name = index.get("match_name") or fid
    timeline = index.get("timeline") or []
    changes = index.get("changes") or []

    pred_card = _wrap_export_module("recommend", _build_pred_cards(prediction))
    settled_card = _wrap_export_module("settled", _settled_card(settled))
    strategy_panel = _wrap_export_module("strategy", _build_match_strategy_panel(name, prediction))
    sweet_spot_panel = _wrap_export_module("sweet-spot", _sweet_spot_panel(prediction))
    score_rec_panel = _score_recommend_panel(prediction)
    quant_panel = _wrap_export_module("quant", _quant_panel(prediction))
    ah_card = _wrap_export_module("handicap", _build_ah_analysis_card(prediction, timeline))
    latest_deep = (deep_records or [None])[0]
    deep_card = _wrap_export_module("deep", _deep_analysis_card(latest_deep))

    from ai_deep_analysis import has_prior_ai_analysis

    fid_for_prior = index.get("fixture_id", "")
    has_prior = has_prior_ai_analysis(
        prediction, ai_records,
        output_root=output_root,
        fixture_id=str(fid_for_prior or fid),
        index=index,
    )
    deep_btn = (
        f'<button type="button" class="btn btn-deep" data-label="🔍 AI 深度分析" '
        f'onclick="aiDeepAnalyze(\'{_e(fid)}\', this)">🔍 AI 深度分析</button>'
    )
    if has_prior:
        deep_hint = (
            '<span class="meta deep-gate-hint" style="margin-left:8px">'
            '基于已有首轮 AI 做二次综合</span>'
        )
    else:
        deep_hint = (
            '<span class="meta deep-gate-hint" style="margin-left:8px">'
            '一键分析：自动跑首轮 AI + 深度综合（约 1–3 分钟）</span>'
        )
    deep_btn += deep_hint

    src = index.get("source") or "file"
    db_n = index.get("db_points")
    file_n = index.get("file_points")
    src_bits = []
    if src == "merged":
        src_bits.append(f"合并时间线 poll {db_n or 0} + AI {file_n or 0} 点")
    elif src == "postgresql":
        src_bits.append("赔率来自 poll")
    else:
        src_bits.append("推荐来自文件")
    last_ts = format_ts(index.get("updated_at") or (timeline[-1].get("ts") if timeline else None))
    freshness = f"<p class='meta freshness'>{' · '.join(src_bits)} · 最新 {_e(last_ts)} · 北京时间</p>"
    qual_banner = _wrap_export_module("qual", _qualification_divergence_banner(prediction))
    tier_banner = _wrap_export_module("tier", _buy_tier_banner(prediction))

    jingcai_card = _jingcai_card(_latest_jingcai(timeline), prediction)
    bf = _latest_betfair(timeline)
    betfair_card = _betfair_card(bf)
    bf_charts = _betfair_chart_data(timeline, bf)
    eu_multi = build_eu_multi_chart_data(timeline)
    has_bf_trend = bool(bf_charts.get("trend_labels"))
    has_bf_poll = bool(bf_charts.get("poll_labels"))
    has_eu_multi = bool(eu_multi.get("labels")) and bool(eu_multi.get("books"))
    implied_card = _implied_card(
        eu_multi.get("latest_implied") if has_eu_multi else None,
        prediction=prediction,
    )

    labels = [chart_time_label(p.get("ts") or p.get("hour")) for p in timeline]
    eu_h = [(p.get("odds") or {}).get("eu_home") for p in timeline]
    eu_d = [(p.get("odds") or {}).get("eu_draw") for p in timeline]
    eu_a = [(p.get("odds") or {}).get("eu_away") for p in timeline]
    ah_l = [(p.get("odds") or {}).get("ah_line") for p in timeline]
    ah_hw = [(p.get("odds") or {}).get("ah_home_water") for p in timeline]
    ah_aw = [(p.get("odds") or {}).get("ah_away_water") for p in timeline]

    tbl_rows = ""
    for p in timeline:
        o, pk = p.get("odds") or {}, p.get("pick") or {}
        bf_row = o.get("betfair") or {}
        pct = bf_row.get("volume_pct") or {}
        bf_txt = "—"
        if bf_row.get("has_data"):
            bf_txt = f"{pct.get('home', '—')}/{pct.get('draw', '—')}/{pct.get('away', '—')}%"
        ai_pk = pk.get("ai_analyses")
        if ai_pk:
            rec_txt = "<br>".join(
                f"<strong>{_e(a.get('label', k))}</strong>: {_e(a.get('result_1x2_cn'))}"
                for k, a in ai_pk.items()
            )
        else:
            rec_txt = f"<strong>{_e(pk.get('result_1x2_cn'))}</strong>"
        tbl_rows += (
            f"<tr><td>{_e(format_ts(p.get('ts')))}</td>"
            f"<td>{_e(o.get('ah_line'))}</td>"
            f"<td>{_e(o.get('ah_home_water'))}/{_e(o.get('ah_away_water'))}</td>"
            f"<td>{_e(o.get('eu_home'))}/{_e(o.get('eu_draw'))}/{_e(o.get('eu_away'))}</td>"
            f"<td>{bf_txt}</td>"
            f"<td>{rec_txt}</td>"
            f"<td>{_e(pk.get('likely_scores'))}</td>"
            f"<td>{_e(pk.get('confidence_cn'))}</td></tr>\n"
        )

    ch_rows = ""
    for c in reversed(changes[-20:]):
        ch_rows += (
            f"<tr class='chg'><td>{_e(format_ts(c.get('ts')))}</td>"
            f"<td>{_e(c.get('field'))}</td>"
            f"<td>{_e(c.get('from'))}</td><td>→</td><td><strong>{_e(c.get('to'))}</strong></td></tr>\n"
        )
    if not ch_rows:
        ch_rows = "<tr><td colspan='5'>暂无变动（需至少 2 个整点快照）</td></tr>"

    chart_data = json.dumps({
        "labels": labels,
        "eu_h": eu_h, "eu_d": eu_d, "eu_a": eu_a,
        "ah_l": ah_l, "ah_hw": ah_hw, "ah_aw": ah_aw,
        **bf_charts,
    }, ensure_ascii=False, default=_json_default)

    bf_charts_inner = ""
    if has_bf_trend or has_bf_poll:
        if has_bf_trend:
            bf_charts_inner += '<div class="card inner"><h4>必发占比（单场）</h4><canvas id="bfTrendChart"></canvas></div>'
        if has_bf_poll:
            bf_charts_inner += '<div class="card inner"><h4>必发占比（poll）</h4><canvas id="bfPollChart"></canvas></div>'
        bf_charts_inner = f'<div class="grid">{bf_charts_inner}</div>'

    market_fold = _fold(
        "竞彩 · 必发 · 隐含概率",
        jingcai_card + implied_card + betfair_card,
        muted=True,
        export_slug="market",
    )
    charts_fold = _fold(
        "欧赔 & 亚盘走势",
        """<div class="grid">
  <div class="card inner"><h4>欧赔（主盘汇总）</h4><canvas id="euChart"></canvas></div>
  <div class="card inner"><h4>亚盘</h4><canvas id="ahChart"></canvas></div>
</div>""",
        open=True,
        export_slug="charts",
    )
    bf_fold = _fold("必发占比走势", bf_charts_inner, muted=True, export_slug="betfair") if bf_charts_inner else ""
    changes_fold = _fold(
        f"推荐变动（{len(changes)} 次）",
        f"""<table>
    <tr><th>时间</th><th>项目</th><th>原值</th><th></th><th>新值</th></tr>
    {ch_rows}
  </table>""",
        muted=True,
        export_slug="changes",
    )
    snapshot_fold = _fold(
        f"Poll 快照明细（{len(timeline)} 条）",
        f"""<table>
    <tr><th>时间</th><th>亚盘</th><th>水位</th><th>欧赔</th><th>必发%</th><th>推荐</th><th>比分</th><th>置信</th></tr>
    {tbl_rows}
  </table>""",
        muted=True,
        export_slug="snapshot",
    )
    ai_body = _build_ai_history_html(ai_records)
    ai_fold = _fold(
        f"AI 分析记录（{len(ai_records or [])} 次）",
        ai_body,
        muted=True,
        export_slug="ai-records",
    ) if ai_body else ""
    deep_hist = _build_deep_history_html(deep_records)
    deep_fold = _fold(
        f"深度分析历史（{len(deep_records or [])} 次）",
        deep_hist,
        muted=True,
        export_slug="deep-history",
    ) if deep_hist else ""
    similar_body = _build_similarity_html(prediction, fixture_id=fid, output_root=output_root)
    similar_fold = _fold(
        "历史相似盘口 Top10（初盘 / 实时盘）",
        similar_body,
        open=True,
        export_slug="similar",
    ) if similar_body else ""
    team_form_fold = _team_form_fold_html(name)

    match_css = _shared_css("""
.card.inner { box-shadow: none; border: 1px solid #e2e8f0; padding: 12px; margin: 0; }
.pick { font-size: clamp(1rem, 3.5vw, 1.15rem); }
.pred-card { border-left: 4px solid #7c3aed; }
.deep-card { border-left: 4px solid #0d9488; }
.deep-headline { font-size: clamp(1.05rem, 3.5vw, 1.2rem); font-weight: 600; color: #0f766e; margin: 0 0 8px; }
.deep-section { margin: 10px 0; }
.deep-section h4 { margin: 0 0 4px; font-size: 13px; color: #475569; }
.deep-list { margin: 4px 0 0 16px; padding: 0; }
.deep-list li { margin: 2px 0; font-size: 13px; color: #334155; }
.btn-deep { background: #0d9488; }
.btn-deep:disabled { background: #94a3b8; opacity: 0.7; cursor: not-allowed; }
.settled-card { border-left: 4px solid #059669; }
.ah-card { border-left: 4px solid #7c3aed; margin-bottom: 12px; }
.ah-stats-table { margin-top: 10px; }
.strategy-card { border-left: 4px solid #059669; margin-bottom: 14px; }
.quant-card { border-left: 4px solid #059669; margin-bottom: 14px; }
.score-rec-card { border-left: 4px solid #ea580c; margin-bottom: 14px; }
.sweet-spot-card { border-left: 4px solid #ea580c; margin-bottom: 14px; }
.sweet-spot-card.sweet-in { border-left-color: #c2410c; background: linear-gradient(135deg,#fffbf5,#fff7ed); }
.sweet-spot-card.sweet-below { border-left-color: #059669; }
.sweet-spot-card.sweet-above { border-left-color: #d97706; }
.sweet-headline { font-size: 1.05rem; margin: 8px 0; }
.sweet-check-table .chk-ok td:first-child { color: #047857; font-weight: 700; }
.sweet-check-table .chk-bad td:first-child { color: #b91c1c; font-weight: 700; }
.sweet-verdict { margin: 10px 0 6px; font-size: 14px; color: #1e293b; }
.score-headline { font-size: 1.05rem; margin: 8px 0; }
.score-rec-table .score-cell { font-size: 1.1rem; letter-spacing: 0.02em; }
.score-track-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 220px), 1fr)); gap: 8px; margin: 10px 0; font-size: 0.92rem; }
.quant-score-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 240px), 1fr)); gap: 12px; margin: 10px 0; }
.quant-track { background: #f8fafc; border-radius: 8px; padding: 10px; border: 1px solid #e2e8f0; }
.quant-track.model-track { background: #ecfdf5; border-color: #bbf7d0; }
.quant-ev { margin: 10px 0; padding: 10px 12px; border-radius: 8px; font-size: 14px; }
.quant-ev.value-yes { background: #ecfdf5; border: 1px solid #86efac; color: #166534; }
.quant-ev.value-no { background: #f8fafc; border: 1px solid #e2e8f0; color: #475569; }
.quant-mc { margin-top: 12px; }
.strategy-head { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 12px; }
.strategy-head h3 { margin: 0; flex: 1; min-width: min(100%, 200px); }
.strategy-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr)); gap: 14px; margin-bottom: 14px; }
.path-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr)); gap: 14px; margin-bottom: 14px; }
.path-block { background: #f8fafc; border-radius: 10px; padding: 12px; border: 1px solid #e2e8f0; }
.path-block h4 { margin: 0 0 8px; font-size: 14px; }
.path-notes { margin: 8px 0 0 16px; padding: 0; line-height: 1.55; }
.bracket-lane { margin: 10px 0 12px; padding: 10px; background: #fff; border: 1px dashed #cbd5e1; border-radius: 8px; }
.lane-title { font-size: 12px; color: #64748b; margin-bottom: 8px; }
.bracket-node { padding: 6px 10px; border-radius: 6px; font-size: 13px; text-align: center; }
.bracket-node.group { background: #ede9fe; color: #5b21b6; }
.bracket-node.r32 { background: #dcfce7; color: #166534; }
.bracket-node.r16 { background: #fee2e2; color: #991b1b; }
.bracket-node.half, .bracket-node.note { background: #f1f5f9; color: #475569; font-size: 12px; }
.bracket-connector { text-align: center; color: #94a3b8; line-height: 1.2; font-size: 12px; }
.path-row-preferred td { background: #ecfdf5; font-weight: 600; }
.prediction-col { background: #fffbeb; border: 1px solid #fde68a; border-radius: 10px; padding: 12px; }
.picking-warn { color: #92400e; }
.bracket-notes { margin-top: 12px; font-size: 13px; }
.group-bracket-strip { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 12px;
  padding: 10px; background: #f0fdf4; border-radius: 8px; border: 1px solid #bbf7d0; }
.group-chaos-banner { margin: 0 0 12px; padding: 10px 12px; border-radius: 8px; font-size: 13px; line-height: 1.5; }
.group-chaos-banner.chaos-high { background: #fff7ed; border: 1px solid #fdba74; color: #9a3412; }
.group-chaos-banner.chaos-med { background: #eff6ff; border: 1px solid #93c5fd; color: #1e40af; }
.race-badge { font-size: 12px; padding: 6px 10px; border-radius: 8px; margin: 0 0 8px; }
.race-badge.race-lock { background: #ecfdf5; color: #166534; border: 1px solid #86efac; }
.race-badge.race-fight { background: #fef3c7; color: #92400e; border: 1px solid #fcd34d; }
.race-badge.race-out { background: #f1f5f9; color: #64748b; border: 1px solid #e2e8f0; }
.likely-r32 { background: #f0fdf4; padding: 8px 10px; border-radius: 6px; margin-bottom: 8px; }
.likely-opp-table { margin-top: 8px; }
.bracket-chip { display: inline-block; padding: 4px 10px; border-radius: 999px; font-size: 12px; }
.bracket-chip.r32 { background: #dcfce7; color: #166534; }
.rec-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr)); gap: 12px; margin-bottom: 12px; }
.dual-hint { color: #b45309; background: #fffbeb; padding: 8px 12px; border-radius: 6px; }
canvas { max-height: 260px; }
tr.chg td { background: #fffbeb; }
.style-clash-banner { margin-bottom: 8px; line-height: 1.5; }
.style-clash-banner strong { color: #92400e; }
.similar-block { overflow-x: auto; }
.similar-block table { min-width: min(960px, 100%); }
.similar-block .tag { margin-bottom: 4px; }
.similar-head { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 8px; }
.similar-head h4 { margin: 0; flex: 1; min-width: min(100%, 200px); }
.similar-ai-btn { font-size: 12px; padding: 5px 10px; white-space: nowrap; }
.similar-ai-out { margin: 10px 0; }
.similar-ai-box { background: #f5f3ff; border: 1px solid #ddd6fe; border-radius: 10px; padding: 10px 12px; }
.similar-ai-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; margin-bottom: 6px; }
.similar-ai-top strong { color: #5b21b6; font-size: 14px; line-height: 1.35; }
.similar-ai-pick { margin: 0 0 8px; font-size: 13px; }
.similar-ai-ev { margin: 6px 0; padding-left: 18px; font-size: 12px; color: #475569; line-height: 1.45; }
.similar-ai-action { margin: 8px 0 0; font-size: 13px; font-weight: 600; color: #6d28d9; }
.similar-ai-err { color: #b91c1c; }
h4 { margin: 0 0 8px; font-size: 13px; color: #475569; }
.export-hero h1 { margin: 0 0 6px; font-size: clamp(1.15rem, 4vw, 1.45rem); }
.export-footer { margin-top: 16px; padding-top: 10px; border-top: 1px dashed #cbd5e1; text-align: center; font-size: 11px; color: #64748b; }
#match-export-root { background: #f8fafc; padding: 4px 0 8px; }
.export-chart-img { border-radius: 8px; background: #fff; max-width: 100%; }
""" + AI_SUMMARY_POSTER_CSS)

    safe_name = re.sub(r"[^\w\-]+", "_", name).strip("_") or fid
    export_fname = f"match-{fid}-{safe_name[:40]}"
    export_script = long_image_export_script(root_id="match-export-root", filename=export_fname)
    export_hero = _wrap_export_module(
        "header",
        f"""<div class="export-hero">
    <h1>{_e(name)}</h1>
    {freshness}
  </div>""",
    )
    summary_ctx = build_ai_summary_context(
        fid,
        match_name=name,
        timeline=timeline,
        prediction=prediction,
        deep_record=latest_deep if latest_deep else None,
        ai_records=ai_records,
    )
    ai_summary_panel = html_ai_summary_panel(summary_ctx)

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{_e(name)} · 趋势</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
{export_script}
<style>
{match_css}
</style>
<script>{_AI_BTN_JS}{_AI_CHAT_JS}</script>
</head><body>
<p class="back page-nav"><a href="/">← 返回首页</a> · <a href="/daily">当日推荐</a> · <a href="/handicap">亚盘赢盘</a> · <a href="/quant">量化回测</a> · <a href="/kelly">Kelly</a></p>
<p class="action-bar">
  <button type="button" class="btn btn-ai" data-label="✨ AI 推荐本场"
    onclick="aiRecommend('{_e(fid)}', this)">✨ AI 推荐本场</button>
  {deep_btn}
  <button type="button" class="btn" style="background:#64748b" onclick="savePageLongImage(this)">📷 整页长图（可选）</button>
  <a class="btn" href="/share/match/{_e(fid)}" target="_blank" rel="noopener">📷 朋友圈分享图</a>
  <a class="btn" style="background:#2563eb" href="/kelly?fixture_id={_e(fid)}">🧮 Kelly</a>
  <span class="tag">{len(timeline)} 快照</span>
  <span class="tag">{len(changes)} 变动</span>
</p>
<p class="meta">「AI 分析 &amp; 总结」点 <strong>📷 保存推荐图</strong> 下载 PNG（存图时自动隐藏竞彩/SP/免责声明等敏感字样，适合发抖音）；页面上仍可见完整分析。</p>

<div id="match-export-root" data-export-base="{_e(export_fname)}">
{export_hero}
{ai_summary_panel}
{qual_banner}
{tier_banner}
{settled_card}
{_ai_chat_card(scope="match", fid=fid)}
{strategy_panel}
{sweet_spot_panel}
{score_rec_panel}
{quant_panel}
{deep_card}
<div class="rec-grid">
  {pred_card}
  {ah_card}
</div>
<div class="fold-stack">
{market_fold}
{charts_fold}
{bf_fold}
{changes_fold}
{snapshot_fold}
{similar_fold}
{ai_fold}
{deep_fold}
{team_form_fold}
</div>
  <p class="export-footer">公益体彩 量力而行 · 仅供参考 不构成投注建议 · 最新 {_e(last_ts)}</p>
</div>

<script>
const D = {chart_data};
function lineChart(id, datasets, title) {{
  new Chart(document.getElementById(id), {{
    type: 'line',
    data: {{ labels: D.labels, datasets }},
    options: {{
      responsive: true,
      plugins: {{ legend: {{ position: 'bottom' }} }},
      scales: {{ y: {{ beginAtZero: false }} }}
    }}
  }});
}}
lineChart('euChart', [
  {{ label: '主胜', data: D.eu_h, borderColor: '#2563eb', tension: 0.2 }},
  {{ label: '平局', data: D.eu_d, borderColor: '#16a34a', tension: 0.2 }},
  {{ label: '客胜', data: D.eu_a, borderColor: '#dc2626', tension: 0.2 }},
]);
lineChart('ahChart', [
  {{ label: '盘口(主视角)', data: D.ah_l, borderColor: '#7c3aed', tension: 0.2, yAxisID: 'y' }},
  {{ label: '上水', data: D.ah_hw, borderColor: '#0891b2', tension: 0.2 }},
  {{ label: '下水', data: D.ah_aw, borderColor: '#ea580c', tension: 0.2 }},
]);
function pctChart(id, labels, home, draw, away, title) {{
  if (!labels || !labels.length) return;
  new Chart(document.getElementById(id), {{
    type: 'line',
    data: {{
      labels,
      datasets: [
        {{ label: '主胜', data: home, borderColor: '#2563eb', backgroundColor: 'rgba(37,99,235,.08)', fill: true, tension: 0.25 }},
        {{ label: '平局', data: draw, borderColor: '#16a34a', backgroundColor: 'rgba(22,163,74,.08)', fill: true, tension: 0.25 }},
        {{ label: '客胜', data: away, borderColor: '#dc2626', backgroundColor: 'rgba(220,38,38,.08)', fill: true, tension: 0.25 }},
      ]
    }},
    options: {{
      responsive: true,
      plugins: {{ legend: {{ position: 'bottom' }}, title: {{ display: !!title, text: title || '' }} }},
      scales: {{
        y: {{ beginAtZero: true, max: 100, ticks: {{ callback: v => v + '%' }} }}
      }}
    }}
  }});
}}
if (D.trend_labels && D.trend_labels.length) {{
  pctChart('bfTrendChart', D.trend_labels, D.trend_home, D.trend_draw, D.trend_away);
}}
if (D.poll_labels && D.poll_labels.length) {{
  pctChart('bfPollChart', D.poll_labels, D.poll_home, D.poll_draw, D.poll_away);
}}
</script>
</body></html>"""
