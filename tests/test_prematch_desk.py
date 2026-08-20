"""Tests for the independent pre-match desk and cross-desk comparison summary."""

import pytest

from prematch_desk import (
    SUPPORTED_LEAGUES,
    attach_prematch_and_summary,
    build_comparison_summary,
    build_prematch_desk,
    ensure_prematch_attached,
    _resolve_league_name,
    _normalize_league_name,
)
from match_agents.factor_fetch import (
    _resolve_venue_from_catalog,
    enrich_match_factors,
)


def test_supported_leagues_are_top_five():
    short = {"英超", "西甲", "德甲", "意甲", "法甲"}
    long = {
        "英格兰超级联赛",
        "西班牙甲级联赛",
        "德国甲级联赛",
        "意大利甲级联赛",
        "法国甲级联赛",
    }
    assert short.issubset(SUPPORTED_LEAGUES)
    assert long.issubset(SUPPORTED_LEAGUES)
    assert not SUPPORTED_LEAGUES - short - long


def test_unsupported_league_returns_unavailable():
    desk = build_prematch_desk(league_name="日职")
    assert desk["available"] is False
    assert desk["league_supported"] is False
    assert desk["reason"] == "league_not_supported"
    assert not desk["dimensions"]


def test_supported_league_with_no_data_is_available_but_missing():
    desk = build_prematch_desk(league_name="英超")
    assert desk["available"] is True
    assert desk["league_supported"] is True
    ids = {d["id"] for d in desk["dimensions"]}
    assert ids == {"availability", "schedule_fatigue", "weather", "recent_status", "referee", "motivation"}
    assert all(d["missing"] for d in desk["dimensions"])
    assert desk["high_impact_facts"] == []


def test_comparison_summary_holds_when_no_high_impact():
    pred = {
        "judgment": "倾向客胜·小注",
        "result_1x2_cn": "客胜",
    }
    summary = build_comparison_summary(pred)
    assert summary["odds_desk_pick"] == "倾向客胜·小注"
    assert summary["action"] == "hold"
    assert summary["prematch_high_impact"] is False
    assert summary["cannot_flip_direction"] is True
    assert "维持" in summary["summary"]


def test_comparison_summary_skips_when_odds_desk_skip():
    pred = {"result_1x2_cn": "观望"}
    summary = build_comparison_summary(pred)
    assert summary["action"] == "skip"


def test_high_impact_fact_only_size_down_not_flip():
    pred = {
        "judgment": "倾向主胜·标准",
        "result_1x2_cn": "主胜",
    }
    desk = build_prematch_desk(league_name="英超")
    desk["high_impact_facts"] = ["主队主力门将确认缺阵"]
    summary = build_comparison_summary(pred, desk)
    assert summary["action"] == "size_down"
    assert "降成小注" in summary["summary"]
    assert "主胜" in summary["summary"]  # direction preserved


def test_action_never_flip():
    pred = {
        "judgment": "倾向客胜·小注",
        "result_1x2_cn": "客胜",
    }
    for league in SUPPORTED_LEAGUES:
        desk = build_prematch_desk(league_name=league)
        desk["high_impact_facts"] = ["客队核心停赛"]
        summary = build_comparison_summary(pred, desk)
        assert summary["action"] in {"hold", "size_down", "skip"}
        assert summary["action"] != "flip"
        assert "客胜" in summary["summary"] or summary["action"] == "skip"


def test_attach_prematch_and_summary_mutates_pred():
    pred = {"result_1x2_cn": "主胜"}
    attach_prematch_and_summary(pred, league_name="西甲")
    assert pred["league_name"] == "西甲"
    assert "prematch_desk" in pred
    assert "comparison_summary" in pred


def test_unsupported_league_still_shows_odds_conclusion():
    pred = {
        "league_name": "德乙",
        "judgment": "倾向客胜·小注",
    }
    attach_prematch_and_summary(pred, league_name="德乙")
    assert pred["comparison_summary"]["action"] == "hold"
    assert pred["comparison_summary"]["prematch_available"] is False
    assert "本场不在支持范围" in pred["prematch_desk"]["note"]


def test_empty_prediction_safe():
    desk = build_prematch_desk({})
    assert desk["available"] is False
    assert desk["reason"] == "league_not_supported"


def _availability_dim(desk: dict) -> dict:
    return next(d for d in desk["dimensions"] if d["id"] == "availability")


