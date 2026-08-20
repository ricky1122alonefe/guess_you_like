"""Tests for adaptive poll interval around Jingcai release hour."""
from datetime import datetime

from poll_interval import poll_interval_seconds
from time_utils import BEIJING


def _dt(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 20, hour, minute, tzinfo=BEIJING)


def test_poll_interval_pre_jingcai():
    """北京时间 10:00 应使用更短 pre-jingcai 间隔。"""
    assert poll_interval_seconds(_dt(10), default=300, pre_jingcai=120) == 120


def test_poll_interval_jingcai_hours():
    """北京时间 14:00 应使用默认间隔。"""
    assert poll_interval_seconds(_dt(14), default=300, pre_jingcai=120) == 300


def test_poll_interval_at_release_hour():
    """北京时间 11:00 起应切回默认间隔。"""
    assert poll_interval_seconds(_dt(11), default=300, pre_jingcai=120) == 300


def test_poll_interval_defaults():
    """默认参数符合 CLI 默认值。"""
    assert poll_interval_seconds(_dt(10)) == 120
    assert poll_interval_seconds(_dt(11)) == 300
