"""Poisson + Dixon-Coles scoreline model — free structural pricing layer."""

from __future__ import annotations

import math
import re
from typing import Any

import config as cfg

OUTCOMES = ("home", "draw", "away")
RHO = getattr(cfg, "DIXON_COLES_RHO", -0.13)
MAX_GOALS = getattr(cfg, "SCORE_MODEL_MAX_GOALS", 6)


def _extract_prob_pct(detail: str) -> float | None:
    """Extract numeric probability from strings like '2-1(15.3%)'.

    Returns None when the string has no probability suffix.
    Whitespace inside the suffix is tolerated.
    """
    if not isinstance(detail, str):
        return None
    cleaned = detail.replace(" ", "")
    if "(" not in cleaned or not cleaned.endswith("%)"):
        return None
    try:
        start = cleaned.rfind("(") + 1
        return float(cleaned[start:-2])
    except (ValueError, TypeError):
        return None


def filter_valid_score_details(details: list[str]) -> list[str]:
    """Return score details whose probability is strictly > 0.

    Strings without a probability suffix are preserved (e.g. plain score lists).
    """
    valid: list[str] = []
    for item in details:
        if not item:
            continue
        prob = _extract_prob_pct(item)
        if prob is None or prob > 0:
            valid.append(item)
    return valid


_ZERO_PCT_RE = re.compile(r"\(\s*0(?:\.0)?\s*%\)")
_SCORE_ITEM_RE = re.compile(r"\d+-\d+(?:\(\d+(?:\.\d+)?%\))?")


def _scrub_score_text(text: str) -> str:
    """从「2-1(12.3%)、3-1(0.0%)」中剔除全 0.0% 项，保留正常概率比分。"""
    if not isinstance(text, str) or not text:
        return text
    items = [x.strip() for x in re.split(r"[、,，/\s]+", text) if x.strip()]
    keep = [x for x in items if not _ZERO_PCT_RE.search(x)]
    return "、".join(keep)


def _scrub_score_segments(text: str) -> str:
    """移除 summary 中全 0.0% 的「比分 …」段；混合时保留正常概率比分。"""
    if not isinstance(text, str) or not text:
        return text

    def _rebuild(match: re.Match[str]) -> str:
        seg = match.group(0)
        items = _SCORE_ITEM_RE.findall(seg)
        if not items:
            return seg
        keep = [it for it in items if not _ZERO_PCT_RE.search(it)]
        if keep:
            return "比分 " + "、".join(keep) + "。"
        return ""

    out = re.sub(r"比分[^。]*?。", _rebuild, text)
    out = re.sub(r"[，,]\s*。", "。", out)
    out = re.sub(r"[\s　]+", " ", out).strip()
    return out


def scrub_zero_percent_scores(pred: dict[str, Any]) -> None:
    """展示/落盘前统一清理全 0.0% 比分（summary 段 / 推荐比分 / likely_scores_detail）。

    就地修改 pred。有正常概率的比分照常保留。
    """
    if not isinstance(pred, dict):
        return
    summary = pred.get("summary")
    if isinstance(summary, str) and summary:
        pred["summary"] = _scrub_score_segments(summary)
    row = pred.get("predict_row")
    if isinstance(row, dict):
        rec = row.get("推荐比分")
        if isinstance(rec, str) and rec:
            row["推荐比分"] = _scrub_score_text(rec)
    detail_raw = pred.get("likely_scores_detail")
    if isinstance(detail_raw, list) and detail_raw:
        filtered = filter_valid_score_details([str(x) for x in detail_raw])
        pred["likely_scores_detail"] = filtered
        if not filtered:
            # 带概率的 detail 全为 0.0% 等无有效概率：裸比分 likely_scores 同样
            # 不可信，一并清空，避免展示「仅 2-1 无 %」这类无有效概率的比分。
            pred["likely_scores"] = []
    else:
        for key in ("likely_scores_detail", "likely_scores"):
            val = pred.get(key)
            if isinstance(val, list) and val:
                pred[key] = filter_valid_score_details([str(x) for x in val])
            elif isinstance(val, str) and val:
                pred[key] = _scrub_score_text(val)


def _poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def _dc_tau(i: int, j: int, lam_h: float, lam_a: float, rho: float) -> float:
    if i > 1 or j > 1:
        return 1.0
    if i == 0 and j == 0:
        return 1.0 - lam_h * lam_a * rho
    if i == 0 and j == 1:
        return 1.0 + lam_h * rho
    if i == 1 and j == 0:
        return 1.0 + lam_a * rho
    if i == 1 and j == 1:
        return 1.0 - rho
    return 1.0


def score_matrix(
    lam_home: float,
    lam_away: float,
    *,
    rho: float = RHO,
    max_goals: int = MAX_GOALS,
) -> dict[tuple[int, int], float]:
    """Dixon-Coles adjusted score probability matrix."""
    cells: dict[tuple[int, int], float] = {}
    total = 0.0
    for i in range(max_goals + 1):
        for j in range(max_goals + 1):
            p = _poisson_pmf(i, lam_home) * _poisson_pmf(j, lam_away) * _dc_tau(i, j, lam_home, lam_away, rho)
            cells[(i, j)] = p
            total += p
    if total <= 0:
        return cells
    return {k: v / total for k, v in cells.items()}


