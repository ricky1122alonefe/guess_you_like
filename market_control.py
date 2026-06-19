"""Backward-compatible shim — use analysis.signals.market_control."""

from analysis.signals.market_control import (
    LEVEL_CN,
    RISK_CN,
    ControlAnalysis,
    PATTERN_WEIGHT,
    analyze_control,
)

__all__ = [
    "ControlAnalysis",
    "analyze_control",
    "LEVEL_CN",
    "RISK_CN",
    "PATTERN_WEIGHT",
]
