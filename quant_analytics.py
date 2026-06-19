"""Attach Poisson/Elo/EV/MC bundle to predictions + quant backtest report.

Implementation lives under analysis/quant/; this module keeps the public API stable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from analysis.quant.bundle import run_quant_analysis
from elo_ratings import apply_finished_results, load_ratings
from share_card import split_teams


def attach_quant_analysis(pred: dict, *, cur: dict | None = None) -> dict:
    """Mutate pred with quant block (score model, EV, Elo, optional MC)."""
    return run_quant_analysis(pred, cur=cur)


def refresh_elo_from_settled(output_root: str | Path) -> dict[str, float]:
    """Update Elo from settled match files + WC API."""
    results: list[dict] = []
    settled_dir = Path(output_root) / "settled"
    if settled_dir.is_dir():
        for p in settled_dir.glob("*.json"):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                if d.get("home_score") is not None:
                    name = d.get("match_name") or ""
                    hr, ar = split_teams(name)
                    results.append({
                        "home": hr,
                        "away": ar,
                        "home_score": d["home_score"],
                        "away_score": d["away_score"],
                    })
            except (json.JSONDecodeError, KeyError):
                continue
    try:
        from wc_standings_fetch import fetch_finished_fixtures

        for fx in fetch_finished_fixtures():
            results.append({
                "home": fx.home,
                "away": fx.away,
                "home_score": fx.home_score,
                "away_score": fx.away_score,
            })
    except Exception:
        pass
    return apply_finished_results(results)


def build_quant_backtest_report(output_root: str | Path) -> dict[str, Any]:
    """Extended accuracy: 1X2, score, model score, AH, EV buckets."""
    from match_settlement import load_settled_map
    from worldcup_analytics import compute_accuracy_report, refresh_tournament_ledger

    root = Path(output_root)
    try:
        ledger = refresh_tournament_ledger(root)
        records = ledger.get("records") or []
    except Exception:
        records = list(load_settled_map(root).values())

    base = compute_accuracy_report(records)

    model_hit = model_total = 0
    hist_hit = hist_total = 0
    ev_pos_hit = ev_pos_total = 0
    ah_hit = ah_total = 0

    for r in records:
        payload = r.get("payload") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = {}
        pred = payload.get("prediction") or {}
        score_text = r.get("score_text") or ""
        if not score_text or "-" not in score_text:
            continue

        hs = r.get("home_score")
        aws = r.get("away_score")
        if hs is None or aws is None:
            continue
        actual = f"{hs}-{aws}"

        hist_scores = pred.get("likely_scores") or []
        if hist_scores:
            hist_total += 1
            if actual in [str(s).split("(")[0] for s in hist_scores[:3]]:
                hist_hit += 1

        model_scores = pred.get("model_likely_scores") or (pred.get("quant") or {}).get("score_model", {}).get("likely_scores") or []
        if model_scores:
            model_total += 1
            if actual in model_scores[:3]:
                model_hit += 1

        if r.get("hit_ah") is not None:
            ah_total += 1
            if r.get("hit_ah"):
                ah_hit += 1

        ev = (pred.get("quant") or {}).get("jingcai_ev") or pred.get("jingcai_ev") or {}
        if ev.get("ev_per_unit") is not None and ev.get("ev_per_unit", 0) > 0.03:
            ev_pos_total += 1
            if r.get("hit_1x2"):
                ev_pos_hit += 1

    def rate(h, t):
        return round(h / t * 100, 1) if t else None

    return {
        **base,
        "model_score": {
            "judged": model_total,
            "hit_top3": model_hit,
            "rate_pct": rate(model_hit, model_total),
        },
        "hist_score": {
            "judged": hist_total,
            "hit_top3": hist_hit,
            "rate_pct": rate(hist_hit, hist_total),
        },
        "ah_settled": {
            "judged": ah_total,
            "hit": ah_hit,
            "rate_pct": rate(ah_hit, ah_total),
        },
        "ev_positive": {
            "judged": ev_pos_total,
            "hit_1x2": ev_pos_hit,
            "rate_pct": rate(ev_pos_hit, ev_pos_total),
        },
        "elo_ratings_sample": dict(list(load_ratings().items())[:8]),
    }
