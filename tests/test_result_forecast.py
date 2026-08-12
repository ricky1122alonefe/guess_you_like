"""T1/T2 测试：五源上下文 + 融合引擎。

不依赖 DB / 外网；用 mock context dict 驱动。
"""
from analysis.result_forecast.context import (
    _extract_asian,
    _extract_betfair,
    _extract_european,
    _extract_history,
    _implied_probs,
    build_result_forecast_context,
)
from analysis.result_forecast.engine import forecast, forecast_for_match


# ============ T1: context 提取 ============

def test_implied_probs():
    """朴素去水：1/odds 归一化。"""
    p = _implied_probs(2.0, 3.0, 4.0)
    # 1/2=0.5, 1/3≈0.333, 1/4=0.25, total≈1.083, p_home≈0.4615
    assert abs(p["home"] - 0.4615) < 0.01
    assert abs(sum(p.values()) - 1.0) < 0.001


def test_extract_european():
    """欧赔提取：赔率 + 隐含概率 + 升降水。"""
    odds = {"eu_home": 2.0, "eu_draw": 3.0, "eu_away": 4.0, "eu_open_home": 2.2, "eu_open_away": 3.8}
    eu = _extract_european(odds)
    assert eu is not None
    assert eu["odds"]["home"] == 2.0
    assert eu["best"] == "home"  # 2.0 最低 = 主胜隐含最高
    assert "降水" in eu["move"]  # 2.0 < 2.2 → 主胜降水


def test_extract_european_missing():
    """缺欧赔 → None。"""
    assert _extract_european({}) is None
    assert _extract_european({"eu_home": None}) is None


def test_extract_asian():
    """亚盘提取：盘口 + 方向。"""
    odds = {"ah_line": 1.0, "ah_home_water": 0.85, "ah_away_water": 0.95,
            "ah_open_line": 0.5, "ah_open_home_water": 0.90}
    asian = _extract_asian(odds)
    assert asian is not None
    assert asian["line"] == 1.0
    assert asian["favored"] == "away"  # line > 0 → 主队受让 → 客队方向
    assert asian["water_move"] == "上盘降水"  # 0.85 < 0.90


def test_extract_betfair():
    """必发提取：成交量 + 资金方向。"""
    odds = {"betfair": {
        "has_data": True,
        "volume_total": 30000000,
        "volume_pct": {"home": 10, "draw": 20, "away": 70},
        "trade_price": {"home": 9.0, "draw": 4.5, "away": 1.5},
    }}
    bf = _extract_betfair(odds)
    assert bf is not None
    assert bf["volume_total"] == 30000000
    assert bf["hot"] == "away"  # 70% 资金在客胜
    assert abs(bf["volume_pct"]["away"] - 0.70) < 0.01


def test_extract_betfair_no_data():
    """无必发数据 → None。"""
    assert _extract_betfair({"betfair": {"has_data": False}}) is None
    assert _extract_betfair({}) is None


def test_extract_history():
    """历史相似提取：1X2 分布。"""
    pred = {"payload": {
        "stats": {"count": 100, "home_win_rate": 0.45, "draw_rate": 0.30, "away_win_rate": 0.25},
        "eu_stats": {"count": 0},
        "open_stats": {"count": 0},
    }}
    hist = _extract_history(pred)
    assert hist is not None
    assert hist["count"] == 100
    assert abs(hist["p"]["home"] - 0.45) < 0.01


def test_extract_history_empty():
    """无历史样本 → None。"""
    assert _extract_history(None) is None
    assert _extract_history({"payload": {"stats": {"count": 0}}}) is None


# ============ T2: 融合引擎 ============

def _full_context():
    """五源齐全的 mock context。"""
    return {
        "fixture_id": "999",
        "match_name": "Test vs Mock",
        "european": {
            "odds": {"home": 2.0, "draw": 3.0, "away": 4.0},
            "implied": {"home": 0.50, "draw": 0.33, "away": 0.17},
            "best": "home",
            "move": "主胜降水",
        },
        "asian": {
            "line": 0.5, "home_water": 0.85, "away_water": 0.95,
            "open_line": 0.25, "favored": "home", "water_move": "上盘降水",
        },
        "betfair": {
            "volume_total": 30000000,
            "volume_pct": {"home": 0.55, "draw": 0.25, "away": 0.20},
            "trade_price": {"home": 1.9, "draw": 3.5, "away": 4.2},
            "hot": "home",
        },
        "history_similar": {
            "count": 100,
            "p": {"home": 0.48, "draw": 0.30, "away": 0.22},
            "source": "open",
        },
        "recent_form": {
            "home": {"label": "Test", "form_str": "WWDLW", "win_rate": 0.6, "goals_for": 8, "goals_against": 4},
            "away": {"label": "Mock", "form_str": "LLDWL", "win_rate": 0.2, "goals_for": 3, "goals_against": 7},
        },
        "missing": [],
    }


