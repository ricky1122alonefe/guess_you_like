"""Tests for analysis.market.eu_ah_divergence_ctx."""
from __future__ import annotations

import pytest

from analysis.market import eu_ah_divergence_ctx as ctxmod


def test_build_eu_ah_divergence_from_snapshot():
    fixture = {
        "id": 1,
        "external_id": "999",
        "match_name": "主队VS客队",
        "kickoff_at": "2026-08-12T18:00:00+00:00",
    }
    snap = {
        "eu_home": 2.0,
        "eu_draw": 3.5,
        "eu_away": 3.8,
        "eu_open_home": 2.1,
        "eu_open_draw": 3.4,
        "eu_open_away": 3.7,
        "ah_line": 0.25,
        "ah_home_water": 0.95,
        "ah_away_water": 0.95,
        "ah_open_line": 0.0,
        "ah_open_home_water": 0.95,
        "ah_open_away_water": 0.95,
    }
    div = ctxmod._build_snapshot_from_cur(snap, fixture["external_id"], fixture["match_name"])
    assert div is not None
    assert div["divergence_score"] >= 0
    assert "severity_cn" in div
    assert "signals" in div
    assert "advice" in div


def test_build_eu_ah_divergence_missing_odds():
    fixture = {
        "id": 1,
        "external_id": "998",
        "match_name": "主队VS客队",
    }
    # No odds
    div = ctxmod._build_snapshot_from_cur({}, fixture["external_id"], fixture["match_name"])
    assert div is None or div.get("missing")


def test_divergence_score_calculation():
    # Strong line gap should produce high score
    snap = {
        "eu_home": 1.6,
        "eu_draw": 4.0,
        "eu_away": 5.0,
        "ah_line": -0.25,
        "ah_home_water": 0.9,
        "ah_away_water": 1.0,
    }
    div = ctxmod._build_snapshot_from_cur(snap, "997", "A VS B")
    assert div
    assert div["divergence_score"] >= 50


def test_severity_cn_mapping():
    snap = {
        "eu_home": 2.0,
        "eu_draw": 3.5,
        "eu_away": 3.8,
        "ah_line": 0.25,
        "ah_home_water": 0.95,
        "ah_away_water": 0.95,
    }
    div = ctxmod._build_snapshot_from_cur(snap, "996", "A VS B")
    assert div
    assert div["severity_cn"] in ("基本一致", "轻度分歧", "明显分歧", "巨大分歧")


def test_report_uses_db_and_output(monkeypatch, tmp_path):
    fake_fixtures = [
        {"id": 1, "external_id": "1420010", "source": "500", "home_team": "A", "away_team": "B", "match_name": "A VS B", "kickoff_at": "2026-08-12T18:00:00+00:00"},
        {"id": 2, "external_id": "1420011", "source": "500", "home_team": "C", "away_team": "D", "match_name": "C VS D", "kickoff_at": "2026-08-12T20:00:00+00:00"},
    ]
    monkeypatch.setattr(
        "analysis.signals.eu_ah_divergence._fixtures_with_odds_within",
        lambda source, within_days=7, limit=500: fake_fixtures,
    )

    def fake_build(ext, fixture=None):
        if ext == "1420010":
            return {"fixture_id": ext, "divergence_score": 75, "severity": "extreme", "severity_cn": "巨大分歧", "signals": ["gap"], "advice": "注意", "line_gap": 0.75}
        return {"missing": ["no_odds"], "fixture_id": ext}

    monkeypatch.setattr(
        "analysis.market.eu_ah_divergence_ctx.build_eu_ah_divergence",
        fake_build,
    )

    # 隔离 output/service 缓存扫描，避免真实目录数据影响断言。
    monkeypatch.setattr(
        "daily_picks.load_dashboard_matches",
        lambda *a, **k: [],
    )
    monkeypatch.setattr(
        "analysis.signals.eu_ah_divergence.scan_eu_ah_divergence",
        lambda *a, **k: {"matches": []},
    )

    from analysis.signals.eu_ah_divergence import build_divergence_report

    r = build_divergence_report(str(tmp_path), within_days=7)
    assert r["scanned"] == 2
    assert len(r["matches"]) == 1
    assert r["matches"][0]["divergence_score"] == 75
    assert r["matches"][0]["fixture_id"] == "1420010"
