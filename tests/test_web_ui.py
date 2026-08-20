"""首页主表盘口渲染单测。"""

from web_ui import (
    _ah_cell,
    _ai_expert_desk_card,
    _betfair_cell,
    _comparison_summary_card,
    _confidence_cell,
    _dashboard_active_row,
    _devig_cell,
    _devig_jingcai,
    _eu_odds_details_cell,
    _extract_jingcai_from_tick,
    _first_valid_jingcai,
    _form_card,
    _history_similar_card,
    _is_fake_likely_score,
    _jingcai_rqsp_cell,
    _jingcai_sp_cell,
    _jingcai_sp_line,
    _latest_jingcai,
    _market_lanes_card,
    _market_lanes_one_liner,
    _market_signal_card,
    _poll_status_line,
    _recommendation_text,
    _score_cell,
    _snapshot_footnote,
    _snapshot_recommendation_unchanged,
)


def test_devig_cell_from_snapshot():
    snap = {"eu_home": 2.8, "eu_draw": 3.0, "eu_away": 2.25}
    text, fav = _devig_cell(snap)
    assert "主31%" in text or "主32%" in text
    assert "客" in fav


def test_devig_cell_missing():
    assert _devig_cell({}) == ("—", "")


def test_ah_cell_with_line():
    assert _ah_cell({"ah_line": "-0.25", "ah_home_water": 0.95, "ah_away_water": 0.97}) == "-0.25 主0.95 / 客0.97"


def test_ah_cell_missing():
    assert _ah_cell({}) == "—"


def test_betfair_cell_hot():
    snap = {
        "betfair": {
            "has_data": True,
            "hot": "home",
            "volume_pct": {"home": 0.62, "draw": 0.18, "away": 0.20},
        }
    }
    assert "主 62%" == _betfair_cell(snap)


def test_betfair_cell_no_data():
    assert _betfair_cell({"betfair": {"has_data": False}}) == "—"


def test_jingcai_sp_line():
    snap = {"jingcai": {"has_sp": True, "sp_home": 2.1, "sp_draw": 3.2, "sp_away": 3.5}}
    assert "SP 2.1/3.2/3.5" in _jingcai_sp_line(snap)


def test_dashboard_active_row_with_odds_snapshot():
    m = {
        "fixture_id": "123",
        "match": "测试主VS测试客",
        "kickoff_label": "08-14 20:00",
        "odds_snapshot": {
            "eu_home": 2.8,
            "eu_draw": 3.0,
            "eu_away": 2.25,
            "ah_line": "0.0",
            "ah_home_water": 0.85,
            "ah_away_water": 1.05,
            "betfair": {"has_data": False},
            "jingcai": {"has_sp": True, "sp_home": 2.32, "sp_draw": 3.15, "sp_away": 2.63},
        },
    }
    html = _dashboard_active_row(m, {})
    assert "主31%" in html or "主32%" in html
    assert "0.0 主0.85 / 客1.05" in html
    assert "08-14 20:00" in html
    assert "SP 2.32/3.15/2.63" in html


def test_dashboard_active_row_no_snapshot_shows_dash():
    m = {
        "fixture_id": "123",
        "match": "测试主VS测试客",
        "odds_snapshot": {},
    }
    html = _dashboard_active_row(m, {})
    assert html.count("<td>—</td>") >= 3


def test_poll_status_line_no_state(monkeypatch):
    monkeypatch.setattr("db.repository.get_scraper_state", lambda _key: None)
    assert "poll —" in _poll_status_line()


def test_extract_jingcai_from_odds():
    p = {"odds": {"jingcai": {"has_sp": True, "sp_home": 2.1, "sp_draw": 3.2, "sp_away": 3.5}}}
    jc = _extract_jingcai_from_tick(p)
    assert jc["has_sp"] is True
    assert jc["sp_home"] == 2.1


def test_extract_jingcai_fallback_to_raw_meta():
    p = {"odds": {"raw_meta": {"jingcai": {"has_sp": True, "sp_home": 1.9}}}}
    jc = _extract_jingcai_from_tick(p)
    assert jc["has_sp"] is True
    assert jc["sp_home"] == 1.9


