"""Viz one-line summary builder for detail/list views."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from analysis.market.score_range import build_score_range_forecast


def _extract_jingcai_from_timeline(timeline: list[dict]) -> dict:
    for p in reversed(timeline or []):
        jc = ((p.get("odds") or {}).get("jingcai") or
              ((p.get("odds") or {}).get("raw_meta") or {}).get("jingcai") or
              (p.get("raw_meta") or {}).get("jingcai") or {})
        if jc and (jc.get("has_sp") or jc.get("has_rqsp")):
            return jc
    return {}


def _jingcai_sp_line(jc: dict) -> str | None:
    if not jc or not jc.get("has_sp"):
        return None
    parts = [
        str(jc.get("sp_home")),
        str(jc.get("sp_draw")),
        str(jc.get("sp_away")),
    ]
    return "/".join(p for p in parts if p and p != "None")


def _score_top(poisson_heatmap: Sequence[Sequence]) -> list[dict]:
    cells = []
    for item in poisson_heatmap or []:
        if len(item) < 3:
            continue
        try:
            i, j, p = int(item[0]), int(item[1]), float(item[2])
        except (TypeError, ValueError):
            continue
        cells.append({"score": f"{i}-{j}", "p": p})
    cells.sort(key=lambda x: x["p"], reverse=True)
    return cells[:3]


def _poisson_1x2(poisson_heatmap: Sequence[Sequence]) -> dict[str, float | None]:
    home = draw = away = 0.0
    total = 0.0
    for item in poisson_heatmap or []:
        if len(item) < 3:
            continue
        try:
            i, j, p = int(item[0]), int(item[1]), float(item[2])
        except (TypeError, ValueError):
            continue
        total += p
        if i > j:
            home += p
        elif i == j:
            draw += p
        else:
            away += p
    if total <= 0:
        return {"home": None, "draw": None, "away": None}
    return {
        "home": round(home / total * 100, 1),
        "draw": round(draw / total * 100, 1),
        "away": round(away / total * 100, 1),
    }


def _edge_from_score_range(score_range: dict) -> tuple[str, float]:
    sp_band = (score_range or {}).get("sp_band") or {}
    if not sp_band:
        return "none", 0.0
    direction = sp_band.get("direction") or ""
    edge = sp_band.get("edge") or 0.0
    if direction not in ("home", "draw", "away"):
        return "none", 0.0
    # normalize to percentage points
    if edge <= 1.0:
        edge = edge * 100.0
    return direction, edge


def _edge_from_edge_bars(edge_bars: Sequence[dict] | None) -> tuple[str, float]:
    best = None
    for bar in edge_bars or []:
        if bar.get("edge_pp") and (best is None or bar["edge_pp"] > best["edge_pp"]):
            best = bar
    if not best:
        return "none", 0.0
    side = best.get("direction") or best.get("side") or "none"
    if side not in ("home", "draw", "away"):
        side = "none"
    return side, best.get("edge_pp", 0.0)


def _move_one_liner(market_attitude: dict | None) -> str:
    if not market_attitude:
        return ""
    parts = []
    ah = market_attitude.get("asian") or {}
    eu = market_attitude.get("european") or {}
    if ah.get("line_move"):
        parts.append(f"让球{ah['line_move']}")
    if ah.get("home_water_move"):
        parts.append(f"主水{ah['home_water_move']}")
    if eu.get("home_move"):
        parts.append(f"欧主胜{eu['home_move']}")
    return " · ".join(parts)


def _divergence_one_liner(divergence: dict | None) -> str:
    if not divergence or not divergence.get("divergence_score"):
        return ""
    score = divergence.get("divergence_score")
    sev = divergence.get("severity_cn", "")
    return f"欧亚分歧 {score} 分（{sev}）"


def _form_one_liner(recent_form: dict | None) -> str:
    if not recent_form:
        return "战绩不足"
    # club_form structure
    home_form = recent_form.get("home_form") or {}
    away_form = recent_form.get("away_form") or {}
    if home_form or away_form:
        bits = []
        if home_form:
            pts = home_form.get("pts_last_5")
            gf = home_form.get("goals_for_last_5")
            ga = home_form.get("goals_against_last_5")
            bits.append(f"主近5 {pts}分/{gf}进{ga}失")
        if away_form:
            pts = away_form.get("pts_last_5")
            gf = away_form.get("goals_for_last_5")
            ga = away_form.get("goals_against_last_5")
            bits.append(f"客近5 {pts}分/{gf}进{ga}失")
        return " / ".join(bits)
    # recent_form structure from _extract_recent_form
    home = recent_form.get("home") or {}
    away = recent_form.get("away") or {}
    if not home and not away:
        return recent_form.get("missing_reason") or "战绩不足"
    bits = []
    if home.get("form_str"):
        bits.append(f"主近况 {home['form_str']}（胜率{home.get('win_rate', 0):.0%}）")
    if away.get("form_str"):
        bits.append(f"客近况 {away['form_str']}（胜率{away.get('win_rate', 0):.0%}）")
    return " / ".join(bits)


def _similar_one_liner(history_similar: dict | None) -> str:
    if not history_similar:
        return "同赔不足"
    samples = history_similar.get("samples") or []
    if not samples:
        return history_similar.get("missing_reason") or "同赔不足"
    n = len(samples)
    h = sum(1 for s in samples if (s.get("result") or "").startswith("H"))
    d = sum(1 for s in samples if (s.get("result") or "").startswith("D"))
    a = n - h - d
    return f"同赔 n={n} 主{h}/平{d}/客{a}"


def _missing_list(viz: dict, context: dict | None) -> list[str]:
    missing = list((viz or {}).get("missing") or [])
    recent_form = (context or {}).get("club_form")
    if recent_form is None:
        missing.append("recent_form")
    history_similar = (context or {}).get("history_similar")
    if history_similar is None:
        missing.append("history_similar")
    return sorted(set(missing))


def build_viz_summary(
    viz: dict | None = None,
    context: dict | None = None,
) -> dict[str, Any]:
    """Build a structured one-line summary for detail/list views.

    Args:
        viz: output of build_viz_data.
        context: optional forecast context (club_form, history_similar, etc.).
    """
    viz = viz or {}
    context = context or {}

    poisson_heatmap = viz.get("poisson_heatmap") or []
    score_range = viz.get("score_range") or {}
    edge_bars = viz.get("edge_bars")

    score_top = _score_top(poisson_heatmap)
    poisson_1x2 = _poisson_1x2(poisson_heatmap)

    edge_side, edge_pp = _edge_from_score_range(score_range)
    if edge_side == "none" and edge_bars:
        edge_side, edge_pp = _edge_from_edge_bars(edge_bars)

    jc = _extract_jingcai_from_timeline(viz.get("timeline") or [])
    jingcai_sp = _jingcai_sp_line(jc)

    summary = {
        "score_top": score_top,
        "poisson_1x2": poisson_1x2,
        "edge_side": edge_side,
        "edge_pp": edge_pp,
        "move_one_liner": _move_one_liner(viz.get("market_attitude")),
        "divergence_one_liner": _divergence_one_liner(viz.get("divergence")),
        "jingcai_sp": jingcai_sp,
        "form_one_liner": _form_one_liner(context.get("club_form")),
        "similar_one_liner": _similar_one_liner(context.get("history_similar")),
        "recent_form_one_liner": _form_one_liner(context.get("recent_form")),
        "missing": _missing_list(viz, context),
    }
    return summary


def format_viz_summary_line(summary: dict) -> str:
    """Render a short line for dashboard/list views."""
    if not summary:
        return "—"
    parts = []
    top = (summary.get("score_top") or [])[:1]
    if top:
        parts.append(f"比分 {top[0]['score']} {top[0]['p']:.0%}")
    p1x2 = summary.get("poisson_1x2") or {}
    pmax = max(
        [("主", p1x2.get("home")), ("平", p1x2.get("draw")), ("客", p1x2.get("away"))],
        key=lambda x: x[1] or -1,
    )
    if pmax[1] is not None:
        parts.append(f"模型偏{pmax[0]} {pmax[1]:.0f}%")
    edge_side = summary.get("edge_side")
    if edge_side and edge_side != "none":
        parts.append(f"edge {edge_side} {summary.get('edge_pp', 0):.0f}%")
    div = summary.get("divergence_one_liner")
    if div:
        parts.append(div)
    return " · ".join(parts) if parts else "—"
