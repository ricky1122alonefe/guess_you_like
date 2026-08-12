"""Tests for analysis.market.score_range."""
from __future__ import annotations

import pytest

from analysis.market import score_range as sr


@pytest.fixture
def fake_context() -> dict:
    return {
        "fixture_id": "1420010",
        "match_name": "主队VS客队",
        "home_team": "主队",
        "away_team": "客队",
        "european": {
            "odds": {"home": 2.0, "draw": 3.5, "away": 3.8},
            "implied": {"home": 0.45, "draw": 0.25, "away": 0.30},
        },
        "jingcai": {
            "sp": {"home": 1.95, "draw": 3.4, "away": 3.6},
        },
        "market_open_close": {
            "latest": {"ou_line": 2.5},
        },
        "club_form": {
            "home": {"attack": 1.4, "defense": 1.0},
            "away": {"attack": 1.1, "defense": 1.2},
        },
        "elo_context": {"elo_diff": 100},
        "history_similar": {
            "p": {"home": 0.45, "draw": 0.25, "away": 0.30},
            "count": 5,
            "samples": [
                {"score_h": 1, "score_a": 0, "similarity_dist": 0.1},
                {"score_h": 2, "score_a": 1, "similarity_dist": 0.2},
                {"score_h": 0, "score_a": 0, "similarity_dist": 0.3},
                {"score_h": 2, "score_a": 0, "similarity_dist": 0.4},
                {"score_h": 1, "score_a": 1, "similarity_dist": 0.5},
            ]
        },
    }


def test_build_score_range_bands_sum_to_one(fake_context, monkeypatch):
    monkeypatch.setattr(
        "analysis.result_forecast.context.build_result_forecast_context",
        lambda fid, **kwargs: fake_context,
    )
    result = sr.build_score_range_forecast("1420010")
    assert not result.get("missing"), result.get("missing")
    bands = result["bands"]
    total = sum(b["p"] for b in bands)
    assert abs(total - 1.0) < 0.05, f"bands sum={total}"


def test_top_bands_present(fake_context, monkeypatch):
    monkeypatch.setattr(
        "analysis.result_forecast.context.build_result_forecast_context",
        lambda fid, **kwargs: fake_context,
    )
    result = sr.build_score_range_forecast("1420010")
    top = result.get("top_bands") or []
    assert len(top) <= 5
    assert all("id" in b and "p" in b for b in top)


def test_home_bands_do_not_contain_away_scores():
    cross = sr._empty_cross()
    cross[("home", "low")] = 0.3
    cross[("home", "mid")] = 0.4
    cross[("away", "low")] = 0.3
    home_low = next(b for b in sr._cross_to_bands_list(cross, ["test"]) if b["id"] == "home_low")
    assert sr.band_hit("home_low", 1, 0)
    assert not sr.band_hit("home_low", 0, 1)


def test_missing_when_no_distribution(monkeypatch):
    monkeypatch.setattr(
        "analysis.result_forecast.context.build_result_forecast_context",
        lambda fid, **kwargs: {"fixture_id": "x", "match_name": "aVSb"},
    )
    result = sr.build_score_range_forecast("x")
    assert result.get("missing")
    assert not result.get("top_bands")


def test_no_xg_narrative(fake_context, monkeypatch):
    monkeypatch.setattr(
        "analysis.result_forecast.context.build_result_forecast_context",
        lambda fid, **kwargs: fake_context,
    )
    result = sr.build_score_range_forecast("1420010")
    text = str(result)
    assert "xG" not in text
    assert "泊松" in text or "similar" in text or result.get("missing")


def test_context_and_forecast_contain_score_range(monkeypatch, fake_context):
    def fake_ctx(fid, index=None, prediction=None):
        ctx = dict(fake_context)
        ctx["score_range"] = sr.build_score_range_forecast(fid, context=ctx)
        return ctx

    monkeypatch.setattr(
        "analysis.result_forecast.context.build_result_forecast_context",
        fake_ctx,
    )
    from analysis.result_forecast.context import build_result_forecast_context
    from analysis.result_forecast.engine import forecast_for_match

    ctx = build_result_forecast_context("1420010")
    assert "score_range" in ctx
    assert (ctx["score_range"].get("top_bands") or ctx["score_range"].get("missing"))

    fr = forecast_for_match("1420010")
    sec = fr.get("secondary") or {}
    assert "score_range" in sec


def test_sp_band_degraded_without_score_market(fake_context, monkeypatch):
    monkeypatch.setattr(
        "analysis.result_forecast.context.build_result_forecast_context",
        lambda fid, **kwargs: fake_context,
    )
    result = sr.build_score_range_forecast("1420010")
    sp_band = result.get("sp_band")
    # 可用 SP 1x2 则应有 sp_band；结构校验
    if sp_band:
        assert sp_band.get("pick_1x2") in ("home", "draw", "away")
        assert "disclaimer" in sp_band


def test_band_hit_for_total_and_shape():
    assert sr.band_hit("TG_2_3", 2, 1)
    assert sr.band_hit("TG_2_3", 1, 2)
    assert not sr.band_hit("TG_2_3", 1, 0)
    assert sr.band_hit("H_big", 3, 1)
    assert not sr.band_hit("H_big", 1, 0)
    assert sr.band_hit("D_low", 0, 0)


def test_exact_top_references_only(fake_context, monkeypatch):
    monkeypatch.setattr(
        "analysis.result_forecast.context.build_result_forecast_context",
        lambda fid, **kwargs: fake_context,
    )
    result = sr.build_score_range_forecast("1420010")
    exact = result.get("exact_top") or []
    for e in exact:
        assert e.get("note") == "仅供参考"
