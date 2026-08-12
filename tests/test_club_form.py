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


# ============ FIX-3: resolve_team_name 真映射 ============

def test_resolve_team_name_known():
    """已知中文别名 → 历史库名。"""
    from analysis.team_form.club_form import _resolve_team_name
    assert _resolve_team_name("曼城", "英超") == "Man City"
    assert _resolve_team_name("巴萨", "西甲") == "Barcelona"
    assert _resolve_team_name("拜仁", "德甲") == "Bayern Munich"
    assert _resolve_team_name("国米", "意甲") == "Inter"
    assert _resolve_team_name("巴黎", "法甲") == "Paris Saint Germain"


def test_resolve_team_name_global_search():
    """不在指定联赛但在全局映射中也能找到。"""
    from analysis.team_form.club_form import _resolve_team_name
    # 曼城在英超，指定联赛为西甲也能全局找到
    assert _resolve_team_name("曼城", "西甲") == "Man City"


def test_resolve_team_name_unknown():
    """未知队名原样返回。"""
    from analysis.team_form.club_form import _resolve_team_name
    assert _resolve_team_name("某不知名队", "英超") == "某不知名队"
    assert _resolve_team_name("Unknown FC") == "Unknown FC"


def test_resolve_team_name_alias_variant():
    """别名变体也能映射。"""
    from analysis.team_form.club_form import _resolve_team_name
    assert _resolve_team_name("巴塞罗那", "西甲") == "Barcelona"
    assert _resolve_team_name("国际米兰", "意甲") == "Inter"
    assert _resolve_team_name("拜仁慕尼黑", "德甲") == "Bayern Munich"
    assert _resolve_team_name("巴黎圣日耳曼", "法甲") == "Paris Saint Germain"


def test_resolve_team_name_j_league():
    """日职队别名映射。"""
    from analysis.team_form.club_form import _resolve_team_name
    assert _resolve_team_name("大阪钢巴", "日职") == "Gamba Osaka"
    assert _resolve_team_name("大阪樱花", "日职") == "Cerezo Osaka"
    assert _resolve_team_name("川崎前锋", "日职") == "Kawasaki Frontale"


def test_resolve_team_name_k_league():
    """韩K队别名映射。"""
    from analysis.team_form.club_form import _resolve_team_name
    assert _resolve_team_name("江原FC", "韩K") == "Gangwon FC"
    assert _resolve_team_name("全北现代", "韩K") == "Jeonbuk Hyundai Motors"


def test_build_club_form_samples_shape():
    """返回结构含 samples；无数据时 missing 非空。"""
    cf = build_club_form("不存在的队A", "不存在的队B")
    assert "samples" in cf
    assert "home_all" in cf["samples"]
    assert "away_all" in cf["samples"]
    assert isinstance(cf["samples"]["home_all"], list)
    assert len(cf["missing"]) > 0
