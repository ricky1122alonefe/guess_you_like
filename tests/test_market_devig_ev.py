"""P1/P4/P5 测试：去水概率 + 串关 EV + AI payload。"""
from analysis.market.devig import devig_1x2, devig_from_odds
from analysis.market.parlay_ev import compute_leg_ev, compute_parlay_ev
from analysis.market.ai_payload import build_ai_match_brief_payload, payload_to_markdown


# ============ P1: devig ============

def test_devig_proportional_sum_one():
    """去水后概率和 = 1。"""
    r = devig_1x2(2.0, 3.2, 3.8)
    assert abs(r["p_home"] + r["p_draw"] + r["p_away"] - 1.0) < 0.001
    assert r["overround"] > 0  # 有抽水


def test_devig_overround_positive():
    """抽水 > 0。"""
    r = devig_1x2(1.5, 4.0, 6.0)
    assert r["overround"] > 0.01  # 毛赔有抽水


def test_devig_fair_odds():
    """fair_odds 为去水后公平赔率。"""
    r = devig_1x2(2.0, 3.2, 3.8)
    assert r["fair_odds"]["home"] > 2.0  # 公平赔率 > 毛赔


def test_devig_invalid_odds():
    """无效赔率返回全 0。"""
    r = devig_1x2(0, 0, 0)
    assert r["p_home"] == 0
    assert r["overround"] == 0


def test_devig_from_odds_dict():
    """从 dict 提取去水。"""
    r = devig_from_odds({"eu_home": 2.0, "eu_draw": 3.0, "eu_away": 4.0})
    assert abs(r["p_home"] + r["p_draw"] + r["p_away"] - 1.0) < 0.001


# ============ P4: 串关 EV ============

def test_parlay_ev_two_legs():
    """2 场串关 EV 计算。"""
    legs = [
        {"pick": "home", "p_model": 0.50, "odds": 2.0, "match_name": "A vs B"},
        {"pick": "away", "p_model": 0.40, "odds": 2.5, "match_name": "C vs D"},
    ]
    r = compute_parlay_ev(legs)
    assert r["ok"]
    assert r["n_legs"] == 2
    assert abs(r["parlay_odds"] - 5.0) < 0.01  # 2.0 * 2.5
    assert abs(r["parlay_p"] - 0.20) < 0.001  # 0.5 * 0.4
    # EV = 0.20 * 5.0 - 1 = 0
    assert abs(r["parlay_ev"] - 0.0) < 0.01


def test_parlay_ev_three_legs():
    """3 场串关 EV 计算。"""
    legs = [
        {"pick": "home", "p_model": 0.60, "odds": 1.8, "match_name": "A vs B"},
        {"pick": "home", "p_model": 0.55, "odds": 2.0, "match_name": "C vs D"},
        {"pick": "away", "p_model": 0.45, "odds": 2.2, "match_name": "E vs F"},
    ]
    r = compute_parlay_ev(legs)
    assert r["ok"]
    assert r["n_legs"] == 3
    assert r["parlay_odds"] > 0
    assert r["parlay_p"] > 0


def test_parlay_ev_single_leg_rejected():
    """1 场不可串关。"""
    r = compute_parlay_ev([{"pick": "home", "p_model": 0.5, "odds": 2.0}])
    assert not r["ok"]


def test_parlay_ev_missing_odds():
    """缺赔率 → ok=False。"""
    legs = [
        {"pick": "home", "p_model": 0.5, "odds": 0, "match_name": "A vs B"},
        {"pick": "away", "p_model": 0.4, "odds": 2.5, "match_name": "C vs D"},
    ]
    r = compute_parlay_ev(legs)
    assert not r["ok"]


def test_single_leg_ev():
    """单腿 EV。"""
    ev = compute_leg_ev("home", 0.5, 2.0)
    assert abs(ev["ev"] - 0.0) < 0.001  # 0.5 * 2.0 - 1 = 0


def test_parlay_ev_three_legs_with_names():
    """FIX-2: 3 场串关 EV（含 match_name + odds_source）。"""
    legs = [
        {"pick": "home", "p_model": 0.55, "odds": 2.0, "match_name": "A vs B", "odds_source": "竞彩SP"},
        {"pick": "draw", "p_model": 0.30, "odds": 3.2, "match_name": "C vs D", "odds_source": "欧赔"},
        {"pick": "away", "p_model": 0.40, "odds": 2.5, "match_name": "E vs F", "odds_source": "竞彩SP"},
    ]
    r = compute_parlay_ev(legs)
    assert r["ok"]
    assert r["n_legs"] == 3
    assert r["parlay_odds"] == 16.0  # 2.0 * 3.2 * 2.5
    assert abs(r["parlay_p"] - 0.066) < 0.001  # 0.55*0.30*0.40
    # legs_ev 含 match_name + odds_source
    assert r["legs_ev"][0]["match"] == "A vs B"
    assert r["legs_ev"][0]["odds_source"] == "竞彩SP"


def test_parlay_ev_two_legs_jingcai_sp():
    """FIX-2: 2 场串关用竞彩 SP。"""
    legs = [
        {"pick": "home", "p_model": 0.50, "odds": 1.85, "match_name": "A vs B", "odds_source": "竞彩SP"},
        {"pick": "away", "p_model": 0.45, "odds": 2.10, "match_name": "C vs D", "odds_source": "竞彩SP"},
    ]
    r = compute_parlay_ev(legs)
    assert r["ok"]
    assert abs(r["parlay_odds"] - 3.885) < 0.01
    assert all(l["odds_source"] == "竞彩SP" for l in r["legs_ev"])


# ============ P5: AI payload ============

def test_ai_payload_structure():
    """AI payload 含 market/form/rule_conclusion/missing。"""
    payload = build_ai_match_brief_payload(
        "A vs B",
        market={"devig": {"p_home": 0.5, "p_draw": 0.3, "p_away": 0.2, "overround": 0.05}},
        form={"overall": {"home_team": {"summary_cn": "近30场15胜"}}},
        rule_conclusion={"pick": "home", "pick_cn": "主胜", "reasons": ["欧赔去水主50%"]},
    )
    assert payload["match"] == "A vs B"
    assert payload["market"]["devig"]["p_home"] == 0.5
    assert payload["form"]["overall"]["home_team"]["summary_cn"]
    assert payload["rule_conclusion"]["pick"] == "home"
    assert "devig" not in payload["missing"]  # 有 devig


def test_ai_payload_missing():
    """缺数据进 missing。"""
    payload = build_ai_match_brief_payload("A vs B")
    assert "devig" in payload["missing"]
    assert "asian" in payload["missing"]
    assert "betfair" in payload["missing"]
    assert "form" in payload["missing"]


def test_ai_payload_markdown():
    """payload 转 markdown 可读。"""
    payload = build_ai_match_brief_payload(
        "A vs B",
        market={"devig": {"p_home": 0.5, "p_draw": 0.3, "p_away": 0.2, "overround": 0.05}},
        rule_conclusion={"pick": "home", "pick_cn": "主胜", "confidence_cn": "高", "reasons": ["test"]},
        jingcai={"has_sp": False},
    )
    md = payload_to_markdown(payload)
    assert "A vs B" in md
    assert "去水隐含概率" in md
    assert "主胜" in md
    assert "无竞彩" in md
