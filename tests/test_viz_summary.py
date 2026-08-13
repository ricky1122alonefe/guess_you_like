"""Tests for viz_summary builder and heatmap axis convention."""

import pytest

from analysis.result_forecast.viz_summary import (
    _extract_jingcai_from_timeline,
    _form_one_liner,
    _poisson_1x2,
    _score_top,
    _similar_one_liner,
    build_viz_summary,
    format_viz_summary_line,
)
from web_ui import _is_fake_likely_score


def test_score_top_from_poisson_heatmap():
    heat = [
        [0, 0, 0.05],
        [1, 1, 0.15],
        [2, 1, 0.10],
        [1, 0, 0.08],
    ]
    top = _score_top(heat)
    assert len(top) == 3
    assert top[0] == {"score": "1-1", "p": 0.15}


def test_poisson_1x2_sums_directions():
    heat = [
        [1, 0, 0.10],
        [0, 0, 0.05],
        [0, 1, 0.15],
    ]
    p1x2 = _poisson_1x2(heat)
    assert p1x2["home"] == pytest.approx(33.3, rel=0.01)
    assert p1x2["draw"] == pytest.approx(16.7, rel=0.01)
    assert p1x2["away"] == pytest.approx(50.0, rel=0.01)


def test_build_viz_summary_fields():
    viz = {
        "poisson_heatmap": [
            [1, 0, 0.10],
            [0, 0, 0.05],
            [0, 1, 0.15],
        ],
        "score_range": {
            "sp_band": {"direction": "home", "edge": 0.07},
        },
        "market_attitude": {
            "asian": {"line_move": "升盘 0.25"},
            "european": {"home_move": "升水 0.05"},
        },
        "divergence": {"divergence_score": 35, "severity_cn": "轻微"},
        "timeline": [
            {"odds": {"jingcai": {"has_sp": True, "sp_home": 2.1, "sp_draw": 3.2, "sp_away": 3.5}}},
        ],
        "edge_bars": [],
    }
    context = {
        "club_form": {
            "home_form": {"pts_last_5": 10, "goals_for_last_5": 8, "goals_against_last_5": 2},
            "away_form": {"pts_last_5": 7, "goals_for_last_5": 5, "goals_against_last_5": 5},
        },
        "history_similar": {
            "samples": [
                {"result": "H"},
                {"result": "D"},
                {"result": "A"},
            ],
        },
    }
    s = build_viz_summary(viz, context)
    assert s["score_top"]
    assert s["poisson_1x2"]["home"] is not None
    assert s["edge_side"] == "home"
    assert "升盘" in s["move_one_liner"]
    assert "分歧 35" in s["divergence_one_liner"]
    assert s["jingcai_sp"] == "2.1/3.2/3.5"
    assert "主近5 10分" in s["form_one_liner"]
    assert "n=3" in s["similar_one_liner"]


def test_build_viz_summary_handles_empty():
    s = build_viz_summary({}, {})
    assert s["score_top"] == []
    assert s["poisson_1x2"] == {"home": None, "draw": None, "away": None}
    assert s["form_one_liner"] == "战绩不足"
    assert s["similar_one_liner"] == "同赔不足"


def test_format_viz_summary_line():
    summary = {
        "score_top": [{"score": "1-1", "p": 0.09}],
        "poisson_1x2": {"home": 40.0, "draw": 25.0, "away": 35.0},
        "edge_side": "home",
        "edge_pp": 5.0,
        "divergence_one_liner": "欧亚分歧 20 分（轻微）",
    }
    line = format_viz_summary_line(summary)
    assert "比分 1-1 9%" in line
    assert "模型偏主 40%" in line
    assert "edge home 5%" in line
    assert "分歧 20" in line


def test_format_viz_summary_line_empty():
    assert format_viz_summary_line({}) == "—"


def test_extract_jingcai_from_timeline():
    timeline = [
        {"odds": {"jingcai": {"has_sp": True, "sp_home": 2.0}}},
        {"odds": {"jingcai": {"has_sp": True, "sp_home": 1.9}}},
    ]
    assert _extract_jingcai_from_timeline(timeline)["sp_home"] == 1.9


def test_extract_jingcai_from_raw_meta():
    timeline = [
        {"odds": {"raw_meta": {"jingcai": {"has_sp": True, "sp_home": 2.2}}}},
    ]
    assert _extract_jingcai_from_timeline(timeline)["sp_home"] == 2.2


def test_is_fake_likely_score_g4():
    assert _is_fake_likely_score("2-1(0.0%)")
    assert not _is_fake_likely_score("2-1(12.3%)")


def test_form_one_liner_recent_form_style():
    recent = {
        "home": {"form_str": "WWDLW", "win_rate": 0.6},
        "away": {"form_str": "DLLWD", "win_rate": 0.2},
    }
    assert "主近况 WWDLW" in _form_one_liner(recent)


def test_similar_one_liner_counts_results():
    hs = {
        "samples": [
            {"result": "H"},
            {"result": "H"},
            {"result": "D"},
            {"result": "A"},
        ]
    }
    assert _similar_one_liner(hs) == "同赔 n=4 主2/平1/客1"


def test_similar_one_liner_empty():
    assert _similar_one_liner({}) == "同赔不足"
    assert _similar_one_liner({"samples": []}) == "同赔不足"
