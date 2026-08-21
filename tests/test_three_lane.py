"""Tests for three-lane market view: EU / AH / Jingcai kept independent."""
import pytest

from analysis.market.three_lane import (
    attach_market_lanes,
    build_ah_lane,
    build_eu_lane,
    build_jingcai_lane,
    build_lane_comparison,
    is_abandoned_pred,
    scrub_abandon_summary,
)


def _assert_eu_probs(eu: dict) -> None:
    """去水概率必须非零、归一、reasons 无 0.0%、pick 为 argmax。"""
    p = eu["p_pct"]
    assert p, "p_pct 不应为空"
    assert all(v > 0 for v in p.values()), f"p_pct 不应出现 0.0: {p}"
    assert abs(sum(p.values()) - 1.0) < 0.01, f"p_pct 应归一 ≈1: {p}"
    text = " ".join(eu["reasons"])
    assert "0.0%" not in text, f"reasons 不应含 0.0%: {text}"
    assert eu["pick"] == max(p, key=p.get), f"pick 应为 argmax: {p} -> {eu['pick']}"
    assert eu["pick_cn"] in {"主胜", "平局", "客胜"}


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
    _assert_eu_probs(eu)


def test_eu_lane_from_snapshot_average():
    pred = {"odds_snapshot": {"eu_home": 2.80, "eu_draw": 3.20, "eu_away": 2.50}}
    eu = build_eu_lane(pred)
    assert eu["missing"] is False
    assert "欧赔均值" in eu["source_books"]
    _assert_eu_probs(eu)


def test_eu_lane_acceptance_2_06_2_98_3_84():
    """验收用例：p_pct ≈ 0.45/0.31/0.24，pick=主胜，reasons 无 0.0%。"""
    eu = build_eu_lane(
        {}, eu_books_major=[{"label": "威廉", "home": 2.06, "draw": 2.98, "away": 3.84}]
    )
    p = eu["p_pct"]
    assert abs(p["home"] - 0.45) < 0.02
    assert abs(p["draw"] - 0.31) < 0.02
    assert abs(p["away"] - 0.24) < 0.02
    assert eu["pick"] == "home"
    assert eu["pick_cn"] == "主胜"
    assert "0.0%" not in " ".join(eu["reasons"])
    _assert_eu_probs(eu)


def test_eu_lane_all_zero_probs_skips():
    """去水全零（赔率异常）→ skip/观望，不产出 0.0% 结论。"""
    eu = build_eu_lane(
        {}, eu_books_major=[{"label": "平博", "home": 0.9, "draw": 3.2, "away": 2.5}]
    )
    assert eu["missing"] is False
    assert eu["pick"] == "skip"
    assert eu["pick_cn"] == "观望"
    assert eu["p_pct"] == {}
    assert "0.0%" not in " ".join(eu["reasons"])


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
    # 主胜赔率最低 → 去水后 EU 真倾向 home，与竞彩一致
    eu = build_eu_lane({}, eu_books_major=[{"label": "平博", "home": 2.05, "draw": 3.2, "away": 2.6}])
    ah = {"missing": False, "lean": "home"}
    jc = {"missing": False, "pick": "home", "buyable": True, "play": "胜平负", "sp": "2.05"}
    comp = build_lane_comparison(eu, ah, jc)
    assert eu["pick"] == "home"
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


@pytest.mark.parametrize(
    "pred,expected",
    [
        ({"judgment": "放弃·变数过大"}, True),
        ({"judgment": "观望·赔率不明"}, True),
        ({"result_1x2_cn": "观望"}, True),
        ({"result_1x2_cn": "放弃"}, True),
        ({"result_1x2": "skip"}, True),
        ({"result_1x2_cn": "主胜"}, False),
        ({"judgment": "可购·主胜"}, False),
        ({}, False),
    ],
)
def test_is_abandoned_pred(pred, expected):
    assert is_abandoned_pred(pred) is expected


def test_scrub_abandon_summary_removes_jingcai_buy():
    pred = {
        "judgment": "放弃·变数过大",
        "result_1x2_cn": "观望",
        "summary": "【赛事概率】主42%。【竞彩可购】主胜，SP 2.05。比分 1-0、2-0。",
    }
    scrub_abandon_summary(pred)
    assert "【竞彩可购】" not in pred["summary"]
    assert "【当前建议】放弃" in pred["summary"]
    assert "【赛事概率】" in pred["summary"]


def test_scrub_abandon_summary_keeps_normal_pred():
    pred = {
        "result_1x2_cn": "主胜",
        "summary": "【赛事概率】主42%。【竞彩可购】主胜，SP 2.05。",
    }
    scrub_abandon_summary(pred)
    assert "【竞彩可购】" in pred["summary"]


def test_comparison_skip_when_pred_abandoned():
    """放弃/观望时：comparison.action 必须为 skip，禁止 hold。"""
    pred = {
        "judgment": "放弃·变数过大",
        "result_1x2_cn": "观望",
        "odds_snapshot": {"eu_home": 2.8, "eu_draw": 3.2, "eu_away": 2.5},
        "jingcai_pick_info": {"mode": "sp", "pick": "home", "pick_cn": "主胜", "sp": "2.05"},
    }
    attach_market_lanes(pred)
    comp = pred["market_lanes"]["comparison"]
    assert comp["action"] == "skip"
    assert "已放弃" in comp["summary"]
    assert comp["buyable"] is None
    assert "竞彩可购" not in comp["summary"]


def test_comparison_not_abandoned_keeps_hold():
    """非放弃 pred：竞彩 missing 仍走原 hold 逻辑（不 flip 方向）。"""
    pred = {
        "result_1x2_cn": "主胜",
        "odds_snapshot": {"eu_home": 2.8, "eu_draw": 3.2, "eu_away": 2.5},
    }
    attach_market_lanes(pred)
    comp = pred["market_lanes"]["comparison"]
    assert comp["action"] == "hold"
    assert "仅展示欧/亚参考" in comp["summary"]


def test_build_lane_comparison_abandoned_flag():
    jc = {"missing": False, "pick": "home", "buyable": True, "play": "胜平负", "sp": "2.05"}
    comp = build_lane_comparison({}, {}, jc, abandoned=True)
    assert comp["action"] == "skip"
    assert comp["buyable"] is None
    assert "已放弃" in comp["summary"]