def test_jingcai_sp_cell_with_sp():
    assert _jingcai_sp_cell({"has_sp": True, "sp_home": 2.1, "sp_draw": 3.2, "sp_away": 3.5}) == "2.1/3.2/3.5"


def test_jingcai_sp_cell_missing_shows_placeholder():
    cell = _jingcai_sp_cell({})
    assert "—" in cell
    assert "未开售/未抓到" in cell


def test_jingcai_rqsp_cell_with_rqsp():
    assert (
        _jingcai_rqsp_cell({"has_rqsp": True, "rqsp_home": 1.8, "rqsp_draw": 3.4, "rqsp_away": 3.6})
        == "1.8/3.4/3.6"
    )


def test_jingcai_rqsp_cell_missing_shows_placeholder():
    cell = _jingcai_rqsp_cell({})
    assert "—" in cell
    assert "未开售/未抓到" in cell


def test_eu_odds_details_cell():
    cell = _eu_odds_details_cell({"eu_home": 2.8, "eu_draw": 3.0, "eu_away": 2.25})
    assert "<details" in cell
    assert "欧赔对照" in cell
    assert "2.8/3.0/2.25" in cell


def test_recommendation_text():
    p = {"pick": {"result_1x2_cn": "主胜"}}
    assert _recommendation_text(p) == "<strong>主胜</strong>"


def test_recommendation_text_ai_analyses():
    p = {"pick": {"ai_analyses": {"a": {"label": "A", "result_1x2_cn": "主胜"}, "b": {"label": "B", "result_1x2_cn": "客胜"}}}}
    text = _recommendation_text(p)
    assert "<strong>A</strong>: 主胜" in text
    assert "<strong>B</strong>: 客胜" in text


def test_snapshot_recommendation_unchanged():
    timeline = [
        {"pick": {"result_1x2_cn": "主胜"}},
        {"pick": {"result_1x2_cn": "主胜"}},
    ]
    assert _snapshot_recommendation_unchanged(timeline) is True


def test_snapshot_recommendation_changed():
    timeline = [
        {"pick": {"result_1x2_cn": "主胜"}},
        {"pick": {"result_1x2_cn": "客胜"}},
    ]
    assert _snapshot_recommendation_unchanged(timeline) is False


def test_snapshot_footnote_when_odds_unchanged():
    timeline = [
        {
            "odds": {"eu_home": 2.8, "eu_draw": 3.0, "eu_away": 2.25, "jingcai": {"has_sp": True, "sp_home": 2.1, "sp_draw": 3.2, "sp_away": 3.5}},
            "pick": {"result_1x2_cn": "主胜"},
        },
        {
            "odds": {"eu_home": 2.8, "eu_draw": 3.0, "eu_away": 2.25, "jingcai": {"has_sp": True, "sp_home": 2.1, "sp_draw": 3.2, "sp_away": 3.5}},
            "pick": {"result_1x2_cn": "主胜"},
        },
    ]
    note = _snapshot_footnote(timeline)
    assert "源站未调赔" in note
    assert "必发%仍可能更新" in note
    assert "非每 tick 重算" in note


def test_snapshot_footnote_when_changed_omits_odds_note():
    timeline = [
        {
            "odds": {"eu_home": 2.8, "eu_draw": 3.0, "eu_away": 2.25, "jingcai": {"has_sp": True, "sp_home": 2.1, "sp_draw": 3.2, "sp_away": 3.5}},
            "pick": {"result_1x2_cn": "主胜"},
        },
        {
            "odds": {"eu_home": 2.9, "eu_draw": 3.0, "eu_away": 2.25, "jingcai": {"has_sp": True, "sp_home": 2.1, "sp_draw": 3.2, "sp_away": 3.5}},
            "pick": {"result_1x2_cn": "客胜"},
        },
    ]
    note = _snapshot_footnote(timeline)
    assert "比分/置信仅最新行显示" in note
    assert "源站未调赔" not in note


