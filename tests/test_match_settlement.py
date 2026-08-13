"""结算可信度与 hits 判定单测。"""

from unittest.mock import MagicMock, patch

import pytest

from live_scores_500 import LiveScore
from match_settlement import (
    _is_dirty_name,
    _parse_shuju_score,
    settle_fixture,
)


def _fixture(home="皇马", away="巴萨", fid="999999"):
    return {
        "id": 1,
        "external_id": fid,
        "home_team": home,
        "away_team": away,
        "match_name": f"{home} vs {away}",
        "kickoff_at": None,
    }


def _score(home, away, *, is_finished=True, source="live_html", status="finished"):
    return LiveScore(
        fixture_id="1",
        home_score=home,
        away_score=away,
        score_text=f"{home}-{away}",
        status=status,
        source=source,
        is_finished=is_finished,
        score_source=source,
    )


def test_is_dirty_name_detects_cup_and_round():
    assert _is_dirty_name("解放者杯")
    assert _is_dirty_name("欧冠")
    assert _is_dirty_name("小组赛")
    assert _is_dirty_name("附加赛")
    assert _is_dirty_name("第三轮")
    assert not _is_dirty_name("皇马")
    assert not _is_dirty_name("巴塞罗那")


def test_settle_skips_unfinished_match():
    fx = _fixture()
    score = _score(2, 1, is_finished=False, status="进行中")
    with patch("match_settlement.upsert_match_result") as mock_upsert:
        assert settle_fixture(fx, score) is False
        mock_upsert.assert_not_called()


def test_settle_skips_zero_zero_without_finished_evidence():
    fx = _fixture()
    score = _score(0, 0, is_finished=False)
    with patch("match_settlement.upsert_match_result") as mock_upsert:
        assert settle_fixture(fx, score) is False
        mock_upsert.assert_not_called()


def test_settle_allows_zero_zero_when_finished():
    fx = _fixture()
    score = _score(0, 0, is_finished=True)
    with patch("match_settlement.upsert_match_result") as mock_upsert, \
         patch("match_settlement.get_opening_tick", return_value=None), \
         patch("match_settlement.get_closing_tick", return_value=None), \
         patch("poll_500.ensure_fixture_identity"):
        assert settle_fixture(fx, score) is True
        mock_upsert.assert_called_once()
        row = mock_upsert.call_args[0][1]
        assert row["home_score"] == 0
        assert row["away_score"] == 0
        assert row["score_text"] == "0-0"


def test_settle_zero_zero_stamps_verified_0_0():
    fx = _fixture()
    score = _score(0, 0, is_finished=True, source="500_data_page")
    with patch("match_settlement.upsert_match_result") as mock_upsert, \
         patch("match_settlement.get_opening_tick", return_value=None), \
         patch("match_settlement.get_closing_tick", return_value=None), \
         patch("poll_500.ensure_fixture_identity"):
        assert settle_fixture(fx, score) is True
        row = mock_upsert.call_args[0][1]
        assert row["payload"]["verified_0_0"] is True
        assert row["payload"]["verified_at"]
        assert row["payload"]["score_source"] == "500_data_page"


def test_settle_rejects_dirty_team_names():
    fx = _fixture(home="解放者杯", away="小组赛")
    score = _score(2, 1, is_finished=True)
    with patch("match_settlement.upsert_match_result") as mock_upsert:
        assert settle_fixture(fx, score) is False
        mock_upsert.assert_not_called()


def test_parse_shuju_score_returns_finished_when_ended_marker():
    html = """
    <table><tr><td>皇马</td><td>比赛时间2026-08-10 22:00</td><td>2:1</td><td>巴萨</td></tr></table>
    <div>完场</div>
    """
    s = _parse_shuju_score(html)
    assert s is not None
    assert s.home_score == 2
    assert s.away_score == 1
    assert s.is_finished is True


def test_parse_shuju_score_returns_none_without_finished_marker():
    html = """
    <table><tr><td>皇马</td><td>比赛时间2026-08-10 22:00</td><td>1:0</td><td>巴萨</td></tr></table>
    """
    s = _parse_shuju_score(html)
    assert s is None


def test_hits_payload_structure():
    fx = _fixture()
    score = _score(2, 1, is_finished=True)
    closing_tick = {
        "ah_line": 0.25,
        "ah_home_water": 0.95,
        "ah_away_water": 0.95,
        "raw_meta": {"ou": {"ou_line": "2.5", "ou_over": 0.95, "ou_under": 0.95}},
    }
    pred = {
        "predict_row": {"赛果预测": "主胜"},
        "result_1x2_cn": "主胜",
        "asian_handicap_pick": "home",
        "asian_handicap_cn": "主-0/0.5",
    }
    with patch("match_settlement.upsert_match_result") as mock_upsert, \
         patch("match_settlement.get_opening_tick", return_value=None), \
         patch("match_settlement.get_closing_tick", return_value=closing_tick), \
         patch("poll_500.ensure_fixture_identity"):
        assert settle_fixture(fx, score, pred=pred) is True
        row = mock_upsert.call_args[0][1]
        hits = row["payload"]["hits"]
        assert hits["1x2"] is True
        assert hits["ah"] == "win"
        assert hits["ou"] == "over"


def test_no_prediction_yields_null_hits_but_ou_when_line_present():
    fx = _fixture()
    score = _score(3, 1, is_finished=True)
    closing_tick = {
        "ah_line": 0.0,
        "ah_home_water": 0.9,
        "ah_away_water": 0.9,
        "raw_meta": {"ou": {"ou_line": "2.5", "ou_over": 0.95, "ou_under": 0.95}},
    }
    with patch("match_settlement.upsert_match_result") as mock_upsert, \
         patch("match_settlement.get_opening_tick", return_value=None), \
         patch("match_settlement.get_closing_tick", return_value=closing_tick), \
         patch("poll_500.ensure_fixture_identity"):
        assert settle_fixture(fx, score, pred=None) is True
        row = mock_upsert.call_args[0][1]
        hits = row["payload"]["hits"]
        assert hits["1x2"] is None
        assert hits["ah"] is None
        assert hits["jingcai"] is None
        assert hits["ou"] == "over"


def test_settle_writes_closing_ou_fields():
    fx = _fixture()
    score = _score(1, 0, is_finished=True)
    closing_tick = {
        "ah_line": 0.0,
        "ah_home_water": 0.9,
        "ah_away_water": 0.9,
        "raw_meta": {"ou": {"ou_line": "2.5", "ou_over": 0.95, "ou_under": 0.95}},
    }
    with patch("match_settlement.upsert_match_result") as mock_upsert, \
         patch("match_settlement.get_opening_tick", return_value=None), \
         patch("match_settlement.get_closing_tick", return_value=closing_tick), \
         patch("poll_500.ensure_fixture_identity"):
        assert settle_fixture(fx, score, pred=None) is True
        row = mock_upsert.call_args[0][1]
        assert row["closing_ou_line"] == 2.5
        assert row["closing_ou_over"] == 0.95
        assert row["closing_ou_under"] == 0.95
