"""World Cup group-stage Monte Carlo simulation."""

from __future__ import annotations

from typing import Any

from group_mc import simulate_for_match


def apply_mc(pred: dict, home: str, away: str, quant: dict[str, Any]) -> None:
    if not home or not away:
        return
    try:
        mc = simulate_for_match(home, away, n_sims=2000)
        if mc:
            quant["group_mc"] = mc
    except Exception:
        pass
