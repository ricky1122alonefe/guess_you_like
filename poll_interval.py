"""Adaptive poll interval based on Beijing time and Jingcai release hour."""
from __future__ import annotations

from datetime import datetime

from config import JINGCAI_RELEASE_HOUR


def poll_interval_seconds(
    now: datetime | None = None,
    *,
    default: int = 300,
    pre_jingcai: int = 120,
    release_hour: int = JINGCAI_RELEASE_HOUR,
) -> int:
    """Return poll interval in seconds.

    Before ``release_hour`` Beijing time, use the shorter ``pre_jingcai``
    interval so European odds keep updating while Jingcai SP is still asleep.
    At or after ``release_hour``, fall back to ``default``.
    """
    if now is None:
        from time_utils import now_beijing

        now = now_beijing()
    if now.hour < release_hour:
        return pre_jingcai
    return default


def poll_interval_label(interval: int, *, pre_jingcai: int = 120) -> str:
    return "pre-jingcai" if interval == pre_jingcai else "jingcai-hours"
