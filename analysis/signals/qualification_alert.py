"""Highlight group-stage qualification matches with EU↔AH divergence."""

from __future__ import annotations

from typing import Any

import config as cfg
from analysis.signals.eu_ah_divergence import analyze_eu_ah_divergence

# 出线/战意相关场次：欧亚分歧需单独醒目标注
QUALIFICATION_MATCH_TYPES = frozenset({
    "must_win",
    "collusion_watch",
    "draw_friendly",
    "open_race",
    "gd_race",
    "conservative_favorite",
    "dead_rubber",
})


def build_qualification_divergence_alert(
    cur: dict,
    gs_analysis: dict[str, Any] | None,
    *,
    match_name: str = "",
    fixture_id: str = "",
) -> dict[str, Any] | None:
    """Return alert payload when knockout-relevant group match has EU/AH split."""
    if not gs_analysis or gs_analysis.get("is_finished"):
        return None

    mt = gs_analysis.get("match_type") or "normal"
    rnd = int(gs_analysis.get("round") or 0)
    if mt not in QUALIFICATION_MATCH_TYPES and rnd < 2:
        return None

    div = analyze_eu_ah_divergence(cur, fixture_id=fixture_id, match=match_name)
    if not div or div.divergence_score < cfg.QUALIFICATION_DIVERGENCE_MIN_SCORE:
        return None

    ctx = gs_analysis.get("match_type_cn") or mt
    tag = "出线·欧亚分歧"
    advice = (
        f"【{tag}】{ctx} + {div.consistency_cn}（{div.divergence_score}分）："
        f"{div.advice}"
    )
    return {
        "tag": tag,
        "alert_tags": [tag, f"欧亚·{div.severity_cn}"],
        "divergence_score": div.divergence_score,
        "severity": div.severity,
        "severity_cn": div.severity_cn,
        "consistency": div.consistency,
        "consistency_cn": div.consistency_cn,
        "group_context_cn": ctx,
        "round": rnd,
        "likely_direction_cn": gs_analysis.get("likely_direction_cn") or "",
        "advice": advice,
        "signals": div.signals[:5],
        "pattern_names": div.pattern_names[:4],
        "conversion_summary": div.conversion_summary,
    }
