"""重点关注持久化与首页规则倾向测试。"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from focus_watch import (
    add_focus_fid,
    clear_focus,
    focus_fids,
    is_focused,
    load_focus_watch,
    remove_focus_fid,
    set_focus_fids,
)


class TestFocusWatchPersistence:
    def test_add_and_remove(self, tmp_path):
        root = tmp_path / "out"
        with patch("focus_watch._focus_watch_path", return_value=root / "cache" / "focus_watch.json"):
            clear_focus(output_root=root)
            assert focus_fids(output_root=root) == []
            ok, msg = add_focus_fid("1420010", output_root=root)
            assert ok is True
            assert "1420010" in focus_fids(output_root=root)
            assert is_focused("1420010", output_root=root) is True
            remove_focus_fid("1420010", output_root=root)
            assert is_focused("1420010", output_root=root) is False

    def test_limit(self, tmp_path):
        root = tmp_path / "out"
        with patch("focus_watch._focus_watch_path", return_value=root / "cache" / "focus_watch.json"):
            clear_focus(output_root=root)
            with patch("focus_watch.max_focus_limit", return_value=2):
                add_focus_fid("1", output_root=root)
                add_focus_fid("2", output_root=root)
                ok, msg = add_focus_fid("3", output_root=root)
                assert ok is False
                assert "最多关注 2 场" in msg

    def test_set_and_clear(self, tmp_path):
        root = tmp_path / "out"
        with patch("focus_watch._focus_watch_path", return_value=root / "cache" / "focus_watch.json"):
            clear_focus(output_root=root)
            ok, msg = set_focus_fids(["1", "2", "1"], notes={"1": "note1"}, output_root=root)
            assert ok is True
            assert focus_fids(output_root=root) == ["1", "2"]
            data = load_focus_watch(output_root=root)
            assert data["notes"]["1"] == "note1"
            clear_focus(output_root=root)
            assert focus_fids(output_root=root) == []


class TestDashboardPredictionReal:
    def test_different_fixtures_get_different_picks(self):
        from daily_picks import _get_result_prediction

        def fake_forecast(fid):
            return {"pick_cn": "主胜" if fid == "1" else "客胜", "confidence_cn": "中", "reasons": []}

        with patch("analysis.result_forecast.engine.forecast_for_match", side_effect=fake_forecast):
            r1 = _get_result_prediction("1", force=True)
            r2 = _get_result_prediction("2", force=True)
        assert r1["pick_cn"] == "主胜"
        assert r2["pick_cn"] == "客胜"

    def test_missing_forecast_shows_skip_not_default_home(self):
        from daily_picks import _get_result_prediction

        with patch("analysis.result_forecast.engine.forecast_for_match", return_value=None):
            rp = _get_result_prediction("99", force=True)
        assert rp is None


class TestDashboardPredictionEnrichment:
    def test_different_picks_for_different_fixtures(self):
        from daily_picks import _enrich_result_predictions

        def fake_forecast(fid):
            return {"pick_cn": "主胜" if fid == "1" else "客胜", "confidence_cn": "中", "reasons": []}

        matches = [
            {"fixture_id": "1"},
            {"fixture_id": "2"},
        ]
        with patch("analysis.result_forecast.engine.forecast_for_match", side_effect=fake_forecast):
            _enrich_result_predictions(matches, force_refresh=True)
        assert matches[0]["result_prediction"]["pick_cn"] == "主胜"
        assert matches[1]["result_prediction"]["pick_cn"] == "客胜"

    def test_missing_forecast_becomes_skip_not_default_home(self):
        from daily_picks import _enrich_result_predictions

        matches = [{"fixture_id": "99"}]
        with patch("analysis.result_forecast.engine.forecast_for_match", return_value=None):
            _enrich_result_predictions(matches, force_refresh=True)
        rp = matches[0]["result_prediction"]
        assert rp["pick_cn"] == "观望"
        assert rp.get("missing") is True
        assert rp["pick"] == "skip"


class TestTeamNameSuspicious:
    def test_same_team_suspicious(self):
        from daily_picks import _team_names_suspicious

        assert _team_names_suspicious("帕佛斯", "帕佛斯") is True

    def test_near_same_team_suspicious(self):
        from daily_picks import _team_names_suspicious

        assert _team_names_suspicious("罗萨里奥中央", "罗萨里奥") is True

    def test_normal_teams_not_suspicious(self):
        from daily_picks import _team_names_suspicious

        assert _team_names_suspicious("帕佛斯FC", "佐加顿斯") is False


class TestDashboardRowDoesNotShowDefaultHome:
    def test_missing_prediction_shows_skip(self):
        from web_ui import _dashboard_active_row

        m = {
            "fixture_id": "1",
            "match": "A VS B",
            "predict_row": {"比赛": "A VS B"},
            "result_prediction": {"pick_cn": "观望", "confidence_cn": "-", "missing": True},
        }
        html = _dashboard_active_row(m, {})
        assert "主胜" not in html
        assert "观望" in html