def test_is_fake_likely_score_detects_zero_percent():
    assert _is_fake_likely_score("2-1(0.0%)") is True
    assert _is_fake_likely_score("1-1(0%)") is True
    assert _is_fake_likely_score("2-1(12.3%)") is False
    assert _is_fake_likely_score(None) is False
    assert _is_fake_likely_score("") is False


def test_score_cell_only_latest_row():
    pk = {"likely_scores": "2-1(12.3%)"}
    assert _score_cell(pk, 0, 2) == "—"
    assert _score_cell(pk, 1, 2) == "—"
    assert _score_cell(pk, 2, 2) == "2-1(12.3%)"


def test_score_cell_fake_score_shows_not_ready():
    pk = {"likely_scores": "2-1(0.0%)"}
    assert _score_cell(pk, 2, 2) == "比分未就绪"


def test_confidence_cell_only_latest_row():
    pk = {"confidence_cn": "高"}
    assert _confidence_cell(pk, 0, 2) == "—"
    assert _confidence_cell(pk, 2, 2) == "高"


def test_snapshot_table_hides_score_confidence_in_history():
    """3 条相同 pick 的 timeline，比分/置信只应在最新行出现 1 次，历史行用 — 占位。"""
    from web_ui import html_match_detail

    same_pick = {
        "result_1x2_cn": "主胜",
        "likely_scores": "2-1(12.3%)",
        "confidence_cn": "中",
    }
    timeline = [
        {"ts": "2026-08-14 12:00", "odds": {"eu_home": 2.8, "eu_draw": 3.0, "eu_away": 2.25}, "pick": same_pick},
        {"ts": "2026-08-14 13:00", "odds": {"eu_home": 2.8, "eu_draw": 3.0, "eu_away": 2.25}, "pick": same_pick},
        {"ts": "2026-08-14 14:00", "odds": {"eu_home": 2.8, "eu_draw": 3.0, "eu_away": 2.25}, "pick": same_pick},
    ]
    index = {
        "fixture_id": "f1",
        "match_name": "主队 VS 客队",
        "timeline": timeline,
        "changes": [],
    }
    html = html_match_detail(index, prediction={"pick": same_pick})
    # 比分/置信在 HTML 中应各只出现 1 次（最新行）
    assert html.count("2-1(12.3%)") == 1, html.count("2-1(12.3%)")
    assert html.count(">中<") == 1
    # 快照表历史行应有多个 —
    assert html.count("<td>—</td>") >= 4


def test_snapshot_table_fake_score_not_duplicated():
    """3 条相同 pick 且为假比分的 timeline，假比分字符串最多出现 0 次（显示比分未就绪）。"""
    from web_ui import html_match_detail

    same_pick = {
        "result_1x2_cn": "主胜",
        "likely_scores": "2-1(0.0%)",
        "confidence_cn": "中",
    }
    timeline = [
        {"ts": "2026-08-14 12:00", "odds": {"eu_home": 2.8, "eu_draw": 3.0, "eu_away": 2.25}, "pick": same_pick},
        {"ts": "2026-08-14 13:00", "odds": {"eu_home": 2.8, "eu_draw": 3.0, "eu_away": 2.25}, "pick": same_pick},
        {"ts": "2026-08-14 14:00", "odds": {"eu_home": 2.8, "eu_draw": 3.0, "eu_away": 2.25}, "pick": same_pick},
    ]
    index = {
        "fixture_id": "f1",
        "match_name": "主队 VS 客队",
        "timeline": timeline,
        "changes": [],
    }
    html = html_match_detail(index, prediction={"pick": same_pick})
    assert "2-1(0.0%)" not in html
    assert html.count("比分未就绪") == 1


def test_first_and_latest_jingcai():
    timeline = [
        {"odds": {"jingcai": {"has_sp": True, "sp_home": 1.8, "match_num": "001"}}},
        {"odds": {"jingcai": {"has_sp": True, "sp_home": 2.1, "match_num": "002"}}},
    ]
    assert _first_valid_jingcai(timeline)["sp_home"] == 1.8
    assert _latest_jingcai(timeline)["sp_home"] == 2.1


