"""去水主/备对照（proportional 主 + Shin/power 备）测试。

覆盖：
- devig_pair 正常返回两套概率与方向一致性
- 缺 shin 库 / 数值异常时回退不崩溃
- 三轨 EU 带 alt 对照字段且主方向不变
- 方法分歧降置信、不 flip 竞彩
- value_edge 的 alt_p_mkt 对照字段
"""
import pytest

from analysis.market.devig import devig_1x2, devig_pair
from analysis.market.three_lane import build_eu_lane, build_lane_comparison
from analysis.market.value_edge import build_model_edges, compute_edge


def _fake_shin(h: float, d: float, a: float, *, flip: bool = False) -> dict:
    """假 Shin 实现：与 proportional 同向，或（flip=True）反向指向客胜。"""
    if d <= 0:
        d = 999.0
    inv = [1.0 / h, 1.0 / d, 1.0 / a]
    total = sum(inv)
    p_h, p_d, p_a = (x / total for x in inv)
    if flip:
        p_h, p_a = p_a, p_h
    return {
        "p_home": round(p_h, 4),
        "p_draw": round(p_d, 4),
        "p_away": round(p_a, 4),
        "overround": 0.0,
        "fair_odds": {},
        "method": "shin",
    }


# ---------- devig_pair ----------


def test_devig_pair_two_methods_same_pick(monkeypatch):
    monkeypatch.setattr("analysis.market.devig._devig_shin", _fake_shin)
    out = devig_pair(2.2, 3.1, 3.3, primary="proportional", alt="shin")
    assert out["main"]["method"] == "proportional"
    assert out["alt"]["method"] == "shin"
    assert out["alt_available"] is True
    assert out["main_pick"] == "home"
    assert out["alt_pick"] == "home"
    assert out["same_pick"] is True
    assert out["divergence"] is False
    # 主概率与单独 proportional 去水一致
    solo = devig_1x2(2.2, 3.1, 3.3, method="proportional")
    assert out["main"]["p_home"] == solo["p_home"]


def test_devig_pair_direction_divergence(monkeypatch):
    def flip(h, d, a):
        return _fake_shin(h, d, a, flip=True)

    monkeypatch.setattr("analysis.market.devig._devig_shin", flip)
    out = devig_pair(2.2, 3.1, 3.3)
    assert out["alt_available"] is True
    assert out["main_pick"] == "home"
    assert out["alt_pick"] == "away"
    assert out["same_pick"] is False
    assert out["divergence"] is True


def test_devig_pair_missing_shin_library_falls_back(monkeypatch):
    def boom(h, d, a):
        raise ImportError("No module named 'shin'")

    monkeypatch.setattr("analysis.market.devig._devig_shin", boom)
    out = devig_pair(2.2, 3.1, 3.3)
    # 不崩溃；alt 回退 proportional，且不再当作有效对照
    assert out["alt_available"] is False
    assert out["alt"]["method"] == "proportional"
    assert out["divergence"] is False
    assert out["same_pick"] is True  # 回退后同向，不误报分歧
    assert out["main"]["p_home"] > 0


def test_devig_pair_abnormal_odds_no_crash():
    for odds in [
        (0, 0, 0),
        (1.0, 1.2, 1.1),
        (None, 3.2, 2.5),
        (-2.5, 3.0, 2.8),
        (2.2, 0, 3.3),
    ]:
        out = devig_pair(*odds)
        assert out["main"]["p_home"] == 0.0 or out["main"]["p_home"] > 0


# ---------- 三轨 EU ----------


def test_build_eu_lane_alt_fields_when_shin_missing():
    pred = {"odds_snapshot": {"eu_home": 2.2, "eu_draw": 3.1, "eu_away": 3.3}}
    lane = build_eu_lane(pred)
    assert lane["pick"] == "home"
    # 主去水概率保持 proportional（回归兼容）
    solo = devig_1x2(2.2, 3.1, 3.3, method="proportional")
    assert lane["p_pct"]["home"] == pytest.approx(solo["p_home"], abs=1e-3)
    devig = lane["devig"]
    assert devig["main_method"] == "proportional"
    assert devig["alt_method"] == "shin"
    # 当前环境无 shin 库 → 回退，不算有效对照
    assert devig["alt_available"] is False
    assert devig["alt_p"] == {}
    # reasons 不回退时不应包含对照行
    assert not any("对照" in r for r in lane["reasons"])


def test_build_eu_lane_alt_fields_with_shin(monkeypatch):
    monkeypatch.setattr("analysis.market.devig._devig_shin", _fake_shin)
    pred = {"odds_snapshot": {"eu_home": 2.2, "eu_draw": 3.1, "eu_away": 3.3}}
    lane = build_eu_lane(pred)
    assert lane["pick"] == "home"
    solo = devig_1x2(2.2, 3.1, 3.3, method="proportional")
    assert lane["p_pct"]["home"] == pytest.approx(solo["p_home"], abs=1e-3)
    devig = lane["devig"]
    assert devig["alt_available"] is True
    assert devig["same_pick"] is True
    assert devig["divergence"] is False
    assert set(devig["alt_p"]) == {"home", "draw", "away"}
    assert any("对照" in r and "比例" in r for r in lane["reasons"])
    # 主方向未被 alt 翻转
    assert lane["pick_cn"] == "主胜"


