"""Minimal smoke tests — no network, no API keys."""

from __future__ import annotations

import json
from pathlib import Path

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
    assert pred.get("model_likely_scores")
    assert pred["quant"].get("score_model")
    assert pred["quant"].get("elo")


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

    from scripts._entry import main

    assert main(["version"]) == 0

