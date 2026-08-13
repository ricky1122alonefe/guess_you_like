"""Tests for analysis.market.market_attitude."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from analysis.market import market_attitude as ma


_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _features(
    *,
    eu_home_delta: float | None = 0.0,
    eu_draw_delta: float | None = 0.0,
    eu_away_delta: float | None = 0.0,
    ah_line_delta: float | None = 0.0,
    ah_home_water_delta: float | None = 0.0,
    ah_away_water_delta: float | None = 0.0,
    sp_home_delta: float | None = 0.0,
    sp_draw_delta: float | None = 0.0,
    sp_away_delta: float | None = 0.0,
    bf_volume_delta: float | None = 0.0,
    bf_home_pct_delta: float | None = 0.0,
    eu_sticky: bool = True,
    has_valid_signal: bool = False,
    ticks_n: int = 1,
) -> dict:
    return {
        "external_id": "test",
        "eu_home_delta": eu_home_delta,
        "eu_draw_delta": eu_draw_delta,
        "eu_away_delta": eu_away_delta,
        "ah_line_delta": ah_line_delta,
        "ah_home_water_delta": ah_home_water_delta,
        "ah_away_water_delta": ah_away_water_delta,
        "sp_home_delta": sp_home_delta,
        "sp_draw_delta": sp_draw_delta,
        "sp_away_delta": sp_away_delta,
        "bf_volume_delta": bf_volume_delta,
        "bf_home_pct_delta": bf_home_pct_delta,
        "eu_sticky": eu_sticky,
        "has_valid_signal": has_valid_signal,
        "ticks_n": ticks_n,
    }


def test_classify_attitude_line_up_and_home_water_down():
    """欧不动 + 亚升盘 + 主水降 → 升盘加压 + 追热主，非信号不足。"""
    f = _features(
        eu_home_delta=0.01,
        eu_away_delta=-0.01,
        ah_line_delta=-0.5,
        ah_home_water_delta=-0.08,
        ah_away_water_delta=0.05,
        eu_sticky=True,
        has_valid_signal=True,
    )
    att = ma.classify_attitude(f)
    assert "升盘加压" in att["labels"]
    assert "资金追热" in att["labels"]
    assert "欧粘亚动" in att["labels"]
    assert "信号不足" not in att["labels"]
    assert att["supported_side"] == "home"
    assert att["strength"] in ("mid", "strong")
    assert "亚盘主让升" in att["narrative"]


def test_classify_attitude_no_signal():
    """全平 → 信号不足。"""
    f = _features()
    att = ma.classify_attitude(f)
    assert att["labels"] == ["信号不足"]
    assert att["supported_side"] == "none"
    assert att["strength"] == "weak"
    assert "信号不足" in att["narrative"]


def test_classify_attitude_water_inversion_favors_away():
    """同线主水升客水降 → 水位对倒，偏客。"""
    f = _features(
        ah_line_delta=0.0,
        ah_home_water_delta=0.07,
        ah_away_water_delta=-0.06,
        has_valid_signal=True,
    )
    att = ma.classify_attitude(f)
    assert "水位对倒" in att["labels"]
    assert att["supported_side"] == "away"


def test_classify_attitude_sp_only():
    """仅 SP 主降，欧/亚不动 → 资金追热(主) weak。"""
    f = _features(
        sp_home_delta=-0.05,
        eu_sticky=True,
        has_valid_signal=True,
    )
    att = ma.classify_attitude(f)
    assert "资金追热" in att["labels"]
    assert att["supported_side"] == "home"
    assert att["strength"] == "weak"


def test_classify_attitude_betfair_volume_no_direction():
    """仅 bf 量涨无方向 → 信号不足或弱。"""
    f = _features(
        bf_volume_delta=1000.0,
        bf_home_pct_delta=0.02,
        has_valid_signal=True,
    )
    att = ma.classify_attitude(f)
    # 没有方向明确的 bf 占比变化时，不应单独给出 supported_side
    assert att["supported_side"] in ("none",)


def test_dirty_book_open_does_not_poison_eu_delta():
    """book_open=0.9 类脏欧开盘不得影响 eu_delta。

    lifecycle 层已隔离 book_open；本模块只计算 opening/closing 的差。
    """
    opening = {
        "book_open": 0.9,  # 脏字段，应被忽略
        "eu_home": 1.90,
        "eu_draw": 3.40,
        "eu_away": 4.20,
        "ah_line": -0.25,
        "ah_home_water": 0.92,
        "ah_away_water": 0.96,
        "captured_at": "2026-08-01T10:00:00+00:00",
    }
    closing = {
        "eu_home": 1.90,
        "eu_draw": 3.40,
        "eu_away": 4.20,
        "ah_line": -0.5,
        "ah_home_water": 0.86,
        "ah_away_water": 1.02,
        "captured_at": "2026-08-01T19:00:00+00:00",
    }
    assert ma._delta(opening, closing, "eu_home") == pytest.approx(0.0)
    assert ma._delta_line(opening, closing, "ah_line") == pytest.approx(-0.25)


def test_apply_calibration_reliable_threshold():
    """校准缓存中 n<min_n 的桶应标 unreliable。"""
    with tempfile.TemporaryDirectory() as tmp:
        cache_file = Path(tmp) / "market_attitude_calib.json"
        with mock.patch.object(ma, "CACHE_FILE", cache_file):
            cache_file.write_text(
                json.dumps(
                    {
                        "buckets": [
                            {"label": "资金追热", "supported_side": "home", "n": 25, "hit_rate": 0.52, "draw_rate": 0.20},
                            {"label": "信号不足", "supported_side": "none", "n": 5, "hit_rate": 0.30, "draw_rate": 0.25},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            att = {"labels": ["资金追热"], "supported_side": "home"}
            cal = ma.apply_calibration(att, min_n=20)
            assert cal["reliable"] is True
            assert cal["n"] == 25

            att2 = {"labels": ["信号不足"], "supported_side": "none"}
            cal2 = ma.apply_calibration(att2, min_n=20)
            assert cal2["reliable"] is False
            assert cal2["n"] == 5


def test_bucket_label_order():
    """标签归桶应优先取主要标签。"""
    assert ma._primary_bucket_label(["资金追热", "欧粘亚动"]) == "资金追热"
    assert ma._primary_bucket_label(["升盘加压", "资金追热"]) == "升盘加压"
    assert ma._primary_bucket_label(["信号不足"]) == "信号不足"


@pytest.mark.skipif(
    not (_PROJECT_ROOT / ".env").exists() and not (_PROJECT_ROOT / "config.py").exists(),
    reason="needs project env or config",
)
def test_build_move_features_with_db():
    """任选 ticks>=5 的 fixture，features 非空且 attitude 有 narrative。"""
    from db.connection import cursor

    with cursor() as cur:
        cur.execute(
            """
            SELECT f.external_id, COUNT(*) AS n
            FROM odds_ticks t
            JOIN fixtures f ON f.id = t.fixture_id
            WHERE f.source = '500'
            GROUP BY f.external_id
            HAVING COUNT(*) >= 5
            ORDER BY COUNT(*) DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()
    if not row:
        pytest.skip("no fixture with enough ticks in DB")
    fid = str(row["external_id"])
    features = ma.build_move_features(fid)
    assert "missing" not in features
    assert features["ticks_n"] >= 5
    attitude = ma.classify_attitude(features)
    assert attitude["narrative"]
    assert isinstance(attitude["labels"], list)


