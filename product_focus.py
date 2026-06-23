"""Product focus helpers — jingcai 1X2 / rqsp-first, optional score prediction."""

from __future__ import annotations

import config as cfg


def score_prediction_enabled() -> bool:
    return bool(getattr(cfg, "SCORE_PREDICTION_ENABLED", True))


def strip_score_fields(pred: dict) -> dict:
    """Remove score recommendation artifacts from a prediction dict."""
    if score_prediction_enabled():
        return pred
    for key in (
        "likely_scores",
        "likely_scores_detail",
        "model_likely_scores",
        "model_likely_scores_detail",
        "model_stretch_scores",
        "score_recommend",
        "score_pattern_analysis",
    ):
        pred.pop(key, None)
    row = pred.get("predict_row")
    if isinstance(row, dict):
        row = dict(row)
        row.pop("推荐比分", None)
        pred["predict_row"] = row
    quant = pred.get("quant")
    if isinstance(quant, dict):
        sm = quant.get("score_model")
        if isinstance(sm, dict):
            sm = dict(sm)
            for key in ("likely_scores", "likely_scores_detail", "top_scores", "all_scores", "stretch_scores"):
                sm.pop(key, None)
            quant["score_model"] = sm
            pred["quant"] = quant
    return pred
