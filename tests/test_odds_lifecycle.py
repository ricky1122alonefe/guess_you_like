"""Tests for analysis.market.odds_lifecycle."""

from analysis.market.odds_lifecycle import _tick_summary, _compute_move


def test_tick_summary_includes_ou():
    tick = {
        "eu_home": 2.1,
        "eu_draw": 3.4,
        "eu_away": 3.6,
        "ah_line": "-0.5",
        "ah_home_water": 0.95,
        "ah_away_water": 0.95,
        "ou_line": 2.5,
        "ou_over": 1.0,
        "ou_under": 0.9,
        "captured_at": "2026-08-01 12:00:00",
    }
    s = _tick_summary(tick)
    assert s["ou_line"] == 2.5
    assert s["ou_over"] == 1.0
    assert s["eu_home"] == 2.1


def test_compute_move_calculation():
    opening = {"eu_home": 2.0, "eu_away": 4.0, "ah_line": "-0.5", "ah_home_water": 0.90}
    latest = {"eu_home": 1.8, "eu_away": 4.5, "ah_line": "-0.75", "ah_home_water": 0.95}
    m = _compute_move(opening, latest)
    assert m["eu_home_delta"] == -0.2
    assert m["eu_away_delta"] == 0.5
    assert m["ah_line_delta"] == -0.25
    assert m["ah_home_water_delta"] == 0.05


def test_tick_summary_rejects_fake_eu():
    s = _tick_summary({"eu_home": 0.8, "eu_away": 1.05})
    assert s["eu_home"] == 0.8  # 但不会被选为统计开盘，因为 <1.0
    assert s["eu_away"] == 1.05
