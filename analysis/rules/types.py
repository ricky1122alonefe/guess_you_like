"""Rule-engine types and display constants."""

from __future__ import annotations

from dataclasses import dataclass

import config as cfg

CONFIDENCE_CN = {"high": "高", "medium": "中", "low": "低"}
RESULT_CN = {"home": "主胜", "draw": "平局", "away": "客胜"}
AH_CN = {"home": "上盘", "away": "下盘", "skip": "观望"}
OU_CN = {"over_2.5": "大2.5", "under_2.5": "小2.5", "neutral": "中性"}
MIN_SAMPLES_FOR_PICK = cfg.MIN_SAMPLES_FOR_PICK


@dataclass
class Recommendation:
    match: str
    result_1x2: str
    result_1x2_cn: str
    likely_scores: list[str]
    likely_scores_detail: list[str]
    asian_handicap_pick: str
    asian_handicap_cn: str
    asian_handicap_reason: str
    over_under_hint: str
    over_under_cn: str
    confidence: str
    confidence_cn: str
    summary: str
    sample_count: int
    eu_sample_count: int
    insufficient_data: bool = False
    market_notes: list[str] | None = None
    open_result_1x2_cn: str = ""
    open_probability_summary: str = ""
    pattern_reference_cn: str = ""
    control_level_cn: str = ""
    control_trajectory: str = ""
    risk_level_cn: str = ""
    open_sample_count: int = 0
    open_eu_sample_count: int = 0
    trap_notes: list[str] | None = None
    confidence_reason: str = ""
    funds_interpretation: str = ""
    market_pattern_summary: str = ""
    market_pattern_names: list[str] | None = None
    odds_blend_summary: str = ""
    alert_tags: list[str] | None = None
    qualification_divergence: dict | None = None
    eu_ah_divergence_score: int | None = None