def test_regular_injury_in_evidence_not_high_impact():
    intel = {
        "injury": {
            "home": {
                "injuriesAndSuspensionsList": [
                    {
                        "personName": "张三",
                        "playerPositionDesc": "前锋",
                        "injuryFlag": "1",
                    }
                ]
            },
            "away": {"injuriesAndSuspensionsList": []},
        }
    }
    desk = build_prematch_desk(league_name="英超", sporttery_intel=intel)
    dim = _availability_dim(desk)
    assert dim["missing"] is False
    assert "张三" in " ".join(dim["evidence"])
    assert desk["high_impact_facts"] == []
    pred = {"judgment": "倾向主胜·标准", "result_1x2_cn": "主胜"}
    summary = build_comparison_summary(pred, desk)
    assert summary["action"] == "hold"


def test_goalkeeper_injury_triggers_size_down():
    intel = {
        "injury": {
            "home": {
                "injuriesAndSuspensionsList": [
                    {
                        "personName": "奥纳纳",
                        "playerPositionDesc": "门将",
                        "injuryFlag": "1",
                    }
                ]
            },
            "away": {"injuriesAndSuspensionsList": []},
        }
    }
    desk = build_prematch_desk(league_name="英超", sporttery_intel=intel)
    assert any("主力门将确认" in f for f in desk["high_impact_facts"])
    pred = {"judgment": "倾向主胜·标准", "result_1x2_cn": "主胜"}
    summary = build_comparison_summary(pred, desk)
    assert summary["action"] == "size_down"
    assert "主胜" in summary["summary"]


def test_bench_suspension_does_not_size_down():
    intel = {
        "injury": {
            "away": {
                "injuriesAndSuspensionsList": [
                    {"personName": "李四", "suspensionFlag": "1"}
                ]
            },
            "home": {"injuriesAndSuspensionsList": []},
        }
    }
    desk = build_prematch_desk(league_name="英超", sporttery_intel=intel)
    assert desk["high_impact_facts"] == []
    pred = {"judgment": "倾向客胜·标准", "result_1x2_cn": "客胜"}
    summary = build_comparison_summary(pred, desk)
    assert summary["action"] == "hold"


def test_key_suspension_triggers_size_down():
    intel = {
        "injury": {
            "away": {
                "injuriesAndSuspensionsList": [
                    {"personName": "王五", "suspensionFlag": "1", "appearanceCnt": 12}
                ]
            },
            "home": {"injuriesAndSuspensionsList": []},
        }
    }
    desk = build_prematch_desk(league_name="英超", sporttery_intel=intel)
    assert any("关键球员停赛" in f for f in desk["high_impact_facts"])
    pred = {"judgment": "倾向客胜·标准", "result_1x2_cn": "客胜"}
    summary = build_comparison_summary(pred, desk)
    assert summary["action"] == "size_down"
    assert "客胜" in summary["summary"]


def test_weather_missing_without_reliable_venue():
    desk = build_prematch_desk(league_name="英超")
    dim = next(d for d in desk["dimensions"] if d["id"] == "weather")
    assert dim["missing"] is True


def test_jleague_unavailable_but_comparison_shows_odds():
    pred = {
        "league_name": "日职",
        "judgment": "倾向主胜·标准",
        "result_1x2_cn": "主胜",
    }
    attach_prematch_and_summary(pred, league_name="日职")
    assert pred["prematch_desk"]["available"] is False
    assert pred["comparison_summary"]["action"] == "hold"
    assert "主胜" in pred["comparison_summary"]["summary"]


def test_ensure_prematch_attached_idempotent(monkeypatch):
    pred = {
        "prematch_desk": {"available": False},
        "comparison_summary": {"action": "hold"},
    }

    def _raise(*args, **kwargs):
        raise RuntimeError("should not be called")

    monkeypatch.setattr("prematch_desk.attach_prematch_and_summary", _raise)
    ensure_prematch_attached(pred, output_root="output/service", fixture_id="123")
    assert pred["comparison_summary"]["action"] == "hold"


def test_ensure_prematch_attached_attaches_when_missing():
    pred = {"fixture_id": "123", "league_name": "英超"}
    ensure_prematch_attached(pred, output_root="output/service", fixture_id="123")
    assert "prematch_desk" in pred
    assert "comparison_summary" in pred


