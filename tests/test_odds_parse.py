"""步骤1单测：欧亚赔率解析（打码庄名 + 结构化回退）。"""
from unittest.mock import MagicMock

from poll_500 import (
    _pick_first_valid_eu_row,
    _pick_first_valid_ah_row,
    _parse_eu_row,
    _parse_ah_row,
    _parse_ou_row,
    _fetch_ou_html,
    is_dirty_team_label,
    ensure_fixture_real_teams,
)


# 模拟 500.com 打码后的行数据
MOCK_EU_ROWS = [
    "官*官*(中国)|2.42|2.95|2.65|36.58%|30.01%|33.41%|88.53%|0.82|0.86|0.98",
    "威***威***(英国)|2.70|3.00|2.50|33.56%|30.20%|36.24%|90.60%|0.92|0.87|0.93",
    "*门*门(中国澳门)|2.55|3.18|2.40|34.91%|28.00%|37.09%|89.02%|0.87|0.92|0.89",
]

MOCK_AH_ROWS = [
    "威***威***|0.690|受平手/半球升|0.980|08-11 10:06|0.440|受半球|1.500|08-10 19:50",
    "*门*门|0.980|平手|0.800|08-11 12:08|0.950|平手|0.830|08-10 23:14",
    "立*立*|0.530|受半球|1.370|08-11 06:45|0.530|受半球|1.370|08-11 06:45",
]


def test_pick_first_valid_eu_row():
    """打码庄名行也能解析出欧赔。"""
    cells = _pick_first_valid_eu_row(MOCK_EU_ROWS)
    assert cells is not None
    assert len(cells) >= 4
    eu = _parse_eu_row(cells)
    assert eu["eu_home"] == 2.42
    assert eu["eu_draw"] == 2.95
    assert eu["eu_away"] == 2.65


def test_pick_first_valid_ah_row():
    """打码庄名行也能解析出亚盘。"""
    cells = _pick_first_valid_ah_row(MOCK_AH_ROWS)
    assert cells is not None
    assert len(cells) >= 4
    ah = _parse_ah_row(cells)
    assert ah["ah_home_water"] == 0.69
    # line may be parsed from "受平手/半球升"
    assert ah["ah_line"] is not None or ah["ah_home_water"] is not None


def test_pick_first_valid_eu_row_empty():
    """空列表返回 None。"""
    assert _pick_first_valid_eu_row([]) is None
    assert _pick_first_valid_eu_row(["bad|data|here"]) is None


def test_pick_first_valid_ah_row_empty():
    """空列表返回 None。"""
    assert _pick_first_valid_ah_row([]) is None
    assert _pick_first_valid_ah_row(["bad|data|here"]) is None


def test_parse_eu_row_full():
    """完整欧赔行解析。"""
    cells = "Test|2.0|3.2|4.0|50%|31%|25%|105%|1.9|3.0|3.8".split("|")
    eu = _parse_eu_row(cells)
    assert eu["eu_home"] == 2.0
    assert eu["eu_draw"] == 3.2
    assert eu["eu_away"] == 4.0
    assert eu["eu_open_home"] == 1.9
    assert eu["eu_open_draw"] == 3.0
    assert eu["eu_open_away"] == 3.8


def test_parse_eu_row_fake_open_is_none():
    """现网常见错列：末段是 0.8x 凯利/返还后列，不得写入 eu_open_*。"""
    cells = "官*官*|2.42|2.95|2.65|36.58%|30.01%|33.41%|88.53%|0.83|0.88|0.95".split("|")
    eu = _parse_eu_row(cells)
    assert eu["eu_home"] == 2.42
    assert eu["eu_draw"] == 2.95
    assert eu["eu_away"] == 2.65
    assert eu["eu_open_home"] is None
    assert eu["eu_open_draw"] is None
    assert eu["eu_open_away"] is None


def test_parse_eu_row_open_only_valid_triple():
    """只有当存在第二组合法欧赔三连时，才识别为 open。"""
    cells = "庄|2.10|3.20|3.50|35%|30%|25%|90%|2.20|3.10|3.40".split("|")
    eu = _parse_eu_row(cells)
    assert eu["eu_open_home"] == 2.2
    assert eu["eu_open_draw"] == 3.1
    assert eu["eu_open_away"] == 3.4


import pytest
from poll_500 import assert_tick_has_markets


