"""Central UI theme — dark cyber sports aesthetic (2026 WC style)."""

from __future__ import annotations

# Design tokens
GRADIENT_ACCENT = "linear-gradient(90deg, #ff4b8b 0%, #ffd34e 100%)"
GRADIENT_BTN = "linear-gradient(90deg, #ff4b8b 0%, #ff6b4a 100%)"
GRADIENT_BG = "linear-gradient(165deg, #0a0c18 0%, #121528 45%, #1a1530 100%)"
GLASS_BG = "rgba(255,255,255,0.06)"
GLASS_BORDER = "rgba(255,255,255,0.1)"
TEXT_PRIMARY = "#f1f5f9"
TEXT_MUTED = "#94a3b8"
LINK_COLOR = "#ff9ec8"

FONT_IMPORT = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&display=swap');
"""

TEXT_GRADIENT_UTIL = """
.text-gradient {
  background: linear-gradient(90deg, #ff4b8b 0%, #ffd34e 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  filter: drop-shadow(0 0 24px rgba(255, 75, 139, 0.25));
}
.glass {
  background: rgba(255,255,255,0.06);
  border: 1px solid rgba(255,255,255,0.1);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-radius: 14px;
}
"""


def theme_css() -> str:
    """App-wide CSS for web_ui pages."""
    return f"""
{FONT_IMPORT}
*, *::before, *::after {{ box-sizing: border-box; }}
html {{ -webkit-text-size-adjust: 100%; }}
body {{
  font-family: Inter, system-ui, -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  margin: 0 auto; padding: 16px clamp(12px, 3vw, 24px) 32px;
  background: {GRADIENT_BG}; background-attachment: fixed;
  color: {TEXT_PRIMARY}; max-width: min(1200px, 100%); width: 100%;
  min-height: 100vh; overflow-x: clip;
}}
body::before {{
  content: ""; position: fixed; inset: 0; z-index: -1; pointer-events: none;
  background-image:
    linear-gradient(rgba(255,255,255,0.025) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.025) 1px, transparent 1px);
  background-size: 48px 48px;
  mask-image: radial-gradient(ellipse 80% 60% at 50% 0%, black 20%, transparent 70%);
}}
{TEXT_GRADIENT_UTIL}
.card {{
  background: {GLASS_BG}; border: 1px solid {GLASS_BORDER};
  backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
  border-radius: 16px; padding: 18px clamp(14px, 3vw, 22px); margin-bottom: 16px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.35);
  max-width: 100%;
}}
.card.inner {{ box-shadow: none; border: 1px solid rgba(255,255,255,0.06); padding: 12px; margin: 0; }}
h1 {{ margin: 0 0 10px; font-size: clamp(1.2rem, 4vw, 1.5rem); line-height: 1.3; font-weight: 800; }}
h2 {{ margin: 0 0 12px; font-size: clamp(1rem, 3.2vw, 1.12rem); line-height: 1.35; font-weight: 700; }}
h3 {{ margin: 0 0 12px; font-size: clamp(.95rem, 3vw, 1rem); color: {TEXT_MUTED}; line-height: 1.35; font-weight: 600; }}
h1.text-gradient, h2.text-gradient {{ margin-bottom: 12px; }}
.back {{ margin-bottom: 12px; }}
.back a, .page-nav a {{ color: {LINK_COLOR}; text-decoration: none; opacity: 0.95; }}
.back a:hover, .page-nav a:hover {{ opacity: 1; text-decoration: underline; }}
.meta {{ color: {TEXT_MUTED}; font-size: 13px; line-height: 1.55; }}
.meta strong {{ color: #fde68a; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{
  border-bottom: 1px solid rgba(255,255,255,0.06); padding: 10px 8px;
  text-align: left; font-size: 14px; vertical-align: top;
}}
th {{ background: rgba(255,255,255,0.04); font-weight: 600; white-space: nowrap; color: {TEXT_MUTED}; }}
tr:hover td {{ background: rgba(255,255,255,0.02); }}
a {{ color: {LINK_COLOR}; text-decoration: none; word-break: break-word; }}
a:hover {{ text-decoration: underline; }}
code {{
  background: rgba(255,255,255,0.08); padding: 2px 6px; border-radius: 6px;
  font-size: 12px; color: #fde68a; word-break: break-word;
}}
canvas {{ max-width: 100% !important; height: auto !important; }}
img {{ max-width: 100%; height: auto; }}
.tag {{
  display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 12px;
  margin: 2px 4px 2px 0; max-width: 100%; border: 1px solid transparent;
  background: rgba(255,255,255,0.08); color: {TEXT_PRIMARY};
}}
.tag-live {{ background: rgba(251,191,36,0.15); color: #fcd34d; border-color: rgba(251,191,36,0.35); }}
.tag-qual-div {{ background: rgba(251,146,60,0.12); color: #fdba74; border-color: rgba(251,146,60,0.35); font-weight: 700; }}
.tag-buy-tier-a {{ background: rgba(52,211,153,0.12); color: #6ee7b7; border-color: rgba(52,211,153,0.35); font-weight: 700; }}
.tag-buy-tier-b {{ background: rgba(96,165,250,0.12); color: #93c5fd; border-color: rgba(96,165,250,0.35); font-weight: 700; }}
.tag-buy-tier-c {{ background: rgba(255,255,255,0.06); color: {TEXT_MUTED}; border-color: rgba(255,255,255,0.12); }}
.tag-acc-sweet {{ background: rgba(251,146,60,0.12); color: #fdba74; border-color: rgba(251,146,60,0.35); font-weight: 700; }}
.tag-acc-solid {{ background: rgba(52,211,153,0.12); color: #6ee7b7; border-color: rgba(52,211,153,0.35); font-weight: 700; }}
.tag-acc-ok {{ background: rgba(96,165,250,0.12); color: #93c5fd; border-color: rgba(96,165,250,0.3); }}
.tag-acc-warn {{ background: rgba(248,113,113,0.12); color: #fca5a5; border-color: rgba(248,113,113,0.35); }}
.tag-warn {{ background: rgba(251,191,36,0.12); color: #fcd34d; border-color: rgba(251,191,36,0.3); }}
.tag-ok {{ background: rgba(52,211,153,0.12); color: #6ee7b7; }}
.tag-miss {{ background: rgba(248,113,113,0.12); color: #fca5a5; }}
.tag-active {{ background: {GRADIENT_BTN}; color: #fff; border: none; }}
.sweet-teaser {{
  background: rgba(251,146,60,0.08); border: 1px solid rgba(251,146,60,0.25);
  border-radius: 14px; padding: 12px 16px; margin: 0 0 14px;
}}
.sweet-teaser h3 {{ margin: 0 0 8px; font-size: 15px; color: #fdba74; }}
.qual-div-banner {{
  background: rgba(251,146,60,0.08); border: 1px solid rgba(251,146,60,0.25);
  border-radius: 14px; padding: 14px 16px; margin: 12px 0 16px;
}}
.buy-tier-banner {{ border-radius: 14px; padding: 12px 16px; margin: 12px 0; border: 1px solid rgba(255,255,255,0.1); }}
.buy-tier-tier-a {{ background: rgba(52,211,153,0.08); border-color: rgba(52,211,153,0.25); }}
.buy-tier-tier-a h3 {{ color: #6ee7b7; }}
.buy-tier-tier-b {{ background: rgba(96,165,250,0.08); border-color: rgba(96,165,250,0.25); }}
.buy-tier-tier-b h3 {{ color: #93c5fd; }}
.buy-tier-tier-c {{ background: rgba(255,255,255,0.04); border-color: rgba(255,255,255,0.08); }}
.hero-card, .hero-gs, .hero-outlook, .hero-gsc, .hero-gfc {{
  background: rgba(255,255,255,0.05) !important;
  border: 1px solid rgba(255,255,255,0.1) !important;
  box-shadow: 0 12px 40px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.06) !important;
}}
.hero-card {{ border-radius: 16px; padding: clamp(14px, 3vw, 20px) clamp(14px, 3vw, 24px); margin-bottom: 16px; }}
h2.hero-headline {{ margin: 0; font-size: clamp(1.05rem, 3.5vw, 1.25rem); line-height: 1.45; flex: 1; color: {TEXT_PRIMARY}; }}
.hero-top {{ display: flex; flex-wrap: wrap; align-items: flex-start; gap: 12px; }}
.stat {{
  background: rgba(255,255,255,0.05); border-radius: 12px; padding: 10px 12px;
  border: 1px solid rgba(255,255,255,0.08); text-align: center; min-width: 0;
}}
.stat-val {{ font-size: clamp(1.05rem, 3.5vw, 1.35rem); font-weight: 800; line-height: 1.25;
  word-break: break-word; background: {GRADIENT_ACCENT}; -webkit-background-clip: text;
  background-clip: text; color: transparent; }}
.stat-lbl {{ font-size: 11px; color: {TEXT_MUTED}; margin-top: 4px; }}
.page-nav, .back {{ display: flex; flex-wrap: wrap; gap: 6px 8px; align-items: center; line-height: 1.65; }}
.page-nav a, .back a {{ white-space: nowrap; }}
.action-bar {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 16px; }}
.card:has(> table), .fold-body:has(> table), .similar-block {{
  overflow-x: auto; -webkit-overflow-scrolling: touch; max-width: 100%;
}}
.card > table:not(.mini), .fold-body > table:not(.mini) {{ min-width: 560px; }}
.card > table.dashboard-table {{ min-width: 680px; }}
table.mini {{ width: 100%; min-width: 0; }}
.stat-grid {{
  display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 118px), 1fr));
  gap: 10px; margin-bottom: 12px;
}}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr)); gap: 12px; }}
.gs-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 1fr)); gap: 14px; }}
.match-row {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.2fr); gap: 8px 16px; align-items: start; }}
.match-side {{ justify-self: end; text-align: right; font-size: 12px; color: {TEXT_MUTED}; line-height: 1.65; min-width: 0; }}
@media (max-width: 900px) {{
  .strategy-grid, .path-grid, .rec-grid, .quant-score-grid, .kelly-grid, .gs-grid, .conc-grid,
  .watch-grid, .ai-watch-cols, .ai-match-grid, .match-ai-grid, .watch-stats {{
    grid-template-columns: 1fr !important;
  }}
  .match-row {{ grid-template-columns: 1fr !important; }}
  .match-side {{ justify-self: stretch !important; text-align: left !important; }}
}}
@media (max-width: 640px) {{
  body {{ padding: 12px 10px 24px; }}
  .card {{ padding: 14px 12px; margin-bottom: 12px; border-radius: 12px; }}
  th, td {{ padding: 8px 6px; font-size: 13px; }}
  .btn {{ padding: 8px 12px; font-size: 13px; }}
  .toast {{ left: 10px; right: 10px; bottom: 10px; max-width: none; }}
  details.fold > summary {{ padding: 12px 14px; font-size: 13px; }}
  .fold-body {{ padding: 0 12px 12px; }}
}}
"""


def buttons_css() -> str:
    return """
.btn {
  display: inline-block; padding: 9px 18px; color: #fff !important;
  border-radius: 999px; border: none; cursor: pointer; font-size: 14px;
  font-weight: 700; text-decoration: none;
  background: linear-gradient(90deg, #ff4b8b 0%, #ff6b4a 100%);
  box-shadow: 0 4px 20px rgba(255, 75, 139, 0.35);
  transition: filter 0.15s, transform 0.15s;
}
.btn:hover { filter: brightness(1.08); transform: translateY(-1px); }
.btn-sm { padding: 5px 12px; font-size: 12px; }
.btn:disabled { opacity: 0.55; cursor: wait; transform: none; filter: none; }
.btn-ai { background: linear-gradient(90deg, #a855f7, #6366f1); box-shadow: 0 4px 20px rgba(168,85,247,0.35); }
.btn-deep { background: linear-gradient(90deg, #14b8a6, #0ea5e9); box-shadow: 0 4px 20px rgba(20,184,166,0.3); }
.btn-deep:disabled { background: rgba(148,163,184,0.3); box-shadow: none; opacity: 0.7; }
.btn-share { background: linear-gradient(90deg, #a855f7, #ec4899); }
.btn-poster-save {
  display: inline-block; width: 100%; max-width: 420px; padding: 12px 16px;
  border: none; border-radius: 999px; cursor: pointer; font-size: 15px; font-weight: 800;
  color: #fff; background: linear-gradient(90deg, #ff4b8b, #ffd34e);
  box-shadow: 0 6px 24px rgba(255, 75, 139, 0.4);
}
.btn-poster-save:hover { filter: brightness(1.06); }
.btn-poster-save:disabled { opacity: .65; cursor: wait; }
"""


def fold_css() -> str:
    return """
details.fold {
  background: rgba(255,255,255,0.04); border-radius: 14px; margin-bottom: 10px;
  border: 1px solid rgba(255,255,255,0.08);
}
details.fold > summary {
  padding: 14px 18px; cursor: pointer; font-weight: 600; font-size: 14px;
  color: #e2e8f0; list-style: none; user-select: none;
}
details.fold > summary::-webkit-details-marker { display: none; }
details.fold > summary::before {
  content: '▸'; display: inline-block; margin-right: 8px; color: #ff9ec8;
  transition: transform .15s;
}
details.fold[open] > summary::before { transform: rotate(90deg); }
details.fold-muted > summary { font-weight: 500; color: #94a3b8; }
details.fold-open { border-color: rgba(255, 75, 139, 0.35); }
details.fold-open > summary { color: #ff9ec8; }
.fold-body { padding: 0 16px 16px; }
.fold-body > .card:first-child { margin-top: 0; }
.fold-body .card { box-shadow: none; border: 1px solid rgba(255,255,255,0.06); margin-bottom: 10px; }
.fold-stack { display: flex; flex-direction: column; gap: 10px; margin-bottom: 16px; }
.fold-summary-line { display: flex; align-items: center; gap: 8px; width: 100%; }
.fold-summary-line > span:first-child { flex: 1; min-width: 0; }
.export-module { position: relative; background: transparent; }
.export-module:not(details) { border: 1px solid rgba(255,255,255,0.08); border-radius: 14px; margin-bottom: 12px; }
.export-module-toolbar { position: absolute; top: 8px; right: 8px; z-index: 5; }
.export-module-inner { padding-top: 2px; }
.export-module:not(details) .export-module-inner { padding: 36px 12px 12px; }
.export-module:not(details) .export-module-inner > .card:first-child { margin-top: 0; margin-bottom: 0; }
.btn-export-mod {
  font-size: 11px; padding: 4px 10px; border-radius: 999px;
  border: 1px solid rgba(255,255,255,0.15); background: rgba(255,255,255,0.08);
  color: #e2e8f0; cursor: pointer; white-space: nowrap; line-height: 1.4;
}
.btn-export-mod:hover { background: rgba(255,255,255,0.12); border-color: rgba(255,158,200,0.4); }
.btn-export-mod:disabled { opacity: 0.6; cursor: wait; }
.export-module-poster { max-width: 420px; margin: 0 auto 16px; }
.export-poster-actions { text-align: center; margin-bottom: 10px; }
.export-poster { border-radius: 16px; overflow: hidden; box-shadow: 0 12px 40px rgba(0,0,0,0.5); }
"""


def toast_css() -> str:
    return """
.toast {
  display: none; position: fixed; bottom: 24px; right: 24px; z-index: 9999;
  background: linear-gradient(90deg, #059669, #10b981); color: #fff;
  padding: 12px 20px; border-radius: 999px;
  box-shadow: 0 8px 24px rgba(0,0,0,.4); font-size: 14px; max-width: 360px;
}
.toast-err { background: linear-gradient(90deg, #dc2626, #ef4444); }
"""


def chat_css() -> str:
    return """
.ai-chat-card { border-left: 4px solid #a855f7; }
.ai-chat-toolbar { display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin:8px 0; }
.ai-chat-provider {
  padding:7px 10px; border:1px solid rgba(255,255,255,0.12); border-radius:999px;
  background: rgba(255,255,255,0.06); color: #e2e8f0;
}
.ai-chat-quick { display:flex; gap:8px; flex-wrap:wrap; margin:8px 0; }
.ai-chat-input {
  width:100%; box-sizing:border-box; border:1px solid rgba(255,255,255,0.12);
  border-radius:12px; padding:10px; font-size:14px;
  background: rgba(0,0,0,0.25); color: #e2e8f0;
}
.ai-chat-output {
  min-height:90px; max-height:360px; overflow:auto; white-space:pre-wrap;
  background: rgba(0,0,0,0.35); color:#e2e8f0; border-radius:12px;
  padding:12px; line-height:1.55; font-size:13px; border: 1px solid rgba(255,255,255,0.06);
}
"""


def page_components_css() -> str:
    """Extra components used across multiple pages."""
    return """
.deep-card { border-left: 4px solid #14b8a6; }
.deep-headline { font-size: 1.2rem; font-weight: 700; color: #5eead4; margin: 0 0 8px; }
.deep-section h4 { color: #94a3b8; }
.deep-list li { color: #cbd5e1; }
.pred-card { border-left: 4px solid #a855f7; }
.settled-card { border-left: 4px solid #10b981; }
.conf-low { background: rgba(251,191,36,0.12); color: #fcd34d; }
.conf-medium { background: rgba(96,165,250,0.12); color: #93c5fd; }
.conf-high { background: rgba(52,211,153,0.12); color: #6ee7b7; }
.conc-card { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; }
.conc-card.tone-warn { border-color: rgba(248,113,113,0.35); background: rgba(248,113,113,0.06); }
.conc-card.tone-ok { border-color: rgba(52,211,153,0.35); background: rgba(52,211,153,0.06); }
.watch-item {
  border: 1px solid rgba(255,255,255,0.08); border-radius: 14px; padding: 14px;
  background: rgba(255,255,255,0.04);
}
.watch-item.watch-warn { border-color: rgba(251,146,60,0.35); background: rgba(251,146,60,0.06); }
.watch-pick-strip {
  background: rgba(0,0,0,0.2); border-radius: 10px; border: 1px solid rgba(255,255,255,0.06);
}
.watch-stat { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.06); }
.match-ai-box {
  border: 1px solid rgba(168,85,247,0.35); border-left: 4px solid #a855f7;
  background: rgba(168,85,247,0.08); border-radius: 12px;
}
.watch-badge-warn { background: rgba(248,113,113,0.15); color: #fca5a5; }
.watch-badge-ok { background: rgba(52,211,153,0.15); color: #6ee7b7; }
.watch-badge-neutral { background: rgba(96,165,250,0.15); color: #93c5fd; }
.parlay-option { border: 1px solid rgba(255,255,255,0.08); border-radius: 14px; padding: 12px;
  margin: 12px 0; background: rgba(255,255,255,0.04); }
.parlay-ai-brief { background: rgba(96,165,250,0.08); border-radius: 10px; padding: 10px; }
.parlay-explain-box { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; }
.verdict-ok { color: #6ee7b7; }
.verdict-warn { color: #fcd34d; }
.verdict-bad { color: #fca5a5; }
#worldcup-export-root { background: transparent; padding: 4px 0 8px; }
.metric { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.06); border-radius: 10px; }
.formula { background: rgba(0,0,0,0.25); color: #cbd5e1; border: 1px solid rgba(255,255,255,0.06); }
.prefill-card { background: rgba(96,165,250,0.08); border: 1px solid rgba(96,165,250,0.25); }
.path-block { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); }
.bracket-node.group { background: rgba(168,85,247,0.15); color: #d8b4fe; }
.bracket-node.r32 { background: rgba(52,211,153,0.15); color: #6ee7b7; }
.bracket-node.r16 { background: rgba(248,113,113,0.12); color: #fca5a5; }
.group-bracket-strip { background: rgba(52,211,153,0.06); border-color: rgba(52,211,153,0.25); }
.race-badge.race-lock { background: rgba(52,211,153,0.12); color: #6ee7b7; border-color: rgba(52,211,153,0.3); }
.race-badge.race-fight { background: rgba(251,191,36,0.12); color: #fcd34d; border-color: rgba(251,191,36,0.3); }
.prediction-col { background: rgba(251,191,36,0.06); border: 1px solid rgba(251,191,36,0.2); }
.similar-ai-box { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 12px; }
tr.chg td { background: rgba(251,191,36,0.08); }
.outlook-team { border-top: 1px solid rgba(255,255,255,0.06); }
.gs-fixture { border-top: 1px solid rgba(255,255,255,0.06); }
"""


def legacy_surface_patch() -> str:
    """Neutralize page-local light-theme CSS still present in web_ui extras."""
    return """
.card.inner { border-color: rgba(255,255,255,0.06) !important; }
.parlay-result { border-left-color: #6366f1 !important; }
.parlay-ai-brief, .parlay-explain-box, .parlay-option { background: rgba(255,255,255,0.04) !important; border-color: rgba(255,255,255,0.08) !important; }
.parlay-explain-box h4, .parlay-explain, .parlay-reasons, .leg-reason-text { color: #cbd5e1 !important; }
.parlay-stake { color: #93c5fd !important; }
.hero-card { background: rgba(255,255,255,0.05) !important; border-color: rgba(255,255,255,0.1) !important; }
h2.hero-headline { color: #f1f5f9 !important; }
.conc-card, .conc-card.tone-neutral, .conc-card.tone-warn, .conc-card.tone-ok { background: rgba(255,255,255,0.04) !important; }
.conc-advice, .match-take, .match-side, .watch-reason, .watch-stat-line { color: #94a3b8 !important; }
.match-row { border-bottom-color: rgba(255,255,255,0.06) !important; }
.watch-item, .watch-item.watch-warn { background: rgba(255,255,255,0.04) !important; border-color: rgba(255,255,255,0.08) !important; }
.watch-match { color: #ff9ec8 !important; }
.watch-pick-main { color: #f1f5f9 !important; }
.watch-pick-strip, .watch-fold, .watch-stat { background: rgba(0,0,0,0.2) !important; border-color: rgba(255,255,255,0.06) !important; }
.match-ai-box { background: rgba(168,85,247,0.08) !important; }
.match-ai-title, .ai-headline, .similar-ai-top strong { color: #d8b4fe !important; }
.match-ai-cell { background: rgba(255,255,255,0.04) !important; }
.match-ai-cell p, .match-ai-points { color: #94a3b8 !important; }
.chip-grp { background: rgba(96,165,250,0.12) !important; color: #93c5fd !important; border-color: rgba(96,165,250,0.3) !important; }
.deep-headline { color: #5eead4 !important; }
.deep-section h4, .deep-list li { color: #94a3b8 !important; }
.sweet-spot-card.sweet-in { background: rgba(251,146,60,0.08) !important; }
.sweet-verdict, .score-headline { color: #e2e8f0 !important; }
.quant-track, .quant-ev.value-no { background: rgba(255,255,255,0.04) !important; border-color: rgba(255,255,255,0.08) !important; color: #94a3b8 !important; }
.quant-track.model-track, .quant-ev.value-yes { background: rgba(52,211,153,0.08) !important; border-color: rgba(52,211,153,0.25) !important; color: #6ee7b7 !important; }
.path-block, .bracket-lane { background: rgba(255,255,255,0.04) !important; border-color: rgba(255,255,255,0.08) !important; }
.prediction-col, .dual-hint, tr.chg td { background: rgba(251,191,36,0.06) !important; border-color: rgba(251,191,36,0.2) !important; }
.group-chaos-banner.chaos-high { background: rgba(251,146,60,0.08) !important; color: #fdba74 !important; }
.group-chaos-banner.chaos-med { background: rgba(96,165,250,0.08) !important; color: #93c5fd !important; }
.likely-r32, .group-bracket-strip { background: rgba(52,211,153,0.06) !important; border-color: rgba(52,211,153,0.2) !important; }
.similar-ai-box { background: rgba(168,85,247,0.08) !important; border-color: rgba(168,85,247,0.25) !important; }
.similar-ai-action { color: #d8b4fe !important; }
.floor-note { background: rgba(168,85,247,0.08) !important; border-color: rgba(168,85,247,0.25) !important; }
.quick-btns button { background: rgba(255,255,255,0.06) !important; border-color: rgba(255,255,255,0.12) !important; color: #e2e8f0 !important; }
.gfc-pick, .gfc-result { background: rgba(255,255,255,0.07) !important; border-color: rgba(255,255,255,0.14) !important; color: #f1f5f9 !important; }
.gfc-pick strong { color: #fff !important; font-weight: 900 !important; }
.gfc-pick-meta { color: #e2e8f0 !important; }
.outlook-team-name { color: #fff !important; }
.outlook-r32 { color: #e2e8f0 !important; }
.outlook-sc { color: #cbd5e1 !important; }
.standings-table td { color: #e2e8f0 !important; }
.standings-table td strong { color: #fff !important; }
"""


def app_theme_css(*extra: str) -> str:
    """Full theme bundle for _shared_css()."""
    parts = [
        theme_css(),
        buttons_css(),
        fold_css(),
        toast_css(),
        chat_css(),
        page_components_css(),
        *extra,
        legacy_surface_patch(),
    ]
    raw = "".join(parts)
    return raw.replace("{{", "{").replace("}}", "}")


def poster_css() -> str:
    """Share card / AI summary poster styles."""
    return f"""
{FONT_IMPORT}
{TEXT_GRADIENT_UTIL}
.export-poster-safe {{ display: none; }}
.jc-poster, .jc-poster-safe {{
  position: relative; overflow: hidden;
  background: {GRADIENT_BG}; color: {TEXT_PRIMARY};
  font-family: Inter, system-ui, "PingFang SC", "Microsoft YaHei", sans-serif;
}}
.jc-poster::before, .jc-poster-safe::before {{
  content: ""; position: absolute; inset: 0; pointer-events: none;
  background-image:
    linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px);
  background-size: 40px 40px;
}}
.jc-poster-top, .jc-safe-top {{
  position: relative; z-index: 1;
  padding: 14px 16px 10px; display: flex; justify-content: space-between; align-items: center; gap: 8px;
  border-bottom: 1px solid rgba(255,255,255,0.06);
}}
.jc-brand, .jc-safe-brand {{
  font-size: 11px; font-weight: 800; letter-spacing: .14em; text-transform: uppercase;
  background: {GRADIENT_ACCENT}; -webkit-background-clip: text; background-clip: text; color: transparent;
}}
.jc-match-num, .jc-safe-num {{
  font-size: 11px; font-weight: 700; padding: 4px 10px; border-radius: 999px;
  background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.12); color: {TEXT_MUTED};
}}
.jc-teams {{
  position: relative; z-index: 1;
  display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 8px;
  padding: 20px 16px 8px; text-align: center;
}}
.jc-team span {{
  display: block; font-size: clamp(1.1rem, 4.2vw, 1.4rem); font-weight: 900;
  line-height: 1.25; color: #fff;
}}
.jc-vs {{
  font-size: 12px; font-weight: 900; color: #ff9ec8;
  background: rgba(255,75,139,0.12); border-radius: 999px; padding: 6px 10px;
  border: 1px solid rgba(255,75,139,0.25);
}}
.jc-schedule {{
  position: relative; z-index: 1;
  text-align: center; font-size: 12px; color: {TEXT_MUTED}; padding: 0 16px 14px;
}}
.jc-rec-panel, .jc-safe-trend-panel {{
  position: relative; z-index: 1;
  margin: 0 14px 12px; padding: 16px 14px; border-radius: 16px;
  background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1);
  backdrop-filter: blur(12px);
}}
.jc-rec-hd, .jc-safe-trend-hd {{
  font-size: 10px; font-weight: 800; letter-spacing: .16em; text-align: center; color: {TEXT_MUTED};
}}
.jc-rec-pick, .jc-safe-trend-pick {{
  font-size: clamp(2rem, 8vw, 2.6rem); font-weight: 900; text-align: center;
  line-height: 1.1; margin: 8px 0 6px;
  background: {GRADIENT_ACCENT}; -webkit-background-clip: text; background-clip: text; color: transparent;
}}
.jc-rec-pick.is-wait {{ font-size: clamp(1.2rem, 5vw, 1.6rem); color: {TEXT_MUTED}; background: none; }}
.jc-rec-sub {{ text-align: center; font-size: 14px; font-weight: 600; color: {TEXT_MUTED}; margin-bottom: 10px; }}
.jc-sp-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }}
.jc-sp-cell {{
  background: rgba(0,0,0,0.25); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 8px 4px; text-align: center;
}}
.jc-sp-lbl {{ display: block; font-size: 12px; color: {TEXT_MUTED}; font-weight: 600; }}
.jc-sp-val {{ display: block; font-size: 18px; font-weight: 900; color: #fff; margin-top: 2px; }}
.jc-sp-cell.is-rec {{
  background: rgba(255,75,139,0.15); border-color: rgba(255,211,78,0.45);
}}
.jc-sp-cell.is-rec .jc-sp-val {{ background: {GRADIENT_ACCENT}; -webkit-background-clip: text; background-clip: text; color: transparent; }}
.jc-rec-tag {{
  display: block; font-style: normal; font-size: 10px; font-weight: 800; color: #0a0c18;
  background: {GRADIENT_ACCENT}; border-radius: 4px; margin-top: 4px; padding: 1px 0;
}}
.jc-tier, .jc-safe-tier {{
  position: relative; z-index: 1;
  margin: 0 14px 10px; padding: 8px 12px; border-radius: 12px; font-size: 13px; text-align: center;
  background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.08); color: {TEXT_PRIMARY};
}}
.jc-synth, .jc-safe-synth {{
  position: relative; z-index: 1;
  margin: 0 14px 10px; padding: 10px 12px; border-radius: 12px; text-align: left;
  background: rgba(52,211,153,0.08); border: 1px solid rgba(52,211,153,0.2);
}}
.jc-synth-hd, .jc-safe-synth-hd {{ font-size: 11px; font-weight: 800; color: #6ee7b7; margin-bottom: 4px; letter-spacing: .06em; }}
.jc-synth p, .jc-safe-synth p {{ margin: 0; font-size: 13px; line-height: 1.6; color: #cbd5e1; }}
.jc-synth.is-muted, .jc-safe-synth.is-muted {{ background: rgba(255,255,255,0.04); border-color: rgba(255,255,255,0.08); }}
.jc-ai-section, .jc-safe-ai-section {{ position: relative; z-index: 1; margin: 0 14px 10px; text-align: left; }}
.jc-ai-section-hd, .jc-safe-ai-hd {{ font-size: 12px; font-weight: 800; color: {TEXT_MUTED}; margin-bottom: 6px; }}
.jc-model-card, .jc-safe-model-card {{
  background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 10px 12px;
}}
.jc-model-name, .jc-safe-model-name {{ font-size: 13px; color: #ff9ec8; }}
.jc-model-pick, .jc-safe-model-pick {{
  font-size: 12px; font-weight: 800; padding: 2px 8px; border-radius: 999px;
  background: rgba(255,75,139,0.15); border: 1px solid rgba(255,75,139,0.3); color: #ff9ec8;
}}
.jc-model-sum, .jc-safe-model-sum {{ margin: 0; font-size: 12px; line-height: 1.55; color: #cbd5e1; }}
.jc-safe-pills {{ display: flex; justify-content: center; gap: 10px; }}
.jc-safe-pill {{
  min-width: 42px; padding: 6px 12px; border-radius: 999px; font-size: 13px; font-weight: 800;
  color: {TEXT_MUTED}; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1);
}}
.jc-safe-pill.is-on {{
  color: #0a0c18; background: {GRADIENT_ACCENT}; border-color: transparent;
}}
.jc-foot, .jc-safe-foot {{
  position: relative; z-index: 1;
  padding: 10px 14px 14px; text-align: center; font-size: 10px; color: {TEXT_MUTED};
  border-top: 1px dashed rgba(255,255,255,0.08); margin-top: 4px;
}}
.jc-hero-layout {{
  position: relative; z-index: 1;
  display: grid; grid-template-columns: 1fr auto; gap: 12px; align-items: center;
  padding: 16px 14px 8px;
}}
.jc-hero-kicker {{ font-size: 12px; color: {TEXT_MUTED}; margin-bottom: 8px; }}
.jc-hero-match {{
  font-size: clamp(1.15rem, 4.5vw, 1.55rem); font-weight: 900; color: #fff; line-height: 1.25;
}}
.jc-vs-inline {{ color: #ff9ec8; margin: 0 6px; font-size: 0.85em; }}
.jc-hero-pills {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }}
.jc-glass-pill {{
  padding: 8px 12px; border-radius: 12px; min-width: 88px;
  background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1);
}}
.jc-pill-lbl {{ display: block; font-size: 10px; color: {TEXT_MUTED}; margin-bottom: 2px; }}
.jc-glass-pill strong {{ font-size: 13px; color: #fff; }}
.jc-hero-right {{ text-align: center; padding-left: 8px; }}
.jc-hero-score {{
  font-size: clamp(2rem, 9vw, 2.8rem); font-weight: 900; line-height: 1;
  background: {GRADIENT_ACCENT}; -webkit-background-clip: text; background-clip: text; color: transparent;
  filter: drop-shadow(0 0 20px rgba(255,75,139,0.3)); margin-bottom: 8px;
}}
.jc-sp-grid-hd {{ font-size: 11px; color: {TEXT_MUTED}; text-align: center; margin-bottom: 6px; font-weight: 600; }}
.jc-sp-empty {{ grid-column: 1 / -1; text-align: center; font-size: 13px; color: {TEXT_MUTED}; padding: 8px; }}
.jc-model-list {{ display: flex; flex-direction: column; gap: 8px; }}
.jc-ref-box, .jc-rq-ref {{ color: {TEXT_MUTED}; }}
.jc-meta-row {{ display: flex; justify-content: center; gap: 8px; padding: 0 14px 8px; position: relative; z-index: 1; }}
.jc-meta-chip, .jc-safe-meta-chip {{
  font-size: 11px; color: {TEXT_MUTED}; background: rgba(255,255,255,0.06);
  padding: 3px 10px; border-radius: 999px; border: 1px solid rgba(255,255,255,0.08);
}}
.jc-agree.is-ok, .jc-safe-agree.is-ok {{ background: rgba(52,211,153,0.15); color: #6ee7b7; }}
.jc-agree.is-warn, .jc-safe-agree.is-warn {{ background: rgba(251,146,60,0.15); color: #fdba74; }}
.jc-agree, .jc-safe-agree {{
  display: inline-block; font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 999px; margin-bottom: 8px;
}}
"""


def share_match_page_css() -> str:
    return f"""
{FONT_IMPORT}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: Inter, "PingFang SC", "Microsoft YaHei", sans-serif;
  background: {GRADIENT_BG}; min-height: 100vh; padding: 16px;
  display: flex; flex-direction: column; align-items: center; gap: 16px;
}}
.toolbar {{ width: min(750px, 100%); display: flex; gap: 10px; flex-wrap: wrap; }}
.toolbar a, .toolbar button {{
  padding: 10px 18px; border-radius: 999px; border: none; cursor: pointer;
  font-size: 14px; font-weight: 700; text-decoration: none; display: inline-block;
}}
.btn-save {{ background: {GRADIENT_BTN}; color: #fff; box-shadow: 0 4px 20px rgba(255,75,139,0.35); }}
.btn-back {{ background: rgba(255,255,255,0.08); color: #e2e8f0; border: 1px solid rgba(255,255,255,0.12); }}
#share-wrap {{
  width: min(750px, 100%); border-radius: 16px; padding: 28px 20px 24px;
  position: relative; overflow: hidden;
  background: {GRADIENT_BG}; border: 1px solid rgba(255,255,255,0.1);
  box-shadow: 0 16px 48px rgba(0,0,0,0.5);
}}
#share-wrap::before {{
  content: ""; position: absolute; inset: 0; opacity: 1; pointer-events: none;
  background-image:
    linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px);
  background-size: 40px 40px;
}}
.scroll {{
  position: relative; z-index: 3; margin: 0 12px;
  background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12);
  backdrop-filter: blur(16px); border-radius: 16px;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.06);
  padding: 28px 22px 20px; text-align: center;
}}
.teams {{
  font-size: clamp(26px, 6vw, 38px); font-weight: 900; color: #fff; line-height: 1.2; margin-bottom: 8px;
}}
.vs {{ color: #ff9ec8; margin: 0 8px; font-size: 0.85em; }}
.sub {{ font-size: 14px; color: {TEXT_MUTED}; margin-bottom: 14px; }}
.deadline {{
  display: inline-block; background: rgba(52,211,153,0.15); color: #6ee7b7;
  font-size: 13px; font-weight: 700; padding: 6px 14px; border-radius: 999px;
  border: 1px solid rgba(52,211,153,0.3); margin-bottom: 18px;
}}
.sp-row {{
  font-size: clamp(20px, 5vw, 28px); font-weight: 900; color: #fff;
  padding: 10px 8px; margin: 6px 0; border-radius: 12px;
}}
.sp-row.highlight {{
  background: rgba(255,75,139,0.12); border: 1px solid rgba(255,211,78,0.35);
}}
.sp-row.highlight, .sp-row.highlight * {{ background: {GRADIENT_ACCENT}; -webkit-background-clip: text; background-clip: text; color: transparent; }}
.rec-tag {{
  display: inline-block; background: {GRADIENT_BTN}; color: #0a0c18 !important;
  font-size: 11px; padding: 2px 8px; border-radius: 999px; margin-right: 8px; font-weight: 800;
  -webkit-background-clip: border-box; background-clip: border-box;
}}
.ai-box {{ margin-top: 16px; padding-top: 14px; border-top: 1px dashed rgba(255,255,255,0.1); text-align: left; }}
.ai-title {{ font-size: 13px; color: {TEXT_MUTED}; margin-bottom: 8px; }}
.ai-chip {{
  display: inline-block; background: rgba(168,85,247,0.2); color: #d8b4fe;
  font-size: 13px; padding: 4px 10px; border-radius: 999px; margin: 0 6px 6px 0;
  border: 1px solid rgba(168,85,247,0.35);
}}
.ai-main {{
  font-size: 18px; font-weight: 900; margin-top: 8px;
  background: {GRADIENT_ACCENT}; -webkit-background-clip: text; background-clip: text; color: transparent;
}}
.footer {{ margin-top: 16px; font-size: 12px; color: {TEXT_MUTED}; text-align: center; position: relative; z-index: 3; }}
.hint {{ color: {TEXT_MUTED}; font-size: 13px; text-align: center; max-width: 750px; }}
"""


def poster_batch_page_css() -> str:
    return f"""
{FONT_IMPORT}
body.poster-batch-page {{ background: {GRADIENT_BG}; color: {TEXT_PRIMARY}; min-height: 100vh; }}
body.poster-batch-page::before {{
  content: ""; position: fixed; inset: 0; z-index: -1; pointer-events: none;
  background-image:
    linear-gradient(rgba(255,255,255,0.025) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.025) 1px, transparent 1px);
  background-size: 48px 48px;
}}
.poster-batch-toolbar {{
  position: sticky; top: 0; z-index: 20;
  background: rgba(10,12,24,0.85); backdrop-filter: blur(12px);
  border-bottom: 1px solid rgba(255,255,255,0.08);
  padding: 12px clamp(12px, 3vw, 24px); margin: 0 0 16px;
  display: flex; gap: 10px; flex-wrap: wrap; align-items: center;
}}
.poster-batch-list {{ max-width: 460px; margin: 0 auto; padding: 0 12px 32px; }}
.poster-batch-item {{ margin-bottom: 28px; }}
.poster-batch-item h2 {{ font-size: 15px; margin: 0 0 10px; color: {TEXT_PRIMARY}; font-weight: 700; }}
.poster-batch-item h2 a {{ color: #ff9ec8; text-decoration: none; }}
.poster-batch-meta {{ color: {TEXT_MUTED}; font-size: 13px; margin: 0 0 16px; line-height: 1.5; }}
"""
