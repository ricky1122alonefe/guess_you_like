"""Backward-compatible shim — use analysis.signals.eu_ah_divergence."""

from analysis.signals.eu_ah_divergence import (
    CONSISTENCY_CN,
    EuAhDivergence,
    analyze_eu_ah_divergence,
    build_divergence_report,
    scan_eu_ah_divergence,
)

__all__ = [
    "EuAhDivergence",
    "CONSISTENCY_CN",
    "analyze_eu_ah_divergence",
    "scan_eu_ah_divergence",
    "build_divergence_report",
]
