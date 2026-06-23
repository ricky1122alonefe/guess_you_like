"""Poisson / Dixon-Coles score model from odds."""

from __future__ import annotations

from typing import Any

from score_models import build_score_model


def apply_poisson(
    pred: dict,
    cur: dict,
    eu_imp: dict | None,
    avg_goals: float | None,
    quant: dict[str, Any],
) -> None:
    pick = pred.get("result_1x2")
    sm = build_score_model(
        eu_home=cur.get("eu_home"),
        eu_draw=cur.get("eu_draw"),
        eu_away=cur.get("eu_away"),
        fair_home_pct=(eu_imp or {}).get("fair_home_pct"),
        fair_draw_pct=(eu_imp or {}).get("fair_draw_pct"),
        fair_away_pct=(eu_imp or {}).get("fair_away_pct"),
        avg_total_goals=avg_goals,
        ah_line=cur.get("ah_line"),
        pick_1x2=pick if pick in ("home", "draw", "away") else None,
    )
    if not sm:
        return
    quant["score_model"] = sm
    from product_focus import score_prediction_enabled

    if score_prediction_enabled():
        pred["model_likely_scores"] = sm.get("likely_scores") or []
        pred["model_likely_scores_detail"] = sm.get("likely_scores_detail") or []
        pred["model_stretch_scores"] = [s.get("score") for s in sm.get("stretch_scores") or []]
    else:
        for key in ("likely_scores", "likely_scores_detail", "top_scores", "all_scores", "stretch_scores"):
            sm.pop(key, None)
        quant["score_model"] = sm
