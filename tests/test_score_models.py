"""Tests for score_models score-detail generation and filtering."""

from __future__ import annotations

import pytest

from score_models import (
    build_score_model,
    filter_valid_score_details,
    scrub_zero_percent_scores,
    top_scores,
)


def test_filter_valid_score_details_keeps_positive_probs():
    assert filter_valid_score_details(["2-1(12.3%)", "3-1(8.5%)"]) == [
        "2-1(12.3%)",
        "3-1(8.5%)",
    ]


def test_filter_valid_score_details_drops_zero_percent():
    assert filter_valid_score_details(["2-1(0.0%)", "3-1(0.0%)"]) == []


def test_filter_valid_score_details_drops_mixed_zero_percent():
    assert filter_valid_score_details(["2-1(12.3%)", "3-1(0.0%)", "3-2(0.0%)"]) == [
        "2-1(12.3%)",
    ]


def test_filter_valid_score_details_preserves_plain_scores():
    """Plain scores without probability suffix should not be dropped."""
    assert filter_valid_score_details(["2-1", "1-0"]) == ["2-1", "1-0"]


def test_filter_valid_score_details_handles_empty_and_none():
    assert filter_valid_score_details([]) == []
    assert filter_valid_score_details([""]) == []
    assert filter_valid_score_details([None]) == []  # type: ignore[list-item]


def test_filter_valid_score_details_handles_whitespace():
    assert filter_valid_score_details(["2-1( 0.0 % )"]) == []
    assert filter_valid_score_details(["2-1( 12.3 % )"]) == ["2-1( 12.3 % )"]


def test_top_scores_with_zero_probability():
    cells = {(1, 2): 0.0, (2, 1): 0.0}
    rows = top_scores(cells, limit=3)
    assert len(rows) == 2
    assert rows[0]["prob_pct"] == 0.0


def test_build_score_model_with_zero_probabilities_returns_empty_detail():
    """When the probability matrix is all zeros, likely_scores_detail should be empty."""
    model = build_score_model(
        fair_home_pct=50.0,
        fair_draw_pct=25.0,
        fair_away_pct=25.0,
    )
    assert model is not None
    assert model["model"] == "dixon_coles_poisson"
    # Normal model should produce positive probabilities, so detail must be non-empty.
    assert model["likely_scores_detail"]
    assert all(
        float(item.split("(")[1].rstrip("%)")) > 0
        for item in model["likely_scores_detail"]
    )


def test_build_score_model_detail_excludes_zero_prob_scores():
    """Simulate an all-zero matrix by manually injecting zero-prob top scores."""
    model = build_score_model(
        fair_home_pct=50.0,
        fair_draw_pct=25.0,
        fair_away_pct=25.0,
    )
    assert model is not None
    assert model["likely_scores_detail"]
    # Top scores should be ordered with the highest probability first.
    probs = [
        float(item.split("(")[1].rstrip("%)"))
        for item in model["likely_scores_detail"]
    ]
    assert probs == sorted(probs, reverse=True)


@pytest.mark.parametrize(
    "detail,expected",
    [
        (["2-1(0.0%)", "3-1(0.0%)"], []),
        (["2-1(12.3%)", "3-1(0.0%)"], ["2-1(12.3%)"]),
        (["2-1", "3-1(0.0%)"], ["2-1"]),
        ([], []),
    ],
)
def test_filter_valid_score_details_parametrized(detail, expected):
    assert filter_valid_score_details(detail) == expected


def test_scrub_zero_percent_scores_removes_all_zero_summary_segment():
    pred = {
        "summary": "【赛事概率】主45%。【竞彩可购】主胜。比分 2-1(0.0%)、3-1(0.0%)、3-2(0.0%)。",
        "predict_row": {"推荐比分": "2-1(0.0%)、3-1(0.0%)"},
        "likely_scores_detail": ["2-1(0.0%)", "3-1(0.0%)", "3-2(0.0%)"],
    }
    scrub_zero_percent_scores(pred)
    assert "0.0%" not in pred["summary"]
    assert "比分" not in pred["summary"]
    assert pred["predict_row"]["推荐比分"] == ""
    assert pred["likely_scores_detail"] == []


def test_scrub_zero_percent_scores_keeps_valid_mixed():
    pred = {
        "summary": "比分 2-1(12.3%)、3-1(0.0%)、3-2(8.5%)。",
        "predict_row": {"推荐比分": "2-1(12.3%)、3-1(0.0%)"},
        "likely_scores_detail": ["2-1(12.3%)", "3-1(0.0%)"],
    }
    scrub_zero_percent_scores(pred)
    assert pred["summary"] == "比分 2-1(12.3%)、3-2(8.5%)。"
    assert pred["predict_row"]["推荐比分"] == "2-1(12.3%)"
    assert pred["likely_scores_detail"] == ["2-1(12.3%)"]


def test_scrub_zero_percent_scores_keeps_plain_scores():
    pred = {"summary": "比分 2-1、1-0。", "predict_row": {"推荐比分": "2-1"}}
    scrub_zero_percent_scores(pred)
    assert pred["summary"] == "比分 2-1、1-0。"
    assert pred["predict_row"]["推荐比分"] == "2-1"


def test_scrub_zero_percent_scores_keeps_normal_summary():
    pred = {"summary": "【赛事概率】主45%。比分 2-1(12.3%)。"}
    scrub_zero_percent_scores(pred)
    assert pred["summary"] == "【赛事概率】主45%。比分 2-1(12.3%)。"


def test_scrub_zero_percent_scores_non_dict_noop():
    assert scrub_zero_percent_scores(None) is None