def test_devig_jingcai_computes_probabilities():
    jc = {"has_sp": True, "sp_home": 2.1, "sp_draw": 3.2, "sp_away": 3.5}
    text = _devig_jingcai(jc)
    assert text != "—"
    assert "主" in text and "平" in text and "客" in text


def test_market_signal_card_jingcai_first():
    """有竞彩时主区先出现竞彩 SP，欧赔在欧亚对照（辅助）details 内。"""
    timeline = [
        {"odds": {"jingcai": {"has_sp": True, "sp_home": 2.1, "sp_draw": 3.2, "sp_away": 3.5, "match_num": "周六001"}, "eu_home": 2.8, "eu_draw": 3.0, "eu_away": 2.25}},
        {"odds": {"jingcai": {"has_sp": True, "sp_home": 2.0, "sp_draw": 3.2, "sp_away": 3.6, "match_num": "周六001"}, "eu_home": 2.8, "eu_draw": 3.0, "eu_away": 2.25}},
    ]
    moc = {
        "opening": {"eu_home": 2.8, "eu_draw": 3.0, "eu_away": 2.25},
        "latest": {"eu_home": 2.8, "eu_draw": 3.0, "eu_away": 2.25},
    }
    html = _market_signal_card("主队 VS 客队", {}, timeline, market_open_close=moc)
    assert "盘口（竞彩为主）" in html
    assert "竞彩 SP" in html
    assert "2.1 → 2.0" in html
    # 欧赔应出现在折叠的欧亚对照内
    assert "欧亚对照（辅助）" in html
    assert "<details" in html
    assert "欧赔 2.8/3.0/2.25" in html


def test_market_signal_card_no_jingcai_shows_placeholder():
    timeline = [
        {"odds": {"eu_home": 2.8, "eu_draw": 3.0, "eu_away": 2.25}},
    ]
    html = _market_signal_card("主队 VS 客队", {}, timeline, market_open_close={"opening": {"eu_home": 2.8, "eu_draw": 3.0, "eu_away": 2.25}, "latest": {"eu_home": 2.8, "eu_draw": 3.0, "eu_away": 2.25}})
    assert "本场暂无竞彩开售/未抓到 SP" in html
    assert "欧亚对照（辅助）" in html
    assert "欧赔 2.8/3.0/2.25" in html


def test_viz_charts_card_has_axis_labels_and_summary():
    """6x6 泊松热力图 HTML 必须含 0-5 轴标、hover title、Top3/1X2 摘要。"""
    from web_ui import _viz_charts_card

    viz = {
        "poisson_heatmap": [[0, 0, 0.05], [1, 1, 0.15], [1, 0, 0.10]],
        "summary": {
            "score_top": [{"score": "1-1", "p": 0.15}],
            "poisson_1x2": {"home": 40.0, "draw": 20.0, "away": 40.0},
        },
    }
    html = _viz_charts_card(viz, "f1")
    # axis labels 0-5 rendered by JS
    assert "主\\客" in html
    assert "heatmap-axis" in html
    assert "for (let j = 0; j <= 5; j++)" in html
    assert "for (let i = 0; i <= 5; i++)" in html
    # hover title with score and probability (JS concatenation)
    assert "主' + i + '-客" in html
    assert "p=' + (p * 100).toFixed(2)" in html
    # summary line
    assert "poissonSummary" in html
    assert "score_top" in html or "Top3" in html
    assert "poisson_1x2" in html or "泊松1X2" in html


