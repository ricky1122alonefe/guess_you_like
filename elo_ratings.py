"""Lightweight Elo ratings for fixtures.

产品定位：
主证据仍为盘口（开/即）+ 战绩 + 同赔频率；Elo 仅作为轻量模型对照层，
不压过同赔主结论。队名通过 jingcai_league_map 与 fixtures 对齐。
"""

from __future__ import annotations

import json
import logging
from contextlib import closing
from pathlib import Path
from typing import Any

import config

log = logging.getLogger(__name__)

TIER_SEED = {"elite": 2100, "strong": 2000, "mid": 1900, "weak": 1750}

DEFAULT_RATING = float(getattr(config, "ELO_DEFAULT_RATING", 1500.0))
K_FACTOR = float(getattr(config, "ELO_K_FACTOR", 32.0))
HOME_ADV = float(getattr(config, "ELO_HOME_ADVANTAGE", 70.0))
LOGISTIC_SCALE = float(getattr(config, "ELO_LOGISTIC_SCALE", 400.0))
DRAW_BASE = float(getattr(config, "ELO_DRAW_BASE", 0.25))

_DATA = Path(__file__).resolve().parent / "data" / "elo_ratings.json"


def _load_groups_config() -> dict:
    path = Path(__file__).resolve().parent / "data" / "wc2026_groups.json"
    return json.loads(path.read_text(encoding="utf-8"))


def seed_ratings() -> dict[str, float]:
    cfg = _load_groups_config()
    tiers = cfg.get("team_strength_tiers") or {}
    ratings: dict[str, float] = {}
    for teams in (cfg.get("groups") or {}).values():
        for t in teams:
            ratings[t] = float(TIER_SEED.get(tiers.get(t, "mid"), DEFAULT_RATING))
    return ratings


def load_ratings() -> dict[str, float]:
    if _DATA.is_file():
        try:
            data = json.loads(_DATA.read_text(encoding="utf-8"))
            if isinstance(data.get("ratings"), dict):
                return {k: float(v) for k, v in data["ratings"].items()}
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    return seed_ratings()


