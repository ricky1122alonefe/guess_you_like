"""脏队名规则与首页名称优先级测试。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from poll_500 import is_dirty_team_label, ensure_fixture_real_teams
from download_500 import MatchFixture
from daily_picks import (
    _extract_existing_match_name,
    _resolve_dashboard_name,
)


class TestIsDirtyTeamLabel:
    def test_europa_placeholder_is_dirty(self):
        assert is_dirty_team_label("欧罗巴") is True

    def test_qualifying_round_is_dirty(self):
        assert is_dirty_team_label("资格赛3") is True

    def test_pafos_fc_is_clean(self):
        assert is_dirty_team_label("帕佛斯FC") is False

    def test_real_madrid_is_clean(self):
        assert is_dirty_team_label("皇马") is False

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("欧联杯", True),
            ("欧会杯", True),
            ("欧冠杯", True),
            ("亚冠", True),
            ("解放者杯", True),
            ("南美杯", True),
            ("世界杯", True),
            ("世俱杯", True),
            ("附加赛", True),
            ("预选赛", True),
            ("第3轮", True),
            ("第三轮", True),
            ("(队名待核)", True),
            ("队名待核", True),
            ("沙特职业联赛", True),
            ("资格赛3", True),
            ("第4轮", True),
            ("第十轮", True),
            ("德乙", True),
            ("英甲", True),
            ("基尔", False),
            ("切尔西", False),
            ("第戎", False),
            ("", True),
            ("a", True),
        ],
    )
    def test_various_labels(self, name, expected):
        assert is_dirty_team_label(name) is expected


class TestExtractExistingMatchName:
    def test_extracts_vs_without_spaces(self):
        m = {"match": "东京绿茵VS柏太阳神"}
        assert _extract_existing_match_name(m) == ("东京绿茵", "柏太阳神")
        m = {"match": "帕佛斯FC VS 佐加顿斯"}
        assert _extract_existing_match_name(m) == ("帕佛斯FC", "佐加顿斯")

    def test_extracts_bisai_name(self):
        m = {"predict_row": {"比赛": "皇马 VS 巴萨"}}
        assert _extract_existing_match_name(m) == ("皇马", "巴萨")

    def test_returns_none_for_missing(self):
        assert _extract_existing_match_name({}) is None


def test_parse_live_row_skips_league_token():
    from download_500 import _parse_teams_from_row
    home, away = _parse_teams_from_row(
        "周五001|德乙|08-14 18:00|马格德堡|VS|基尔",
        skip_tokens={"德乙"},
    )
    assert home == "马格德堡"
    assert away == "基尔"


def test_parse_live_row_skips_duplicate_home_cell():
    from download_500 import _parse_teams_from_row
    home, away = _parse_teams_from_row("周五001|日职|08-14 18:00|东京绿茵|东京绿茵|柏太阳神")
    assert home == "东京绿茵"
    assert away == "柏太阳神"


class TestResolveDashboardName:
    def test_db_same_team_falls_back_to_existing_pair(self):
        m = {"match": "东京绿茵 VS 柏太阳神"}
        db = {"home": "东京绿茵", "away": "东京绿茵", "source": "500"}
        name = _resolve_dashboard_name("1419227", m, db)
        assert name == "东京绿茵 VS 柏太阳神"

    def test_db_clean_names_take_priority(self):
        m = {"match": "欧罗巴 VS 资格赛3"}
        db = {"home": "帕佛斯FC", "away": "佐加顿斯", "source": "500"}
        name = _resolve_dashboard_name("1420010", m, db)
        assert name == "帕佛斯FC VS 佐加顿斯"

    def test_db_dirty_and_fetch_success(self):
        m = {"match": "欧罗巴 VS 资格赛3"}
        db = {"home": "欧罗巴", "away": "资格赛3", "source": "500"}
        with patch("daily_picks._try_local_stored_name", return_value=None):
            with patch("daily_picks._try_fix_name_from_500", return_value=("帕佛斯FC", "佐加顿斯")):
                with patch("daily_picks._write_back_clean_name") as wb:
                    name = _resolve_dashboard_name("1420010", m, db, allow_network=True)
        assert name == "帕佛斯FC VS 佐加顿斯"
        wb.assert_called_once_with("1420010", "帕佛斯FC", "佐加顿斯", "500")

    def test_db_dirty_fetch_falls_back_to_existing_clean(self):
        m = {"match": "帕佛斯FC VS 佐加顿斯"}
        db = {"home": "欧罗巴", "away": "资格赛3", "source": "500"}
        with patch("daily_picks._try_fix_name_from_500", return_value=None):
            name = _resolve_dashboard_name("1420010", m, db)
        assert name == "帕佛斯FC VS 佐加顿斯"

    def test_all_dirty_and_fetch_fails_shows_placeholder(self):
        m = {"match": "欧罗巴 VS 资格赛3"}
        db = {"home": "欧罗巴", "away": "资格赛3", "source": "500"}
        with patch("daily_picks._try_local_stored_name", return_value=None):
            with patch("daily_picks._try_fix_name_from_500", return_value=None):
                name = _resolve_dashboard_name("1420010", m, db)
        assert name == "队名待核 (1420010)"

    def test_no_db_fetch_success_writes_back(self):
        m = {"match": "欧罗巴 VS 资格赛3"}
        with patch("daily_picks._try_local_stored_name", return_value=None):
            with patch("daily_picks._try_fix_name_from_500", return_value=("帕佛斯FC", "佐加顿斯")):
                with patch("daily_picks._write_back_clean_name") as wb:
                    name = _resolve_dashboard_name("1420010", m, None, allow_network=True)
        assert name == "帕佛斯FC VS 佐加顿斯"
        wb.assert_called_once_with("1420010", "帕佛斯FC", "佐加顿斯", "500")

    def test_no_db_fetch_fails_shows_placeholder(self):
        m = {"match": "欧罗巴 VS 资格赛3"}
        with patch("daily_picks._try_local_stored_name", return_value=None):
            with patch("daily_picks._try_fix_name_from_500", return_value=None):
                name = _resolve_dashboard_name("1420010", m, None)
        assert name == "队名待核 (1420010)"


class TestEnsureFixtureRealTeams:
    def test_does_not_overwrite_clean_with_dirty_fetched(self):
        """fetch_match_info 返回脏名时，不应覆盖原干净队名。"""
        fixture = MatchFixture(
            fixture_id="1420010",
            home="帕佛斯FC",
            away="佐加顿斯",
            kickoff=None,
            status_phase="upcoming",
            status_label="",
            live_score="",
            league="欧罗巴",
        )
        info = MagicMock(home="欧罗巴", away="资格赛3", label="")
        with patch("download_500.fetch_match_info", return_value=info):
            result = ensure_fixture_real_teams(MagicMock(), fixture)
        assert result.home == "帕佛斯FC"
        assert result.away == "佐加顿斯"

    def test_replaces_dirty_side_only(self):
        """仅替换仍为脏的那一侧。"""
        fixture = MatchFixture(
            fixture_id="1420010",
            home="欧罗巴",
            away="佐加顿斯",
            kickoff=None,
            status_phase="upcoming",
            status_label="",
            live_score="",
            league="欧罗巴",
        )
        info = MagicMock(home="帕佛斯FC", away="资格赛3", label="")
        with patch("download_500.fetch_match_info", return_value=info):
            result = ensure_fixture_real_teams(MagicMock(), fixture)
        assert result.home == "帕佛斯FC"
        assert result.away == "佐加顿斯"

    def test_no_change_when_both_clean(self):
        fixture = MatchFixture(
            fixture_id="1420010",
            home="帕佛斯FC",
            away="佐加顿斯",
            kickoff=None,
            status_phase="upcoming",
            status_label="",
            live_score="",
            league="欧罗巴",
        )
        with patch("download_500.fetch_match_info") as mock_fetch:
            result = ensure_fixture_real_teams(MagicMock(), fixture)
            mock_fetch.assert_not_called()
        assert result.home == "帕佛斯FC"
        assert result.away == "佐加顿斯"