def test_form_card_shows_opening_and_closing_odds():
    club_form = {
        "home_overall": {"played": 5, "win_rate": 0.6, "form_str": "WWDLW"},
        "away_overall": {"played": 5, "win_rate": 0.4, "form_str": "WDLWD"},
        "samples": {
            "home_all": [
                {
                    "date": "2026-07-01",
                    "match": "主队 2-1 客队A",
                    "home_score": 2,
                    "away_score": 1,
                    "opening_eu_home": 2.0,
                    "opening_eu_draw": 3.3,
                    "opening_eu_away": 3.8,
                    "closing_eu_home": 1.9,
                    "closing_eu_draw": 3.4,
                    "closing_eu_away": 4.0,
                    "closing_ah_line": "-0.5",
                    "closing_ah_home_water": 0.95,
                    "closing_ah_away_water": 0.95,
                }
            ]
        }
    }
    html = _form_card("主队 VS 客队", {}, club_form)
    assert "开盘欧赔" in html
    assert "2.0/3.3/3.8" in html
    assert "1.9/3.4/4.0" in html
    assert "2-1" in html


def test_form_card_missing_reason_readable():
    club_form = {
        "missing": ["home_overall(主队): 队名未映射"],
        "home_overall": {},
        "away_overall": {},
    }
    html = _form_card("主队 VS 客队", {}, club_form)
    assert "缺数据原因" in html
    assert "队名未映射" in html


def test_history_similar_card_shows_opening_odds():
    history_similar = {
        "n": 3,
        "p_home": 2,
        "p_draw": 1,
        "p_away": 0,
        "samples": [
            {
                "date": "2026-07-01",
                "match": "A vs B",
                "score": "2-1",
                "result_cn": "主胜",
                "eu_open": "2.1/3.2/3.5",
                "eu": "2.0/3.3/3.8",
                "ah_open": "-0.5",
                "ah_open_water": "0.90/0.90",
                "ah": "-0.5",
                "ah_water": "0.95/0.95",
            }
        ],
    }
    html = _history_similar_card(history_similar)
    assert "开盘欧赔" in html
    assert "2.1/3.2/3.5" in html
    assert "比分" in html
    assert "2-1" in html


def _sample_ai_expert_desk_payload() -> dict:
    return {
        "jingcai": {
            "available": True,
            "match_num": "周日001",
            "play_types": ["胜平负", "让球胜平负"],
            "sp_open_live": {
                "open": "未抓取开盘SP，仅展示临盘",
                "live": {"主胜": "1.80", "平": "3.40", "客胜": "4.20"},
            },
            "rqsp_open_live": {
                "open": "未抓取开盘RQSP，仅展示临盘",
                "live": {"主胜": "3.10", "平": "3.25", "客胜": "2.05"},
                "handicap": "-1",
            },
            "devig_probabilities": {
                "胜平负": {"主胜": "48.1%", "平": "25.5%", "客胜": "26.4%", "margin_percent": 6.5},
            },
            "note": "竞彩SP/RQSP为可购价格",
        },
        "divergence": {
            "available": True,
            "score": 0.35,
            "severity": "中",
            "advice": "欧亚略分裂，建议观望或小注",
            "signals": ["欧热亚浅"],
        },
        "market": {
            "available": True,
            "ah_open": {"line": -0.5, "home_water": 0.95, "away_water": 0.90},
            "ah_live": {"line": -0.75, "home_water": 0.98, "away_water": 0.87},
            "market_attitude": {
                "labels": ["升盘降水"],
                "supported_side": "home",
                "strength": "中",
                "narrative": "亚盘升盘降水支持主队",
            },
        },
        "result_forecast": {
            "available": True,
            "pick": "主胜",
            "p": 0.62,
            "reasons": ["主队近况占优"],
        },
        "similar_ev_trap": {
            "similar_summary": "同赔样本 42 场，主胜 58%",
            "ev": {"edge_side": "home", "edge_pp": 0.06, "value_bet": True},
            "trap_control": {"control_level": "中", "patterns": ["诱上盘"]},
            "form": {"available": True, "home": "近5场 3胜1平1负", "away": "近5场 1胜2平2负"},
        },
        "missing": [],
    }


