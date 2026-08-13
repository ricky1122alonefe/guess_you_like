"""赔率桶校准单测。"""

import pytest

from analysis.market.odds_bucket_stats import (
    _ah_bucket_label,
    _bucket_for_value,
    _lookup_bucket,
    _resolve_eu_odds,
    build_bucket_stats,
)


def test_bucket_for_value_boundary():
    edges = [1.01, 1.30, 1.45, 1.60, 1.85, 2.20, 2.80, 4.00]
    # 1.60 应落在 [1.60,1.85)
    low_i, high_i = _bucket_for_value(1.60, edges)
    assert edges[low_i] == 1.60
    assert edges[high_i] == 1.85
    # 4.0 应落在最后桶
    low_i, high_i = _bucket_for_value(4.00, edges)
    assert low_i == len(edges) - 1


def test_resolve_eu_odds_priority_sp_over_closing():
    row = {
        "closing_eu_home": 2.0,
        "closing_eu_draw": 3.0,
        "closing_eu_away": 3.5,
        "payload": {
            "jingcai_sp": {"sp_home": 1.9, "sp_draw": 3.1, "sp_away": 3.8},
            "opening_odds": {"eu_home": 2.2, "eu_draw": 3.0, "eu_away": 3.2},
        },
    }
    h, d, a, src = _resolve_eu_odds(row)
    assert h == 1.9
    assert src == "sp"


def test_resolve_eu_odds_fallback_opening():
    row = {"payload": {"opening_odds": {"eu_home": 2.2, "eu_draw": 3.0, "eu_away": 3.2}}}
    h, d, a, src = _resolve_eu_odds(row)
    assert h == 2.2
    assert src == "opening"


def test_resolve_eu_odds_missing():
    assert _resolve_eu_odds({}) == (None, None, None, "missing")


def test_lookup_bucket():
    buckets = [
        {"bucket": "1.60–1.85"},
        {"bucket": "4.00+"},
    ]
    assert _lookup_bucket(buckets, 1.70, [1.01, 1.60, 1.85]) == buckets[0]
    assert _lookup_bucket(buckets, 5.00, [1.01, 1.60, 1.85, 4.00]) == buckets[1]


def test_ah_bucket_label():
    assert _ah_bucket_label(0.5)[0] == "主让 0.25~0.5"
    assert _ah_bucket_label(-0.5)[0] == "客让 0.25~0.5"
    assert _ah_bucket_label(0.0)[0] == "平手附近"


def test_build_bucket_stats_reliable_threshold():
    stats = build_bucket_stats(days=90)
    for b in stats.get("home", []):
        assert "reliable" in b
        assert b["reliable"] == (b["n"] >= 20)


def test_build_bucket_stats_small_sample_not_reliable():
    stats = build_bucket_stats(days=90)
    small = [b for b in stats.get("home", []) if b["n"] > 0 and b["n"] < 20]
    if small:
        assert small[0]["reliable"] is False
