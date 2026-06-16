"""Shared schema for AI analysis / expert recommendation JSON."""

ANALYSIS_JSON_KEYS = (
    "historical_overview",
    "market_vs_history_analysis",
    "odds_movement_analysis",
    "asian_handicap_deep_dive",
    "score_pattern_analysis",
    "historical_cases",
    "final_verdict",
    "key_risks",
    "analysis_basis",
)

# 精算师核心输出（EV 评估）
ACTUARY_JSON_KEYS = (
    "implied_probability",
    "adjusted_probability",
    "value_bet",
    "recommendation",
    "confidence_level",
    "actuary_reasoning",
)

RECOMMENDATION_KEYS = (
    "result_1x2",
    "result_1x2_cn",
    "likely_scores",
    "likely_scores_detail",
    "asian_handicap_pick",
    "asian_handicap_cn",
    "asian_handicap_reason",
    "over_under_hint",
    "over_under_cn",
    "confidence",
    "confidence_cn",
)

EXPERT_OUTPUT_KEYS = ACTUARY_JSON_KEYS + RECOMMENDATION_KEYS + ANALYSIS_JSON_KEYS

# Locked-baseline mode: AI must not output picks (legacy --locked-baseline)
FORBIDDEN_AI_KEYS = frozenset(RECOMMENDATION_KEYS + ACTUARY_JSON_KEYS)

VALID_1X2 = frozenset({"home", "draw", "away", "skip"})
VALID_AH = frozenset({"home", "away", "skip"})
VALID_OU = frozenset({"over_2.5", "under_2.5", "neutral"})
VALID_CONF = frozenset({"high", "medium", "low"})

RESULT_CN = {"home": "主胜", "draw": "平局", "away": "客胜", "skip": "观望"}

RECOMMENDATION_CN_TO_1X2 = {
    "主胜": "home",
    "平局": "draw",
    "平": "draw",
    "客胜": "away",
    "客": "away",
    "放弃参与": "skip",
    "观望": "skip",
}

CONFIDENCE_CN_TO_EN = {"高": "high", "中": "medium", "低": "low"}

DEEP_ANALYSIS_JSON_KEYS = (
    "headline",
    "deep_verdict",
    "final_pick",
    "final_pick_reason",
    "confidence_level",
    "stake_advice",
    "score_outlook",
    "model_synthesis",
    "contrarian_case",
    "handicap_deep",
    "over_under_deep",
    "pre_match_watchlist",
    "key_risks",
    "analysis_layers",
)
