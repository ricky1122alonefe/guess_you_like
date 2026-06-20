"""Backward-compatible shim — use analysis.signals.patterns."""

from analysis.signals.patterns import (
    MarketPatternAnalysis,
    ah_to_eu_sketch,
    analyze_market_patterns,
    eu_implied_probs,
    eu_to_ah_line,
    pattern_penalties,
)

__all__ = [
    "MarketPatternAnalysis",
    "eu_implied_probs",
    "eu_to_ah_line",
    "ah_to_eu_sketch",
    "analyze_market_patterns",
    "pattern_penalties",
]
