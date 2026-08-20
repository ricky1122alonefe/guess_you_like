"""Tests for three-lane market view: EU / AH / Jingcai kept independent."""
from analysis.market.three_lane import (
    build_ah_lane,
    build_eu_lane,
    build_jingcai_lane,
    build_lane_comparison,
    attach_market_lanes,
)


def _eu_books() -> list[dict]:
    return [
        {"label": "平博", "name": "平博", "home": 2.80, "draw": 3.20, "away": 2.50},
        {"label": "威廉", "name": "威廉***", "home": 2.85, "draw": 3.15, "away": 2.55},
    ]


def test_eu_lane_from_major_books():
    eu = build_eu_lane({}, eu_books_major=_eu_books())
    assert eu["missing"] is False
    assert eu["buyable"] is False
    assert eu["tag"] == "参考·不可购"
    assert eu["pick"] in {"home", "draw", "away"}
    assert "平博" in eu["source_books"]
    assert "去水隐含概率" in " ".join(eu["reasons"])


def test_eu_lane_from_snapshot_average():
    pred = {"odds_snapshot": {"eu_home": 2.80, "eu_draw": 3.20, "eu_away": 2.50}}
    eu = build_eu_lane(pred)
    assert eu["missing"] is False
    assert "欧赔均值" in eu["source_books"]


def test_eu_lane_missing():
    assert build_eu_lane({})["missing"] is True


def test_ah_lane_from_snapshot():
    pred = {"odds_snapshot": {"ah_line": "-0.25", "ah_home_water": 0.95, "ah_away_water": 0.97}}
    ah = build_ah_lane(pred)
    assert ah["missing"] is False
    assert ah["line"] == -0.25
    assert "非竞彩让球" in ah["tag"]
    assert "不是竞彩让球" in " ".join(ah["reasons"])


def test_ah_lane_missing():
    assert build_ah_lane({})["missing"] is True


def test_jingcai_lane_sp():
    pred = {
        "jingcai_pick_info": {"mode": "sp", "pick": "home", "pick_cn": "主胜", "sp": "2.05"},
    }
    jc = build_jingcai_lane(pred)
    assert jc["buyable"] is True
    assert jc["play"] == "胜平负"
    assert jc["pick"] == "home"


def test_jingcai_lane_missing():
    jc = build_jingcai_lane({})
    assert jc["missing"] is True
    assert jc["buyable"] is False


def test_three_align_hold():
    eu = build_eu_lane({}, eu_books_major=[{"label": "平博", "home": 2.8, "draw": 3.2, "away": 2.5}])
    ah = {"missing": False, "lean": "home"}
    jc = {"missing": False, "pick": "home", "buyable": True, "play": "胜平负", "sp": "2.05"}
    comp = build_lane_comparison(eu, ah, jc)
    assert comp["agreement"] == "align"
    assert comp["action"] == "hold"
    assert comp["buyable"]["pick"] == "home"


def test_eu_conflicts_jingcai_size_down():
    eu = build_eu_lane({}, eu_books_major=[{"label": "平博", "home": 2.1, "draw": 3.4, "away": 3.2}])
    ah = {"missing": True}
    jc = {"missing": False, "pick": "away", "buyable": True, "play": "胜平负", "sp": "2.05"}
    comp = build_lane_comparison(eu, ah, jc)
    assert comp["action"] in {"size_down", "skip"}
    assert comp["buyable"] is not None
    assert comp["buyable"]["pick"] == "away"


def test_both_conflict_skip():
    eu = build_eu_lane({}, eu_books_major=[{"label": "平博", "home": 2.1, "draw": 3.4, "away": 3.2}])
    ah = {"missing": False, "lean": "home"}
    jc = {"missing": False, "pick": "away", "buyable": True, "play": "胜平负", "sp": "2.05"}
    comp = build_lane_comparison(eu, ah, jc)
    assert comp["action"] == "skip"
    assert comp["buyable"] is None


def test_jingcai_missing_no_buyable():
    eu = build_eu_lane({}, eu_books_major=_eu_books())
    ah = {"missing": False, "lean": "home"}
    jc = {"missing": True, "buyable": False}
    comp = build_lane_comparison(eu, ah, jc)
    assert comp["buyable"] is None
    assert comp["action"] == "hold"


def test_attach_market_lanes_adds_key():
    pred = {
        "odds_snapshot": {"eu_home": 2.8, "eu_draw": 3.2, "eu_away": 2.5, "ah_line": -0.25, "ah_home_water": 0.95, "ah_away_water": 0.97},
        "jingcai_pick_info": {"mode": "sp", "pick": "home", "pick_cn": "主胜", "sp": "2.05"},
    }
    attach_market_lanes(pred)
    assert "market_lanes" in pred
    assert pred["market_lanes"]["eu"]["missing"] is False
    assert pred["market_lanes"]["jingcai"]["buyable"] is True


def test_attach_market_lanes_no_crash_on_empty():
    pred = {}
    attach_market_lanes(pred)
    assert "market_lanes" in pred
    assert pred["market_lanes"]["jingcai"]["missing"] is True