def test_attach_prematch_forces_recalc_with_new_intel(monkeypatch):
    """传入 sporttery_intel 时必须用新伤停重算，不能因已有 summary 而跳过。"""
    pred = {
        "fixture_id": "124",
        "league_name": "英超",
        "judgment": "倾向主胜·标准",
        "result_1x2_cn": "主胜",
        "prematch_desk": {"available": False},
        "comparison_summary": {"action": "hold"},
    }
    intel = {
        "injury": {
            "home": {
                "injuriesAndSuspensionsList": [
                    {"personName": "门将A", "playerPositionDesc": "门将", "injuryFlag": "1"}
                ]
            },
            "away": {"injuriesAndSuspensionsList": []},
        }
    }
    monkeypatch.setattr("prematch_desk._is_supported_league", lambda _l: True)
    monkeypatch.setattr("prematch_desk._parse_teams", lambda _p: ("主队", "客队"))
    attach_prematch_and_summary(pred, sporttery_intel=intel)
    assert any("主力门将" in f for f in pred["prematch_desk"]["high_impact_facts"])
    assert pred["comparison_summary"]["action"] == "size_down"


def test_kickoff_and_venue_populate_weather(monkeypatch):
    """attach 用 kickoff + 球场坐标调用 enrich_match_factors，天气写入 weather 维度。"""
    pred = {
        "fixture_id": "125",
        "league_name": "英超",
        "home_team": "曼城",
        "away_team": "利物浦",
        "kickoff_at": "2026-08-22 15:00:00",
    }

    def fake_enrich(p, **kwargs):
        return {
            "weather": {
                "summary": "晴",
                "temperature_c": 22,
                "wind_kph": 12,
                "precipitation_mm": 0,
            },
            "venue": {"stadium": "伊蒂哈德球场", "lat": 53.4831, "lon": -2.2004},
        }

    monkeypatch.setattr("prematch_desk._is_supported_league", lambda _l: True)
    monkeypatch.setattr("match_agents.factor_fetch.enrich_match_factors", fake_enrich)
    attach_prematch_and_summary(pred)
    weather_dim = next(d for d in pred["prematch_desk"]["dimensions"] if d["id"] == "weather")
    assert weather_dim["missing"] is False
    assert "晴" in weather_dim["evidence"]


def test_club_form_populates_schedule_fatigue():
    """pred 有 club_form 时 schedule_fatigue 维度被填充。"""
    pred = {
        "fixture_id": "126",
        "league_name": "英超",
        "home_team": "曼城",
        "away_team": "利物浦",
        "club_form": {
            "samples": {
                "home_all": [
                    {"date": "2026-08-15"},
                    {"date": "2026-08-08"},
                    {"date": "2026-08-01"},
                ],
                "away_all": [
                    {"date": "2026-08-16"},
                    {"date": "2026-08-09"},
                ],
            }
        },
    }
    attach_prematch_and_summary(pred)
    schedule_dim = next(d for d in pred["prematch_desk"]["dimensions"] if d["id"] == "schedule_fatigue")
    assert schedule_dim["missing"] is False
    assert any("近7天" in e for e in schedule_dim["evidence"])


def test_ensure_prematch_recalc_when_intel_newer(monkeypatch, tmp_path):
    """sporttery_intel.json fetched_at 新于 desk as_of 时 ensure 强制重算。"""
    from prematch_desk import ensure_prematch_attached
    from sporttery_intel import save_sporttery_intel

    fid = "127"
    root = str(tmp_path)
    old_intel = {
        "injury": {"home": {"injuriesAndSuspensionsList": []}, "away": {"injuriesAndSuspensionsList": []}},
        "fetched_at": "2026-08-20 08:00:00",
    }
    save_sporttery_intel(root, fid, old_intel)

    pred = {
        "fixture_id": fid,
        "league_name": "英超",
        "judgment": "倾向主胜·标准",
        "result_1x2_cn": "主胜",
    }
    attach_prematch_and_summary(pred, output_root=root, fixture_id=fid)
    assert pred["comparison_summary"]["action"] == "hold"

    new_intel = {
        "injury": {
            "home": {
                "injuriesAndSuspensionsList": [
                    {"personName": "门将B", "playerPositionDesc": "门将", "injuryFlag": "1"}
                ]
            },
            "away": {"injuriesAndSuspensionsList": []},
        },
        "fetched_at": "2099-08-20 14:00:00",
    }
    save_sporttery_intel(root, fid, new_intel)

    ensure_prematch_attached(pred, output_root=root, fixture_id=fid)
    assert any("主力门将" in f for f in pred["prematch_desk"]["high_impact_facts"])
    assert pred["comparison_summary"]["action"] == "size_down"


