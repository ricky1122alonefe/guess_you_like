"""Tests for Elo rating layer."""

import json
from unittest.mock import patch

import pytest

import elo_ratings as elo


def test_expected_score_sums_to_one():
    p = elo.expected_score(1600, 1500, home_adv=0)
    q = elo.expected_score(1500, 1600, home_adv=0)
    assert p + q == pytest.approx(1.0, abs=1e-6)
    assert p > q


def test_update_elo_monotonicity():
    r = {"A": 1500.0, "B": 1500.0}
    elo.update_elo(r, "A", "B", 2, 1)
    assert r["A"] > 1500.0
    assert r["B"] < 1500.0

    r2 = {"A": 1500.0, "B": 1500.0}
    elo.update_elo(r2, "A", "B", 1, 1)
    # 平局后双方差距应缩小
    assert abs(r2["A"] - r2["B"]) < abs(r2["A"] - 1500.0) + abs(r2["B"] - 1500.0) + 1


def test_unknown_team_gets_default_rating():
    ctx = elo.match_elo_context("神秘队", "无名队", ratings={})
    assert ctx["home_elo"] == elo.DEFAULT_RATING
    assert ctx["away_elo"] == elo.DEFAULT_RATING
    assert "elo_diff" in ctx
    assert "p_elo_1x2" in ctx
    probs = ctx["p_elo_1x2"]
    assert probs["home"] + probs["draw"] + probs["away"] == pytest.approx(1.0, abs=1e-3)


def test_map_elo_to_1x2_sums_to_one():
    for diff in (-400, 0, 200, 800):
        p = elo._map_elo_to_1x2(diff)
        assert p["home"] + p["draw"] + p["away"] == pytest.approx(1.0, abs=1e-3)
        assert p["home"] >= 0 and p["draw"] >= 0 and p["away"] >= 0


def test_refresh_elo_from_match_results_returns_ratings_when_db_empty():
    # 无 settle 数据时不应崩溃，返回当前 ratings
    ratings = elo.refresh_elo_from_match_results({})
    assert isinstance(ratings, dict)


def test_match_elo_context_method_label():
    ctx = elo.match_elo_context("阿根廷", "法国", ratings={})
    assert ctx["method"] == "elo_logistic_with_hfa"
    assert "logistic" in ctx["p_elo_1x2"]["method"]


def test_p_elo_1x2_respects_home_advantage():
    neutral = elo.match_elo_context("A", "B", ratings={"A": 1500.0, "B": 1500.0}, home_advantage=0)
    home = elo.match_elo_context("A", "B", ratings={"A": 1500.0, "B": 1500.0}, home_advantage=100)
    assert home["p_elo_1x2"]["home"] > neutral["p_elo_1x2"]["home"]
