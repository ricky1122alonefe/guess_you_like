"""Tests for the independent pre-match desk and cross-desk comparison summary."""

import pytest

from prematch_desk import (
    SUPPORTED_LEAGUES,
    attach_prematch_and_summary,
    build_comparison_summary,
    build_prematch_desk,
)


def test_supported_leagues_are_top_five():
    assert SUPPORTED_LEAGUES == {"英超", "西甲", "德甲", "意甲", "法甲"}


def test_unsupported_league_returns_unavailable():
    desk = build_prematch_desk(league_name="日职")
    assert desk["available"] is False
    assert desk["league_supported"] is False
    assert desk["reason"] == "league_not_supported"
    assert not desk["dimensions"]


def test_supported_league_with_no_data_is_available_but_missing():
    desk = build_prematch_desk(league_name="英超")
    assert desk["available"] is True
    assert desk["league_supported"] is True
    ids = {d["id"] for d in desk["dimensions"]}
    assert ids == {"availability", "schedule_fatigue", "weather", "referee", "motivation"}
    assert all(d["missing"] for d in desk["dimensions"])
    assert desk["high_impact_facts"] == []


def test_comparison_summary_holds_when_no_high_impact():
    pred = {
        "judgment": "倾向客胜·小注",
        "result_1x2_cn": "客胜",
    }
    summary = build_comparison_summary(pred)
    assert summary["odds_desk_pick"] == "倾向客胜·小注"
    assert summary["action"] == "hold"
    assert summary["prematch_high_impact"] is False
    assert summary["cannot_flip_direction"] is True
    assert "维持" in summary["summary"]


def test_comparison_summary_skips_when_odds_desk_skip():
    pred = {"result_1x2_cn": "观望"}
    summary = build_comparison_summary(pred)
    assert summary["action"] == "skip"


def test_high_impact_fact_only_size_down_not_flip():
    pred = {
        "judgment": "倾向主胜·标准",
        "result_1x2_cn": "主胜",
    }
    desk = build_prematch_desk(league_name="英超")
    desk["high_impact_facts"] = ["主队主力门将确认缺阵"]
    summary = build_comparison_summary(pred, desk)
    assert summary["action"] == "size_down"
    assert "降成小注" in summary["summary"]
    assert "主胜" in summary["summary"]  # direction preserved


def test_action_never_flip():
    pred = {
        "judgment": "倾向客胜·小注",
        "result_1x2_cn": "客胜",
    }
    for league in SUPPORTED_LEAGUES:
        desk = build_prematch_desk(league_name=league)
        desk["high_impact_facts"] = ["客队核心停赛"]
        summary = build_comparison_summary(pred, desk)
        assert summary["action"] in {"hold", "size_down", "skip"}
        assert summary["action"] != "flip"
        assert "客胜" in summary["summary"] or summary["action"] == "skip"


def test_attach_prematch_and_summary_mutates_pred():
    pred = {"result_1x2_cn": "主胜"}
    attach_prematch_and_summary(pred, league_name="西甲")
    assert pred["league_name"] == "西甲"
    assert "prematch_desk" in pred
    assert "comparison_summary" in pred


def test_unsupported_league_still_shows_odds_conclusion():
    pred = {
        "league_name": "德乙",
        "judgment": "倾向客胜·小注",
    }
    attach_prematch_and_summary(pred, league_name="德乙")
    assert pred["comparison_summary"]["action"] == "hold"
    assert pred["comparison_summary"]["prematch_available"] is False
    assert "本场不在支持范围" in pred["prematch_desk"]["note"]


def test_empty_prediction_safe():
    desk = build_prematch_desk({})
    assert desk["available"] is False
    assert desk["reason"] == "league_not_supported"
