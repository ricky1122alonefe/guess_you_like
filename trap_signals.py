"""Backward-compatible shim — use analysis.signals.traps."""

from analysis.signals.traps import TrapAnalysis, analyze_traps, apply_penalties

__all__ = ["TrapAnalysis", "analyze_traps", "apply_penalties"]
