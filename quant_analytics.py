"""Attach Poisson/Elo/EV/MC bundle to predictions + quant backtest report."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from elo_ratings import apply_finished_results, load_ratings, match_elo_context
from eu_implied_metrics import compute_eu_implied
from group_mc import simulate_for_match
from jingcai_ev import compute_jingcai_ev
from score_models import build_score_model
from share_card import split_teams


def _coerce_odds_dict(cur) -> dict:
    """Accept odds snapshot dict or parser.MatchOdds dataclass."""
    if not cur:
        return {}
    if isinstance(cur, dict):
        return cur
    d = getattr(cur, "__dict__", None)
    return d if isinstance(d, dict) else {}


def attach_quant_analysis(pred: dict, *, cur: dict | None = None) -> dict:
    """Mutate pred with quant block (score model, EV, Elo, optional MC)."""
    cur = _coerce_odds_dict(cur or pred.get("odds_snapshot") or {})
    eu_imp = pred.get("eu_implied")
    if not eu_imp:
        m = compute_eu_implied(cur.get("eu_home"), cur.get("eu_draw"), cur.get("eu_away"))
        if m:
            eu_imp = m.to_dict()
            pred["eu_implied"] = eu_imp

    avg_goals = None
    sim = pred.get("similarity_analysis") or {}
    for block in sim.get("open") or []:
        if block.get("avg_total_goals"):
            avg_goals = block.get("avg_total_goals")
            break

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

    quant: dict[str, Any] = {}
    if sm:
        quant["score_model"] = sm
        pred["model_likely_scores"] = sm.get("likely_scores") or []
        pred["model_likely_scores_detail"] = sm.get("likely_scores_detail") or []
        pred["model_stretch_scores"] = [s.get("score") for s in sm.get("stretch_scores") or []]

    hr, ar = split_teams(pred.get("match") or "")
    if hr and ar:
        try:
            from wc_standings_fetch import normalize_team

            hr, ar = normalize_team(hr), normalize_team(ar)
        except Exception:
            pass
        quant["elo"] = match_elo_context(hr, ar, ratings=load_ratings())

    pred["quant"] = quant
    ev = compute_jingcai_ev(pred)
    if ev:
        quant["jingcai_ev"] = ev
        pred["jingcai_ev"] = ev
        if ev.get("value_bet"):
            pred["value_bet"] = True

    try:
        mc = simulate_for_match(hr, ar, n_sims=2000)
        if mc:
            quant["group_mc"] = mc
    except Exception:
        pass

    return pred


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
