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