def _patch_network(monkeypatch, *, weather=None):
    monkeypatch.setattr(
        "match_agents.factor_fetch.scrape_500_youliao", lambda fid: ({}, [])
    )
    monkeypatch.setattr(
        "match_agents.factor_fetch.search_match_intel",
        lambda *a, **k: ({}, []),
    )
    monkeypatch.setattr(
        "match_agents.factor_fetch.fetch_open_meteo_weather",
        lambda *a, **k: (weather or {}, []),
    )


def test_unmapped_team_does_not_fetch_weather(monkeypatch):
    _patch_network(monkeypatch)
    pred = {"fixture_id": "999", "home_team": "某未映射队", "away_team": "另一未映射队", "league_name": "英超"}
    factors = enrich_match_factors(pred)
    assert not factors["venue"]
    assert not factors["weather"]


def test_team_mapping_fetches_weather(monkeypatch):
    _patch_network(
        monkeypatch,
        weather={
            "source": "open_meteo",
            "summary": "晴",
            "temperature_c": 20,
            "wind_kph": 10,
        },
    )
    pred = {
        "fixture_id": "998",
        "home_team": "曼城",
        "away_team": "利物浦",
        "league_name": "英超",
    }
    factors = enrich_match_factors(pred)
    assert factors["venue"].get("catalog_source") == "team"
    assert factors["weather"]
    assert factors["weather"]["summary"] == "晴"


def test_resolve_venue_without_competition_fallback():
    pred = {"fixture_id": "997", "home_team": "某未知队", "league_name": "英超"}
    venue, _logs = _resolve_venue_from_catalog(
        pred, None, allow_competition_fallback=False
    )
    assert not venue


def test_team_mapping_resolves_venue():
    pred = {"fixture_id": "996", "home_team": "切尔西", "away_team": "曼城", "league_name": "英超"}
    venue, _logs = _resolve_venue_from_catalog(
        pred, None, allow_competition_fallback=False
    )
    assert venue.get("catalog_source") == "team"
    assert venue.get("stadium") == "斯坦福桥球场"


def test_vallecano_venue_and_weather(monkeypatch):
    """巴列卡诺应解析到巴列卡斯球场并可拉天气。"""
    _patch_network(
        monkeypatch,
        weather={
            "source": "open_meteo",
            "summary": "多云",
            "temperature_c": 25,
            "wind_kph": 8,
        },
    )
    pred = {
        "fixture_id": "9981",
        "home_team": "巴列卡诺",
        "away_team": "阿拉维斯",
        "league_name": "西甲",
    }
    factors = enrich_match_factors(pred)
    assert factors["venue"].get("stadium") == "巴列卡斯球场"
    assert factors["weather"]["summary"] == "多云"


def test_burnley_venue_and_weather(monkeypatch):
    """伯恩利应解析到特夫摩尔球场并可拉天气。"""
    _patch_network(
        monkeypatch,
        weather={
            "source": "open_meteo",
            "summary": "小雨",
            "temperature_c": 15,
            "wind_kph": 18,
        },
    )
    pred = {
        "fixture_id": "9982",
        "home_team": "伯恩利",
        "away_team": "卢顿",
        "league_name": "英超",
    }
    factors = enrich_match_factors(pred)
    assert factors["venue"].get("stadium") == "特夫摩尔球场"
    assert factors["weather"]["summary"] == "小雨"


def test_normalize_long_league_name():
    assert _normalize_league_name("西班牙甲级联赛") == "西甲"
    assert _normalize_league_name("英超") == "英超"
    assert _normalize_league_name("") == ""


def test_resolve_league_name_prefers_index():
    pred = {"league_name": "英超"}
    index = {"league_name": "西甲"}
    # index takes precedence over pred when provided explicitly
    assert _resolve_league_name(pred, index=index) == "西甲"


def test_resolve_league_name_from_predict_row():
    pred = {"predict_row": {"联赛": "西班牙甲级联赛"}}
    assert _resolve_league_name(pred) == "西甲"


def test_resolve_league_name_from_competition_field():
    pred = {"competition": "意大利甲级联赛"}
    assert _resolve_league_name(pred) == "意甲"


