"""Product focus helpers — jingcai 1X2 / rqsp-first, optional score prediction.

Q1-D0: 产品转向竞彩开售联赛。默认联赛模式（非世界杯）。
"""

from __future__ import annotations

from datetime import datetime

import config as cfg
from time_utils import now_beijing


def score_prediction_enabled() -> bool:
    return bool(getattr(cfg, "SCORE_PREDICTION_ENABLED", True))


def knockout_phase() -> bool:
    """是否处于淘汰赛阶段。Q1-D0 后默认 False（联赛模式）。"""
    return getattr(cfg, "TOURNAMENT_PHASE", "league") == "knockout"


def focus_jingcai_only() -> bool:
    """首页是否默认只显示竞彩在售场。

    竞彩官方开售列表通常在北京时间 11:00 前后才放出，此前若只按竞彩信号过滤
    会导致已保存的场次全部空白。因此 configured True 时，仍只在开售时间之后
    才生效；开售之前自动回退为显示全部已保存场次。
    """
    base = bool(getattr(cfg, "FOCUS_JINGCAI_ONLY", True))
    if not base:
        return False
    release_hour = getattr(cfg, "JINGCAI_RELEASE_HOUR", 11)
    try:
        return now_beijing().hour >= release_hour
    except Exception:
        return base


def ai_profile() -> str:
    """AI 默认 profile：联赛而非世界杯。"""
    return getattr(cfg, "AI_PROFILE_DEFAULT", "league")


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
