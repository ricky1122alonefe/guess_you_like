"""Tests for the unified visualization data API."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from apps.api.viz import _poisson_heatmap, build_viz_data, get_viz_or_404


@pytest.fixture
def sample_context() -> dict:
    return {
        "score_range": {
            "bands": [
                {"id": "home_win", "label": "主胜", "p": 0.42},
                {"id": "draw", "label": "平局", "p": 0.28},
            ],
            "total_bands": [
                {"label": "0-2 球", "low": 0, "high": 2, "p": 0.35},
                {"label": "3+ 球", "low": 3, "high": 99, "p": 0.65},
            ],
            "exact_top": [{"score": "1-0", "p": 0.11}],
        },
        "poisson": {
            "score_matrix": [
                [i, j, 0.05 if i == j else 0.02]
                for i in range(7)
                for j in range(7)
            ]
        },
    }


@pytest.fixture
def sample_result_forecast() -> dict:
        return {
        "primary": {"home": 0.40, "draw": 0.30, "away": 0.30},
        "secondary": {"home": 0.42, "draw": 0.28, "away": 0.30},
    }


def test_viz_api_schema(tmp_path: Path, sample_context, sample_result_forecast):
    """build_viz_data should return the expected top-level schema."""
    root = tmp_path / "output"
    root.mkdir()

    with patch("apps.api.viz.get_fixture_by_external", return_value={"id": 1}):
        with patch("apps.api.viz.load_match_index_from_db", return_value=None):
            with patch(
                "apps.api.viz._load_match_index_file",
                return_value={
                    "fixture_id": "1420010",
                    "timeline": [
                        {
                            "ts": "2026-08-10 12:00",
                            "odds": {
                                "eu_home": 2.10,
                                "eu_draw": 3.20,
                                "eu_away": 3.50,
                            },
                        }
                    ],
                },
            ):
                with patch(
                    "apps.api.viz.build_result_forecast_context",
                    return_value=sample_context,
                ):
                    with patch(
                        "apps.api.viz.forecast_for_match",
                        return_value=sample_result_forecast,
                    ):
                        with patch(
                            "apps.api.viz.build_eu_ah_divergence",
                            return_value={
                                "divergence_score": 45,
                                "line_gap": -0.53,
                                "signals": ["亚盘偏低"],
                                "advice": "关注主队",
                            },
                        ):
                            with patch(
                                "apps.api.viz.get_match_odds_lifecycle",
                                return_value={
                                    "opening": {
                                        "eu_home": 2.20,
                                        "eu_draw": 3.10,
                                        "eu_away": 3.30,
                                    },
                                    "closing": {
                                        "eu_home": 2.05,
                                        "eu_draw": 3.25,
                                        "eu_away": 3.70,
                                    },
                                },
                            ):
                                with patch(
                                    "apps.api.viz.get_match_result_by_external",
                                    return_value={
                                        "payload": {"hits": {"score_bands": []}}
                                    },
                                ):
                                    data = build_viz_data(root, "1420010")

    assert data["fixture_id"] == "1420010"
    assert "timeline" in data
    assert "open_close" in data
    assert "divergence" in data
    assert "score_range" in data
    assert "poisson_heatmap" in data
    assert "edge_bars" in data
    assert "settled_hits" in data
    assert data["timeline"]["eu"]
    assert data["open_close"]["opening"]
    assert data["score_range"]["top_bands"]


def test_poisson_heatmap_truncation():
    """Heatmap should drop cells outside 0..5 and be at most 6x6."""
    matrix = [[i, j, 0.01] for i in range(8) for j in range(8)]
    heat = _poisson_heatmap({"score_matrix": matrix})
    assert heat is not None
    assert len(heat) == 36
    for i, j, _ in heat:
        assert 0 <= i <= 5
        assert 0 <= j <= 5


def test_poisson_heatmap_dict_matrix():
    """Support {i-j: p} dict score_matrix produced by real poisson_matrix."""
    heat = _poisson_heatmap({"score_matrix": {"0-0": 0.10, "1-0": 0.12, "6-6": 0.01}})
    assert heat is not None
    assert len(heat) == 2
    coords = {(i, j) for i, j, _ in heat}
    assert (0, 0) in coords
    assert (1, 0) in coords
    assert (6, 6) not in coords


def test_viz_real_poisson_matrix_dict(tmp_path: Path):
    """When context has no poisson, result_forecast.secondary.models.poisson_matrix should still yield heatmap + edge bars."""
    root = tmp_path / "output"
    root.mkdir()

    context_without_poisson = {
        "score_range": {
            "bands": [{"id": "home_win", "label": "主胜", "p": 0.42}],
            "total_bands": [],
            "exact_top": [{"score": "1-0", "p": 0.11}],
        },
    }

    result_forecast = {
        "primary": {"home": 0.40, "draw": 0.30, "away": 0.30},
        "secondary": {
            "models": {
                "poisson_matrix": {
                    "score_matrix": {"0-0": 0.08, "1-0": 0.15, "2-1": 0.10}
                }
            }
        },
    }

    edges = {
        "result_forecast": {
            "model_source": "result_forecast",
            "market_source": "jc",
            "p_model": {"home": 0.42, "draw": 0.28, "away": 0.30},
            "p_mkt": {"home": 0.40, "draw": 0.30, "away": 0.30},
            "edge": {"home": 0.02, "draw": -0.02, "away": 0.00},
        },
        "poisson": {
            "model_source": "poisson",
            "market_source": "jc",
            "p_model": {"home": 0.45, "draw": 0.25, "away": 0.30},
            "p_mkt": {"home": 0.40, "draw": 0.30, "away": 0.30},
            "edge": {"home": 0.05, "draw": -0.05, "away": 0.00},
        },
    }

    with patch("apps.api.viz.get_fixture_by_external", return_value={"id": 1}):
        with patch("apps.api.viz.load_match_index_from_db", return_value=None):
            with patch(
                "apps.api.viz._load_match_index_file",
                return_value={"fixture_id": "1420010", "timeline": []},
            ):
                with patch(
                    "apps.api.viz.build_result_forecast_context",
                    return_value=context_without_poisson,
                ):
                    with patch(
                        "apps.api.viz.forecast_for_match",
                        return_value=result_forecast,
                    ):
                        with patch("apps.api.viz.build_eu_ah_divergence", return_value=None):
                            with patch(
                                "apps.api.viz.get_match_odds_lifecycle",
                                return_value={},
                            ):
                                with patch(
                                    "apps.api.viz.get_match_result_by_external",
                                    return_value=None,
                                ):
                                    with patch(
                                        "apps.api.viz.build_model_edges",
                                        return_value=edges,
                                    ):
                                        data = build_viz_data(root, "1420010")

    assert "poisson_heatmap" not in data.get("missing", [])
    assert data["poisson_heatmap"]
    assert "edge_bars" not in data.get("missing", [])
    assert data["edge_bars"]
    assert any(e["outcome"] == "home" for e in data["edge_bars"])


def test_no_divergence_no_500(tmp_path: Path, sample_context, sample_result_forecast):
    """A failing divergence builder must not crash the whole response."""
    root = tmp_path / "output"
    root.mkdir()

    with patch("apps.api.viz.get_fixture_by_external", return_value={"id": 1}):
        with patch("apps.api.viz.load_match_index_from_db", return_value=None):
            with patch(
                "apps.api.viz._load_match_index_file",
                return_value={"fixture_id": "1420010", "timeline": []},
            ):
                with patch(
                    "apps.api.viz.build_result_forecast_context",
                    return_value=sample_context,
                ):
                    with patch(
                        "apps.api.viz.forecast_for_match",
                        return_value=sample_result_forecast,
                    ):
                        with patch(
                            "apps.api.viz.build_eu_ah_divergence",
                            side_effect=RuntimeError("db unavailable"),
                        ):
                            with patch(
                                "apps.api.viz.get_match_odds_lifecycle",
                                return_value={},
                            ):
                                data = build_viz_data(root, "1420010")

    assert "divergence" in data.get("missing", [])
    assert data["divergence"] is None
    assert data["fixture_id"] == "1420010"


def test_viz_or_404_when_fixture_missing(tmp_path: Path):
    """get_viz_or_404 should return 404 if fixture and timeline are absent."""
    root = tmp_path / "output"
    root.mkdir()

    with patch("apps.api.viz.get_fixture_by_external", return_value=None):
        with patch("apps.api.viz.load_match_index_from_db", return_value=None):
            with patch(
                "apps.api.viz._load_match_index_file",
                return_value=None,
            ):
                data, status = get_viz_or_404(root, "1420010")

    assert status == 404
    assert data.get("error") == "not found"
