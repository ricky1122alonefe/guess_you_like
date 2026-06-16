"""Shared odds normalization: validate EU triples, extract opening/closing from ticks."""

from __future__ import annotations

from typing import Any

OUTCOMES = ("home", "draw", "away")
EU_KEYS = ("eu_home", "eu_draw", "eu_away")
EU_OPEN_KEYS = ("eu_open_home", "eu_open_draw", "eu_open_away")


def _num(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def valid_eu_triple(h, d, a) -> tuple[float, float, float] | None:
    oh, od, oa = _num(h), _num(d), _num(a)
    if oh and od and oa and oh > 1 and od > 1 and oa > 1:
        return oh, od, oa
    return None


def eu_dict(h, d, a) -> dict[str, float]:
    return {"eu_home": h, "eu_draw": d, "eu_away": a}


def eu_favorite(eu_h, eu_d, eu_a) -> str | None:
    vals = {"home": eu_h, "draw": eu_d, "away": eu_a}
    clean = {k: v for k, v in vals.items() if v and v > 1}
    if not clean:
        return None
    return min(clean, key=clean.get)


def opening_eu_from_tick(tick: dict | None) -> dict[str, float]:
    """Prefer eu_open_*; fall back to eu_* only when all > 1."""
    if not tick:
        return {}
    for keys in (EU_OPEN_KEYS, EU_KEYS):
        t = valid_eu_triple(tick.get(keys[0]), tick.get(keys[1]), tick.get(keys[2]))
        if t:
            return eu_dict(*t)
    return {}


def closing_eu_from_tick(tick: dict | None) -> dict[str, float]:
    if not tick:
        return {}
    t = valid_eu_triple(tick.get("eu_home"), tick.get("eu_draw"), tick.get("eu_away"))
    return eu_dict(*t) if t else {}


def odds_from_tick(tick: dict | None, *, opening: bool = False) -> dict[str, Any]:
    """Extract AH + EU fields from a poll tick."""
    if not tick:
        return {}
    if opening:
        eu = opening_eu_from_tick(tick)
        return {
            **eu,
            "eu_open_home": eu.get("eu_home"),
            "eu_open_draw": eu.get("eu_draw"),
            "eu_open_away": eu.get("eu_away"),
            "ah_line": _num(tick.get("ah_open_line") or tick.get("ah_line")),
            "ah_home_water": _num(tick.get("ah_open_home") or tick.get("ah_home_water")),
            "ah_away_water": _num(tick.get("ah_open_away") or tick.get("ah_away_water")),
            "ah_open_line": _num(tick.get("ah_open_line") or tick.get("ah_line")),
            "captured_at": tick.get("captured_at"),
            "odds_valid": bool(eu),
        }
    eu = closing_eu_from_tick(tick)
    open_eu = opening_eu_from_tick(tick)
    return {
        **eu,
        "eu_open_home": open_eu.get("eu_home"),
        "eu_open_draw": open_eu.get("eu_draw"),
        "eu_open_away": open_eu.get("eu_away"),
        "ah_line": _num(tick.get("ah_line")),
        "ah_home_water": _num(tick.get("ah_home_water")),
        "ah_away_water": _num(tick.get("ah_away_water")),
        "ah_open_line": _num(tick.get("ah_open_line")),
        "captured_at": tick.get("captured_at"),
        "odds_valid": bool(eu),
    }


def opening_eu_from_fixture(fx) -> dict[str, float]:
    t = valid_eu_triple(getattr(fx, "eu_home", None), getattr(fx, "eu_draw", None), getattr(fx, "eu_away", None))
    return eu_dict(*t) if t else {}
