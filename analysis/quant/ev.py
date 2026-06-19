"""Jingcai expected-value overlay."""

from __future__ import annotations

from typing import Any

from jingcai_ev import compute_jingcai_ev


def apply_ev(pred: dict, quant: dict[str, Any]) -> None:
    ev = compute_jingcai_ev(pred)
    if not ev:
        return
    quant["jingcai_ev"] = ev
    pred["jingcai_ev"] = ev
    if ev.get("value_bet"):
        pred["value_bet"] = True
