"""详情页/attach 时补算 quant.score_model（泊松比分矩阵），供大小球轨使用。

约束：
- 无欧赔时诚实 missing，不编 λ
- buyable 仍 False；绝不因大小球 flip 1X2
"""
import pytest

from analysis.market.ou_lane import attach_ou_lane, build_ou_lane
from analysis.pipeline import backfill_score_model, ensure_quant

_EU = {"eu_home": 2.06, "eu_draw": 2.98, "eu_away": 3.84}


def _pred_with_elo_only(**extra) -> dict:
    pred = {
        "fixture_id": "1427956",
        "home_team": "主队",
        "away_team": "客队",
        "quant": {"elo": {"elo_home": 1500.0, "elo_away": 1480.0, "prob_home": 0.42}},
    }
    pred.update(extra)
    return pred


_EU_BOOKS_MAJOR = [
    {"label": "威廉", "home": 2.06, "draw": 2.98, "away": 3.84},
    {"label": "平博", "home": 2.05, "draw": 3.00, "away": 3.90},
]


def test_backfill_falls_back_to_major_mean_when_snapshot_missing():
    """snapshot 无 eu_* → 回退 odds_snapshot.eu_books_major 均值。"""
    pred = _pred_with_elo_only(odds_snapshot={"eu_books_major": _EU_BOOKS_MAJOR})
    ensure_quant(pred)
    sm = (pred.get("quant") or {}).get("score_model")
    assert sm, "有 major 均值时应补写 score_model"
    assert sm.get("lambda_home", 0) > 0
    assert sm.get("lambda_away", 0) > 0
    attach_ou_lane(pred)
    ou = (pred.get("market_lanes") or {}).get("ou") or {}
    assert ou.get("missing") is False
    assert (ou.get("p_over") or 0) > 0
    assert "P(大2.5)≈" in " ".join(ou.get("reasons") or [])
    assert ou.get("buyable") is False


def test_backfill_falls_back_when_snapshot_odds_are_zero():
    """snapshot eu_* 为 0/缺失 → 回退 major 均值，不把 0 当有效欧赔。"""
    pred = _pred_with_elo_only(
        odds_snapshot={"eu_home": 0, "eu_draw": 0, "eu_away": 0, "eu_books_major": _EU_BOOKS_MAJOR}
    )
    ensure_quant(pred)
    sm = (pred.get("quant") or {}).get("score_model")
    assert sm and sm.get("lambda_home", 0) > 0


def test_backfill_no_major_books_keeps_honest_missing():
    """无欧赔也无 major → 诚实 missing，不编 λ。"""
    pred = _pred_with_elo_only(fixture_id="999999999", odds_snapshot={"eu_home": None})
    ensure_quant(pred)
    assert not (pred.get("quant") or {}).get("score_model")
    attach_ou_lane(pred)
    ou = (pred.get("market_lanes") or {}).get("ou") or {}
    assert ou.get("missing") is True
    assert ou.get("buyable") is False


def test_backfill_from_raw_meta_eu_books():
    """raw_meta.eu_books 也可作为 major 来源（与 three_lane 同源）。"""
    pred = _pred_with_elo_only(
        raw_meta={"eu_books": [{"name": "Pinnacle", "home": 2.06, "draw": 2.98, "away": 3.84}]}
    )
    backfill_score_model(pred)
    sm = (pred.get("quant") or {}).get("score_model")
    assert sm and sm.get("lambda_home", 0) > 0


def test_run_quant_analysis_full_path_uses_major_fallback():
    """quant 为空的全量路径同样回退 major 均值。"""
    from analysis.quant.bundle import run_quant_analysis

    pred = _pred_with_elo_only()
    pred.pop("quant", None)
    pred["odds_snapshot"] = {"eu_books_major": _EU_BOOKS_MAJOR}
    run_quant_analysis(pred)
    sm = (pred.get("quant") or {}).get("score_model")
    assert sm and sm.get("lambda_home", 0) > 0