def test_forecast_engine_uses_market_attitude():
    """forecast() 把 market_attitude 写进 factors，并在 reasons 中给出市场态度句。"""
    from analysis.result_forecast.engine import forecast

    context = {
        "european": {
            "implied": {"home": 0.40, "draw": 0.28, "away": 0.32},
            "best": "home",
        },
        "asian": {"line": -0.5, "favored": "home", "home_water": 0.90, "away_water": 0.98},
        "betfair": {
            "volume_total": 5000,
            "volume_pct": {"home": 0.45, "draw": 0.25, "away": 0.30},
            "hot": "home",
        },
        "market_attitude": {
            "features": {
                "external_id": "999",
                "eu_home_delta": 0.01,
                "eu_away_delta": -0.01,
                "ah_line_delta": -0.5,
                "ah_home_water_delta": -0.08,
                "ah_away_water_delta": 0.05,
                "eu_sticky": True,
                "has_valid_signal": True,
                "ticks_n": 12,
            },
            "attitude": ma.classify_attitude(
                {
                    "external_id": "999",
                    "eu_home_delta": 0.01,
                    "eu_away_delta": -0.01,
                    "ah_line_delta": -0.5,
                    "ah_home_water_delta": -0.08,
                    "ah_away_water_delta": 0.05,
                    "eu_sticky": True,
                    "has_valid_signal": True,
                    "ticks_n": 12,
                }
            ),
        },
    }
    result = forecast(context)
    assert "market_attitude" in result["factors"]
    ma_reasons = [r for r in result["reasons"] if "市场态度" in r]
    assert ma_reasons
    assert result["factors"]["market_attitude"]["attitude"]["supported_side"] == "home"
