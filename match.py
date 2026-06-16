"""Find historically similar odds profiles."""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from parser import MatchOdds


@dataclass
class MatchConfig:
    line_tol: float = 0.25
    water_tol: float = 0.18
    eu_home_tol: float = 0.30
    eu_draw_tol: float = 0.40
    eu_away_tol: float = 0.50
    min_samples: int = 15


import config as cfg

SCORE_POOL_TOP_N = cfg.SCORE_POOL_TOP_N


def _similarity_weight(dist) -> float:
    if dist is None or (isinstance(dist, float) and dist != dist):
        return 1.0
    if dist == float("inf"):
        return 0.0
    # 越接近当前盘口权重越高（指数衰减）
    return math.exp(-cfg.SCORE_SIMILARITY_DECAY * float(dist))


def _compute_score_tops(matches: pd.DataFrame, *, top_n: int = SCORE_POOL_TOP_N) -> dict:
    """Score frequency from the most similar subset, weighted by closeness."""
    from collections import Counter

    df = matches
    if "_similarity_dist" in df.columns:
        df = df.sort_values("_similarity_dist", kind="mergesort").head(min(top_n, len(df)))

    def weighted_counter(sub: pd.DataFrame) -> Counter:
        c: Counter = Counter()
        has_dist = "_similarity_dist" in sub.columns
        for _, row in sub.iterrows():
            if pd.isna(row.get("score_h")) or pd.isna(row.get("score_a")):
                continue
            sc = f"{int(row['score_h'])}-{int(row['score_a'])}"
            wt = _similarity_weight(row["_similarity_dist"]) if has_dist else 1.0
            c[sc] += wt
        return c

    def tops(sub: pd.DataFrame, n: int = 12) -> list[dict]:
        if sub.empty:
            return []
        c = weighted_counter(sub)
        total = sum(c.values()) or 1.0
        return [
            {"score": sc, "count": round(cnt, 3), "pct": round(cnt / total * 100, 1)}
            for sc, cnt in c.most_common(n)
        ]

    by_result = {}
    for res in ("home", "draw", "away"):
        sub = df[df["result_1x2"] == res]
        if not sub.empty:
            by_result[res] = tops(sub)
    return {
        "score_top": tops(df),
        "score_top_by_result": by_result,
        "score_pool_size": len(df),
    }


def _eu_tolerances(current: MatchOdds, cfg: MatchConfig) -> tuple[float, float, float]:
    """Widen EU tolerances for heavy favorites / longshots (low decimal odds)."""
    home_tol = cfg.eu_home_tol
    draw_tol = cfg.eu_draw_tol
    away_tol = cfg.eu_away_tol
    if current.eu_home is not None and current.eu_home < 1.35:
        home_tol = max(home_tol, 0.55 - current.eu_home * 0.15)
    if current.eu_away is not None and current.eu_away < 1.35:
        away_tol = max(away_tol, 0.55 - current.eu_away * 0.15)
    return home_tol, draw_tol, away_tol


def history_for_phase(history: pd.DataFrame, phase: str) -> pd.DataFrame:
    """Map history columns to open or closing odds for like-with-like matching."""
    if phase == "close":
        return history
    df = history.dropna(subset=["eu_home_open"]).copy()
    mapping = {
        "eu_home_open": "eu_home",
        "eu_draw_open": "eu_draw",
        "eu_away_open": "eu_away",
        "ah_line_open": "ah_line",
        "ah_home_water_open": "ah_home_water",
        "ah_away_water_open": "ah_away_water",
    }
    for src, dst in mapping.items():
        if src in df.columns:
            df[dst] = df[src]
    return df


def find_similar_eu_only(
    history: pd.DataFrame,
    current: MatchOdds,
    cfg: MatchConfig | None = None,
    *,
    phase: str = "close",
) -> pd.DataFrame:
    """仅按欧赔匹配，可纳入国家队/美洲联赛（无亚盘）。"""
    cfg = cfg or MatchConfig()
    df = history_for_phase(history, phase).dropna(subset=["eu_home"]).copy()
    home_tol, draw_tol, away_tol = _eu_tolerances(current, cfg)
    if current.eu_home is not None:
        df = df[(df["eu_home"] - current.eu_home).abs() <= home_tol]
    if current.eu_draw is not None and not df.empty:
        df = df[(df["eu_draw"] - current.eu_draw).abs() <= draw_tol]
    if current.eu_away is not None and not df.empty:
        df = df[(df["eu_away"] - current.eu_away).abs() <= away_tol]
    return df.reset_index(drop=True)


def find_similar(
    history: pd.DataFrame,
    current: MatchOdds,
    cfg: MatchConfig | None = None,
    *,
    phase: str = "close",
) -> pd.DataFrame:
    cfg = cfg or MatchConfig()
    df = history_for_phase(history, phase).copy()

    if current.ah_line is not None:
        df = df.dropna(subset=["ah_line", "ah_home_water", "ah_away_water"])
        home_dec = current.ah_home_decimal
        away_dec = current.ah_away_decimal
        line_tol = cfg.line_tol
        if abs(current.ah_line) >= 1.25:
            line_tol = max(line_tol, abs(current.ah_line) * 0.2)
        mask = (
            (df["ah_line"] - current.ah_line).abs() <= line_tol
        ) & (
            (df["ah_home_water"] - home_dec).abs() <= cfg.water_tol
        ) & (
            (df["ah_away_water"] - away_dec).abs() <= cfg.water_tol
        )
        df = df[mask]
    else:
        df = df.dropna(subset=["eu_home"])

    if current.eu_home is not None:
        df = df.dropna(subset=["eu_home"])
        home_tol, draw_tol, away_tol = _eu_tolerances(current, cfg)
        df = df[(df["eu_home"] - current.eu_home).abs() <= home_tol]

    if current.eu_draw is not None and not df.empty:
        _, draw_tol, away_tol = _eu_tolerances(current, cfg)
        df = df[(df["eu_draw"] - current.eu_draw).abs() <= draw_tol]
    if current.eu_away is not None and not df.empty:
        _, _, away_tol = _eu_tolerances(current, cfg)
        df = df[(df["eu_away"] - current.eu_away).abs() <= away_tol]

    return df.reset_index(drop=True)


