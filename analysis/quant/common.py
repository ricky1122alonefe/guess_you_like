"""Shared helpers for quant analyzers."""

from __future__ import annotations

from typing import Any

from eu_implied_metrics import compute_eu_implied
from share_card import split_teams


def coerce_odds_dict(cur: Any) -> dict:
    """Accept odds snapshot dict or parser.MatchOdds dataclass."""
    if not cur:
        return {}
    if isinstance(cur, dict):
        return cur
    d = getattr(cur, "__dict__", None)
    return d if isinstance(d, dict) else {}


def ensure_eu_implied(pred: dict, cur: dict) -> dict | None:
    eu_imp = pred.get("eu_implied")
    if eu_imp:
        return eu_imp
    m = compute_eu_implied(cur.get("eu_home"), cur.get("eu_draw"), cur.get("eu_away"))
    if m:
        eu_imp = m.to_dict()
        pred["eu_implied"] = eu_imp
        return eu_imp
    return None


def _valid_odds(v: Any) -> bool:
    try:
        return float(v) > 0
    except (TypeError, ValueError):
        return False


def fill_eu_from_books_major(
    pred: dict,
    cur: dict,
    *,
    output_root=None,
    fixture_id: str | None = None,
) -> dict:
    """cur 缺欧赔（0/缺失）时回退到 major 均值，与 three_lane 欧赔轨同源。

    来源链与 attach_market_lanes 一致：snapshot/raw_meta → DB timeline → xls。
    仅当 major 均值三值齐全且均 > 0 才回填；否则原样返回（诚实 missing，不编赔率）。
    """
    if not isinstance(cur, dict):
        cur = {}
    if (
        _valid_odds(cur.get("eu_home"))
        and _valid_odds(cur.get("eu_draw"))
        and _valid_odds(cur.get("eu_away"))
    ):
        return cur
    try:
        from analysis.market.three_lane import _load_eu_books_major, _mean_odds

        major = _load_eu_books_major(
            pred,
            output_root=output_root,
            fixture_id=fixture_id or (pred or {}).get("fixture_id"),
        )
        mean = _mean_odds(major) if major else None
    except Exception:  # noqa: BLE001 - 回退失败保持原样
        mean = None
    if not mean:
        return cur
    home, draw, away = mean.get("home"), mean.get("draw"), mean.get("away")
    if not (_valid_odds(home) and _valid_odds(draw) and _valid_odds(away)):
        return cur
    out = dict(cur)
    if not _valid_odds(out.get("eu_home")):
        out["eu_home"] = home
    if not _valid_odds(out.get("eu_draw")):
        out["eu_draw"] = draw
    if not _valid_odds(out.get("eu_away")):
        out["eu_away"] = away
    return out


def avg_goals_from_similarity(pred: dict) -> float | None:
    sim = pred.get("similarity_analysis") or {}
    for block in sim.get("open") or []:
        if block.get("avg_total_goals"):
            return block.get("avg_total_goals")
    return None


def resolve_team_names(pred: dict) -> tuple[str, str]:
    hr, ar = split_teams(pred.get("match") or "")
    if hr and ar:
        try:
            from wc_standings_fetch import normalize_team

            hr, ar = normalize_team(hr), normalize_team(ar)
        except Exception:
            pass
    return hr, ar
