"""Tests for ai_prompt, especially ai_expert_desk payload."""

import pytest

from ai_prompt import (
    EXPERT_SYSTEM_PROMPT,
    attach_expert_desk_sources,
    build_ai_expert_desk_payload,
    enrich_analysis_context,
)


def test_expert_system_prompt_has_actuary_desk_order():
    assert "精算师桌：输入顺序" in EXPERT_SYSTEM_PROMPT
    assert "竞彩：SP开→临" in EXPERT_SYSTEM_PROMPT
    assert "分歧：eu_ah_divergence" in EXPERT_SYSTEM_PROMPT
    assert "market_attitude" in EXPERT_SYSTEM_PROMPT
    assert "result_forecast pick/p/reasons" in EXPERT_SYSTEM_PROMPT
    assert "missing 项禁止编造" in EXPERT_SYSTEM_PROMPT


def test_expert_system_prompt_has_oral_reasoning_steps():
    assert "专家口头推理顺序" in EXPERT_SYSTEM_PROMPT
    assert "看可购价" in EXPERT_SYSTEM_PROMPT
    assert "看分歧是否打架" in EXPERT_SYSTEM_PROMPT
    assert "给「倾向/小注/放弃」" in EXPERT_SYSTEM_PROMPT
    assert "竞彩可购方向" in EXPERT_SYSTEM_PROMPT


def _base_ctx() -> dict:
    return {
        "jingcai": {
            "has_sp": True,
            "has_rqsp": True,
            "sp_home": 1.80,
            "sp_draw": 3.40,
            "sp_away": 4.20,
            "rqsp_home": 3.10,
            "rqsp_draw": 3.25,
            "rqsp_away": 2.05,
            "handicap": "-1",
            "match_num": "周日001",
        },
        "divergence": {
            "divergence_score": 0.35,
            "severity_cn": "中",
            "advice": "欧亚略分裂，建议观望或小注",
            "signals": ["欧热亚浅", "主队水位偏高"],
            "line_gap": 0.25,
            "consistency": "ah_shallow",
        },
        "market_attitude": {
            "labels": ["升盘降水", "主热"],
            "supported_side": "home",
            "strength": "中",
            "narrative": "亚盘升盘降水支持主队，但欧赔未同步跟进",
        },
        "current_odds": {
            "asian_handicap_open": {"line": -0.5, "home_water": 0.95, "away_water": 0.90},
            "asian_handicap_live": {"line": -0.75, "home_water": 0.98, "away_water": 0.87},
        },
        "result_forecast": {
            "pick": "主胜",
            "p": 0.62,
            "reasons": ["主队近况占优", "亚盘升盘降水"],
            "score_range": "1-0 2-1",
        },
        "history_similar": {
            "sample_count": 42,
            "home_win_rate": "58%",
            "draw_rate": "24%",
            "away_win_rate": "18%",
            "avg_total_goals": 2.3,
        },
        "precomputed_ev": {
            "edge_side": "home",
            "edge_pp": 0.06,
            "value_bet": True,
            "confidence": "中",
        },
        "control_analysis": {"level_cn": "中", "score": 0.45},
        "market_patterns": {"patterns": [{"name": "诱上盘"}]},
        "trap_analysis": {"notes": ["主队资金过热"]},
        "club_form": {
            "home_form": "近5场 3胜1平1负，场均进1.8球",
            "away_form": "近5场 1胜2平2负，客场防守不稳",
        },
    }


def test_expert_desk_payload_has_required_keys():
    payload = build_ai_expert_desk_payload(_base_ctx())
    assert set(payload.keys()) == {
        "jingcai",
        "divergence",
        "market",
        "result_forecast",
        "similar_ev_trap",
        "missing",
    }


def test_jingcai_block_has_sp_and_rqsp():
    payload = build_ai_expert_desk_payload(_base_ctx())
    jc = payload["jingcai"]
    assert jc["available"] is True
    assert "胜平负" in jc["play_types"]
    assert "让球胜平负" in jc["play_types"]
    assert "sp_open_live" in jc
    assert "rqsp_open_live" in jc
    assert jc["rqsp_open_live"]["handicap"] == "-1"
    assert "胜平负" in jc["devig_probabilities"]
    assert "让球胜平负" in jc["devig_probabilities"]
    assert jc["match_num"] == "周日001"


def test_jingcai_block_missing():
    ctx = _base_ctx()
    ctx["jingcai"] = {}
    payload = build_ai_expert_desk_payload(ctx)
    assert payload["jingcai"]["available"] is False
    assert "jingcai" in payload["missing"]


def test_divergence_block_score_and_advice():
    payload = build_ai_expert_desk_payload(_base_ctx())
    div = payload["divergence"]
    assert div["available"] is True
    assert div["score"] == 0.35
    assert div["severity"] == "中"
    assert "观望" in div["advice"]
    assert "欧热亚浅" in div["signals"]


def test_market_block_attitude_and_ah():
    payload = build_ai_expert_desk_payload(_base_ctx())
    mkt = payload["market"]
    assert mkt["available"] is True
    assert mkt["ah_open"]["line"] == -0.5
    assert mkt["ah_live"]["line"] == -0.75
    assert "支持主队" in mkt["market_attitude"]["narrative"]
    assert "升盘降水" in mkt["market_attitude"]["labels"]


def test_result_forecast_block():
    payload = build_ai_expert_desk_payload(_base_ctx())
    rf = payload["result_forecast"]
    assert rf["available"] is True
    assert rf["pick"] == "主胜"
    assert rf["p"] == 0.62
    assert "主队近况占优" in rf["reasons"]