def test_serve_ensure_quant_analysis_backfills_from_major():
    """serve 详情入口：timeline 无欧赔、snapshot 有 major → 回退补写。"""
    serve = pytest.importorskip("serve")
    pred = _pred_with_elo_only(odds_snapshot={"eu_books_major": _EU_BOOKS_MAJOR})
    idx = {"timeline": [{"ts": "2026-08-21 20:00", "odds": {}}]}
    serve._ensure_quant_analysis(pred, idx)
    sm = (pred.get("quant") or {}).get("score_model")
    assert sm and sm.get("lambda_home", 0) > 0


def test_backfill_writes_score_model_when_eu_odds_present():
    pred = _pred_with_elo_only(odds_snapshot=dict(_EU))
    ensure_quant(pred)
    sm = (pred.get("quant") or {}).get("score_model")
    assert sm, "有欧赔时应补写 score_model"
    assert sm.get("lambda_home", 0) > 0
    assert sm.get("lambda_away", 0) > 0
    # 保留已有 elo，不覆盖
    assert pred["quant"]["elo"]["elo_home"] == 1500.0


def test_backfill_no_odds_keeps_honest_missing():
    # 用不存在的 fid，避免命中本地 DB/xls 的 major 数据
    pred = _pred_with_elo_only(fixture_id="999999999")
    ensure_quant(pred)
    assert not (pred.get("quant") or {}).get("score_model"), "无欧赔不得编 λ"
    ou = build_ou_lane(pred)
    assert ou["missing"] is True
    assert "无泊松比分矩阵" in ou["missing_reason"]


def test_ou_lane_shows_p_over_after_backfill():
    pred = _pred_with_elo_only(odds_snapshot=dict(_EU))
    ensure_quant(pred)
    attach_ou_lane(pred)
    ou = (pred.get("market_lanes") or {}).get("ou") or {}
    assert ou.get("missing") is False
    assert (ou.get("p_over") or 0) > 0
    assert "P(大2.5)≈" in " ".join(ou.get("reasons") or [])
    assert ou.get("buyable") is False


def test_ou_lane_never_flips_1x2():
    pred = _pred_with_elo_only(odds_snapshot=dict(_EU), result_1x2="home")
    ensure_quant(pred)
    attach_ou_lane(pred)
    assert pred["result_1x2"] == "home", "大小球轨不得 flip 1X2"
    ou = (pred.get("market_lanes") or {}).get("ou") or {}
    assert ou.get("buyable") is False
    comp = (pred.get("market_lanes") or {}).get("ou_comparison") or {}
    assert comp.get("buyable") is False
    assert comp.get("action") in {"hold", "size_down", "skip"}


def test_backfill_function_direct():
    pred = _pred_with_elo_only(odds_snapshot=dict(_EU))
    backfill_score_model(pred)
    sm = (pred.get("quant") or {}).get("score_model")
    assert sm and sm.get("lambda_home", 0) > 0


def test_ensure_quant_noop_when_score_model_present():
    pred = _pred_with_elo_only(
        odds_snapshot=dict(_EU),
        quant={"elo": {"x": 1}, "score_model": {"lambda_home": 1.23, "lambda_away": 1.01}},
    )
    ensure_quant(pred)
    assert pred["quant"]["score_model"]["lambda_home"] == 1.23, "已有 score_model 不得重算覆盖"


def test_serve_ensure_quant_analysis_backfills_existing_quant():
    """详情页入口：quant 已有（仅 elo）时也必须补 score_model。"""
    serve = pytest.importorskip("serve")
    pred = _pred_with_elo_only()
    idx = {"timeline": [{"ts": "2026-08-21 20:00", "odds": dict(_EU)}]}
    serve._ensure_quant_analysis(pred, idx)
    sm = (pred.get("quant") or {}).get("score_model")
    assert sm, "serve 详情入口应补写 score_model"
    assert sm.get("lambda_home", 0) > 0
    assert pred["quant"]["elo"]["elo_home"] == 1500.0


def test_serve_ensure_quant_analysis_no_odds_honest_missing():
    serve = pytest.importorskip("serve")
    pred = _pred_with_elo_only(fixture_id="999999999")
    idx = {"timeline": []}
    serve._ensure_quant_analysis(pred, idx)
    assert not (pred.get("quant") or {}).get("score_model"), "无欧赔不得编 λ"
