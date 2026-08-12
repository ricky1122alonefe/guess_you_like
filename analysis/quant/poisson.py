"""Poisson / Dixon-Coles score model from odds and recent form.

产品定位：
泊松比分矩阵是轻量模型层，输出为 "期望进球(泊松λ)"；禁止用 "xG" 作为λ的主标签。
"""

from __future__ import annotations

import logging
from typing import Any

import config
from score_models import build_score_model, probs_from_matrix, score_matrix, top_scores

log = logging.getLogger(__name__)

MAX_GOALS = int(getattr(config, "POISSON_MAX_GOALS", 5))
ELO_DIFF_SENSITIVITY = float(getattr(config, "POISSON_ELO_DIFF_SENSITIVITY", 0.15))


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


def _safe_goals_per_game(goals: int | float | None, played: int | float | None) -> float | None:
    if goals is None or played is None:
        return None
    try:
        p = int(played)
        g = float(goals)
    except (TypeError, ValueError):
        return None
    if p <= 0 or g < 0:
        return None
    return g / p


def _ou25_from_matrix(cells: dict[tuple[int, int], float]) -> dict[str, float]:
    over = 0.0
    for (i, j), prob in cells.items():
        if i + j > 2.5:
            over += prob
    under = max(0.0, 1.0 - over)
    total = over + under
    if total <= 0:
        return {"over": 0.0, "under": 0.0}
    return {"over": round(over / total, 4), "under": round(under / total, 4)}


def build_poisson_matrix(
    home_team: str,
    away_team: str,
    *,
    club_form: dict[str, Any] | None = None,
    elo_diff: float | None = None,
    max_goals: int = MAX_GOALS,
) -> dict[str, Any] | None:
    """基于两队近期攻防（club_form）构建泊松比分矩阵。

    λ_home = (主队场均进球 + 客队场均失球) / 2
    λ_away = (客队场均进球 + 主队场均失球) / 2

    样本不足 → 返回 None，不伪造矩阵。
    可选 elo_diff 对 λ 做轻量微调。
    """
    if not home_team or not away_team:
        return None

    if club_form is None:
        try:
            from analysis.team_form.club_form import build_club_form

            club_form = build_club_form(home_team, away_team)
        except Exception as exc:
            log.debug("build_club_form failed for poisson: %s", exc)
            return None

    overall = (club_form or {}).get("overall") or {}
    home_stats = overall.get("home_team") or {}
    away_stats = overall.get("away_team") or {}

    home_played = home_stats.get("played") or 0
    away_played = away_stats.get("played") or 0
    if home_played <= 0 or away_played <= 0:
        return None

    home_gf = _safe_goals_per_game(home_stats.get("goals_for"), home_played)
    home_ga = _safe_goals_per_game(home_stats.get("goals_against"), home_played)
    away_gf = _safe_goals_per_game(away_stats.get("goals_for"), away_played)
    away_ga = _safe_goals_per_game(away_stats.get("goals_against"), away_played)

    if home_gf is None or home_ga is None or away_gf is None or away_ga is None:
        return None

    lam_home = (home_gf + away_ga) / 2.0
    lam_away = (away_gf + home_ga) / 2.0

    if lam_home <= 0 or lam_away <= 0:
        return None

    # Elo diff 轻量微调：强队提升本队 λ，压缩对手 λ
    if elo_diff is not None and elo_diff != 0:
        scale = 1.0 + ELO_DIFF_SENSITIVITY * (elo_diff / 400.0)
        if scale > 0:
            lam_home *= scale
            lam_away /= scale

    cells = score_matrix(lam_home, lam_away, max_goals=max_goals)
    p_1x2 = probs_from_matrix(cells)

    score_map = {f"{i}-{j}": round(p, 5) for (i, j), p in cells.items()}
    top = top_scores(cells, limit=5)

    return {
        "lambda_home": round(lam_home, 3),
        "lambda_away": round(lam_away, 3),
        "score_matrix": score_map,
        "p_1x2": {k: round(v, 4) for k, v in p_1x2.items()},
        "p_ou25": _ou25_from_matrix(cells),
        "top_scores": [{"score": t["score"], "prob_pct": t["prob_pct"]} for t in top],
        "method": "poisson_independent",
        "label": "期望进球(泊松λ)",
    }