def test_forecast_full_context():
    """五源齐全 → 出 pick，概率和=1，reasons 非空。"""
    result = forecast(_full_context())
    assert result["pick"] in ("home", "draw", "away")
    assert result["pick"] != "skip"
    assert abs(result["p_home"] + result["p_draw"] + result["p_away"] - 1.0) < 0.01
    assert len(result["reasons"]) >= 4  # 至少 4 条理由
    assert result["missing"] == []


def test_forecast_missing_betfair():
    """缺必发 → 仍出预测，missing 含 betfair。"""
    ctx = _full_context()
    ctx["betfair"] = None
    ctx["missing"] = ["betfair"]
    result = forecast(ctx)
    assert result["pick"] != "skip"  # 4 源仍够
    assert "betfair" in result["missing"]
    assert any("必发" not in r for r in result["reasons"])  # 必发不进 reasons


def test_forecast_missing_history_and_form():
    """缺历史+战绩 → 3 源仍出预测。"""
    ctx = _full_context()
    ctx["history_similar"] = None
    ctx["recent_form"] = None
    ctx["missing"] = ["history_similar", "recent_form"]
    result = forecast(ctx)
    assert result["pick"] != "skip"
    assert "history_similar" in result["missing"]
    assert "recent_form" in result["missing"]


def test_forecast_no_sources():
    """全部缺失 → skip。"""
    ctx = {
        "fixture_id": "0", "match_name": "",
        "european": None, "asian": None, "betfair": None,
        "history_similar": None, "recent_form": None,
        "missing": ["european", "asian", "betfair", "history_similar", "recent_form"],
    }
    result = forecast(ctx)
    assert result["pick"] == "skip"
    assert result["pick_cn"] == "观望"


def test_forecast_divergence():
    """欧亚分歧 → confidence=low。"""
    ctx = _full_context()
    # 制造分歧：欧赔倾向主胜，亚盘客队让球
    ctx["asian"]["favored"] = "away"
    ctx["asian"]["line"] = -0.5
    ctx["european"]["best"] = "home"
    result = forecast(ctx)
    assert result["confidence"] == "low"
    assert any("分歧" in r for r in result["reasons"])


def test_forecast_factors_present():
    """factors 含全部五源（含 None）。"""
    result = forecast(_full_context())
    for key in ("european", "asian", "betfair", "history_similar", "recent_form"):
        assert key in result["factors"]


def test_forecast_reasons_explainable():
    """reasons 可解释：每条有实质内容（非空话）。"""
    result = forecast(_full_context())
    for r in result["reasons"]:
        assert len(r) > 5  # 不是空话
        # 至少含中文关键词或数据
        assert any(kw in r for kw in ("欧赔", "亚盘", "必发", "历史", "近况", "分歧", "%", "盘", "场"))


# ============ F5: 回落场景测试 ============

def test_f5_timeline_only_eu_ah():
    """F5-1: 只有 timeline eu/ah → 非 skip，missing 可含 betfair/recent。"""
    ctx = build_result_forecast_context(
        "test-fid",
        index={
            "fixture_id": "test-fid",
            "match_name": "A vs B",
            "timeline": [{
                "ts": "2026-08-08 10:00",
                "odds": {
                    "eu_home": 2.0, "eu_draw": 3.0, "eu_away": 4.0,
                    "ah_line": -0.5, "ah_home_water": 0.90, "ah_away_water": 0.95,
                },
            }],
        },
        prediction=None,
    )
    assert ctx["european"] is not None
    assert ctx["asian"] is not None
    assert "betfair" in ctx["missing"]
    result = forecast(ctx)
    assert result["pick"] != "skip"
    assert "european" not in result["missing"]
    assert "asian" not in result["missing"]


def test_f5_pred_snapshot_only():
    """F5-2: 只有 pred.odds_snapshot 欧亚 → 非 skip。"""
    ctx = build_result_forecast_context(
        "test-fid",
        index={"fixture_id": "test-fid", "match_name": "A vs B", "timeline": []},
        prediction={
            "match_name": "A vs B",
            "odds_snapshot": {
                "eu_home": 1.50, "eu_draw": 4.0, "eu_away": 6.0,
                "ah_line": -1.0, "ah_home_water": 0.85, "ah_away_water": 0.95,
                "eu_open_home": 1.60, "eu_open_away": 5.5,
            },
            "similarity_analysis": {
                "open": [{
                    "source": "open_ah",
                    "count": 100,
                    "home_win_rate": 0.60,
                    "draw_rate": 0.25,
                    "away_win_rate": 0.15,
                }],
            },
        },
    )
    assert ctx["european"] is not None
    assert ctx["asian"] is not None
    assert ctx["history_similar"] is not None
    result = forecast(ctx)
    assert result["pick"] != "skip"
    assert result["p_home"] > 0  # 有非零概率


def test_f5_empty_all():
    """F5-3: 空 timeline 空 pred → skip + 明确 missing。"""
    ctx = build_result_forecast_context(
        "test-fid",
        index={"fixture_id": "test-fid", "match_name": "A vs B", "timeline": []},
        prediction=None,
    )
    assert len(ctx["missing"]) == 5
    result = forecast(ctx)
    assert result["pick"] == "skip"


