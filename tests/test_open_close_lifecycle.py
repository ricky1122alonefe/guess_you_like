"""初盘/临盘 lifecycle 单测。"""
from unittest.mock import patch, MagicMock
from datetime import datetime
from analysis.market.odds_lifecycle import (
    _tick_summary,
    _jingcai_from_raw,
    _betfair_from_raw,
    get_match_odds_lifecycle,
)
from db.repository import get_opening_tick, get_closing_tick


def test_tick_summary_valid():
    """tick_summary 提取欧亚字段。"""
    tick = {
        "captured_at": "2026-08-11 10:00:00",
        "eu_home": 2.0, "eu_draw": 3.2, "eu_away": 4.0,
        "ah_line": -0.5, "ah_home_water": 0.90, "ah_away_water": 0.95,
        "eu_open_home": 2.1, "eu_open_away": 3.9,
    }
    s = _tick_summary(tick)
    assert s["eu_home"] == 2.0
    assert s["ah_line"] == -0.5
    assert s["eu_open_home"] == 2.1
    assert s["captured_at"] == "2026-08-11 10:00:00"


def test_tick_summary_none():
    """空 tick 返回 None。"""
    assert _tick_summary(None) is None


def test_jingcai_from_raw():
    """从 raw_meta 提取竞彩 SP。"""
    raw = {"jingcai": {"has_sp": True, "sp_home": 2.0, "sp_draw": 3.0, "sp_away": 4.0, "match_num": "周二001"}}
    jc = _jingcai_from_raw(raw)
    assert jc["has_sp"] is True
    assert jc["sp_home"] == 2.0
    assert jc["match_num"] == "周二001"


def test_jingcai_from_raw_empty():
    """无竞彩返回 None。"""
    assert _jingcai_from_raw({"jingcai": {}}) is None
    assert _jingcai_from_raw(None) is None


def test_betfair_from_raw():
    """从 raw_meta 提取必发。"""
    raw = {"betfair": {"has_data": True, "volume_total": 50000, "volume_pct": {"home": 0.6}}}
    bf = _betfair_from_raw(raw)
    assert bf["has_data"] is True
    assert bf["volume_total"] == 50000


def test_betfair_from_raw_empty():
    """无必发返回 None。"""
    assert _betfair_from_raw({"betfair": {}}) is None
    assert _betfair_from_raw(None) is None


def test_get_match_odds_lifecycle_mock():
    """mock DB：lifecycle 返回 opening + closing + devig。"""
    mock_fx = {
        "id": 1, "kickoff_at": datetime(2026, 8, 11, 19, 0),
        "home_team": "A", "away_team": "B",
    }
    mock_opening = {
        "captured_at": datetime(2026, 8, 10, 10, 0),
        "eu_home": 2.2, "eu_draw": 3.2, "eu_away": 3.8,
        "ah_line": -0.5, "ah_home_water": 0.90, "ah_away_water": 0.95,
        "raw_meta": None,
    }
    mock_closing = {
        "captured_at": datetime(2026, 8, 11, 18, 0),
        "eu_home": 2.0, "eu_draw": 3.4, "eu_away": 4.0,
        "ah_line": -0.5, "ah_home_water": 0.85, "ah_away_water": 1.00,
        "eu_open_home": 2.2, "eu_open_away": 3.8,
        "raw_meta": None,
    }
    mock_mr = None  # 未 settle

    with patch("db.connection.cursor") as mock_cursor_cls, \
         patch("db.repository.get_opening_tick", return_value=mock_opening), \
         patch("db.repository.get_closing_tick", return_value=mock_closing):
        mock_cur = MagicMock()
        mock_cur.fetchone.side_effect = [mock_fx, mock_mr]
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cursor_cls.return_value = mock_cur

        r = get_match_odds_lifecycle("999")
        assert r["opening"] is not None
        assert r["closing"] is not None
        assert r["opening"]["eu_home"] == 2.2
        assert r["closing"]["eu_home"] == 2.0
        assert r["p_open_devig"] is not None
        assert r["p_close_devig"] is not None
        assert r["provisional"] is True  # 未 settle
        assert r["settled"] is False
        # devig sum = 1
        po = r["p_open_devig"]
        assert abs(po["p_home"] + po["p_draw"] + po["p_away"] - 1.0) < 0.01


def test_get_match_odds_lifecycle_settled():
    """mock DB：已 settle 的场返回 result_1x2。"""
    mock_fx = {
        "id": 1, "kickoff_at": datetime(2026, 8, 10, 19, 0),
        "home_team": "A", "away_team": "B",
    }
    mock_mr = {"home_score": 2, "away_score": 1, "result_1x2": "H", "payload": None}
    mock_tick = {
        "captured_at": datetime(2026, 8, 10, 10, 0),
        "eu_home": 2.0, "eu_draw": 3.0, "eu_away": 4.0,
        "ah_line": -0.5, "ah_home_water": 0.90, "ah_away_water": 0.95,
        "raw_meta": None,
    }

    with patch("db.connection.cursor") as mock_cursor_cls, \
         patch("db.repository.get_opening_tick", return_value=mock_tick), \
         patch("db.repository.get_closing_tick", return_value=mock_tick):
        mock_cur = MagicMock()
        mock_cur.fetchone.side_effect = [mock_fx, mock_mr]
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cursor_cls.return_value = mock_cur

        r = get_match_odds_lifecycle("999")
        assert r["settled"] is True
        assert r["result_1x2"] == "H"
        assert r["scores"]["home"] == 2
        assert r["provisional"] is False