def test_ai_expert_desk_card_renders_all_sections():
    html = _ai_expert_desk_card("测试主VS测试客", _sample_ai_expert_desk_payload())
    assert "精算师桌" in html
    assert "1) 竞彩" in html
    assert "2) 欧亚分歧" in html
    assert "3) 水位/变盘" in html
    assert "4) 规则桌" in html
    assert "5) 同赔+EV+诱盘" in html
    assert "6) 缺失项" in html
    assert "7) 研判框架" in html
    assert "预览入参" in html
    assert "周日001" in html
    assert "亚盘升盘降水支持主队" in html
    assert "同赔样本 42 场" in html


def test_ai_expert_desk_card_missing_shows_red():
    payload = _sample_ai_expert_desk_payload()
    payload["missing"] = ["jingcai", "team_recent_form/club_form"]
    html = _ai_expert_desk_card("测试主VS测试客", payload)
    assert "jingcai" in html
    assert "team_recent_form/club_form" in html
    assert "禁止编造" in html


def test_ai_expert_desk_card_empty_payload():
    html = _ai_expert_desk_card("测试主VS测试客", None)
    assert "暂无精算师输入数据" in html


def test_collect_verdict_view_prefers_ai_basis():
    from web_ui import _collect_verdict_view

    pred = {
        "recommendation_source": "ai_expert_deepseek",
        "ai_analyses": {
            "deepseek": {
                "ai_provider_label": "DeepSeek 精算师",
                "result_1x2_cn": "主胜",
                "confidence_cn": "低",
                "actuary_reasoning": "竞彩主胜SP仍有正EV，欧赔客热但亚盘未跟。",
                "analysis_basis": [
                    "【基准概率】竞彩去水主胜 48%",
                    "【EV结论】历史同赔主胜 58% 高于隐含",
                    "【综合结论】倾向主胜，小注",
                ],
                "implied_probability": {"主胜": "42%", "平": "28%", "客胜": "30%"},
                "adjusted_probability": {"主胜": "48%", "平": "26%", "客胜": "26%"},
                "value_bet": True,
                "predict_row": {"竞彩推荐": "主胜", "竞彩SP": 1.81, "胜平负": "主胜"},
            }
        },
        "predict_row": {"竞彩推荐": "主胜", "竞彩SP": 1.81, "胜平负": "主胜"},
    }
    view = _collect_verdict_view(pred)
    assert view["pick"] == "主胜"
    assert view["source"] == "DeepSeek 精算师"
    assert view["confidence"] == "低"
    assert any("EV结论" in x for x in view["basis"])
    assert view["value_bet"] is True


def test_verdict_basis_card_shows_who_and_why():
    from web_ui import _verdict_basis_card

    html = _verdict_basis_card({
        "ai_analyses": {
            "deepseek": {
                "ai_provider_label": "DeepSeek 精算师",
                "result_1x2_cn": "主胜",
                "confidence_cn": "低",
                "actuary_reasoning": "历史主胜高于隐含，升盘降水支撑上盘。",
                "analysis_basis": ["【基准概率】去水主胜 48%", "【综合结论】倾向主胜"],
                "predict_row": {"竞彩推荐": "主胜", "胜平负": "主胜"},
            }
        },
        "predict_row": {"竞彩推荐": "主胜", "胜平负": "主胜"},
    })
    assert "谁赢 · 依据" in html
    assert "主胜" in html
    assert "【基准概率】去水主胜 48%" in html
    assert "历史主胜高于隐含" in html
    assert "DeepSeek 精算师" in html


def test_recommendation_text_latest_row_includes_reason():
    p = {
        "pick": {
            "ai_analyses": {
                "ds": {
                    "label": "DeepSeek 精算师",
                    "result_1x2_cn": "主胜",
                    "actuary_reasoning": "竞彩SP主胜仍便宜",
                }
            }
        }
    }
    html = _recommendation_text(p, with_reason=True)
    assert "DeepSeek 精算师" in html
    assert "主胜" in html
    assert "竞彩SP主胜仍便宜" in html
    assert "rec-reason" in html
    # unchanged-check still compares without reason
    assert "竞彩SP主胜仍便宜" not in _recommendation_text(p)