def probs_from_matrix(cells: dict[tuple[int, int], float]) -> dict[str, float]:
    p = {"home": 0.0, "draw": 0.0, "away": 0.0}
    for (i, j), prob in cells.items():
        if i > j:
            p["home"] += prob
        elif i == j:
            p["draw"] += prob
        else:
            p["away"] += prob
    return p


def top_scores(
    cells: dict[tuple[int, int], float],
    *,
    limit: int = 8,
    pick: str | None = None,
) -> list[dict[str, Any]]:
    rows = [
        {"score": f"{i}-{j}", "prob_pct": round(prob * 100, 1), "outcome": "home" if i > j else ("draw" if i == j else "away")}
        for (i, j), prob in cells.items()
    ]
    rows.sort(key=lambda x: -x["prob_pct"])
    if pick in OUTCOMES:
        primary = [r for r in rows if r["outcome"] == pick]
        other = [r for r in rows if r["outcome"] != pick]
        rows = primary + other
    return rows[:limit]


def ah_home_cover_prob(cells: dict[tuple[int, int], float], line: float) -> float | None:
    """P(home covers Asian handicap from home perspective)."""
    if line is None:
        return None
    try:
        line = float(line)
    except (TypeError, ValueError):
        return None
    cover = 0.0
    for (i, j), prob in cells.items():
        diff = i - j + line
        if diff > 0.25:
            cover += prob
        elif diff == 0.25:
            cover += prob * 0.5
        elif diff == -0.25:
            cover += prob * 0.5
        elif diff == 0:
            pass
    return round(cover, 4)


def fit_lambdas_from_probs(
    fair_home: float,
    fair_draw: float,
    fair_away: float,
    *,
    total_hint: float | None = None,
    rho: float = RHO,
) -> tuple[float, float]:
    """Grid-fit (λ_h, λ_a) to match de-vigged 1X2 probs."""
    th = total_hint if total_hint and total_hint > 0.5 else 2.55
    target = {
        "home": max(0.01, min(0.98, fair_home)),
        "draw": max(0.01, min(0.98, fair_draw)),
        "away": max(0.01, min(0.98, fair_away)),
    }
    best = (th / 2, th / 2)
    best_err = 1e9
    for hi in range(40, 361, 5):
        lh = hi / 100.0
        for ai in range(40, 361, 5):
            la = ai / 100.0
            if abs((lh + la) - th) > 1.2:
                continue
            cells = score_matrix(lh, la, rho=rho)
            got = probs_from_matrix(cells)
            err = sum((got[k] - target[k]) ** 2 for k in OUTCOMES)
            if err < best_err:
                best_err = err
                best = (lh, la)
    return best


def build_score_model(
    *,
    eu_home: float | None = None,
    eu_draw: float | None = None,
    eu_away: float | None = None,
    fair_home_pct: float | None = None,
    fair_draw_pct: float | None = None,
    fair_away_pct: float | None = None,
    avg_total_goals: float | None = None,
    ah_line: float | None = None,
    pick_1x2: str | None = None,
) -> dict[str, Any] | None:
    """Build full score model output from odds + optional sample avg goals."""
    if fair_home_pct is not None:
        fh = fair_home_pct / 100.0
        fd = (fair_draw_pct or 0) / 100.0
        fa = (fair_away_pct or 0) / 100.0
    elif eu_home and eu_draw and eu_away:
        ih, id_, ia = 1 / eu_home, 1 / eu_draw, 1 / eu_away
        s = ih + id_ + ia
        fh, fd, fa = ih / s, id_ / s, ia / s
    else:
        return None

    lam_h, lam_a = fit_lambdas_from_probs(fh, fd, fa, total_hint=avg_total_goals)
    cells = score_matrix(lam_h, lam_a)
    model_probs = probs_from_matrix(cells)
    tops = top_scores(cells, limit=8, pick=pick_1x2 if pick_1x2 in OUTCOMES else None)
    stretch = tops[3:5] if len(tops) > 3 else []

    return {
        "model": "dixon_coles_poisson",
        "lambda_home": round(lam_h, 3),
        "lambda_away": round(lam_a, 3),
        "rho": RHO,
        "avg_total_goals": round(lam_h + lam_a, 2),
        "prob_1x2_pct": {k: round(model_probs[k] * 100, 1) for k in OUTCOMES},
        "top_scores": tops[:3],
        "stretch_scores": stretch,
        "all_scores": tops,
        "likely_scores": [t["score"] for t in tops[:3]],
        "likely_scores_detail": filter_valid_score_details(
            [f"{t['score']}({t['prob_pct']}%)" for t in tops[:3]]
        ),
        "ah_home_cover_pct": round(ah_home_cover_prob(cells, ah_line) * 100, 1) if ah_line is not None else None,
    }