def test_f5_similarity_analysis_no_stats():
    """F5-4: 有 similarity_analysis 无 payload.stats → history 有。"""
    pred = {
        "similarity_analysis": {
            "open": [{
                "source": "open_ah",
                "count": 200,
                "home_win_rate": 0.70,
                "draw_rate": 0.20,
                "away_win_rate": 0.10,
            }],
        },
        # 无 stats / eu_stats / open_stats
    }
    hist = _extract_history(pred)
    assert hist is not None
    assert hist["count"] == 200
    assert abs(hist["p"]["home"] - 0.70) < 0.01


def test_f5_probability_summary_fallback():
    """F5-4b: 有 open_probability_summary 文本 → history 有。"""
    pred = {
        "open_probability_summary": "初盘亚盘+欧赔融合相似 240/407 场：主胜 73.9%、平 16.1%、客胜 10.1%",
        "sample_count": 240,
    }
    hist = _extract_history(pred)
    assert hist is not None
    assert hist["count"] == 407
    assert abs(hist["p"]["home"] - 0.739 / (0.739 + 0.161 + 0.101)) < 0.01


def test_f5_recent_missing_not_skip():
    """F5-5: 缺 recent_form 不应导致 skip（有欧亚即可预测）。"""
    ctx = _full_context()
    ctx["recent_form"] = None
    ctx["missing"] = ["recent_form"]
    result = forecast(ctx)
    assert result["pick"] != "skip"
    assert "recent_form" in result["missing"]


# ============ G5: 北欧/非竞彩场场景 ============

def test_g5_history_only_can_pick():
    """G5: 仅 history_similar（无欧亚必发近况）→ 可 pick，文案含缺盘口提示。"""
    ctx = build_result_forecast_context(
        "g5-fid",
        index={"fixture_id": "g5-fid", "match_name": "A vs B", "timeline": []},
        prediction={
            "match_name": "A vs B",
            "similarity_analysis": {
                "open": [{
                    "source": "open_ah", "count": 55487,
                    "home_win_rate": 0.439, "draw_rate": 0.264, "away_win_rate": 0.297,
                }],
            },
            "odds_snapshot": {"eu_home": 0.0, "eu_draw": 0.0, "eu_away": 0.0, "ah_line": None},
        },
    )
    # 欧亚应 missing（0.0 不算有效赔率）
    assert "european" in ctx["missing"]
    assert "asian" in ctx["missing"]
    # 历史应可用
    assert ctx["history_similar"] is not None
    assert ctx["history_similar"]["count"] == 55487
    # 仍可出预测
    result = forecast(ctx)
    assert result["pick"] != "skip"
    assert result["p_home"] > 0


def test_g5_zero_odds_not_used():
    """G5: odds_snapshot 中 eu_home=0.0 不应被当作有效欧赔。"""
    ctx = build_result_forecast_context(
        "g5-fid",
        index={"fixture_id": "g5-fid", "match_name": "A vs B", "timeline": []},
        prediction={
            "odds_snapshot": {"eu_home": 0.0, "eu_draw": 0.0, "eu_away": 0.0},
        },
    )
    assert ctx["european"] is None
    assert "european" in ctx["missing"]


def test_g5_weights_match_factors():
    """G5: weights 只含真正参与融合的源。"""
    ctx = _full_context()
    ctx["betfair"] = None
    ctx["recent_form"] = None
    ctx["missing"] = ["betfair", "recent_form"]
    result = forecast(ctx)
    # weights 不应含 betfair / recent_form
    assert "betfair" not in result["weights"]
    assert "recent_form" not in result["weights"]
    # weights 应含 european / asian / history_similar
    assert "european" in result["weights"]
    assert "history_similar" in result["weights"]


def test_forecast_reasons_cover_opening_form_similar():
    """reasons 至少覆盖：开盘vs即盘、战绩、同赔 三类。"""
    ctx = _full_context()
    ctx["european"]["move"] = "主胜降水"
    ctx["asian"]["water_move"] = "上盘降水"
    result = forecast(ctx)
    reasons = " ".join(result["reasons"])
    assert any(kw in reasons for kw in ("开盘", "初盘", "降水", "水位", "让球"))
    assert any(kw in reasons for kw in ("近况", "战绩", "状态"))
    assert any(kw in reasons for kw in ("历史", "同赔", "相似"))


def test_context_returns_market_open_close_for_known_fixture():
    """第1关：forecast context 必须包含 market_open_close（开盘+临盘）。"""
    ctx = build_result_forecast_context("1420010")
    moc = ctx.get("market_open_close") or {}
    assert moc.get("opening"), "missing opening odds"
    assert moc.get("latest") or moc.get("closing"), "missing latest/closing odds"
    assert "eu_home" in moc["opening"]
    assert "eu_home" in (moc.get("latest") or moc.get("closing") or {})
