"""Tests for analysis.market.tick_quality and dirty team labels."""
from __future__ import annotations

import pytest

from analysis.market.tick_quality import validate_tick
from poll_500 import is_dirty_team_label


def _tick(**kwargs) -> dict:
    base = {
        "eu_home": 1.90,
        "eu_draw": 3.40,
        "eu_away": 4.20,
        "ah_line": -0.25,
        "ah_home_water": 0.92,
        "ah_away_water": 0.96,
        "raw_meta": {
            "jingcai": {
                "match_num": "周三001",
                "has_sp": True,
                "sp_home": 2.10,
                "sp_draw": 3.20,
                "sp_away": 3.10,
            },
            "betfair": {"has_data": True, "volume_total": 12000},
        },
    }
    base.update(kwargs)
    return base


def test_valid_tick_passes():
    assert validate_tick(_tick())["ok"] is True


def test_ah_water_in_eu_fails():
    v = validate_tick(_tick(eu_home=0.82, eu_draw=1.12, eu_away=0.96))
    assert v["ok"] is False


def test_incomplete_eu_fails():
    v = validate_tick(_tick(eu_home=1.90, eu_draw=None, eu_away=None))
    assert v["ok"] is False


def test_eu_open_suspicious_warning():
    v = validate_tick(_tick(eu_open_home=0.82, eu_open_draw=0.88, eu_open_away=0.90))
    assert v["ok"] is True
    assert any("开盘字段串水" in w for w in v["warnings"])


def test_dirty_team_labels():
    assert is_dirty_team_label("沙特职业联赛") is True
    assert is_dirty_team_label("职业联赛") is True
    assert is_dirty_team_label("皇家马德里") is False
    assert is_dirty_team_label("北京国安") is False
    assert is_dirty_team_label("小组赛") is True
