"""Asian handicap settlement helpers."""

from __future__ import annotations


def ah_settle(score_home: int, score_away: int, line: float, side: str = "home") -> float:
    """
    Return settlement units for one side of an Asian handicap bet.
    +1 full win, +0.5 half win, 0 push, -0.5 half loss, -1 full loss.
    """
    diff = score_home - score_away
    if side == "away":
        diff = -diff
        line = -line

    # split quarter lines into two half stakes
    frac = abs(line * 4) % 2
    if frac == 1:  # .25 or .75
        low = _single_settle(diff, _floor_quarter(line))
        high = _single_settle(diff, _ceil_quarter(line))
        return (low + high) / 2
    return _single_settle(diff, line)


def _floor_quarter(line: float) -> float:
    return int(line * 4) / 4 if line >= 0 else -((int(abs(line) * 4) + 1) // 4)


def _ceil_quarter(line: float) -> float:
    return _floor_quarter(line) + (0.25 if line >= 0 else -0.25)


def _single_settle(diff: float, line: float) -> float:
    adjusted = diff + line
    if adjusted > 0:
        return 1.0
    if adjusted < 0:
        return -1.0
    return 0.0


def result_1x2(score_home: int, score_away: int) -> str:
    if score_home > score_away:
        return "home"
    if score_home < score_away:
        return "away"
    return "draw"
