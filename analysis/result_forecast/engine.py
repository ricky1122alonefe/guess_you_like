"""T2: 规则融合「结果预测」引擎。

五源权重（可配置，默认）：
  1. history_similar  0.35  — 历史相似 1X2 分布
  2. european         0.25  — 欧赔去水隐含概率
  3. asian            0.15  — 亚盘方向（映射到主/客倾向）
  4. betfair          0.15  — 必发热度与资金方向
  5. recent_form      0.10  — 近期战绩（主客近况差）

规则：
  - 权重在 missing 源上按比例重分配到「仍有」的源
  - pick = argmax(p_home, p_draw, p_away)；max(p) < 0.38 → skip
  - 欧亚严重分歧 → confidence 降级
  - reasons[]：每个进入融合的源至少 1 条中文短句
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# 默认权重（与 config.py RESULT_FORECAST_WEIGHTS 对齐）
DEFAULT_WEIGHTS: dict[str, float] = {
    "history_similar": 0.35,
    "european": 0.25,
    "asian": 0.15,
    "betfair": 0.15,
    "recent_form": 0.10,
}
SKIP_THRESHOLD = 0.38
HIGH_CONFIDENCE = 0.50

RESULT_CN = {"home": "主胜", "draw": "平", "away": "客胜", "skip": "观望"}


def _get_weights() -> dict[str, float]:
    """从 config.py 读取权重，回退默认。"""
    try:
        import config as cfg
        w = getattr(cfg, "RESULT_FORECAST_WEIGHTS", None)
        if w and isinstance(w, dict):
            return dict(w)
    except ImportError:
        pass
    return dict(DEFAULT_WEIGHTS)


def _get_skip_threshold() -> float:
    try:
        import config as cfg
        return float(getattr(cfg, "RESULT_FORECAST_SKIP_THRESHOLD", SKIP_THRESHOLD))
    except (ImportError, TypeError, ValueError):
        return SKIP_THRESHOLD


def _asian_to_probs(asian: dict) -> dict[str, float]:
    """亚盘方向 → 概率分布。"""
    favored = asian.get("favored", "even")
    line = abs(asian.get("line", 0))
    home_water = asian.get("home_water") or 0.9
    away_water = asian.get("away_water") or 0.9
    if favored == "home":
        p_home = 0.42 + min(line * 0.04, 0.15)
        p_away = 0.30 - min(line * 0.03, 0.10)
    elif favored == "away":
        p_home = 0.30 - min(line * 0.03, 0.10)
        p_away = 0.42 + min(line * 0.04, 0.15)
    else:
        p_home = 0.35
        p_away = 0.33
    # 水位微调：低水方更热
    if home_water > 0 and away_water > 0:
        diff = (away_water - home_water) * 0.05
        p_home = max(0.10, p_home + diff)
        p_away = max(0.10, p_away - diff)
    p_draw = max(0.15, 1.0 - p_home - p_away)
    total = p_home + p_draw + p_away
    return {"home": p_home / total, "draw": p_draw / total, "away": p_away / total}


def _recent_to_probs(recent: dict) -> dict[str, float]:
    """近期战绩 → 概率分布。"""
    home = recent.get("home") or {}
    away = recent.get("away") or {}
    hw = home.get("win_rate")
    aw = away.get("win_rate")
    if hw is not None and aw is not None:
        # 胜率差映射
        diff = float(hw) - float(aw)
        p_home = 0.38 + diff * 0.3
        p_away = 0.32 - diff * 0.3
    elif hw is not None:
        p_home = 0.35 + float(hw) * 0.1
        p_away = 0.32
    elif aw is not None:
        p_away = 0.35 + float(aw) * 0.1
        p_home = 0.32
    else:
        return {"home": 0.35, "draw": 0.33, "away": 0.32}
    p_home = max(0.10, min(0.70, p_home))
    p_away = max(0.10, min(0.70, p_away))
    p_draw = max(0.15, 1.0 - p_home - p_away)
    total = p_home + p_draw + p_away
    return {"home": p_home / total, "draw": p_draw / total, "away": p_away / total}


def _build_reasons(context: dict, fused: dict[str, float], sources_used: dict[str, dict]) -> list[str]:
    """生成可解释的中文理由列表。"""
    reasons: list[str] = []
    eu = context.get("european")
    if eu:
        imp = eu["implied"]
        move_txt = f"，{eu['move']}" if eu.get("move") else ""
        reasons.append(
            f"欧赔去水隐含：主{imp['home']:.0%}/平{imp['draw']:.0%}/客{imp['away']:.0%}{move_txt}"
        )
    asian = context.get("asian")
    if asian:
        fav_cn = {"home": "主队", "away": "客队", "even": "均势"}.get(asian["favored"], "均势")
        wm = f"，{asian['water_move']}" if asian.get("water_move") else ""
        reasons.append(f"亚盘让球{asian['line']:+.1f}（{fav_cn}方向）{wm}")
    bf = context.get("betfair")
    if bf:
        vp = bf["volume_pct"]
        hot_cn = {"home": "主胜", "draw": "平", "away": "客胜"}.get(bf["hot"], "—")
        vol = bf.get('volume_total', 0) or 0
        vol_str = f"{vol/10000:.1f}万" if vol >= 10000 else f"{vol:.0f}"
        reasons.append(
            f"必发成交{vol_str}，资金倾向{hot_cn}"
            f"（{vp['home']:.0%}/{vp['draw']:.0%}/{vp['away']:.0%}）"
        )
    hist = context.get("history_similar")
    if hist:
        p = hist["p"]
        reasons.append(
            f"历史相似{hist['count']}场：主{p['home']:.0%}/平{p['draw']:.0%}/客{p['away']:.0%}"
            f"（{hist.get('source', 'close')}盘）"
        )
    rf = context.get("recent_form")
    if rf:
        h = rf.get("home") or {}
        a = rf.get("away") or {}
        parts = []
        # 优先用 summary_cn（含主客分场数据）
        if h.get("home_at_home"):
            parts.append(h["home_at_home"])
        elif h.get("form_str"):
            parts.append(f"主队近况{h['form_str']}")
        if a.get("away_at_away"):
            parts.append(a["away_at_away"])
        elif a.get("form_str"):
            parts.append(f"客队近况{a['form_str']}")
        if parts:
            reasons.append("；".join(parts))
    return reasons


def _check_divergence(context: dict) -> str | None:
    """检查欧亚严重分歧，优先使用 DB 主链 divergence。"""
    div = context.get("divergence")
    if isinstance(div, dict) and "divergence_score" in div:
        score = div.get("divergence_score") or 0
        if score >= 50:
            severity = div.get("severity_cn", "明显分歧")
            signals = ", ".join(div.get("signals") or []) or "欧亚不匹配"
            return f"{severity}（{score} 分）{signals}"
        return None

    # Fallback legacy direction check
    eu = context.get("european")
    asian = context.get("asian")
    if not eu or not asian:
        return None
    eu_best = eu.get("best")
    asian_favored = asian.get("favored")
    if eu_best and asian_favored:
        if eu_best == "home" and asian_favored == "away":
            return "欧赔倾向主胜但亚盘客队让球，方向分歧"
        if eu_best == "away" and asian_favored == "home":
            return "欧赔倾向客胜但亚盘主队让球，方向分歧"
    return None


def forecast(context: dict[str, Any]) -> dict[str, Any]:
    """融合五源 → result_prediction。

    Args:
        context: build_result_forecast_context() 返回的 dict

    Returns:
        {pick, pick_cn, p_home, p_draw, p_away, confidence, reasons, factors, missing}
    """
    weights = _get_weights()
    skip_threshold = _get_skip_threshold()
    missing = context.get("missing") or []

    # 重分配权重
    active = {k: v for k, v in weights.items() if k not in missing}
    total_w = sum(active.values())
    if total_w <= 0:
        return _skip_result(context, "五源全部缺失，无法预测")
    norm_weights = {k: v / total_w for k, v in active.items()}

    # 各源概率
    source_probs: dict[str, dict[str, float]] = {}

    eu = context.get("european")
    if eu:
        source_probs["european"] = eu["implied"]

    asian = context.get("asian")
    if asian:
        source_probs["asian"] = _asian_to_probs(asian)

    bf = context.get("betfair")
    if bf:
        source_probs["betfair"] = bf["volume_pct"]

    hist = context.get("history_similar")
    if hist:
        source_probs["history_similar"] = hist["p"]

    rf = context.get("recent_form")
    if rf:
        source_probs["recent_form"] = _recent_to_probs(rf)

    if not source_probs:
        return _skip_result(context, "无可用信号源")

    # 加权融合
    fused = {"home": 0.0, "draw": 0.0, "away": 0.0}
    for src, probs in source_probs.items():
        w = norm_weights.get(src, 0)
        for k in fused:
            fused[k] += w * probs.get(k, 0)

    total = sum(fused.values())
    if total > 0:
        fused = {k: v / total for k, v in fused.items()}

    # pick
    best = max(fused, key=fused.get)
    best_pct = fused[best]

    # 分歧检查
    divergence = _check_divergence(context)
    has_market = bool(context.get("european") or context.get("asian"))

    # confidence
    if best_pct < skip_threshold:
        # 阈值以下：仍输出 pick + 真实概率，标低置信度
        confidence = "low"
        reasons = _build_reasons(context, fused, source_probs)
        reasons.append(f"倾向{RESULT_CN.get(best, best)}但 {best_pct:.0%} 未达阈值 {skip_threshold:.0%}，盘口接近、边际不足")
        if divergence:
            reasons.append(f"⚠ {divergence}")
        if not has_market:
            reasons.append("⚠ 缺盘口验证")
        return {
            "pick": best,
            "pick_cn": f"倾向{RESULT_CN.get(best, best)}（观望）",
            "p_home": round(fused["home"], 4),
            "p_draw": round(fused["draw"], 4),
            "p_away": round(fused["away"], 4),
            "confidence": confidence,
            "confidence_cn": {"high": "高", "mid": "中", "low": "低"}.get(confidence, confidence),
            "reasons": reasons,
            "factors": {
                "european": context.get("european"),
                "asian": context.get("asian"),
                "betfair": context.get("betfair"),
                "history_similar": context.get("history_similar"),
                "recent_form": context.get("recent_form"),
                "recent_missing_reason": context.get("recent_missing_reason", ""),
            },
            "missing": missing,
            "weights": norm_weights,
        }

    if best_pct >= HIGH_CONFIDENCE and not divergence and has_market:
        confidence = "high"
    elif divergence:
        confidence = "low"
    elif not has_market:
        confidence = "low"  # 仅历史/战绩，缺盘口 → 降级
    elif best_pct >= skip_threshold + 0.05:
        confidence = "mid"
    else:
        confidence = "low"

    reasons = _build_reasons(context, fused, source_probs)
    if divergence:
        reasons.append(f"⚠ {divergence}，置信度降级")
    if not has_market:
        reasons.append("⚠ 仅历史相似/战绩，缺盘口验证；请补抓欧亚")

    return {
        "pick": best,
        "pick_cn": RESULT_CN.get(best, best),
        "p_home": round(fused["home"], 4),
        "p_draw": round(fused["draw"], 4),
        "p_away": round(fused["away"], 4),
        "confidence": confidence,
        "confidence_cn": {"high": "高", "mid": "中", "low": "低"}.get(confidence, confidence),
        "reasons": reasons,
        "factors": {
            "european": context.get("european"),
            "asian": context.get("asian"),
            "betfair": context.get("betfair"),
            "history_similar": context.get("history_similar"),
            "recent_form": context.get("recent_form"),
            "recent_missing_reason": context.get("recent_missing_reason", ""),
        },
        "missing": missing,
        "weights": norm_weights,
    }


def _skip_result(context: dict, reason: str) -> dict:
    return {
        "pick": "skip",
        "pick_cn": "观望",
        "p_home": 0.0,
        "p_draw": 0.0,
        "p_away": 0.0,
        "confidence": "low",
        "confidence_cn": "低",
        "reasons": [reason],
        "factors": {
            "european": context.get("european"),
            "asian": context.get("asian"),
            "betfair": context.get("betfair"),
            "history_similar": context.get("history_similar"),
            "recent_form": context.get("recent_form"),
            "recent_missing_reason": context.get("recent_missing_reason", ""),
        },
        "missing": context.get("missing") or [],
        "weights": {},
    }


def _parse_match_name(match_name: str) -> tuple[str, str]:
    """从 '主队 vs 客队' / '主队VS客队' 解析主客队名。"""
    if not match_name:
        return "", ""
    import re
    m = re.split(r"\s*(?:vs|VS|v|V)\s*", match_name, maxsplit=1)
    if len(m) == 2:
        return m[0].strip(), m[1].strip()
    for sep in (" - ", "–", "—"):
        if sep in match_name:
            parts = match_name.split(sep, 1)
            return parts[0].strip(), parts[1].strip()
    return "", ""


def _build_models_for_context(
    context: dict[str, Any],
    result: dict[str, Any],
    prediction: dict | None = None,
) -> dict[str, Any] | None:
    """生成轻量模型层：Elo + 泊松 + edge（不压过主结论）。"""
    home, away = _parse_match_name(context.get("match_name") or "")
    if not home or not away:
        p = prediction or {}
        home = p.get("home_team") or p.get("home") or ""
        away = p.get("away_team") or p.get("away") or ""
    if not home or not away:
        return None

    models: dict[str, Any] = {}

    try:
        import elo_ratings

        elo_ctx = elo_ratings.match_elo_context(home, away)
        models["elo"] = elo_ctx
    except Exception as exc:
        log.debug("elo model failed: %s", exc)
        elo_ctx = None

    try:
        from analysis.quant import poisson

        elo_diff = (elo_ctx or {}).get("elo_diff")
        poisson_ctx = poisson.build_poisson_matrix(home, away, elo_diff=elo_diff)
        if poisson_ctx:
            models["poisson_matrix"] = poisson_ctx
    except Exception as exc:
        log.debug("poisson model failed: %s", exc)
        poisson_ctx = None

    try:
        from analysis.market import value_edge

        edge_ctx = value_edge.build_model_edges(
            context, result, poisson_ctx, prediction=prediction
        )
        if edge_ctx:
            models["edge"] = edge_ctx
    except Exception as exc:
        log.debug("edge model failed: %s", exc)

    return models or None


def forecast_for_match(fixture_id: str, *, index: dict | None = None, prediction: dict | None = None) -> dict:
    """便捷入口：build context + forecast + 轻量模型对照。"""
    from analysis.result_forecast.context import build_result_forecast_context
    ctx = build_result_forecast_context(fixture_id, index=index, prediction=prediction)
    result = forecast(ctx)
    try:
        models = _build_models_for_context(ctx, result, prediction=prediction)
        if models:
            result.setdefault("secondary", {})["models"] = models
    except Exception as exc:
        log.debug("model layer failed: %s", exc)

    # 比分区间预测接入 secondary（context 中已计算）
    score_range = ctx.get("score_range")
    if score_range:
        result.setdefault("secondary", {})["score_range"] = score_range

    return result
