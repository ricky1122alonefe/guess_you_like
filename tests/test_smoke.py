"""Minimal smoke tests — no network, no API keys."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_groups_json_valid():
    path = ROOT / "data" / "wc2026_groups.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["format"]["teams"] == 48
    assert len(data["groups"]) == 12


def test_import_core_modules():
    import config  # noqa: F401
    import market_patterns  # noqa: F401
    import eu_implied_metrics  # noqa: F401
    import share_card  # noqa: F401
    import ah_analytics  # noqa: F401
    import kelly  # noqa: F401


def test_ah_settle_and_evaluate():
    from ah import ah_settle
    from ah_analytics import evaluate_ah_pick, ah_win_rate_from_net, ah_rate_text

    assert ah_settle(2, 0, -0.5, "home") == 1.0
    assert ah_settle(1, 1, -0.5, "home") == -1.0
    assert ah_settle(1, 0, -1.0, "home") == 0.0

    ev = evaluate_ah_pick("home", home_score=2, away_score=0, line=-0.5)
    assert ev["hit_ah"] is True
    assert ev["ah_settlement"] == 1.0

    stats = {"ah_home_net": 0.2, "ah_away_net": -0.2}
    assert ah_win_rate_from_net(0.2) == 0.6
    assert "上盘赢" in (ah_rate_text(stats) or "")


def test_kelly_compute():
    from kelly import compute_kelly, kelly_prefill_from_prediction

    r = compute_kelly(0.55, decimal_odds=2.0, fraction=0.5)
    assert r["ok"] is True
    assert r["full_kelly"] > 0
    assert r["ev_per_unit"] > 0

    r_neg = compute_kelly(0.40, decimal_odds=2.0)
    assert r_neg["ok"] is True
    assert r_neg["full_kelly"] <= 0

    r_water = compute_kelly(0.52, water=0.95, fraction=0.25)
    assert r_water["ok"] is True
    assert r_water["decimal_odds"] == 1.95

    pre = kelly_prefill_from_prediction({
        "match": "A vs B",
        "result_1x2": "home",
        "result_1x2_cn": "主胜",
        "odds_snapshot": {"eu_home": 1.8, "ah_home_water": 0.92},
        "eu_implied": {"fair_home_pct": 52.0},
        "similarity_analysis": {
            "open": [{"source": "open_ah", "home_win_rate": 0.58, "count": 100}],
        },
    }, fixture_id="123")
    assert pre["available"] is True
    assert pre["probability_pct"] == 58.0


def test_similar_samples_ah_rates():
    from similar_samples import build_similarity_analysis

    payload = {
        "open_stats": {
            "count": 10,
            "home_win_rate": 0.5,
            "draw_rate": 0.2,
            "away_win_rate": 0.3,
            "ah_home_net": 0.1,
            "ah_away_net": -0.1,
            "ah_home_full_win": 0.4,
            "ah_home_half_win": 0.1,
            "ah_home_push": 0.1,
            "score_top": [],
            "samples": [],
        },
        "open_eu_stats": {"count": 0},
        "stats": {"count": 0},
        "eu_stats": {"count": 0},
    }
    sim = build_similarity_analysis(payload)
    block = sim["open"][0]
    assert block.get("ah_rate_text")
    assert "上盘赢" in block["rate_text"]


def test_group_stage_motivation():
    from group_stage_model import analyze_fixture_motivation, rank_best_third_places

    standings = {
        "A": [
            {"team": "墨西哥", "played": 1, "points": 3, "gd": 1, "gf": 2, "ga": 1, "won": 1, "drawn": 0, "lost": 0},
            {"team": "韩国", "played": 1, "points": 3, "gd": 1, "gf": 2, "ga": 1, "won": 1, "drawn": 0, "lost": 0},
            {"team": "捷克", "played": 1, "points": 0, "gd": -1, "gf": 1, "ga": 2, "won": 0, "drawn": 0, "lost": 1},
            {"team": "南非", "played": 1, "points": 0, "gd": -1, "gf": 1, "ga": 2, "won": 0, "drawn": 0, "lost": 1},
        ],
        "B": [
            {"team": "瑞士", "played": 1, "points": 1, "gd": 0, "gf": 1, "ga": 1, "won": 0, "drawn": 1, "lost": 0},
            {"team": "卡塔尔", "played": 1, "points": 1, "gd": 0, "gf": 1, "ga": 1, "won": 0, "drawn": 1, "lost": 0},
            {"team": "加拿大", "played": 1, "points": 1, "gd": 0, "gf": 1, "ga": 1, "won": 0, "drawn": 1, "lost": 0},
            {"team": "波黑", "played": 1, "points": 1, "gd": 0, "gf": 1, "ga": 1, "won": 0, "drawn": 1, "lost": 0},
        ],
    }
    best3 = rank_best_third_places(standings)
    assert len(best3) == 2

    mx_kr = analyze_fixture_motivation(
        home="墨西哥", away="韩国", group="A", standings=standings, round_num=2, best_thirds=best3,
    )
    assert mx_kr["match_type"] == "collusion_watch"

    cz_sa = analyze_fixture_motivation(
        home="捷克", away="南非", group="A", standings=standings, round_num=2, best_thirds=best3,
    )
    assert cz_sa["match_type"] == "must_win"

    b_open = analyze_fixture_motivation(
        home="瑞士", away="波黑", group="B", standings=standings, round_num=2, best_thirds=best3,
    )
    assert b_open["match_type"] in ("open_race", "draw_friendly")


def test_group_stage_does_not_flip_clear_open_home():
    from analysis.rules.engine import _open_hist_favors, _resolve_group_stage_pick
    from analysis.tournament.group_stage import adjust_rates_for_group_stage

    hist_rates = {"home": 0.505, "draw": 0.291, "away": 0.204}
    assert _open_hist_favors(hist_rates, "home") is True

    combined = {"home": 0.159, "draw": 0.092, "away": 0.064}
    gs = {
        "match_type": "collusion_watch",
        "match_type_cn": "默契球观察",
        "draw_bias": 0.14,
        "home_bias": -0.04,
        "away_bias": -0.04,
        "likely_direction_cn": "平局或小比分",
    }
    adjusted, _ = adjust_rates_for_group_stage(combined, gs)
    new_key, notes = _resolve_group_stage_pick("home", adjusted, hist_rates, "home", gs)
    assert new_key == "home"


def test_odds_reference_blend():
    from analysis.signals.odds_probs import blend_reference_1x2, check_jingcai_reference_divergence

    cur = {
        "eu_home": 1.85,
        "eu_draw": 3.4,
        "eu_away": 4.2,
        "eu_open_home": 2.0,
        "eu_open_draw": 3.3,
        "eu_open_away": 3.8,
        "ah_open_line": -0.5,
        "ah_line": -0.75,
        "ah_open_home_water": 0.95,
        "ah_home_water": 0.88,
        "ah_open_away_water": 0.93,
        "ah_away_water": 0.98,
    }
    hist = {"home": 0.55, "draw": 0.25, "away": 0.20}
    blended, summary, shares = blend_reference_1x2(cur, hist)
    assert blended["home"] > blended["away"]
    assert "参考融合" in summary
    assert "竞彩" not in summary
    assert "hist" in shares

    ref = {"home": 0.52, "draw": 0.24, "away": 0.24}
    jc = {"has_sp": True, "sp_home": 2.80, "sp_draw": 2.05, "sp_away": 3.50}
    div = check_jingcai_reference_divergence("home", ref, jc)
    assert div is not None
    assert div["jingcai_implied_key"] == "draw"


def test_jingcai_attach_uses_reference():
    from jingcai_pick import attach_jingcai_recommendation

    pred = {
        "result_1x2": "home",
        "result_1x2_cn": "主胜",
        "reference_result_1x2": "home",
        "reference_result_1x2_cn": "主胜",
    }
    jc = {"has_sp": True, "sp_home": 1.95, "sp_draw": 3.10, "sp_away": 3.60}
    attach_jingcai_recommendation(pred, jc)
    row = pred["predict_row"]
    assert row["赛果预测"] == "主胜"
    assert row["竞彩推荐"] == "主胜"
    assert row["竞彩SP"] == 1.95


def test_qualification_divergence_alert():
    from analysis.signals.qualification_alert import build_qualification_divergence_alert

    cur = {
        "eu_open_home": 1.55,
        "eu_open_draw": 4.0,
        "eu_open_away": 5.5,
        "eu_home": 1.45,
        "eu_draw": 4.2,
        "eu_away": 6.0,
        "ah_open_line": -1.0,
        "ah_line": -0.5,
        "ah_open_home_water": 0.92,
        "ah_home_water": 0.95,
        "ah_open_away_water": 0.94,
        "ah_away_water": 0.91,
    }
    gs = {
        "match_type": "collusion_watch",
        "match_type_cn": "默契球观察",
        "round": 2,
        "likely_direction_cn": "平局或小比分",
        "is_finished": False,
    }
    alert = build_qualification_divergence_alert(cur, gs, match_name="墨西哥VS韩国")
    assert alert is not None
    assert alert["tag"] == "出线·欧亚分歧"
    assert alert["divergence_score"] >= 30
    assert "出线·欧亚分歧" in alert["advice"]


def test_long_image_export_helper():
    from share_card import long_image_export_script

    js = long_image_export_script(root_id="test-root", filename="demo")
    assert "savePageLongImage" in js
    assert "test-root" in js


def test_match_result_payload_serialized():
    from db.repository import _match_result_values

    row = {
        "fixture_id": 1,
        "status": "finished",
        "home_score": 2,
        "away_score": 1,
        "score_text": "2-1",
        "result_1x2": "H",
        "result_1x2_cn": "主胜",
        "payload": {"prediction": {"pick_1x2_cn": "主胜"}, "line_move": 0.25},
        "source": "500",
    }
    vals = _match_result_values(row)
    payload_idx = 22  # payload column position
    assert isinstance(vals[payload_idx], str)
    assert json.loads(vals[payload_idx])["line_move"] == 0.25


def test_knockout_path_group_a():
    from knockout_path import (
        analyze_opponent_picking,
        bracket_flow_steps,
        build_group_bracket_overview,
        path_for_rank,
    )

    p1 = path_for_rank("A", 1)
    p2 = path_for_rank("A", 2)
    assert p1["r32_match"] == 79
    assert p2["r32_match"] == 73
    assert p2["r32_opponent_slot"] == "2B"
    assert p2["difficulty_score"] < p1["difficulty_score"]

    steps = bracket_flow_steps(p2)
    assert steps[0]["stage"] == "group"
    assert "M73" in steps[1]["label"]

    overview = build_group_bracket_overview("A")
    assert overview["first"]["slot"] == "1A"
    assert overview["second"]["slot"] == "2A"

    pick = analyze_opponent_picking("墨西哥", "A", standings_row={"points": 3, "played": 1})
    assert pick["easiest_path_rank"] == 2
    assert pick["picking_level"] in ("watch", "medium")
    assert any("挑对手" in n or "第二" in n for n in pick["notes"])


def test_prediction_archive_kickoff_compare():
    import tempfile
    from datetime import datetime, timezone
    from pathlib import Path

    from prediction_archive import load_best_prediction
    from time_utils import BEIJING, coerce_beijing_dt

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        runs = root / "runs" / "2026-06-17_1000"
        runs.mkdir(parents=True)
        (runs / "predictions.json").write_text(
            json.dumps({
                "generated_at": "2026-06-17 09:00:00",
                "matches": [{"fixture_id": "1359218", "result_1x2_cn": "主胜"}],
            }),
            encoding="utf-8",
        )
        ko_aware = datetime(2026, 6, 17, 12, 0, tzinfo=timezone.utc)
        pred = load_best_prediction(root, "1359218", kickoff_at=ko_aware)
        assert pred is not None
        assert pred.get("result_1x2_cn") == "主胜"

        ko_naive = datetime(2026, 6, 17, 20, 0)
        pred2 = load_best_prediction(root, "1359218", kickoff_at=ko_naive)
        assert pred2 is not None
        assert coerce_beijing_dt(ko_naive).tzinfo == BEIJING

        # mimic DB naive kickoff vs UTC-aware predict_ts stored in memory
        (runs / "predictions.json").write_text(
            json.dumps({
                "generated_at": "2026-06-17T09:00:00+00:00",
                "matches": [{"fixture_id": "1359257", "result_1x2_cn": "平局"}],
            }),
            encoding="utf-8",
        )
        pred3 = load_best_prediction(
            root,
            "1359257",
            kickoff_at=datetime(2026, 6, 17, 20, 0),  # naive, like psycopg2 + SET TIME ZONE
        )
        assert pred3 is not None
        assert pred3.get("result_1x2_cn") == "平局"


def test_parlay_uses_jingcai_sp_only():
    from custom_parlay import _leg_from_match
    from daily_picks import _combined_odds
    from jingcai_pick import attach_jingcai_recommendation, resolve_jingcai_sp

    jc = {
        "has_sp": True,
        "sp_home": 1.85,
        "sp_draw": 3.20,
        "sp_away": 4.10,
    }
    m = {
        "fixture_id": "1",
        "match": "A vs B",
        "result_1x2_cn": "home",
        "result_1x2": "home",
        "predict_row": {"胜平负": "主胜", "置信度": "高", "竞彩玩法": "胜平负", "竞彩SP": 1.85},
        "odds_snapshot": {"eu_home": 1.70, "eu_draw": 3.5, "eu_away": 5.0},
    }
    attach_jingcai_recommendation(m, jc)
    assert resolve_jingcai_sp(m, pick_key="home", market="sp") == 1.85

    leg = _leg_from_match(m)
    assert leg["jingcai_sp"] == 1.85
    assert leg["odds_used"] == 1.85
    assert leg["eu_odds"] == 1.70

    m2 = dict(m, fixture_id="2", match="C vs D")
    attach_jingcai_recommendation(m2, {**jc, "sp_home": 2.10})
    leg2 = _leg_from_match(m2)
    combined = _combined_odds([leg, leg2])
    assert combined == round(1.85 * 2.10, 2)


def test_jingcai_rqsp_from_foreign_odds():
    from jingcai_pick import attach_jingcai_recommendation, infer_rq_pick_from_foreign_odds

    pred = {
        "reference_result_1x2": "home",
        "reference_result_1x2_cn": "主胜",
        "eu_implied": {"fair_home_pct": 18.0, "fair_draw_pct": 24.0, "fair_away_pct": 58.0},
        "odds_snapshot": {"eu_home": 4.5, "eu_draw": 3.4, "eu_away": 1.65},
        "quant": {
            "score_model": {"lambda_home": 0.9, "lambda_away": 1.6, "prob_1x2_pct": {"home": 22, "draw": 24, "away": 54}},
        },
        "similarity_analysis": {
            "open": [{
                "source": "open_eu",
                "title": "初盘欧赔相似",
                "count": 120,
                "samples": [
                    {"score": "0-1"}, {"score": "0-2"}, {"score": "1-2"},
                    {"score": "0-1"}, {"score": "0-0"}, {"score": "1-1"},
                    {"score": "0-2"}, {"score": "0-1"}, {"score": "1-2"},
                ],
            }],
        },
    }
    pick, reason, meta = infer_rq_pick_from_foreign_odds(pred, -1)
    assert pick in ("home", "draw", "away")
    assert meta.get("probs_pct")
    assert "国外" in reason or "欧赔" in reason or "相似" in reason
    assert "参考研判" not in reason

    jc = {"has_sp": False, "has_rqsp": True, "handicap": -1, "rqsp_home": 3.2, "rqsp_draw": 3.4, "rqsp_away": 1.85}
    attach_jingcai_recommendation(pred, jc)
    info = pred["jingcai_pick_info"]
    assert info["jingcai_market"] == "rqsp"
    assert info["jingcai_pick"] in ("home", "draw", "away")
    assert pred.get("predict_row", {}).get("让球参考胜率")


def test_score_model_from_odds():
    from score_models import build_score_model

    sm = build_score_model(
        eu_home=1.70,
        eu_draw=3.50,
        eu_away=5.00,
        fair_home_pct=55.0,
        fair_draw_pct=26.0,
        fair_away_pct=19.0,
        ah_line=-0.5,
        pick_1x2="home",
    )
    assert sm is not None
    assert len(sm["likely_scores"]) == 3
    assert sm["prob_1x2_pct"]["home"] > sm["prob_1x2_pct"]["away"]
    assert sm["ah_home_cover_pct"] is not None


def test_jingcai_ev_positive():
    from jingcai_ev import compute_jingcai_ev
    from jingcai_pick import attach_jingcai_recommendation

    jc = {"has_sp": True, "sp_home": 2.20, "sp_draw": 3.20, "sp_away": 4.50}
    pred = {
        "result_1x2": "home",
        "result_1x2_cn": "主胜",
        "predict_row": {"胜平负": "主胜", "置信度": "高", "竞彩玩法": "胜平负", "竞彩SP": 2.20},
        "odds_snapshot": {"eu_home": 1.70, "eu_draw": 3.5, "eu_away": 5.0},
        "eu_implied": {"fair_home_pct": 58.0, "fair_draw_pct": 24.0, "fair_away_pct": 18.0},
        "quant": {
            "score_model": {"prob_1x2_pct": {"home": 57.0, "draw": 25.0, "away": 18.0}},
        },
    }
    attach_jingcai_recommendation(pred, jc)
    ev = compute_jingcai_ev(pred)
    assert ev is not None
    assert ev["jingcai_sp"] == 2.20
    assert ev["ev_per_unit"] > 0


def test_elo_update():
    from elo_ratings import apply_finished_results, expected_score, match_elo_context

    ratings = apply_finished_results([
        {"home": "巴西", "away": "阿根廷", "home_score": 2, "away_score": 1},
    ])
    assert "巴西" in ratings
    ctx = match_elo_context("巴西", "阿根廷", ratings=ratings)
    assert ctx["home_elo"] >= ctx["away_elo"]
    assert 0 < expected_score(ctx["home_elo"], ctx["away_elo"]) < 1


def test_group_mc_simulate():
    from group_mc import simulate_group_outcomes

    out = simulate_group_outcomes(
        "A",
        current_standings=[
            {"team": "墨西哥", "played": 1, "points": 3, "gd": 1, "gf": 2, "ga": 1, "won": 1, "drawn": 0, "lost": 0},
            {"team": "韩国", "played": 1, "points": 3, "gd": 1, "gf": 2, "ga": 1, "won": 1, "drawn": 0, "lost": 0},
            {"team": "捷克", "played": 1, "points": 0, "gd": -1, "gf": 1, "ga": 2, "won": 0, "drawn": 0, "lost": 1},
            {"team": "南非", "played": 1, "points": 0, "gd": -1, "gf": 1, "ga": 2, "won": 0, "drawn": 0, "lost": 1},
        ],
        n_sims=200,
    )
    assert out["group"] == "A"
    assert len(out["teams"]) == 4
    assert abs(sum(t["p_top2_pct"] + t["p_best3_pct"] + t["p_out_pct"] for t in out["teams"]) - 400) < 5


def test_attach_quant_analysis_match_odds():
    from parser import MatchOdds
    from quant_analytics import attach_quant_analysis

    mo = MatchOdds(
        "墨西哥 vs 韩国", -0.5, 0.9, 0.95, -0.25, 0.88, 0.92,
        2.1, 3.2, 3.5, 2.0, 3.3, 3.6,
    )
    pred = {"match": mo.match_name, "result_1x2": "home"}
    attach_quant_analysis(pred, cur=mo)
    assert pred.get("quant", {}).get("score_model")


def test_attach_quant_analysis():
    from jingcai_pick import attach_jingcai_recommendation
    from quant_analytics import attach_quant_analysis

    jc = {"has_sp": True, "sp_home": 2.05, "sp_draw": 3.10, "sp_away": 3.20}
    pred = {
        "match": "墨西哥 vs 韩国",
        "result_1x2": "home",
        "result_1x2_cn": "主胜",
        "predict_row": {"胜平负": "主胜", "置信度": "中", "竞彩玩法": "胜平负", "竞彩SP": 2.05},
        "likely_scores": ["1-0", "2-1"],
        "odds_snapshot": {"eu_home": 2.10, "eu_draw": 3.20, "eu_away": 3.40, "ah_line": -0.25},
    }
    attach_jingcai_recommendation(pred, jc)
    attach_quant_analysis(pred)
    assert pred.get("quant")
    assert pred["quant"].get("score_model")
    assert pred["quant"].get("elo")
    from product_focus import score_prediction_enabled

    if score_prediction_enabled():
        assert pred.get("model_likely_scores")
    else:
        assert not pred.get("model_likely_scores")
        assert pred["quant"]["score_model"].get("prob_1x2_pct")


def test_score_recommendation_module():
    from product_focus import score_prediction_enabled
    from score_recommend import attach_score_recommendation, build_score_recommendation

    if not score_prediction_enabled():
        sr = build_score_recommendation({"result_1x2": "home"})
        assert sr.get("disabled") is True
        pred = {"result_1x2": "home"}
        attach_score_recommendation(pred)
        assert "score_recommend" not in pred or pred.get("score_recommend", {}).get("disabled")
        return

    pred = {
        "match": "荷兰 vs 瑞典",
        "fixture_id": "1359204",
        "result_1x2": "home",
        "result_1x2_cn": "主胜",
        "confidence_cn": "中",
        "over_under_cn": "大2.5",
        "likely_scores": ["2-1", "2-0", "1-0"],
        "likely_scores_detail": ["2-1(14.8%)", "2-0(12.1%)", "1-0(9.5%)"],
        "model_likely_scores": ["2-0", "1-0", "2-1"],
        "model_likely_scores_detail": ["2-0(13.6%)", "1-0(8.9%)", "2-1(6.1%)"],
        "quant": {
            "score_model": {
                "lambda_home": 1.45,
                "lambda_away": 0.92,
                "avg_total_goals": 2.37,
                "prob_1x2_pct": {"home": 56.5, "draw": 22.1, "away": 21.4},
                "stretch_scores": [{"score": "3-1"}],
            }
        },
    }
    sr = build_score_recommendation(pred)
    assert sr["ok"] is True
    assert len(sr["primary"]) == 3
    assert sr["primary"][0]["score"] in {"2-1", "2-0", "1-0"}
    assert sr["pick_1x2_cn"] == "主胜"
    attach_score_recommendation(pred)
    assert pred["score_recommend"]["headline"]


def test_parse_fulltime_score_not_halftime():
    from bs4 import BeautifulSoup
    from live_scores_500 import _parse_score_from_tr, align_score_to_fixture, LiveScore

    html = """
    <tr>
      <td>世界杯</td>
      <td class="teamvs">
        <span class="score">2 - 0</span>
        <span class="score2">半场：1-0</span>
      </td>
      <td>完</td>
    </tr>
    """
    tr = BeautifulSoup(html, "html.parser").find("tr")
    h, a, txt = _parse_score_from_tr(tr)
    assert (h, a, txt) == (2, 0, "2-0")

    row_html = """
    <tr>
      <td>世界杯</td>
      <td>墨西哥</td>
      <td>南非</td>
      <td>半场：1-0</td>
      <td>2-0</td>
      <td>完</td>
    </tr>
    """
    tr2 = BeautifulSoup(row_html, "html.parser").find("tr")
    h2, a2, txt2 = _parse_score_from_tr(tr2)
    assert (h2, a2, txt2) == (2, 0, "2-0")

    score = LiveScore("1", 0, 2, "0-2", home_name="南非", away_name="墨西哥")
    aligned = align_score_to_fixture(score, {
        "home_team": "墨西哥",
        "away_team": "南非",
        "match_name": "墨西哥VS南非",
    })
    assert aligned.score_text == "2-0"
    assert aligned.home_score == 2 and aligned.away_score == 0


def test_eu_ah_divergence_scoring():
    from eu_ah_divergence import analyze_eu_ah_divergence

    # 欧赔支持主让0.75，实际仅主让0.25 → 巨大浅盘分歧
    shallow = analyze_eu_ah_divergence({
        "eu_home": 1.55, "eu_draw": 4.0, "eu_away": 5.5,
        "ah_line": -0.25,
        "eu_open_home": 1.60, "eu_open_draw": 4.0, "eu_open_away": 5.2,
        "ah_open_line": -0.5,
    }, fixture_id="1", match="测试A")
    assert shallow is not None
    assert shallow.consistency == "ah_shallow"
    assert shallow.divergence_score >= 45

    aligned = analyze_eu_ah_divergence({
        "eu_home": 2.10, "eu_draw": 3.20, "eu_away": 3.40,
        "ah_line": -0.25,
    }, fixture_id="2", match="测试B")
    assert aligned is not None
    assert aligned.consistency == "aligned"
    assert aligned.divergence_score < 45


def test_ai_config_and_profiles():
    from ai_config import list_provider_entries, load_raw_config, public_config_summary
    from ai_profiles import get_profile_by_id, load_profiles

    cfg = load_raw_config()
    assert cfg.get("primary_id")
    assert isinstance(cfg.get("providers"), list)
    summary = public_config_summary()
    assert "predict_mode" in summary
    chat_providers = list_provider_entries(cfg, role="chat", configured_only=False)
    assert any(p["id"] == "deepseek" for p in chat_providers)

    profiles = load_profiles(dual=False, role="predict")
    assert isinstance(profiles, list)

    prof = get_profile_by_id("deepseek")
    if prof and prof.resolve_api_key():
        assert prof.provider_id == "deepseek"

    errors = __import__("ai_config", fromlist=["validate_config_patch"]).validate_config_patch(
        {"predict_mode": "invalid"}
    )
    assert errors

    editable = __import__(
        "ai_config", fromlist=["editable_config_summary"]
    ).editable_config_summary()
    assert editable.get("providers")
    assert all("api_key" not in p for p in editable["providers"])

    from scripts._entry import main

    assert main(["version"]) == 0


def test_analysis_rules_and_signals():
    from analysis.rules import MIN_SAMPLES_FOR_PICK, build_recommendation
    from analysis.signals import analyze_control, analyze_traps, build_market_signals

    assert MIN_SAMPLES_FOR_PICK >= 1
    cur = {
        "match_name": "测试A vs 测试B",
        "ah_open_line": -0.5,
        "ah_line": -0.75,
        "ah_open_home_water": 0.95,
        "ah_home_water": 0.88,
        "ah_open_away_water": 0.93,
        "ah_away_water": 0.98,
        "eu_open_home": 2.0,
        "eu_open_draw": 3.3,
        "eu_open_away": 3.8,
        "eu_home": 1.85,
        "eu_draw": 3.4,
        "eu_away": 4.2,
    }
    sig = build_market_signals(cur)
    assert sig.bias_1x2
    ctrl = analyze_control(cur)
    assert ctrl.level in ("low", "medium", "high")
    trap = analyze_traps(cur, intensity=ctrl.intensity, level=ctrl.level)
    assert trap.penalties
    payload = {
        "current": cur,
        "stats": {"count": 0},
        "eu_stats": {"count": 0},
        "open_stats": {"count": 0},
        "open_eu_stats": {"count": 0},
    }
    rec = build_recommendation(payload)
    assert rec.insufficient_data


def test_open_prob_summary_pct():
    from analysis.rules.engine import _open_prob_summary

    cn, txt = _open_prob_summary(
        {"count": 100, "home_win_rate": 0.5, "draw_rate": 0.25, "away_win_rate": 0.25},
        {"count": 100, "home_win_rate": 0.5, "draw_rate": 0.25, "away_win_rate": 0.25},
    )
    assert cn == "主胜"
    assert "50.0%" in txt


def test_analysis_registry():
    from analysis.registry import enrichment_steps, load_raw_config, public_config_summary, quant_steps

    cfg = load_raw_config()
    assert cfg.get("version") == 1
    assert "quant" in enrichment_steps("default")
    assert quant_steps() == ("poisson", "elo", "ev", "mc")
    summary = public_config_summary()
    assert "enrichment_default" in summary


def test_analysis_pipeline_modules():
    from analysis.pipeline import DEFAULT_STEPS, enrich_prediction
    from analysis.registry import enrichment_steps
    from analysis.quant.bundle import run_quant_analysis
    from core.context import EnrichmentContext

    assert "quant" in DEFAULT_STEPS
    assert enrichment_steps("reuse") == ("jingcai", "quant")

    pred = {"match": "A vs B", "result_1x2": "home"}
    enrich_prediction(
        EnrichmentContext(pred=pred, poll_meta={"jingcai": {}}),
        steps=enrichment_steps("reuse"),
    )
    run_quant_analysis(
        {
            "match": "巴西 vs 阿根廷",
            "result_1x2": "home",
            "odds_snapshot": {"eu_home": 2.1, "eu_draw": 3.2, "eu_away": 3.5},
        }
    )


def test_analysis_p1_modules():
    from analysis.ai import run_one_match
    from analysis.ai.deep import has_prior_ai_analysis
    from analysis.signals.eu_ah_divergence import analyze_eu_ah_divergence
    from analysis.tournament import build_match_knockout_context, rank_best_third_places
    from analysis.tournament.group_stage import MATCH_TYPES

    assert callable(run_one_match)
    assert has_prior_ai_analysis({"recommendation_source": "ai_expert"}) is True
    assert has_prior_ai_analysis(
        {"recommendation_source": "rule_engine"},
        [{"analyses": {"deepseek": {"label": "DS", "result_1x2_cn": "主胜"}}}],
    ) is True
    assert has_prior_ai_analysis(
        {"recommendation_source": "rule_engine"},
        index={"timeline": [{"pick": {"recommendation_source": "ai_dual"}}]},
    ) is True
    assert has_prior_ai_analysis({"recommendation_source": "rule_engine"}) is False
    assert "must_win" in MATCH_TYPES
    assert callable(rank_best_third_places)
    div = analyze_eu_ah_divergence(
        {
            "eu_home": 1.55,
            "eu_draw": 4.0,
            "eu_away": 5.5,
            "ah_line": -0.5,
            "eu_open_home": 1.6,
            "eu_open_draw": 3.9,
            "eu_open_away": 5.0,
            "ah_open_line": -1.0,
        },
        fixture_id="1",
        match="测试",
    )
    assert div is not None
    ctx = build_match_knockout_context("墨西哥 vs 南非")
    assert ctx is None or isinstance(ctx, dict)


def test_api_app():
    pytest = __import__("pytest")
    fastapi = pytest.importorskip("fastapi")
    httpx = pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from apps.api.main import create_app

    app = create_app(ROOT / "output" / "service", within_days=7)
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json().get("ok") is True
    r2 = client.get("/v1/analysis/config")
    assert r2.status_code == 200
    assert "enrichment_default" in r2.json()


def test_buy_tier_classification():
    from jingcai_tier import TIER_A, TIER_B, TIER_C, attach_buy_tier, compute_buy_tier

    def _pred(**kw):
        base = {
            "confidence_cn": "中",
            "reference_result_1x2_cn": "主胜",
            "open_result_1x2_cn": "主胜",
            "alert_tags": [],
            "jingcai_divergence": {},
            "predict_row": {"置信度": "中", "初盘倾向": "主胜", "赛果预测": "主胜"},
            "jingcai_pick_info": {
                "jingcai_market": "sp",
                "jingcai_market_label": "胜平负",
                "jingcai_pick": "home",
                "jingcai_pick_display": "主胜",
                "jingcai_sp": 1.85,
            },
            "jingcai_snapshot": {"has_sp": True, "sp_home": 1.85, "sp_draw": 3.2, "sp_away": 4.0},
        }
        base.update(kw)
        return attach_buy_tier(base)

    a = _pred()
    assert a["buy_tier"] == TIER_A
    assert a["parlay_eligible"] is True
    assert a["predict_row"]["购买档位"] == "可串"

    b = _pred(
        confidence_cn="低",
        predict_row={"置信度": "低", "初盘倾向": "主胜", "赛果预测": "主胜"},
    )
    assert b["buy_tier"] == TIER_B
    assert b["parlay_eligible"] is False

    c = _pred(
        alert_tags=["竞彩·参考分歧"],
        jingcai_divergence=None,
        jingcai_pick_info={
            "jingcai_market": "sp",
            "jingcai_market_label": "胜平负",
            "jingcai_pick": "draw",
            "jingcai_pick_display": "平局",
            "jingcai_sp": 3.1,
        },
        open_result_1x2_cn="主胜",
        reference_result_1x2_cn="主胜",
        predict_row={
            "置信度": "低", "初盘倾向": "主胜", "赛果预测": "主胜", "竞彩推荐": "平局",
        },
    )
    assert c["buy_tier"] == TIER_C
    assert c["parlay_eligible"] is False

    no_jc = compute_buy_tier({"predict_row": {}, "jingcai_pick_info": {"jingcai_market": "none"}})
    assert no_jc["buy_tier"] == TIER_C


def test_buy_tier_purchase_win_rate():
    from worldcup_analytics import compute_accuracy_report

    records = [
        {"pick_jingcai_cn": "主胜", "hit_1x2": True, "buy_tier": "A", "buy_tier_cn": "可串"},
        {"pick_jingcai_cn": "主胜", "hit_1x2": False, "buy_tier": "A", "buy_tier_cn": "可串"},
        {"pick_jingcai_cn": "平局", "hit_1x2": True, "buy_tier": "B", "buy_tier_cn": "可单关"},
        {"pick_jingcai_cn": "客胜", "hit_1x2": False, "buy_tier": "C", "buy_tier_cn": "仅参考"},
    ]
    acc = compute_accuracy_report(records)
    by = acc["by_buy_tier"]
    assert by["A"]["total"] == 2
    assert by["A"]["hit"] == 1
    assert by["A"]["rate_pct"] == 50.0
    assert by["B"]["rate_pct"] == 100.0
    assert by["C"]["rate_pct"] == 0.0
    purchase = acc["purchase_jingcai"]
    assert purchase["judged"] == 4
    assert purchase["hit"] == 2
    assert purchase["rate_pct"] == 50.0
    assert purchase["tier_a"]["total"] == 2


def test_recommendation_review_builder():
    from recommendation_review import _compare_summary, build_recommendation_review

    assert "✓" in _compare_summary(pick_cn="主胜", result_cn="主胜", hit=True)
    assert "✗" in _compare_summary(pick_cn="平局", result_cn="主胜", hit=False)

    root = ROOT / "output" / "service"
    if not root.is_dir():
        pytest.skip("no service output")
    report = build_recommendation_review(root)
    assert report.get("total_settled", 0) >= 0
    if report.get("records"):
        row = report["records"][0]
        assert "pick_jingcai_cn" in row
        assert "compare_summary" in row


def test_sweet_spot_analysis():
    from accuracy_pick import (
        attach_accuracy_pick,
        build_sweet_spot_analysis,
        evaluate_accuracy_pick,
        sp_in_sweet_spot,
    )

    assert sp_in_sweet_spot(1.50) is True
    assert sp_in_sweet_spot(1.35) is True
    assert sp_in_sweet_spot(1.29) is False
    assert sp_in_sweet_spot(1.70) is False

    pred = {
        "fixture_id": "999",
        "match": "A vs B",
        "predict_row": {
            "比赛": "A vs B",
            "赛果预测": "主胜",
            "初盘倾向": "主胜",
            "置信度": "高",
            "竞彩SP": 1.48,
            "竞彩推荐": "主胜",
        },
        "reference_result_1x2_cn": "主胜",
        "open_result_1x2_cn": "主胜",
        "confidence_cn": "高",
        "control_level_cn": "低",
        "risk_level_cn": "常规",
        "buy_tier": "A",
        "jingcai_pick_info": {
            "jingcai_pick": "home",
            "jingcai_market": "sp",
            "jingcai_sp": 1.48,
            "jingcai_pick_cn": "主胜",
            "jingcai_pick_display": "主胜",
        },
        "jingcai_snapshot": {"sp_home": 1.48, "sp_draw": 3.2, "sp_away": 4.5},
        "eu_implied": {"fair_home_pct": 58.0, "fair_draw_pct": 24.0, "fair_away_pct": 18.0},
    }

    info = evaluate_accuracy_pick(pred)
    assert info["sweet_spot"] is True
    assert info["accuracy_grade"] == "稳胆甜区"

    sa = build_sweet_spot_analysis(pred)
    assert sa["ok"] is True
    assert sa["band"] == "in_sweet"
    assert sa["checklist_passed"] >= 7
    assert sa["sp_implied_pct"] == round(100 / 1.48, 1)
    assert sa["model_prob_pct"] == 58.0

    attach_accuracy_pick(pred)
    assert pred.get("sweet_spot_analysis", {}).get("sweet_spot") is True

    high_sp = dict(pred)
    high_sp["jingcai_pick_info"] = dict(pred["jingcai_pick_info"], jingcai_sp=1.85)
    high_sp["predict_row"] = dict(pred["predict_row"], 竞彩SP=1.85)
    high_sp["jingcai_snapshot"] = dict(pred["jingcai_snapshot"], sp_home=1.85)
    high_sp.pop("accuracy_pick", None)
    high_sp.pop("sweet_spot_analysis", None)
    sa_high = build_sweet_spot_analysis(high_sp)
    assert sa_high["band"] == "above_sweet"
    assert sa_high["sweet_spot"] is False


def test_parse_row_status_live():
    from download_500 import _parse_row_status
    from bs4 import BeautifulSoup

    html_up = "<tr><td>周六036</td><td>世界杯</td><td>第2轮</td><td>06-21 12:00</td><td>未</td></tr>"
    html_live = (
        "<tr><td>周六035</td><td>世界杯</td><td>第2轮</td><td>06-21 08:00</td>"
        "<td>厄瓜多尔</td><td>0 - 0</td></tr>"
    )
    html_done = (
        "<tr><td>周六033</td><td>世界杯</td><td>第2轮</td><td>06-21 01:00</td>"
        "<td>完</td><td>荷兰</td><td>2 - 0</td><td>胜</td></tr>"
    )
    up = _parse_row_status(BeautifulSoup(html_up, "html.parser").find("tr"))
    live = _parse_row_status(BeautifulSoup(html_live, "html.parser").find("tr"))
    done = _parse_row_status(BeautifulSoup(html_done, "html.parser").find("tr"))
    assert up.get("phase") == "upcoming"
    assert live.get("phase") == "live"
    assert live.get("score") == "0-0"
    assert done.get("phase") == "finished"
    assert done.get("score") == "2-0"


def test_wc_status4_not_finished():
    from wc_standings_fetch import GroupFixture, STATUS_FINISHED

    fx = GroupFixture(
        fixture_id="1359237",
        group="A",
        round=2,
        kickoff="2026-06-21 08:00",
        home="厄瓜多尔",
        away="库拉索",
        home_score=0,
        away_score=0,
        status=4,
    )
    assert 4 not in STATUS_FINISHED
    assert fx.is_finished is False
    assert fx.is_live is True


def test_similarity_ai_payload():
    from similarity_ai import build_similarity_ai_payload, get_similarity_block

    pred = {
        "fixture_id": "123",
        "match": "A vs B",
        "odds_snapshot": {
            "ah_open_line": 0.75,
            "ah_open_home_water": 0.91,
            "ah_open_away_water": 0.89,
            "eu_open_home": 4.2,
            "eu_open_draw": 3.3,
            "eu_open_away": 1.95,
            "ah_line": 0.5,
            "ah_home_water": 0.88,
            "ah_away_water": 0.92,
            "eu_home": 3.8,
            "eu_draw": 3.4,
            "eu_away": 2.0,
        },
        "similarity_analysis": {
            "open": [{
                "source": "open_ah",
                "title": "初盘亚盘相似",
                "count": 25,
                "rate_text": "主胜 12.0% / 平 16.0% / 客胜 72.0%",
                "samples": [{"date": "2020-01-01", "match": "X vs Y", "score": "0-1"}],
            }],
            "live": [{
                "source": "live_eu",
                "title": "实时欧赔 vs 历史终盘相似",
                "count": 1012,
                "rate_text": "主胜 21.6% / 平 26.4% / 客胜 52.0%",
                "samples": [],
            }],
        },
        "result_1x2_cn": "客胜",
        "predict_row": {"赛果预测": "客胜", "亚盘": "下盘", "推荐比分": "0-1、1-2"},
    }
    block = get_similarity_block(pred, "live_eu")
    assert block and block["count"] == 1012
    payload = build_similarity_ai_payload(pred, "live_eu")
    assert payload["section"] == "实时欧赔 vs 历史终盘相似"
    assert payload["sample_stats"]["count"] == 1012
    assert payload["current_odds"]["european"]["away"] == 2.0
    assert payload["baseline_recommendation"]["final_pick_cn"]


def test_settlement_status_preview():
    from match_settlement import build_settlement_status
    from serve import _parse_settle_params

    status = build_settlement_status("output/service")
    assert "pending_count" in status
    assert "usage" in status
    resettle, fids = _parse_settle_params(
        {"resettle": ["1"], "fixture_id": ["1359237", "1359238"]},
        {"fixture_ids": ["1359239"]},
    )
    assert resettle is True
    assert fids == ["1359237", "1359238", "1359239"]


def test_similarity_ai_button_in_html():
    from web_ui import _build_similarity_html

    pred = {
        "similarity_analysis": {
            "open": [{"source": "open_ah", "title": "初盘亚盘相似", "count": 10, "rate_text": "x", "samples": []}],
            "live": [{"source": "live_ah", "title": "实时亚盘 vs 历史终盘相似", "count": 20, "rate_text": "y", "samples": []}],
        }
    }
    html = _build_similarity_html(pred, fixture_id="999", output_root=Path("/tmp/nope"))
    assert "aiSimilarityAnalyze('999', 'open_ah'" in html
    assert "aiSimilarityAnalyze('999', 'live_ah'" in html
    assert "AI盘口解读" in html

