"""standings CLI / 缓存刷新测试（football-data.org 积分榜 motivation 维）。

覆盖：
- 无 API key：诚实 missing，不拉取不写缓存
- 有 key：拉取并写缓存、失败标记 failed
- 新鲜缓存复用（TTL），不重复拉取
- build_standings_context 携带 total_teams（is_relegation_battle 依赖）
"""
from analysis.team_form import standings


FAKE_PAYLOAD = {
    "competition": {"name": "Premier League"},
    "season": {"currentMatchday": 38},
    "standings": [
        {
            "type": "TOTAL",
            "table": [
                {"position": 1, "team": {"name": "Arsenal"}, "points": 82, "playedGames": 38},
                {"position": 17, "team": {"name": "Burnley"}, "points": 24, "playedGames": 38},
                {"position": 18, "team": {"name": "Luton Town"}, "points": 26, "playedGames": 38},
            ],
        }
    ],
}


def test_refresh_no_key_skips_all(monkeypatch, tmp_path):
    monkeypatch.setattr(standings, "_api_key", lambda: None)
    statuses = standings.refresh_standings_cache(tmp_path, force=True)
    assert set(statuses) == set(standings._LEAGUE_CODES)
    assert all(s == "no_key" for s in statuses.values())
    # 不写任何缓存文件，load 也诚实返回 None
    assert list(tmp_path.rglob("*.json")) == []
    assert standings.load_standings("英超", tmp_path) is None


def test_refresh_with_key_fetches_and_caches(monkeypatch, tmp_path):
    monkeypatch.setattr(standings, "_api_key", lambda: "test-key")
    monkeypatch.setattr(
        standings, "fetch_standings",
        lambda league, api_key=None: FAKE_PAYLOAD,
    )
    statuses = standings.refresh_standings_cache(tmp_path, force=True)
    assert all(s == "ok" for s in statuses.values())
    # 缓存已写且可被 load_standings 复用
    table = standings.load_standings("英超", tmp_path)
    assert table and table[0]["position"] == 1
    assert list(tmp_path.rglob("standings/*.json"))


def test_refresh_fetch_failure_reports_failed(monkeypatch, tmp_path):
    monkeypatch.setattr(standings, "_api_key", lambda: "test-key")
    monkeypatch.setattr(standings, "fetch_standings", lambda league, api_key=None: None)
    statuses = standings.refresh_standings_cache(tmp_path, force=True)
    assert all(s == "failed" for s in statuses.values())


def test_refresh_reuses_fresh_cache(monkeypatch, tmp_path):
    """force=False 时新鲜缓存不触发网络拉取。"""
    monkeypatch.setattr(standings, "_api_key", lambda: "test-key")
    calls = {"n": 0}

    def fake_fetch(league, api_key=None):
        calls["n"] += 1
        return FAKE_PAYLOAD

    monkeypatch.setattr(standings, "fetch_standings", fake_fetch)
    first = standings.refresh_standings_cache(tmp_path, force=True)
    assert all(s == "ok" for s in first.values())
    assert calls["n"] == len(standings._LEAGUE_CODES)

    second = standings.refresh_standings_cache(tmp_path, force=False)
    assert all(s == "ok" for s in second.values())
    assert calls["n"] == len(standings._LEAGUE_CODES)  # 新鲜缓存，未再拉取


def test_load_standings_no_key_honest_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(standings, "_api_key", lambda: None)
    assert standings.load_standings("英超", tmp_path) is None


def test_build_standings_context_has_total_teams():
    table = [
        {"position": 17, "team": {"name": "Burnley"}, "points": 24, "playedGames": 20},
        {"position": 18, "team": {"name": "Luton Town"}, "points": 26, "playedGames": 20},
    ]
    ctx = standings.build_standings_context(table, "伯恩利", "卢顿", "英超")
    assert ctx["total_teams"] == 2
    assert ctx["total_rounds"] == 2  # (2-1)*2
    assert ctx["is_final_round"] is True  # played=20 >= total_rounds=2
    # is_relegation_battle 用 total_teams 而非 fallback
    assert standings.is_relegation_battle(ctx) is True


def test_cli_main_no_key_returns_error(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(standings, "_api_key", lambda: None)
    rc = standings.main(["-o", str(tmp_path)])
    assert rc == 1
    out, err = capsys.readouterr()
    assert "未配置 FOOTBALL_DATA_API_KEY" in out
    assert "FOOTBALL_DATA_API_KEY" in err