def test_attach_resolves_league_from_predict_row_and_makes_available():
    pred = {
        "fixture_id": "200",
        "predict_row": {"联赛": "西甲"},
        "judgment": "倾向主胜·标准",
        "result_1x2_cn": "主胜",
    }
    attach_prematch_and_summary(pred)
    assert pred["league_name"] == "西甲"
    assert pred["prematch_desk"]["available"] is True
    assert pred["comparison_summary"]["action"] == "hold"


def test_attach_resolves_unsupported_league_from_predict_row():
    pred = {
        "fixture_id": "201",
        "predict_row": {"联赛": "日职"},
        "judgment": "倾向主胜·标准",
        "result_1x2_cn": "主胜",
    }
    attach_prematch_and_summary(pred)
    assert pred["league_name"] == "日职"
    assert pred["prematch_desk"]["available"] is False
    assert pred["comparison_summary"]["action"] == "hold"
    assert "主胜" in pred["comparison_summary"]["summary"]


def test_ensure_prematch_uses_passed_league_name(monkeypatch):
    pred = {
        "fixture_id": "202",
        "judgment": "倾向客胜·小注",
        "result_1x2_cn": "客胜",
    }
    monkeypatch.setattr("prematch_desk._is_supported_league", lambda _l: True)
    ensure_prematch_attached(pred, output_root="output/service", fixture_id="202", league_name="德甲")
    assert pred["league_name"] == "德甲"
    assert pred["prematch_desk"]["league_name"] == "德甲"
    assert pred["comparison_summary"]["action"] == "hold"
    assert "客胜" in pred["comparison_summary"]["summary"]


def _dim(desk: dict, dim_id: str) -> dict:
    return next(d for d in desk["dimensions"] if d["id"] == dim_id)


def _make_table_20(*pairs: tuple[int, str, int, int]) -> list[dict]:
    """Build a minimal 20-team standings table."""
    rows: list[dict] = []
    for pos, name, pts, played in pairs:
        rows.append({
            "position": pos,
            "team": {"name": name},
            "points": pts,
            "playedGames": played,
        })
    # pad to 20
    for pos in range(len(pairs) + 1, 21):
        rows.append({
            "position": pos,
            "team": {"name": f"Team{pos}"},
            "points": 50,
            "playedGames": 38,
        })
    return rows


def test_motivation_with_standings(monkeypatch):
    """积分榜可用时 motivation 维度非 missing；末轮保级对话进 high_impact。"""
    table = _make_table_20(
        (17, "Nottingham Forest", 32, 38),
        (18, "Burnley", 24, 38),
        (19, "Luton Town", 26, 38),
        (20, "Sheffield United", 16, 38),
    )
    monkeypatch.setattr(
        "analysis.team_form.standings.load_standings",
        lambda league, output_root: table,
    )

    pred = {
        "fixture_id": "300",
        "league_name": "英超",
        "home_team": "伯恩利",
        "away_team": "卢顿",
        "judgment": "倾向主胜·标准",
        "result_1x2_cn": "主胜",
    }
    attach_prematch_and_summary(pred, output_root="output/service")
    motivation = _dim(pred["prematch_desk"], "motivation")
    assert motivation["missing"] is False
    assert "来自 football-data.org 积分榜" in motivation["note"]
    evidence_text = " ".join(motivation["evidence"])
    assert "主队排名第18" in evidence_text
    assert "客队排名第19" in evidence_text
    assert "联赛末轮" in evidence_text
    assert any("保级直接对话" in f for f in pred["prematch_desk"]["high_impact_facts"])
    # high impact 只能触发 size_down，不能 flip 方向
    assert pred["comparison_summary"]["action"] == "size_down"
    assert "主胜" in pred["comparison_summary"]["summary"]


def test_motivation_missing_without_standings(monkeypatch):
    """无积分榜数据时 motivation 保持 missing，裁判仍 missing。"""
    monkeypatch.setattr(
        "analysis.team_form.standings.load_standings",
        lambda *a, **k: None,
    )

    pred = {
        "fixture_id": "301",
        "league_name": "英超",
        "home_team": "曼城",
        "away_team": "利物浦",
        "judgment": "倾向主胜·标准",
        "result_1x2_cn": "主胜",
    }
    attach_prematch_and_summary(pred, output_root="output/service")
    motivation = _dim(pred["prematch_desk"], "motivation")
    referee = _dim(pred["prematch_desk"], "referee")
    assert motivation["missing"] is True
    assert referee["missing"] is True
    assert pred["comparison_summary"]["action"] == "hold"