def test_similar_ev_trap_block():
    payload = build_ai_expert_desk_payload(_base_ctx())
    sim = payload["similar_ev_trap"]
    assert "同赔样本 42 场" in sim["similar_summary"]
    assert sim["ev"]["edge_side"] == "home"
    assert sim["ev"]["edge_pp"] == 0.06
    assert "诱上盘" in sim["trap_control"]["patterns"]
    assert sim["form"]["available"] is True
    assert "近5场" in sim["form"]["home"]


def test_no_form_does_not_fabricate_recent_5():
    ctx = _base_ctx()
    ctx["club_form"] = {}
    ctx["recent_form"] = {}
    ctx["form"] = {}
    payload = build_ai_expert_desk_payload(ctx)
    assert payload["similar_ev_trap"]["form"]["available"] is False
    assert "近5场" not in payload["similar_ev_trap"]["form"]["home"]
    assert "近5场" not in payload["similar_ev_trap"]["form"]["away"]
    assert "team_recent_form/club_form" in payload["missing"]


def test_missing_is_explicit_when_data_incomplete():
    ctx = {key: {} for key in _base_ctx()}
    payload = build_ai_expert_desk_payload(ctx)
    assert "jingcai" in payload["missing"]
    assert "divergence" in payload["missing"]
    assert "market_attitude" in payload["missing"]
    assert "result_forecast" in payload["missing"]
    assert "team_recent_form/club_form" in payload["missing"]


def test_attach_expert_desk_sources_fills_jingcai_from_prediction():
    pred = {
        "jingcai": {"has_sp": True, "sp_home": 2.0, "sp_draw": 3.0, "sp_away": 4.0},
        "result_prediction": {
            "pick": "主胜",
            "p": 0.55,
        },
    }
    ctx = attach_expert_desk_sources({}, fixture_id="fid-001", prediction=pred)
    assert ctx["jingcai"]["has_sp"] is True
    assert ctx["result_forecast"]["pick"] == "主胜"


def test_attach_expert_desk_sources_preserves_forecast_ctx():
    forecast_ctx = {
        "divergence": {"divergence_score": 0.4, "advice": "观望"},
        "market_attitude": {"narrative": "支持主队"},
        "club_form": {"home_form": "3胜1平1负", "away_form": "1胜2平2负"},
        "history_similar": {"sample_count": 20},
    }
    ctx = attach_expert_desk_sources(forecast_ctx, fixture_id="fid-002", prediction={})
    assert ctx["divergence"]["advice"] == "观望"
    assert ctx["market_attitude"]["narrative"] == "支持主队"
    assert ctx["club_form"]["home_form"] == "3胜1平1负"
    assert ctx["history_similar"]["sample_count"] == 20


def test_detail_and_enrich_actuary_input_same_mock():
    """详情页 build 与 enrich 后的 actuary_input 关键块一致（同 mock）。"""
    prediction = {
        "jingcai": {"has_sp": True, "sp_home": 2.0, "sp_draw": 3.1, "sp_away": 3.9},
        "result_prediction": {
            "pick": "主胜",
            "p": 0.56,
            "factors": {
                "ev": {"edge_side": "home", "edge_pp": 0.04},
            },
        },
    }
    forecast_ctx = {
        "divergence": {"divergence_score": 0.2, "advice": "正常"},
        "market_attitude": {"narrative": "主队受注"},
    }
    # detail path
    expert_ctx = attach_expert_desk_sources(
        {
            "divergence": forecast_ctx["divergence"],
            "market_attitude": forecast_ctx["market_attitude"],
            "result_forecast": prediction["result_prediction"],
        },
        fixture_id="fid-003",
        prediction=prediction,
    )
    detail_actuary = build_ai_expert_desk_payload(expert_ctx)

    # enrich path
    payload = {
        "current": {"match": {"home": "主", "away": "客"}},
        "stats": {},
        "eu_stats": {},
        "fixture_id": "fid-003",
        "jingcai": prediction["jingcai"],
        "poll_meta": {"jingcai": prediction["jingcai"]},
        "divergence": forecast_ctx["divergence"],
        "market_attitude": forecast_ctx["market_attitude"],
        "result_forecast": prediction["result_prediction"],
    }
    ctx = enrich_analysis_context(payload, fixture_id="fid-003")
    enrich_actuary = ctx["actuary_input"]

    assert detail_actuary["jingcai"]["available"] == enrich_actuary["jingcai"]["available"]
    assert detail_actuary["divergence"]["advice"] == enrich_actuary["divergence"]["advice"]
    assert detail_actuary["market"]["market_attitude"]["narrative"] == enrich_actuary["market"]["market_attitude"]["narrative"]
    assert detail_actuary["result_forecast"]["pick"] == enrich_actuary["result_forecast"]["pick"]
    assert detail_actuary["similar_ev_trap"]["ev"]["edge_side"] == enrich_actuary["similar_ev_trap"]["ev"]["edge_side"]


def test_attach_expert_desk_sources_missing_jingcai_no_fabrication():
    ctx = attach_expert_desk_sources({}, fixture_id="fid-004", prediction={})
    payload = build_ai_expert_desk_payload(ctx)
    assert payload["jingcai"]["available"] is False
    assert "jingcai" in payload["missing"]
    ev = payload["similar_ev_trap"]["ev"]
    assert ev["edge_side"] is None
    assert ev["edge_pp"] is None
    assert ev["value_bet"] is None
    assert ev["implied_probabilities"] == {}
