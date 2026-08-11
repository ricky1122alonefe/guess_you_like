"""Q1-D0 测试：竞彩转向 — 列表过滤 + 联赛映射 + 导航去世界杯主轴。"""
import yaml
from pathlib import Path
from product_focus import focus_jingcai_only, knockout_phase, ai_profile


def test_focus_jingcai_only_default_true():
    """FOCUS_JINGCAI_ONLY 默认 True。"""
    assert focus_jingcai_only() is True


def test_knockout_phase_default_false():
    """knockout_phase 默认 False（联赛模式）。"""
    assert knockout_phase() is False


def test_ai_profile_default_league():
    """AI profile 默认 league。"""
    assert ai_profile() == "league"


def test_jingcai_league_map_exists():
    """联赛映射表存在且含五大联赛。"""
    p = Path("config/jingcai_league_map.yaml")
    assert p.exists()
    data = yaml.safe_load(p.read_text())
    leagues = data.get("leagues") or {}
    assert "英超" in leagues
    assert "西甲" in leagues
    assert "意甲" in leagues
    assert "德甲" in leagues
    assert "法甲" in leagues
    # 每个联赛有 fd_code
    for name, info in leagues.items():
        assert "fd_code" in info, f"{name} missing fd_code"


def test_jingcai_league_map_has_asian():
    """映射表含亚洲竞彩常见联赛。"""
    data = yaml.safe_load(Path("config/jingcai_league_map.yaml").read_text())
    leagues = data.get("leagues") or {}
    assert "日职" in leagues
    assert "韩K" in leagues
    assert "澳超" in leagues


def test_nav_no_worldcup_main():
    """导航主链只有首页/当日推荐/复盘，无世界杯/更多。"""
    from web_ui import _page_nav
    html = _page_nav()
    assert "首页" in html
    assert "复盘" in html
    assert "worldcup" not in html  # 世界杯不进导航
    assert "更多" not in html  # 不再有更多折叠


def test_dashboard_title_no_worldcup():
    """首页标题不含世界杯（title 标签 + h1）。"""
    from web_ui import html_dashboard
    html = html_dashboard({}, None, output_root=Path("/tmp"))
    # 检查 <title> 和 <h1> 标签
    import re
    title_m = re.search(r"<title>(.*?)</title>", html)
    h1_m = re.search(r"<h1[^>]*>(.*?)</h1>", html)
    title_text = title_m.group(1) if title_m else ""
    h1_text = h1_m.group(1) if h1_m else ""
    assert "竞彩盘口" in title_text
    assert "世界杯" not in title_text
    assert "世界杯" not in h1_text


def test_filter_jingcai_priority():
    """_filter_jingcai_priority 默认只保留有竞彩编号/SP 的场（删除无编号的）。"""
    from web_ui import _filter_jingcai_priority
    matches = [
        {"fixture_id": "1", "predict_row": {}},  # 无编号 → 删除
        {"fixture_id": "2", "predict_row": {"竞彩编号": "周一001"}},  # 有编号 → 保留
        {"fixture_id": "3", "predict_row": {}},  # 无编号 → 删除
        {"fixture_id": "4", "jingcai": {"has_sp": True, "sp_home": 1.5}},  # 有 SP → 保留
        # 真实现场用 jingcai_snapshot，旧过滤器只看 m['jingcai'] 会误杀
        {"fixture_id": "5", "jingcai_snapshot": {"has_sp": True, "sp_home": 1.8}},
        {"fixture_id": "6", "match_num": "周二003"},
    ]
    result = _filter_jingcai_priority(matches)
    fids = [m["fixture_id"] for m in result]
    assert "1" not in fids  # 无编号的被删除
    assert "3" not in fids
    assert "2" in fids
    assert "4" in fids
    assert "5" in fids
    assert "6" in fids


def test_filter_jingcai_show_all():
    """show_all=True 返回全部（有竞彩排前，但不删除）。"""
    from web_ui import _filter_jingcai_priority
    matches = [
        {"fixture_id": "1", "predict_row": {}},
        {"fixture_id": "2", "predict_row": {"竞彩编号": "周一001"}},
    ]
    result = _filter_jingcai_priority(matches, show_all=True)
    fids = [m["fixture_id"] for m in result]
    assert "1" in fids  # 全部保留
    assert "2" in fids
    # 有竞彩的排前
    assert fids[0] == "2"


def test_dashboard_all_param():
    """?all=1 时首页状态行有「显示全部」链接。"""
    from pathlib import Path
    from web_ui import html_dashboard
    html = html_dashboard({}, None, output_root=Path("/tmp"), show_all=False)
    assert "显示全部" in html
    html_all = html_dashboard({}, None, output_root=Path("/tmp"), show_all=True)
    assert "显示全部" not in html_all


def test_match_has_jingcai_signal_variants():
    """_match_has_jingcai_signal 认所有真字段（现网必挂点）。"""
    from web_ui import _match_has_jingcai_signal
    # predict_row 编号
    assert _match_has_jingcai_signal({"predict_row": {"竞彩编号": "周二001"}})
    # match_num
    assert _match_has_jingcai_signal({"match_num": "周二003"})
    # jingcai_snapshot.has_sp（现网必挂点）
    assert _match_has_jingcai_signal({"jingcai_snapshot": {"has_sp": True}})
    # jingcai SP
    assert _match_has_jingcai_signal({"jingcai": {"sp_home": 1.5}})
    # jingcai_pick_info.jingcai_market 非空非 none
    assert _match_has_jingcai_signal({"jingcai_pick_info": {"jingcai_market": "spf"}})
    # predict_row 竞彩SP 有效
    assert _match_has_jingcai_signal({"predict_row": {"竞彩SP": "1.50/3.20/4.00"}})
    # 无信号 → False
    assert not _match_has_jingcai_signal({"predict_row": {}})
    assert not _match_has_jingcai_signal({"jingcai_pick_info": {"jingcai_market": "none"}})
    assert not _match_has_jingcai_signal({})
