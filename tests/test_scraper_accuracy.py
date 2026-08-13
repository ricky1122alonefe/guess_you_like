"""Tests for scraper accuracy gate."""
from __future__ import annotations

import json
from unittest import mock

import pytest

from scripts.scraper_accuracy_audit import _validate_tick


def _tick(
    eu_home=1.90,
    eu_draw=3.40,
    eu_away=4.20,
    ah_line=-0.25,
    ah_home_water=0.92,
    ah_away_water=0.96,
    **kwargs,
) -> dict:
    base = {
        "eu_home": eu_home,
        "eu_draw": eu_draw,
        "eu_away": eu_away,
        "ah_line": ah_line,
        "ah_home_water": ah_home_water,
        "ah_away_water": ah_away_water,
        "raw_meta": {
            "jingcai": {
                "match_num": "周三001",
                "has_sp": True,
                "sp_home": 2.10,
                "sp_draw": 3.20,
                "sp_away": 3.10,
            },
            "betfair": {"has_data": True, "volume_total": 12000},
            "ou": {"has_data": True, "ou_line": 2.5, "ou_over": 1.02, "ou_under": 0.84},
        },
    }
    base.update(kwargs)
    return base


def test_valid_tick_passes():
    v = _validate_tick(_tick())
    assert v["ok"] is True
    assert not v["errors"]


def test_ah_water_in_eu_fails():
    """亚水误入 eu_* 必须报 error/warning。"""
    v = _validate_tick(_tick(eu_home=0.82, eu_draw=1.12, eu_away=0.96))
    assert not v["ok"]
    assert any("疑似亚水串入" in e or "不完整或含非法值" in e for e in v["errors"])


def test_incomplete_eu_fails():
    """欧赔只有主胜有数 → error。"""
    v = _validate_tick(_tick(eu_home=1.90, eu_draw=None, eu_away=None))
    assert not v["ok"]
    assert any("不完整" in e for e in v["errors"])


def test_ah_missing_water_fails():
    """亚盘有 line 但缺水 → error。"""
    v = _validate_tick(_tick(ah_home_water=None))
    assert not v["ok"]
    assert any("亚盘" in e and "水位" in e for e in v["errors"])


def test_dirty_eu_open_warning():
    """eu_open_* <1.30 疑似串水 → warning。"""
    v = _validate_tick(_tick(eu_open_home=0.82, eu_open_draw=0.88, eu_open_away=0.90))
    assert v["ok"] is True
    assert any("疑似开盘字段串水" in w for w in v["warnings"])


def test_no_market_fails():
    """欧亚全无 → error。"""
    v = _validate_tick(_tick(eu_home=None, eu_draw=None, eu_away=None, ah_line=None, ah_home_water=None, ah_away_water=None))
    assert not v["ok"]
    assert any("欧亚市场均为空" in e for e in v["errors"])


def test_jingcai_has_sp_missing_value_warning():
    v = _validate_tick(_tick(raw_meta={"jingcai": {"has_sp": True, "match_num": "周三001"}}))
    assert any("sp_home" in w for w in v["warnings"])


def test_latest_tick_consistency_logic():
    """latest 与 tick 关键字段不一致应被检出。"""
    from scripts.scraper_accuracy_audit import _latest_tick_consistency

    rows = [
        {
            "external_id": "123456",
            "latest_hash": "abc",
            "tick_hash": "abc",
            "l_eu_home": 1.90,
            "t_eu_home": 1.92,
            "l_eu_away": 4.20,
            "t_eu_away": 4.20,
            "l_ah_line": -0.25,
            "t_ah_line": -0.25,
            "l_ah_home_water": 0.92,
            "t_ah_home_water": 0.92,
            "l_ah_away_water": 0.96,
            "t_ah_away_water": 0.96,
        }
    ]
    with mock.patch("scripts.scraper_accuracy_audit.cursor") as mc:
        cm = mc.return_value.__enter__.return_value
        cm.fetchall.return_value = rows
        res = _latest_tick_consistency(mock.MagicMock())
        assert res["mismatches"] == 1
        assert "123456:eu_home" in res["bad_fids"]


def test_eu_sticky_diagnosis_counts():
    """欧粘亚动统计应能识别欧平但亚水动。"""
    from scripts.scraper_accuracy_audit import _eu_sticky_diagnosis

    ticks = [
        {
            "eu_home": 1.90,
            "eu_draw": 3.40,
            "eu_away": 4.20,
            "ah_line": -0.25,
            "ah_home_water": 0.92,
            "ah_away_water": 0.96,
            "raw_meta": json.dumps({"jingcai": {}, "betfair": {}}),
        },
        {
            "eu_home": 1.90,
            "eu_draw": 3.40,
            "eu_away": 4.20,
            "ah_line": -0.25,
            "ah_home_water": 0.85,
            "ah_away_water": 1.02,
            "raw_meta": json.dumps({"jingcai": {}, "betfair": {}}),
        },
    ]
    with mock.patch("scripts.scraper_accuracy_audit.cursor") as mc:
        cm = mc.return_value.__enter__.return_value
        cm.fetchall.side_effect = [
            [{"external_id": "1", "fixture_id": 100}],
            ticks,
        ]
        res = _eu_sticky_diagnosis(mock.MagicMock())
        assert res["total"] == 1
        assert res["eu_sticky_but_moved"] == 1


def test_dirty_team_label():
    from poll_500 import is_dirty_team_label

    assert is_dirty_team_label("欧冠") is True
    assert is_dirty_team_label("小组赛") is True
    assert is_dirty_team_label("北京国安") is False
