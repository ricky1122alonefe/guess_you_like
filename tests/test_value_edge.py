"""Tests for value / edge对照 layer."""

import pytest

from analysis.market.value_edge import compute_edge, build_model_edges


def test_compute_edge_with_sp():
    p_model = {"home": 0.45, "draw": 0.28, "away": 0.27}
    sp = {"home": 2.10, "draw": 3.40, "away": 3.50}
    edge = compute_edge(p_model, sp=sp, model_source="result_forecast")
    assert edge is not None
    assert edge["market_source"] == "jingcai_sp"
    assert edge["model_source"] == "result_forecast"
    p_mkt = edge["p_mkt"]
    assert p_mkt["home"] + p_mkt["draw"] + p_mkt["away"] == pytest.approx(1.0, abs=1e-3)
    assert edge["edge"]["home"] == pytest.approx(p_model["home"] - p_mkt["home"], abs=1e-4)
    # half-Kelly 封顶检查
    assert all((v is None or v <= 0.25) for v in edge["half_kelly"].values())
    assert "非投注建议" in edge["disclaimer"]


def test_compute_edge_with_eu_odds():
    p_model = {"home": 0.40, "draw": 0.30, "away": 0.30}
    eu = {"home": 2.50, "draw": 3.20, "away": 3.20}
    edge = compute_edge(p_model, eu_odds=eu, model_source="poisson")
    assert edge is not None
    assert edge["market_source"] == "eu_closing"
    assert edge["model_source"] == "poisson"


def test_compute_edge_missing_when_no_market():
    p_model = {"home": 0.40, "draw": 0.30, "away": 0.30}
    assert compute_edge(p_model) is None


def test_compute_edge_negative_kelly_is_none():
    p_model = {"home": 0.20, "draw": 0.30, "away": 0.50}
    sp = {"home": 1.40, "draw": 4.50, "away": 9.00}
    edge = compute_edge(p_model, sp=sp)
    # 模型认为主队概率低于市场 → edge 负，half-Kelly 应为 None
    assert edge["edge"]["home"] < 0
    assert edge["half_kelly"]["home"] is None


def test_build_model_edges_with_eu_market():
    ctx = {
        "european": {
            "odds": {"home": 2.20, "draw": 3.30, "away": 3.40},
        }
    }
    result_forecast = {"p_home": 0.42, "p_draw": 0.28, "p_away": 0.30}
    poisson = {"p_1x2": {"home": 0.40, "draw": 0.30, "away": 0.30}}
    edges = build_model_edges(ctx, result_forecast, poisson)
    assert edges is not None
    assert edges["market_source"] == "eu_closing"
    assert "result_forecast" in edges
    assert "poisson" in edges


def test_build_model_edges_missing_when_no_odds():
    edges = build_model_edges({}, {"p_home": 0.4}, None)
    assert edges is None