# ---------- 三轨比较：方法分歧不 flip ----------


def _lanes(jc_pick="home", *, eu_pick="home", method_diverged=False):
    eu = {
        "id": "eu",
        "missing": False,
        "pick": eu_pick,
        "devig": {"divergence": method_diverged, "alt_available": True},
    }
    ah = {"id": "ah", "missing": False, "lean": "home"}
    jc = {
        "id": "jingcai",
        "missing": False,
        "pick": jc_pick,
        "play": "胜平负",
        "pick_cn": "主胜",
        "sp": 2.0,
        "buyable": True,
    }
    return eu, ah, jc


def test_comparison_no_divergence_aligns():
    eu, ah, jc = _lanes(method_diverged=False)
    comp = build_lane_comparison(eu, ah, jc)
    assert comp["agreement"] == "align"
    assert comp["action"] == "hold"
    assert comp["buyable"]["pick"] == "home"


def test_comparison_method_divergence_downgrades_but_keeps_jc():
    eu, ah, jc = _lanes(method_diverged=True)
    comp = build_lane_comparison(eu, ah, jc)
    # 分歧 → 不提升置信、降小注；竞彩方向不被 flip
    assert comp["agreement"] == "partial"
    assert comp["action"] == "size_down"
    assert "去水" in comp["summary"]
    assert comp["buyable"]["pick"] == "home"


def test_comparison_method_divergence_never_flips_jc():
    # 即使 alt 指向与竞彩相反，主方向仍以竞彩为准
    eu, ah, jc = _lanes(jc_pick="away", eu_pick="home", method_diverged=True)
    comp = build_lane_comparison(eu, ah, jc)
    assert comp["action"] in ("size_down", "skip")
    if comp["buyable"]:
        assert comp["buyable"]["pick"] == "away"


# ---------- value_edge ----------


def test_compute_edge_with_alt_p_mkt():
    p_model = {"home": 0.45, "draw": 0.28, "away": 0.27}
    sp = {"home": 2.10, "draw": 3.40, "away": 3.50}
    edge = compute_edge(
        p_model,
        sp=sp,
        model_source="result_forecast",
        alt_p_mkt={"home": 0.50, "draw": 0.25, "away": 0.25},
        devig_meta={
            "main_method": "proportional",
            "alt_method": "shin",
            "alt_available": True,
            "same_pick": True,
            "divergence": False,
        },
    )
    assert edge is not None
    assert edge["p_mkt_alt"]["home"] == pytest.approx(0.50, abs=1e-4)
    assert edge["edge_alt"]["home"] == pytest.approx(-0.05, abs=1e-4)
    assert edge["devig"]["alt_method"] == "shin"
    assert edge["devig"]["same_pick"] is True
    # 主 edge 保持原有比例去水口径
    assert edge["edge"]["home"] == pytest.approx(p_model["home"] - edge["p_mkt"]["home"], abs=1e-4)


def test_compute_edge_ignores_invalid_alt():
    p_model = {"home": 0.45, "draw": 0.28, "away": 0.27}
    sp = {"home": 2.10, "draw": 3.40, "away": 3.50}
    edge = compute_edge(
        p_model,
        sp=sp,
        alt_p_mkt={"home": 0, "draw": 0, "away": 0},
        devig_meta={
            "alt_available": True,
            "main_method": "proportional",
            "alt_method": "shin",
            "same_pick": False,
            "divergence": True,
        },
    )
    # alt 概率无效 → 只写元信息，不写对照概率/edge
    assert edge["devig"]["alt_available"] is True
    assert edge["devig"]["divergence"] is True
    assert "p_mkt_alt" not in edge
    assert "edge_alt" not in edge


def test_build_model_edges_with_shin_alt(monkeypatch):
    monkeypatch.setattr("analysis.market.devig._devig_shin", _fake_shin)
    ctx = {"european": {"odds": {"home": 2.20, "draw": 3.30, "away": 3.40}}}
    result_forecast = {"p_home": 0.42, "p_draw": 0.28, "p_away": 0.30}
    poisson = {"p_1x2": {"home": 0.40, "draw": 0.30, "away": 0.30}}
    edges = build_model_edges(ctx, result_forecast, poisson)
    assert edges is not None
    rf = edges["result_forecast"]
    assert rf["devig"]["alt_available"] is True
    assert rf["devig"]["main_method"] == "proportional"
    assert rf["devig"]["alt_method"] == "shin"
    assert rf["p_mkt_alt"]["home"] > 0


def test_build_model_edges_falls_back_without_shin(monkeypatch):
    def boom(h, d, a):
        raise ImportError("No module named 'shin'")

    monkeypatch.setattr("analysis.market.devig._devig_shin", boom)
    ctx = {"european": {"odds": {"home": 2.20, "draw": 3.30, "away": 3.40}}}
    result_forecast = {"p_home": 0.42, "p_draw": 0.28, "p_away": 0.30}
    edges = build_model_edges(ctx, result_forecast, None)
    assert edges is not None
    assert edges["result_forecast"]["devig"]["alt_available"] is False
    assert "p_mkt_alt" not in edges["result_forecast"]
