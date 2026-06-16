"""Match phase helpers and post-match evaluation."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from time_utils import now_beijing, to_beijing

RESULT_CN = {"home": "主胜", "draw": "平局", "away": "客胜"}
RESULT_MAP = {
    "主胜": "home", "主": "home", "home": "home", "h": "home", "3": "home",
    "平": "draw", "平局": "draw", "draw": "draw", "d": "draw", "1": "draw",
    "客胜": "away", "客": "away", "away": "away", "a": "away", "0": "away",
}

FINISHED_AFTER_MINUTES = 105
LIVE_GRACE_MINUTES = 30


def goals_to_result_1x2(home: int, away: int) -> str:
    if home > away:
        return "home"
    if home == away:
        return "draw"
    return "away"


def norm_result(text: str | None) -> str | None:
    s = (text or "").strip()
    return RESULT_MAP.get(s) or RESULT_MAP.get(s.lower())


def match_phase(
    kickoff_at: datetime | None,
    *,
    now: datetime | None = None,
    has_result: bool = False,
) -> str:
    """Return finished | live | upcoming | unknown."""
    if has_result:
        return "finished"
    if kickoff_at is None:
        return "unknown"
    now = now or now_beijing()
    ko = to_beijing(kickoff_at)
    ref = to_beijing(now)
    delta_min = (ref - ko).total_seconds() / 60.0
    if delta_min >= FINISHED_AFTER_MINUTES:
        return "finished"
    if delta_min >= -LIVE_GRACE_MINUTES:
        return "live"
    return "upcoming"


def evaluate_prediction_hits(
    pred: dict | None,
    *,
    home_score: int,
    away_score: int,
) -> dict[str, Any]:
    """Compare stored prediction vs actual score; reuse check_results semantics."""
    score_text = f"{home_score}-{away_score}"
    actual_1x2 = goals_to_result_1x2(home_score, away_score)
    actual_cn = RESULT_CN[actual_1x2]

    out: dict[str, Any] = {
        "score_text": score_text,
        "result_1x2": actual_1x2,
        "result_1x2_cn": actual_cn,
        "pick_1x2_cn": None,
        "pick_jingcai_cn": None,
        "recommended_scores": None,
        "hit_1x2": None,
        "hit_score": None,
    }
    if not pred:
        return out

    row = pred.get("predict_row") or {}
    from jingcai_pick import final_recommendation_cn

    pick_cn = final_recommendation_cn(pred)
    pick_key = norm_result(pick_cn)
    out["pick_jingcai_cn"] = pick_cn
    out["pick_1x2_cn"] = row.get("胜平负") or pred.get("result_1x2_cn")

    if pick_key:
        out["hit_1x2"] = pick_key == actual_1x2

    scores_raw = row.get("推荐比分") or ""
    if not scores_raw:
        detail = pred.get("likely_scores_detail") or pred.get("likely_scores") or []
        if isinstance(detail, list):
            scores_raw = "、".join(str(s) for s in detail)
    out["recommended_scores"] = scores_raw or None
    if scores_raw:
        recommended = [s.split("(")[0].strip() for s in scores_raw.split("、") if s.strip()]
        out["hit_score"] = score_text in recommended

    return out
