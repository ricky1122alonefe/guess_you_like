"""OU（大小球）参考轨测试 — 独立于 1X2/竞彩轨，不改竞彩方向。"""
from analysis.market.ou_lane import _devig_ou, build_ou_comparison, build_ou_lane
from analysis.market.three_lane import attach_market_lanes
from score_models import score_matrix


def _matrix_pred(lam_home: float = 2.2, lam_away: float = 1.4) -> dict:
    cells = score_matrix(lam_home, lam_away)
    return {
        "result_forecast": {
            "secondary": {
                "models": {
                    "poisson_matrix": {
                        "score_matrix": {f"{i}-{j}": p for (i, j), p in cells.items()},
                        "lambda_home": lam_home,
                        "lambda_away": lam_away,
                    }
                }
            }
        }
    }


def test_ou_lane_missing_without_matrix():
    pred = {}
    attach_market_lanes(pred)
    ou = pred["market_lanes"]["ou"]
    assert ou["missing"] is True
    assert ou["buyable"] is False
    assert pred["market_lanes"]["ou_comparison"]["action"] == "hold"


def test_ou_lane_populated_with_poisson_matrix():
    pred = _matrix_pred(2.2, 1.4)
    attach_market_lanes(pred)
    ou = pred["market_lanes"]["ou"]
    assert ou["missing"] is False
    assert ou["p_over"] is not None and ou["p_under"] is not None
    assert abs(ou["p_over"] + ou["p_under"] - 1.0) < 1e-6
    assert 0 < ou["btts"] < 1
    assert 0 < ou["zero_zero"] < 1
    assert ou["exp_total"] is not None
    assert ou["lean_cn"] in ("大球", "小球", "中性")
    assert ou["buyable"] is False
    # 高 λ 组合（预期总进球≈3.6）大2.5 概率应过半
    assert ou["p_over"] > 0.5


def test_ou_lane_from_lambda_fallback():
    pred = {"quant": {"score_model": {"lambda_home": 2.0, "lambda_away": 1.2}}}
    attach_market_lanes(pred)
    ou = pred["market_lanes"]["ou"]
    assert ou["missing"] is False
    assert ou["exp_total"] is not None
    assert abs(ou["p_over"] + ou["p_under"] - 1.0) < 1e-6


def test_ou_lane_lines_include_15_and_35():
    ou = build_ou_lane(_matrix_pred(2.2, 1.4))
    for line in ("1.5", "2.5", "3.5"):
        assert line in ou["lines"]
        item = ou["lines"][line]
        assert 0 < item["over"] < 1
        assert abs(item["over"] + item["under"] - 1.0) < 1e-6
    # 越高的线大球概率越低（单调）
    assert ou["lines"]["1.5"]["over"] > ou["lines"]["2.5"]["over"] > ou["lines"]["3.5"]["over"]


def test_ou_does_not_change_1x2_comparison():
    pred = {
        "odds_snapshot": {"eu_home": 2.2, "eu_draw": 3.2, "eu_away": 3.0},
        "jingcai_pick_info": {"mode": "sp", "pick": "home", "pick_cn": "主胜", "sp": "2.05"},
    }
    pred.update(_matrix_pred(2.2, 1.4))
    attach_market_lanes(pred)
    comp = pred["market_lanes"]["comparison"]
    # OU 参考轨不 flip 1X2：竞彩轨方向仍为主胜
    assert comp["buyable"] is not None
    assert comp["buyable"]["pick_cn"] == "主胜"
    # OU 独立存在且不可购
    ou = pred["market_lanes"]["ou"]
    assert ou["missing"] is False
    assert pred["market_lanes"]["ou_comparison"]["buyable"] is False
    # 1X2 对照摘要不被 OU 改写
    assert comp["action"] in ("hold", "size_down", "skip")


def test_ou_lane_with_sp_reports_edge_and_buyable_false():
    pred = _matrix_pred(2.2, 1.4)
    pred["ou_sp"] = {"line": 2.5, "over": 2.5, "under": 1.8}
    ou = build_ou_lane(pred)
    assert ou["missing"] is False
    assert ou["sp"] is not None
    assert ou["implied"] is not None
    assert ou["edge"] is not None
    assert ou["buyable"] is False
    assert "devig" in " ".join(ou["reasons"])


def test_devig_ou_basic():
    imp = _devig_ou(2.0, 2.0)
    assert abs(imp["p_over"] - 0.5) < 1e-3
    imp2 = _devig_ou(1.8, 2.2)
    assert imp2["p_over"] > 0.5


def test_ou_comparison_hold_without_sp():
    ou = {"missing": False, "p_over": 0.6, "p_under": 0.4, "buyable": False, "sp": None}
    comp = build_ou_comparison(ou)
    assert comp["action"] == "hold"
    assert comp["buyable"] is False
    assert "不影响竞彩 1X2" in comp["summary"]


def test_ou_comparison_skip_on_severe_reverse():
    ou = {
        "missing": False,
        "p_over": 0.75,
        "p_under": 0.25,
        "lean": "over",
        "lean_cn": "大球",
        "sp": {"line": 2.5, "over": 2.5, "under": 1.8},
        "implied": {"p_over": 0.42, "p_under": 0.58, "margin": 0.0},
        "edge": {"over": 0.33, "under": -0.33},
        "buyable": False,
    }
    comp = build_ou_comparison(ou)
    assert comp["action"] == "skip"
    assert "放弃" in comp["summary"]
    assert "不改竞彩 1X2" in comp["summary"]


def test_ou_comparison_size_down_on_moderate_reverse():
    ou = {
        "missing": False,
        "p_over": 0.65,
        "p_under": 0.35,
        "lean": "over",
        "lean_cn": "大球",
        "sp": {"line": 2.5, "over": 2.2, "under": 1.65},
        "implied": {"p_over": 0.45, "p_under": 0.55, "margin": 0.0},
        "edge": {"over": 0.20, "under": -0.20},
        "buyable": False,
    }
    comp = build_ou_comparison(ou)
    assert comp["action"] == "size_down"
    assert "降为小注" in comp["summary"]


def test_weather_storm_only_note_not_lean():
    pred = _matrix_pred(2.2, 1.4)
    pred["prematch_desk"] = {
        "dimensions": [{"id": "weather", "missing": False, "evidence": ["暴雨，降水 20mm"]}]
    }
    ou = build_ou_lane(pred)
    assert any("暴雨" in n for n in ou["notes"])
    assert ou["lean_cn"] in ("大球", "小球", "中性")
    assert ou["lean"] in (None, "over", "under")


def test_market_lanes_card_renders_ou_lane():
    from web_ui import _market_lanes_card

    pred = _matrix_pred(2.2, 1.4)
    attach_market_lanes(pred)
    html = _market_lanes_card(pred)
    assert "大小球轨" in html
    assert "参考·非改 1X2" in html
    assert "P(大2.5)≈" in html
    assert "预期总进球≈" in html
    assert "仅模型基准，不可购" in html


def test_pred_card_prefers_range_probs_over_zero_pct_scores():
    from web_ui import _pred_card

    pred = _matrix_pred(2.2, 1.4)
    pred["predict_row"] = {"推荐比分": "2-1(0.0%)、1-1(0.0%)", "亚盘": "受让0.25", "置信度": "低"}
    attach_market_lanes(pred)
    html = _pred_card(pred)
    assert "区间概率参考" in html
    assert "大2.5≈" in html
    assert "2-1" not in html
