"""Tests for Poisson score matrix layer."""

import json

import pytest

from analysis.quant.poisson import build_poisson_matrix


def _sample_form(home_gf=10, home_ga=5, away_gf=8, away_ga=7):
    return {
        "overall": {
            "home_team": {"played": 5, "goals_for": home_gf, "goals_against": home_ga},
            "away_team": {"played": 5, "goals_for": away_gf, "goals_against": away_ga},
        }
    }


def test_build_poisson_matrix_normalized_and_no_xg_label():
    result = build_poisson_matrix("主队", "客队", club_form=_sample_form())
    assert result is not None
    assert result["method"] == "poisson_independent"
    assert "xG" not in result["label"]
    assert "期望进球(泊松λ)" in result["label"]

    p = result["p_1x2"]
    assert p["home"] + p["draw"] + p["away"] == pytest.approx(1.0, abs=1e-3)
    assert len(result["score_matrix"]) > 0
    assert abs(sum(result["score_matrix"].values()) - 1.0) < 1e-3


def test_build_poisson_matrix_top_scores_present():
    result = build_poisson_matrix("主队", "客队", club_form=_sample_form())
    assert result.get("top_scores")
    assert "score" in result["top_scores"][0]
    assert "prob_pct" in result["top_scores"][0]


def test_build_poisson_matrix_missing_when_no_data():
    result = build_poisson_matrix("主队", "客队", club_form={"overall": {}})
    assert result is None


def test_build_poisson_matrix_with_elo_diff():
    base = build_poisson_matrix("主队", "客队", club_form=_sample_form())
    shifted = build_poisson_matrix("主队", "客队", club_form=_sample_form(), elo_diff=200)
    assert shifted["lambda_home"] > base["lambda_home"]
    assert shifted["lambda_away"] < base["lambda_away"]


def test_no_xg_anywhere_in_output():
    result = build_poisson_matrix("主队", "客队", club_form=_sample_form())
    blob = json.dumps(result, ensure_ascii=False)
    assert "xG" not in blob
    assert "期望进球" in blob
