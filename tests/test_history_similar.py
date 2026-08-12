"""Tests for analysis.result_forecast.history_similar."""

from analysis.result_forecast.history_similar import _as_match_odds, _summarize_to_history


def test_as_match_odds_minimal():
    o = _as_match_odds({
        "eu_home": 2.0,
        "eu_draw": 3.2,
        "eu_away": 4.5,
        "ah_line": "-0.5",
        "ah_home_water": 0.95,
        "ah_away_water": 0.95,
    }, match_name="A vs B")
    assert o is not None
    assert o.eu_home == 2.0
    assert o.ah_line == "-0.5"


def test_summarize_to_history_requires_count():
    assert _summarize_to_history({"count": 0}) is None
    assert _summarize_to_history(None) is None


def test_summarize_to_history_distribution():
    block = {
        "count": 100,
        "home_win_rate": 0.45,
        "draw_rate": 0.25,
        "away_win_rate": 0.30,
        "source": "open_eu",
        "samples": [{"date": "2026-01-01", "match": "X 1-0 Y", "result": "W"}],
    }
    h = _summarize_to_history(block)
    assert h["n"] == 100
    assert h["p"] == {"home": 0.45, "draw": 0.25, "away": 0.30}
    assert h["method"] == "open_eu"
    assert len(h["samples"]) == 1


def test_summarize_to_history_invalid_distribution():
    # 全 None 应视为无数据
    assert _summarize_to_history({"count": 5}) is None