def _row_similarity_distance(row, current: MatchOdds, cfg: MatchConfig, *, include_ah: bool) -> float:
    """Lower distance = more similar to current odds."""
    parts: list[float] = []
    if include_ah and current.ah_line is not None and pd.notna(row.get("ah_line")):
        parts.append(abs(float(row["ah_line"]) - current.ah_line) / max(cfg.line_tol, 0.01))
        if current.ah_home_decimal is not None and pd.notna(row.get("ah_home_water")):
            parts.append(
                abs(float(row["ah_home_water"]) - current.ah_home_decimal) / max(cfg.water_tol, 0.01)
            )
        if current.ah_away_decimal is not None and pd.notna(row.get("ah_away_water")):
            parts.append(
                abs(float(row["ah_away_water"]) - current.ah_away_decimal) / max(cfg.water_tol, 0.01)
            )
    if current.eu_home is not None and pd.notna(row.get("eu_home")):
        parts.append(abs(float(row["eu_home"]) - current.eu_home) / max(cfg.eu_home_tol, 0.01))
    if current.eu_draw is not None and pd.notna(row.get("eu_draw")):
        parts.append(abs(float(row["eu_draw"]) - current.eu_draw) / max(cfg.eu_draw_tol, 0.01))
    if current.eu_away is not None and pd.notna(row.get("eu_away")):
        parts.append(abs(float(row["eu_away"]) - current.eu_away) / max(cfg.eu_away_tol, 0.01))
    if not parts:
        return float("inf")
    return sum(parts) / len(parts)


def _rank_by_similarity(
    matches: pd.DataFrame,
    current: MatchOdds,
    cfg: MatchConfig,
    *,
    include_ah: bool,
) -> pd.DataFrame:
    if matches.empty:
        return matches
    df = matches.copy()
    df["_similarity_dist"] = df.apply(
        lambda row: _row_similarity_distance(row, current, cfg, include_ah=include_ah),
        axis=1,
    )
    return df.sort_values("_similarity_dist", kind="mergesort").reset_index(drop=True)


def _format_samples(matches: pd.DataFrame, limit: int) -> list[dict]:
    cols = [
        "date", "home", "away", "score_h", "score_a",
        "result_1x2", "ah_line", "ah_home_water", "ah_away_water",
        "eu_home", "eu_draw", "eu_away", "competition", "source",
        "ah_home_result", "ah_away_result", "_similarity_dist",
    ]
    pick = [c for c in cols if c in matches.columns]
    rows = matches[pick].head(limit).to_dict(orient="records")
    for row in rows:
        dist = row.pop("_similarity_dist", None)
        if dist is not None and dist != float("inf"):
            row["similarity_dist"] = round(float(dist), 3)
    return rows


def summarize(
    matches: pd.DataFrame,
    sample_limit: int = 5,
    *,
    current: MatchOdds | None = None,
    cfg: MatchConfig | None = None,
    include_ah: bool = True,
) -> dict:
    if matches.empty:
        return {"count": 0}

    ranked = matches
    if current is not None:
        ranked = _rank_by_similarity(matches, current, cfg or MatchConfig(), include_ah=include_ah)

    total = len(ranked)
    ah_home = ranked["ah_home_result"].dropna()
    ah_away = ranked["ah_away_result"].dropna()

    def rate(series, predicate):
        if series.empty:
            return None
        return float((series.apply(predicate)).mean())

    return {
        "count": total,
        "worldcup_count": int((ranked["competition"] == "worldcup").sum()),
        "qualifier_count": int((ranked["competition"] == "qualifier").sum()),
        "americas_count": int((ranked["competition"] == "americas").sum()),
        "league_count": int((ranked["competition"] == "league").sum()),
        "home_win_rate": rate(ranked["result_1x2"], lambda x: x == "home"),
        "draw_rate": rate(ranked["result_1x2"], lambda x: x == "draw"),
        "away_win_rate": rate(ranked["result_1x2"], lambda x: x == "away"),
        "ah_home_full_win": rate(ah_home, lambda x: x == 1.0),
        "ah_home_half_win": rate(ah_home, lambda x: x == 0.5),
        "ah_home_push": rate(ah_home, lambda x: x == 0.0),
        "ah_home_half_loss": rate(ah_home, lambda x: x == -0.5),
        "ah_home_full_loss": rate(ah_home, lambda x: x == -1.0),
        "ah_home_net": float(ah_home.mean()) if not ah_home.empty else None,
        "ah_away_net": float(ah_away.mean()) if not ah_away.empty else None,
        "avg_total_goals": float((ranked["score_h"] + ranked["score_a"]).mean()),
        "samples": _format_samples(ranked, sample_limit),
        **_compute_score_tops(ranked),
    }
