"""Tests for detail model fold UI."""

from web_ui import _models_detail_card, _result_forecast_card


def test_models_detail_card_empty():
    assert _models_detail_card({}) == ""
    assert _models_detail_card(None) == ""


def test_models_detail_card_renders_all_blocks():
    models = {
        "elo": {
            "home_elo": 1500,
            "away_elo": 1480,
            "elo_diff": 90,
            "p_elo_1x2": {"home": 0.5, "draw": 0.25, "away": 0.25},
        },
        "poisson_matrix": {
            "lambda_home": 1.5,
            "lambda_away": 1.1,
            "top_scores": [{"score": "1-0", "prob_pct": 15.0}],
            "p_1x2": {"home": 0.4, "draw": 0.3, "away": 0.3},
        },
        "edge": {
            "market_source": "eu_closing",
            "disclaimer": "研究用，非投注建议",
            "result_forecast": {
                "edge": {"home": 0.05, "draw": -0.02, "away": -0.03},
                "half_kelly": {"home": 0.04, "draw": None, "away": None},
            },
        },
    }
    html = _models_detail_card(models)
    assert "模型对照" in html
    assert "Elo" in html
    assert "泊松" in html
    assert "Edge" in html
    assert "研究用" in html


def test_result_forecast_card_includes_model_fold():
    prediction = {
        "result_prediction": {
            "pick": "home",
            "pick_cn": "主胜",
            "confidence_cn": "中",
            "p_home": 0.4,
            "p_draw": 0.3,
            "p_away": 0.3,
            "reasons": [],
            "weights": {},
            "secondary": {
                "models": {
                    "elo": {
                        "home_elo": 1500,
                        "away_elo": 1480,
                        "elo_diff": 90,
                        "p_elo_1x2": {"home": 0.5, "draw": 0.25, "away": 0.25},
                    }
                }
            },
        }
    }
    html = _result_forecast_card(prediction)
    assert "模型对照" in html
    assert "Elo" in html