def test_compact_ai_keeps_analysis_basis():
    from match_timeline import compact_ai_analyses

    pred = {
        "recommendation_source": "ai_expert_deepseek",
        "ai_provider": "deepseek",
        "ai_provider_label": "DeepSeek 精算师",
        "result_1x2_cn": "主胜",
        "actuary_reasoning": "核心逻辑一句",
        "analysis_basis": ["【基准概率】48%", "【综合结论】主胜"],
        "predict_row": {"胜平负": "主胜"},
    }
    compact = compact_ai_analyses(pred)
    assert compact["deepseek"]["analysis_basis"][0].startswith("【基准概率】")
    assert compact["deepseek"]["actuary_reasoning"] == "核心逻辑一句"


def test_comparison_summary_card_renders_when_present():
    pred = {
        "judgment": "倾向主胜·标准",
        "result_1x2_cn": "主胜",
        "prematch_desk": {
            "available": True,
            "high_impact_facts": [],
            "dimensions": [],
        },
        "comparison_summary": {
            "action": "hold",
            "odds_desk_pick": "倾向主胜·标准",
            "summary": "维持",
        },
    }
    html = _comparison_summary_card(pred)
    assert "对照摘要" in html
    assert "维持" in html
    assert "赛前桌明细" in html


def test_comparison_summary_card_empty_when_missing():
    assert _comparison_summary_card({}) == ""


def test_market_lanes_card_renders_three_lanes():
    pred = {
        "market_lanes": {
            "eu": {
                "label": "欧赔轨",
                "tag": "参考·不可购",
                "missing": False,
                "pick_cn": "主胜",
                "reasons": ["去水隐含概率：主 45%", "来源：平博"],
            },
            "ah": {
                "label": "亚盘轨",
                "tag": "参考·非竞彩让球",
                "missing": False,
                "line": -0.25,
                "home_water": 0.95,
                "away_water": 0.97,
                "reasons": ["亚盘 -0.25 主水 0.95"],
            },
            "jingcai": {
                "label": "竞彩轨",
                "tag": "可购",
                "missing": False,
                "play": "胜平负",
                "pick_cn": "主胜",
                "sp": "2.05",
                "buyable": True,
                "reasons": ["胜平负 SP 2.05 → 主胜"],
            },
            "comparison": {
                "agreement": "align",
                "action": "hold",
                "summary": "三轨方向一致，竞彩轨维持原仓位建议。",
                "buyable": {
                    "market": "胜平负",
                    "pick_cn": "主胜",
                    "sp": "2.05",
                    "reason": "胜平负 2.05 → 主胜",
                },
            },
        }
    }
    html = _market_lanes_card(pred)
    assert "三轨盘口" in html
    assert "欧赔轨" in html
    assert "亚盘轨" in html
    assert "竞彩轨" in html
    assert "可购" in html
    assert "非竞彩让球" in html
    assert "维持" in html
    assert "欧亚轨仅作参考" in html


def test_market_lanes_card_empty_when_missing():
    assert _market_lanes_card({}) == ""


def test_market_lanes_one_liner():
    lanes = {
        "eu": {"missing": False, "pick_cn": "主胜"},
        "ah": {"missing": False, "lean_cn": "主胜"},
        "jingcai": {"missing": False, "buyable": True, "play": "胜平负"},
        "comparison": {"agreement": "align"},
    }
    txt = _market_lanes_one_liner(lanes)
    assert "欧↔亚↔彩 一致" in txt
    assert "可购 胜平负" in txt


def test_market_lanes_one_liner_divergent():
    lanes = {
        "eu": {"missing": False, "pick_cn": "客胜"},
        "ah": {"missing": True},
        "jingcai": {"missing": False, "buyable": True, "play": "胜平负"},
        "comparison": {"agreement": "partial"},
    }
    txt = _market_lanes_one_liner(lanes)
    assert "欧↔亚↔彩 分裂" in txt
    assert "欧客胜" in txt
