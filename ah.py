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


def side_handicap(line: float | None, side: str) -> float | None:
    """Return the handicap applied to the selected side.

    In our normalized feed, `line` is the handicap applied to the home side:
    negative means home gives goals, positive means home receives goals.
    """
    if line is None or side not in ("home", "away"):
        return None
    line_f = float(line)
    return line_f if side == "home" else -line_f


def side_upper_lower(line: float | None, side: str) -> str:
    """上盘/下盘 label for a concrete side under the current line."""
    hcap = side_handicap(line, side)
    if hcap is None:
        return "—"
    if hcap < 0:
        return "上盘"
    if hcap > 0:
        return "下盘"
    return "平手"


def format_ah_pick_cn(side: str | None, line: float | None) -> str:
    """Human-readable AH pick, e.g. 上盘（客队 -1） / 下盘（主队 +2）."""
    if side not in ("home", "away") or line is None:
        return "观望"
    hcap = side_handicap(line, side)
    if hcap is None:
        return "观望"
    team = "主队" if side == "home" else "客队"
    label = side_upper_lower(line, side)
    sign = f"{hcap:+g}" if hcap else "0"
    return f"{label}（{team} {sign}）"


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
