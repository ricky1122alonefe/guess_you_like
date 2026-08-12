"""历史同赔匹配：基于本场开盘/即盘欧亚检索相似历史赛果。"""

from __future__ import annotations

import logging
from typing import Any

from analysis.market.odds_lifecycle import get_match_odds_lifecycle
from history import load_all_history
from match import MatchConfig, find_similar, find_similar_eu_only, summarize
from parser import MatchOdds
from similar_samples import build_similarity_analysis

log = logging.getLogger(__name__)


def _as_match_odds(odds: dict | None, match_name: str = "") -> MatchOdds | None:
    """将 tick_summary 字典转为 MatchOdds。"""
    if not odds:
        return None
    return MatchOdds(
        match_name=match_name,
        ah_line=odds.get("ah_line"),
        ah_home_water=odds.get("ah_home_water"),
        ah_away_water=odds.get("ah_away_water"),
        ah_open_line=odds.get("ah_open_line") or odds.get("ah_line"),
        ah_open_home_water=odds.get("ah_open_home_water") or odds.get("ah_home_water"),
        ah_open_away_water=odds.get("ah_open_away_water") or odds.get("ah_away_water"),
        eu_home=odds.get("eu_home"),
        eu_draw=odds.get("eu_draw"),
        eu_away=odds.get("eu_away"),
        eu_open_home=odds.get("eu_open_home") or odds.get("eu_home"),
        eu_open_draw=odds.get("eu_open_draw") or odds.get("eu_draw"),
        eu_open_away=odds.get("eu_open_away") or odds.get("eu_away"),
        bookmaker="pinnacle",
    )


def _summarize_to_history(block: dict | None) -> dict[str, Any] | None:
    """把 build_similarity_analysis 中的 compact block 转成 history_similar 标准结构。"""
    if not block or not block.get("count"):
        return None
    ph = _safe_float(block.get("home_win_rate"))
    pd = _safe_float(block.get("draw_rate"))
    pa = _safe_float(block.get("away_win_rate"))
    if ph is None and pd is None and pa is None:
        return None
    ph, pd, pa = float(ph or 0), float(pd or 0), float(pa or 0)
    total = ph + pd + pa
    if total <= 0:
        return None
    return {
        "n": block["count"],
        "count": block["count"],
        "p_home": ph,
        "p_draw": pd,
        "p_away": pa,
        "p": {"home": ph / total, "draw": pd / total, "away": pa / total},
        "samples": block.get("samples") or [],
        "method": block.get("source", "open_eu"),
        "avg_total_goals": block.get("avg_total_goals"),
        "top_scores": block.get("top_scores") or [],
    }


def _safe_float(v):
    from analysis.result_forecast.context import _safe_float as ctx_safe_float
    return ctx_safe_float(v)


def build_history_similar(
    external_id: str,
    *,
    phase: str = "open",
    use_ah: bool = True,
    history=None,
    sample_limit: int = 10,
    min_samples: int = 20,
) -> dict[str, Any] | None:
    """基于本场开盘（默认）或即盘赔率匹配历史同赔。

    Args:
        external_id: fixture external_id
        phase: "open" 用开盘赔率，"close" 用临盘赔率
        use_ah: 是否同时用亚盘线过滤；False 只做欧赔
        history: 预加载历史 DataFrame；None 时自动加载
        sample_limit: Top 样本条数
        min_samples: 及格样本数；不足时自动放宽容差一次
    """
    lifecycle = get_match_odds_lifecycle(external_id)
    odds_key = "opening" if phase == "open" else "latest"
    odds = lifecycle.get(odds_key)
    if not odds:
        return None

    current = _as_match_odds(odds, match_name=lifecycle.get("match_name") or "")
    if not current:
        return None

    if history is None:
        try:
            history = load_all_history()
        except Exception as exc:
            log.warning("加载历史数据失败 %s: %s", external_id, exc)
            return None

    if history.empty:
        return None

    cfg = MatchConfig()
    if use_ah and current.ah_line is not None:
        similar = find_similar(history, current, cfg, phase=phase)
    else:
        similar = find_similar_eu_only(history, current, cfg, phase=phase)

    auto_relaxed = False
    if len(similar) < min_samples:
        from config import RELAXED_LINE_TOL, RELAXED_WATER_TOL, RELAXED_EU_HOME_TOL
        relaxed_cfg = MatchConfig(
            line_tol=RELAXED_LINE_TOL,
            water_tol=RELAXED_WATER_TOL,
            eu_home_tol=RELAXED_EU_HOME_TOL,
        )
        if use_ah and current.ah_line is not None:
            relaxed = find_similar(history, current, relaxed_cfg, phase=phase)
        else:
            relaxed = find_similar_eu_only(history, current, relaxed_cfg, phase=phase)
        if len(relaxed) > len(similar):
            similar = relaxed
            cfg = relaxed_cfg
            auto_relaxed = True

    stats = summarize(
        similar,
        sample_limit=sample_limit,
        current=current,
        cfg=cfg,
        include_ah=use_ah and current.ah_line is not None,
    )

    # 用 similar_samples 统一格式化，再抽取目标 block
    payload = {
        "open_stats": stats if phase == "open" and use_ah else {},
        "open_eu_stats": stats if phase == "open" and not use_ah else {},
        "stats": stats if phase == "close" and use_ah else {},
        "eu_stats": stats if phase == "close" and not use_ah else {},
        "history_total": len(history),
        "auto_relaxed": auto_relaxed,
    }
    sim_root = build_similarity_analysis(payload)

    # 优先取开盘欧赔；否则开盘亚盘；否则临盘欧赔；否则临盘亚盘
    # 顺序：开盘欧赔 > 开盘亚盘 > 临盘欧赔 > 临盘亚盘
    by_source: dict[str, dict] = {}
    for b in sim_root.get("open", []) + sim_root.get("live", []):
        by_source[b.get("source", "")] = b
    candidates = [by_source.get(s) for s in ("open_eu", "open_ah", "live_eu", "live_ah")]
    for block in candidates:
        hist = _summarize_to_history(block)
        if hist:
            hist["auto_relaxed"] = auto_relaxed
            return hist
    return None
