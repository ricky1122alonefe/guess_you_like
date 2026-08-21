"""Tests for score picking and summary filtering in analysis engine."""

from __future__ import annotations

from analysis.rules.engine import _pick_scores


def test_pick_scores_filters_zero_percent_historical_probs():
    """When all historical joint probabilities are 0.0%, return empty lists."""
    stats = {
        "count": 10,
        "avg_total_goals": 2.5,
        "score_top": [
            {"score": "2-1", "pct": 0.0},
            {"score": "3-1", "pct": 0.0},
            {"score": "3-2", "pct": 0.0},
        ],
    }
    eu_stats = {
        "count": 10,
        "avg_total_goals": 2.5,
    }
    scores, detail = _pick_scores(
        "home", 2.5, stats, eu_stats, {"2-1": 0.0}, ah_count=100, eu_count=100
    )
    assert scores == []
    assert detail == []


def test_pick_scores_keeps_positive_historical_probs():
    """Positive historical probabilities are preserved."""
    stats = {
        "count": 10,
        "avg_total_goals": 2.5,
        "score_top": [
            {"score": "2-1", "pct": 12.3},
            {"score": "3-1", "pct": 8.5},
            {"score": "3-2", "pct": 0.0},
        ],
    }
    eu_stats = {
        "count": 10,
        "avg_total_goals": 2.5,
    }
    scores, detail = _pick_scores(
        "home", 2.5, stats, eu_stats, {"2-1": 12.3}, ah_count=100, eu_count=100
    )
    assert scores == ["2-1", "3-1"]
    assert detail == ["2-1(12.3%)", "3-1(8.5%)"]


def test_pick_scores_falls_back_to_templates_without_history():
    """Without historical rates, template scores (no probabilities) are returned."""
    scores, detail = _pick_scores("home", 2.5, None, None, None)
    assert scores
    assert detail == scores
    assert "2-1" in scores or "1-0" in scores


def test_pick_scores_returns_empty_when_score_prediction_disabled(monkeypatch):
    """If score prediction feature is disabled, no scores are returned."""
    monkeypatch.setattr("product_focus.score_prediction_enabled", lambda: False)
    scores, detail = _pick_scores("home", 2.5, None, None, None)
    assert scores == []
    assert detail == []