def save_ratings(ratings: dict[str, float]) -> None:
    _DATA.parent.mkdir(parents=True, exist_ok=True)
    _DATA.write_text(
        json.dumps({"ratings": ratings}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def expected_score(r_a: float, r_b: float, *, home_adv: float = HOME_ADV) -> float:
    """Logistic 期望得分，含主场优势。"""
    return 1.0 / (1.0 + 10 ** ((r_b - (r_a + home_adv)) / LOGISTIC_SCALE))


def _map_elo_to_1x2(elo_diff: float) -> dict[str, float]:
    """把 Elo 差映射到 1X2 概率（主/平/客）。

    方法：主客胜率用 Logistic；平局概率用一个随实力差衰减的基准，
    最后归一化。简单、透明、不假装精度。
    """
    p_home = 1.0 / (1.0 + 10 ** (-elo_diff / LOGISTIC_SCALE))
    p_away = 1.0 / (1.0 + 10 ** (elo_diff / LOGISTIC_SCALE))
    p_draw = max(0.05, DRAW_BASE - abs(elo_diff) / 2000.0)
    total = p_home + p_draw + p_away
    return {
        "home": round(p_home / total, 4),
        "draw": round(p_draw / total, 4),
        "away": round(p_away / total, 4),
        "method": "logistic_with_draw_base",
    }


def _resolve_team_name_for_elo(name: str, league_name: str | None = None) -> str:
    """通过 jingcai_league_map 把别名/显示名对齐到 Elo 评分主键。"""
    try:
        from analysis.team_form.club_form import _resolve_team_name

        resolved = _resolve_team_name(name, league_name)
        if resolved:
            return resolved
    except Exception as exc:
        log.debug("resolve team name failed: %s", exc)
    return name


def update_elo(
    ratings: dict[str, float],
    home: str,
    away: str,
    hg: int,
    ag: int,
) -> dict[str, float]:
    """单场 Elo 更新；返回同一 ratings 对象。"""
    ra = ratings.setdefault(home, DEFAULT_RATING)
    rb = ratings.setdefault(away, DEFAULT_RATING)
    if hg > ag:
        sa, sb = 1.0, 0.0
    elif hg == ag:
        sa, sb = 0.5, 0.5
    else:
        sa, sb = 0.0, 1.0
    ea = expected_score(ra, rb)
    eb = 1.0 - ea
    ratings[home] = ra + K_FACTOR * (sa - ea)
    ratings[away] = rb + K_FACTOR * (sb - eb)
    return ratings


def apply_finished_results(results: list[dict]) -> dict[str, float]:
    ratings = load_ratings()
    for r in results:
        home = r.get("home_team") or r.get("home")
        away = r.get("away_team") or r.get("away")
        hs, aws = r.get("home_score"), r.get("away_score")
        if not home or not away or hs is None or aws is None:
            continue
        try:
            update_elo(ratings, str(home), str(away), int(hs), int(aws))
        except (TypeError, ValueError):
            continue
    save_ratings(ratings)
    return ratings


def refresh_elo_from_match_results(
    ratings: dict[str, float] | None = None,
) -> dict[str, float]:
    """用自有 settle 的 match_results 按 kickoff 顺序滚动更新 Elo。

    只取 status='finished' 且 home_score/away_score 非空的场。
    队名通过 jingcai_league_map 对齐；未知队给默认分，不崩。
    """
    if ratings is None:
        ratings = load_ratings()
    try:
        from db.connection import connect
    except Exception as exc:
        log.warning("无法加载数据库连接: %s", exc)
        return ratings

    sql = """
        SELECT f.home_team, f.away_team, mr.home_score, mr.away_score
        FROM match_results mr
        JOIN fixtures f ON f.id = mr.fixture_id
        WHERE mr.status = 'finished'
          AND mr.home_score IS NOT NULL
          AND mr.away_score IS NOT NULL
        ORDER BY f.kickoff_at ASC NULLS LAST, mr.settled_at ASC NULLS LAST
    """
    try:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall()
    except Exception as exc:
        log.warning("读取 match_results 失败: %s", exc)
        return ratings

    for home_raw, away_raw, hs, aws in rows:
        home = _resolve_team_name_for_elo(home_raw or "")
        away = _resolve_team_name_for_elo(away_raw or "")
        if not home or not away or hs is None or aws is None:
            continue
        try:
            update_elo(ratings, home, away, int(hs), int(aws))
        except (TypeError, ValueError):
            continue

    save_ratings(ratings)
    return ratings


def match_elo_context(
    home: str,
    away: str,
    *,
    ratings: dict[str, float] | None = None,
    home_advantage: float = HOME_ADV,
) -> dict[str, Any]:
    """返回单场的 Elo 上下文：rating、diff、logistic 1X2 映射。"""
    ratings = ratings or load_ratings()
    home_key = _resolve_team_name_for_elo(home or "")
    away_key = _resolve_team_name_for_elo(away or "")

    home_elo = ratings.get(home_key, DEFAULT_RATING)
    away_elo = ratings.get(away_key, DEFAULT_RATING)
    elo_diff_with_hfa = home_elo - away_elo + home_advantage

    p_elo_1x2 = _map_elo_to_1x2(elo_diff_with_hfa)
    return {
        "home": home,
        "away": away,
        # 兼容旧调用：保留 home_team/away_team 与概率百分比字段
        "home_team": home,
        "away_team": away,
        "home_elo": round(float(home_elo), 0),
        "away_elo": round(float(away_elo), 0),
        "elo_diff": round(elo_diff_with_hfa, 0),
        "home_advantage": home_advantage,
        "expected_home_score": round(expected_score(home_elo, away_elo, home_adv=home_advantage), 4),
        "home_win_prob": p_elo_1x2["home"],
        "draw_prob": p_elo_1x2["draw"],
        "away_prob": p_elo_1x2["away"],
        "home_win_prob_pct": round(p_elo_1x2["home"] * 100, 1),
        "draw_prob_pct": round(p_elo_1x2["draw"] * 100, 1),
        "away_prob_pct": round(p_elo_1x2["away"] * 100, 1),
        "p_elo_1x2": p_elo_1x2,
        "method": "elo_logistic_with_hfa",
    }
