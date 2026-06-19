"""Rule-based recommendation engine."""

from analysis.rules.engine import build_recommendation
from analysis.rules.output import (
    apply_baseline_to_prediction,
    merge_expert_prediction,
    print_ai_recommendation,
    print_batch_summary,
    print_recommendation,
    recommendation_from_dict,
    recommendation_to_baseline,
)
from analysis.rules.types import (
    AH_CN,
    CONFIDENCE_CN,
    MIN_SAMPLES_FOR_PICK,
    OU_CN,
    RESULT_CN,
    Recommendation,
)

__all__ = [
    "Recommendation",
    "MIN_SAMPLES_FOR_PICK",
    "CONFIDENCE_CN",
    "RESULT_CN",
    "AH_CN",
    "OU_CN",
    "build_recommendation",
    "recommendation_to_baseline",
    "recommendation_from_dict",
    "merge_expert_prediction",
    "apply_baseline_to_prediction",
    "print_recommendation",
    "print_batch_summary",
    "print_ai_recommendation",
]
