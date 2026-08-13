"""首页主表盘口渲染单测。"""

from web_ui import (
    _ah_cell,
    _betfair_cell,
    _dashboard_active_row,
    _devig_cell,
    _eu_odds_details_cell,
    _extract_jingcai_from_tick,
    _jingcai_rqsp_cell,
    _jingcai_sp_cell,
    _jingcai_sp_line,
    _poll_status_line,
    _recommendation_text,
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


def test_snapshot_footnote_empty_when_changed():
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
    assert _snapshot_footnote(timeline) == ""