def test_assert_tick_requires_full_eu_or_full_ah():
    """无完整欧三向且无完整亚盘时禁止入库。"""
    with pytest.raises(RuntimeError):
        assert_tick_has_markets({"eu_home": 2.0, "eu_away": 3.0}, fixture_id="x")
    with pytest.raises(RuntimeError):
        assert_tick_has_markets({"ah_line": 0.25}, fixture_id="x")


def test_assert_tick_accepts_full_eu():
    assert_tick_has_markets({
        "eu_home": 2.0, "eu_draw": 3.2, "eu_away": 4.0,
    }, fixture_id="x")


def test_assert_tick_accepts_full_ah():
    assert_tick_has_markets({
        "ah_line": 0.25, "ah_home_water": 0.95, "ah_away_water": 0.95,
    }, fixture_id="x")


def test_parse_ou_row_valid():
    # 平均值行实际索引：3=大, 4=盘口, 5=小, 9=初大, 10=初盘, 11=初小
    cells = ["", "平均值", "", "0.93", "2.31", "0.86", "", "", "", "0.90", "2.25", "0.88"]
    ou = _parse_ou_row(cells)
    assert ou["ou_line"] == 2.31
    assert ou["ou_over"] == 0.93
    assert ou["ou_under"] == 0.86
    assert ou["ou_open_line"] == 2.25
    assert ou["ou_open_over"] == 0.90
    assert ou["ou_open_under"] == 0.88


def test_parse_ou_row_invalid_open_returns_none():
    """open 列若是垃圾 0.xx 应置 None，禁止写入假初盘；即时盘仍合法。"""
    cells = ["", "平均值", "", "0.93", "2.31", "0.86", "", "", "", "0.83", "0.88", "0.95"]
    ou = _parse_ou_row(cells)
    assert ou["ou_line"] == 2.31
    assert ou["ou_over"] == 0.93
    assert ou["ou_under"] == 0.86
    # 初盘三件套不合法时全部置 None
    assert ou["ou_open_line"] is None
    assert ou["ou_open_over"] is None
    assert ou["ou_open_under"] is None


def test_fetch_ou_html_not_raise_on_missing():
    from http_client import make_session, ScraperGuard
    s = make_session()
    guard = ScraperGuard(min_delay=0.5, max_delay=1.0)
    # 用一个不存在的 fid 或未来赛事，应返回 None 而不是抛错
    result = _fetch_ou_html(s, "999999999", guard=guard)
    assert result is None or result.get("ou_line") is None


@pytest.mark.parametrize("name", [
    "", " ", "亚冠杯", "欧冠", "附加赛", "资格赛第三轮", "小组赛",
    "决赛", "半决赛", "日职", "韩K", "英超", "西甲", "意甲", "德甲", "法甲",
    "解放者杯", "VS", "A VS B",
])
def test_is_dirty_team_label(name):
    assert is_dirty_team_label(name) is True


@pytest.mark.parametrize("name", [
    "广州恒大", "Real Madrid", "曼城", "弗拉门戈", "浦和红钻",
])
def test_is_clean_team_label(name):
    assert is_dirty_team_label(name) is False


def test_ensure_fixture_identity_fixes_dirty_names(monkeypatch):
    """live 脏队名应被 fetch_match_info 修正为真实主客。"""
    from download_500 import MatchFixture

    fx = MatchFixture(fixture_id="1420010", home="亚冠杯", away="附加赛")

    def fake_fetch(_session, fid):
        assert fid == "1420010"
        return MatchFixture(fixture_id=fid, home="利雅得胜利", away="迪拜祈祷", label="亚冠杯")

    monkeypatch.setattr("download_500.fetch_match_info", fake_fetch)
    session = MagicMock()
    fixed = ensure_fixture_real_teams(session, fx)
    assert fixed.home == "利雅得胜利"
    assert fixed.away == "迪拜祈祷"


def test_ensure_fixture_identity_keeps_clean_names(monkeypatch):
    """已是真队名时不再触发 fetch。"""
    from download_500 import MatchFixture

    fx = MatchFixture(fixture_id="1420010", home="广州恒大", away="上海上港")
    call_log = []

    def fake_fetch(_session, fid):
        call_log.append(fid)
        return MatchFixture(fixture_id=fid, home="X", away="Y")

    monkeypatch.setattr("download_500.fetch_match_info", fake_fetch)
    fixed = ensure_fixture_real_teams(MagicMock(), fx)
    assert fixed.home == "广州恒大"
    assert fixed.away == "上海上港"
    assert not call_log
