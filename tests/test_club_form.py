"""P2 测试：俱乐部战绩引擎。"""
from analysis.team_form.club_form import build_club_form, _summary_row


def test_summary_row_basic():
    """_summary_row 正确统计 W/D/L。"""
    matches = [
        {"home_team": "A", "away_team": "B", "home_score": 2, "away_score": 1},
        {"home_team": "A", "away_team": "C", "home_score": 1, "away_score": 1},
        {"home_team": "A", "away_team": "D", "home_score": 0, "away_score": 3},
        {"home_team": "A", "away_team": "E", "home_score": 3, "away_score": 0},
    ]
    s = _summary_row("A", matches, "home")
    assert s["played"] == 4
    assert s["w"] == 2
    assert s["d"] == 1
    assert s["l"] == 1
    assert s["goals_for"] == 6
    assert s["goals_against"] == 5
    assert abs(s["win_rate"] - 0.5) < 0.01


def test_summary_row_empty():
    """空数据 → played=0。"""
    s = _summary_row("X", [], "all")
    assert s["played"] == 0
    assert "无数据" in s["summary_cn"]


def test_build_club_form_missing_teams():
    """不存在的队 → missing 非空，不崩。"""
    cf = build_club_form("不存在的队A", "不存在的队B")
    assert len(cf["missing"]) > 0
    # 结构完整
    assert "overall" in cf
    assert "split" in cf
    assert cf["overall"]["window"] == 30


def test_build_club_form_window_config():
    """窗口参数传入正确。"""
    cf = build_club_form("X", "Y", window=20, split_n=10)
    assert cf["overall"]["window"] == 20
    assert cf["split"]["split_n"] == 10
