"""Backward-compatible shim — use analysis.signals.odds."""

from analysis.signals.odds import MarketSignals, build_market_signals

__all__ = ["MarketSignals", "build_market_signals"]
