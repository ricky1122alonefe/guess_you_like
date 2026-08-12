"""比分区间预测引擎。

输出的是概率区间，不是单点神预测。禁止把泊松 λ 包装成 xG。
"""
from __future__ import annotations

import logging
import math
import re
from typing import Any

from analysis.market.devig import devig_from_odds
from config import (
    SCORE_RANGE_EXACT_TOP_N,
    SCORE_RANGE_LOW_MAX,
    SCORE_RANGE_MID_MAX,
    SCORE_RANGE_MIN_SAMPLES,
    SCORE_RANGE_TOP_N,
    VALUE_EDGE_MAX_KELLY,
)

log = logging.getLogger(__name__)

DIRECTIONS = ("home", "draw", "away")
TOTAL_SIZES = ("low", "mid", "high")

# 交叉 band：方向 × 总球大小
BAND_CROSS_LABELS = {
    ("home", "low"): "主胜小球 (0-1球)",
    ("home", "mid"): "主胜一般 (2-3球)",
    ("home", "high"): "主胜大球 (4+球)",
    ("draw", "low"): "平局低分 (0-1球)",
    ("draw", "mid"): "平局一般 (2-3球)",
    ("draw", "high"): "平局高分 (4+球)",
    ("away", "low"): "客胜小球 (0-1球)",
    ("away", "mid"): "客胜一般 (2-3球)",
    ("away", "high"): "客胜大球 (4+球)",
}

SHAPE_BANDS = {
    "H_small": {
        "label_cn": "主胜小球",
        "rule": "主胜且总进球≤2",
        "cells": [("home", "low")],
    },
    "H_big": {
        "label_cn": "主胜一般",
        "rule": "主胜且总进球≥3",
        "cells": [("home", "mid"), ("home", "high")],
    },
    "D_low": {
        "label_cn": "平局低分",
        "rule": "平局且总进球≤2",
        "cells": [("draw", "low")],
    },
    "A_small": {
        "label_cn": "客胜小球",
        "rule": "客胜且总进球≤2",
        "cells": [("away", "low")],
    },
    "A_big": {
        "label_cn": "客胜一般",
        "rule": "客胜且总进球≥3",
        "cells": [("away", "mid"), ("away", "high")],
    },
}

TOTAL_BANDS = {
    "TG_0_1": {
        "label_cn": "0-1球",
        "rule": "总进球 0 或 1",
        "cells": [(d, "low") for d in DIRECTIONS],
    },
    "TG_2_3": {
        "label_cn": "2-3球",
        "rule": "总进球 2 或 3",
        "cells": [(d, "mid") for d in DIRECTIONS],
    },
    "TG_4+": {
        "label_cn": "4+球",
        "rule": "总进球≥4",
        "cells": [(d, "high") for d in DIRECTIONS],
    },
}


def _total_size(total: int) -> str:
    if total <= SCORE_RANGE_LOW_MAX:
        return "low"
    if total <= SCORE_RANGE_MID_MAX:
        return "mid"
    return "high"


def _direction_1x2(home: int, away: int) -> str:
    if home > away:
        return "home"
    if home == away:
        return "draw"
    return "away"


def _parse_score(score: str | None) -> tuple[int, int] | None:
    if not score:
        return None
    m = re.match(r"(\d+)\s*[-:]\s*(\d+)", str(score).strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _empty_cross() -> dict[tuple[str, str], float]:
    return {(d, t): 0.0 for d in DIRECTIONS for t in TOTAL_SIZES}


def _aggregate_score_distribution(scores: dict[str, float]) -> dict[tuple[str, str], float]:
    """把 score -> prob 字典聚合成交叉 band。"""
    bands = _empty_cross()
    for sc, p in (scores or {}).items():
        parsed = _parse_score(sc)
        if parsed is None:
            continue
        h, a = parsed
        direction = _direction_1x2(h, a)
        size = _total_size(h + a)
        bands[(direction, size)] += float(p)
    return bands


def _poisson_score_distribution(poisson: dict | None) -> dict[str, float] | None:
    """从泊松矩阵提取 score -> prob。"""
    if not poisson:
        return None
    matrix = poisson.get("score_matrix")
    if not matrix:
        return None
    out: dict[str, float] = {}
    for sc, p in matrix.items():
        parsed = _parse_score(sc)
        if parsed is None:
            continue
        out[sc] = float(p)
    return out if out else None


def _similar_score_distribution(similar: dict | None) -> dict[str, float] | None:
    """从历史同赔样本提取 score -> prob（按相似度加权后归一）。"""
    if not similar:
        return None
    samples = similar.get("samples") or []
    if samples:
        weights: dict[str, float] = {}
        for s in samples:
            h = s.get("score_h")
            a = s.get("score_a")
            if h is None or a is None:
                continue
            try:
                h_i, a_i = int(h), int(a)
            except (TypeError, ValueError):
                continue
            sc = f"{h_i}-{a_i}"
            dist = s.get("similarity_dist")
            wt = (
                1.0
                if dist is None or (isinstance(dist, float) and dist != dist)
                else float(dist)
            )
            # 距离越近权重越高：指数衰减
            w = math.exp(-wt) if wt >= 0 else 1.0
            weights[sc] = weights.get(sc, 0.0) + w
        total = sum(weights.values())
        if total > 0:
            return {sc: w / total for sc, w in weights.items()}

    top_scores = similar.get("top_scores") or []
    if top_scores:
        weights = {}
        for ts in top_scores:
            sc = ts.get("score")
            pct = ts.get("pct")
            if sc is None or pct is None:
                continue
            try:
                weights[sc] = float(pct)
            except (TypeError, ValueError):
                continue
        total = sum(weights.values())
        if total > 0:
            return {sc: w / total for sc, w in weights.items()}
    return None


def _normalize_cross(bands: dict[tuple[str, str], float]) -> dict[tuple[str, str], float]:
    total = sum(bands.values())
    if total <= 0:
        return bands
    return {k: v / total for k, v in bands.items()}


def _apply_1x2_weighting(
    bands: dict[tuple[str, str], float],
    p_1x2: dict[str, float] | None,
) -> dict[tuple[str, str], float]:
    """用去水后的 1X2 概率对方向做加权校准。"""
    if not p_1x2:
        return bands
    raw_dir: dict[str, float] = {d: 0.0 for d in DIRECTIONS}
    for (direction, _), p in bands.items():
        raw_dir[direction] += p
    out = _empty_cross()
    for (direction, size), p in bands.items():
        raw = raw_dir.get(direction, 0.0)
        target = float(p_1x2.get(direction, 0.0))
        if raw > 0 and target > 0:
            out[(direction, size)] = p * (target / raw)
        elif target > 0:
            # 该方向无内部分布时按大小均分（降级但诚实）
            out[(direction, size)] = target / 3.0
    return _normalize_cross(out)


def _cross_to_bands_list(
    cross: dict[tuple[str, str], float],
    sources: list[str],
) -> list[dict[str, Any]]:
    return [
        {
            "id": f"{direction}_{size}",
            "label_cn": BAND_CROSS_LABELS.get((direction, size), f"{direction}-{size}"),
            "rule": f"{_direction_cn(direction)} & {_size_cn(size)}",
            "p": round(p, 4),
            "sources": sources,
        }
        for (direction, size), p in sorted(cross.items(), key=lambda x: -x[1])
    ]


def _direction_cn(d: str) -> str:
    return {"home": "主胜", "draw": "平局", "away": "客胜"}.get(d, d)


def _size_cn(s: str) -> str:
    return {"low": "0-1球", "mid": "2-3球", "high": "4+球"}.get(s, s)


def _merge_bands(cross: dict[tuple[str, str], float], definition: dict) -> dict[str, Any]:
    p = sum(cross.get(cell, 0.0) for cell in definition["cells"])
    return {
        "id": definition.get("id"),
        "label_cn": definition["label_cn"],
        "rule": definition["rule"],
        "p": round(p, 4),
    }


def _derive_shape_bands(cross: dict[tuple[str, str], float]) -> list[dict[str, Any]]:
    out = []
    for bid, definition in SHAPE_BANDS.items():
        item = _merge_bands(cross, {**definition, "id": bid})
        item["sources"] = ["shape"]
        out.append(item)
    # 按概率降序
    out.sort(key=lambda x: -x["p"])
    return out


def _derive_total_bands(cross: dict[tuple[str, str], float]) -> list[dict[str, Any]]:
    out = []
    for bid, definition in TOTAL_BANDS.items():
        item = _merge_bands(cross, {**definition, "id": bid})
        item["sources"] = ["total"]
        out.append(item)
    out.sort(key=lambda x: -x["p"])
    return out


def _derive_ou_relative_bands(
    cross: dict[tuple[str, str], float],
    ou_line: float,
) -> list[dict[str, Any]] | None:
    """按 OU line 把总球映射到小/走/大。"""
    try:
        line = float(ou_line)
    except (TypeError, ValueError):
        return None

    under_p = 0.0
    push_p = 0.0
    over_p = 0.0
    for (direction, size), p in cross.items():
        # 需要把每个 cell 再拆成精确比分才能判断 push；这里用 cell 边界近似
        if size == "low":
            under_p += p
        elif size == "high":
            over_p += p
        else:  # mid = 2-3 球
            # line 常见 2.0 / 2.25 / 2.5 / 2.75 / 3.0 ...
            if line < 2.0:
                over_p += p
            elif line == 2.0:
                # 2 球走，3 球大
                # 2-3 cell 中按 half 近似
                push_p += p * 0.5
                over_p += p * 0.5
            elif line < 3.0:
                # 2.25/2.5/2.75: 2 球小，3 球大
                under_p += p * 0.5
                over_p += p * 0.5
            elif line == 3.0:
                push_p += p * 0.5
                under_p += p * 0.5
            else:
                under_p += p
    bands = [
        {"id": "OU_under", "label_cn": f"小{line}", "rule": f"总进球<{line}", "p": round(under_p, 4), "sources": ["ou_relative"]},
        {"id": "OU_push", "label_cn": f"走{line}", "rule": f"总进球={line}", "p": round(push_p, 4), "sources": ["ou_relative"]},
        {"id": "OU_over", "label_cn": f"大{line}", "rule": f"总进球>{line}", "p": round(over_p, 4), "sources": ["ou_relative"]},
    ]
    return bands


def _exact_top(
    poisson: dict | None,
    similar: dict | None,
    *,
    n: int = SCORE_RANGE_EXACT_TOP_N,
) -> list[dict[str, Any]]:
    """精确比分参考（非主结论）。"""
    scores: dict[str, float] = {}
    sources: dict[str, list[str]] = {}
    if poisson:
        for sc, p in (poisson.get("score_matrix") or {}).items():
            scores[sc] = scores.get(sc, 0.0) + float(p)
            sources.setdefault(sc, []).append("poisson")
    if similar:
        sim_dist = _similar_score_distribution(similar)
        for sc, p in (sim_dist or {}).items():
            scores[sc] = scores.get(sc, 0.0) + p
            sources.setdefault(sc, []).append("similar")
    if not scores:
        return []
    top = sorted(scores.items(), key=lambda x: -x[1])[:n]
    return [
        {
            "score": sc,
            "p": round(p, 4),
            "sources": list(set(sources.get(sc, []))),
            "note": "仅供参考",
        }
        for sc, p in top
    ]


def _extract_p_1x2(context: dict) -> dict[str, float] | None:
    """竞彩 SP 去水优先，否则欧赔去水。"""
    jingcai = context.get("jingcai") or {}
    sp = jingcai.get("sp") or {}
    if sp and all(sp.get(k) for k in ("home", "draw", "away")):
        dv = devig_from_odds(sp)
        return {"home": dv["p_home"], "draw": dv["p_draw"], "away": dv["p_away"]}

    eu = context.get("european") or {}
    eu_odds = eu.get("odds") or {}
    if eu_odds and all(eu_odds.get(k) for k in ("home", "draw", "away")):
        dv = devig_from_odds(eu_odds)
        return {"home": dv["p_home"], "draw": dv["p_draw"], "away": dv["p_away"]}

    return None


def _extract_poisson(context: dict) -> dict | None:
    """尝试从 context / forecast secondary 取泊松矩阵。"""
    # 1) context 里若已有（通过 engine secondary 写入后回填）
    if "poisson_matrix" in context:
        return context["poisson_matrix"]
    # 2) 从 secondary.models 取
    secondary = context.get("secondary") or {}
    models = secondary.get("models") or {}
    pm = models.get("poisson_matrix") or models.get("poisson")
    if pm:
        return pm

    # 3) 现场算：需要 club_form + elo
    club_form = context.get("club_form")
    if not club_form:
        return None
    elo_ctx = context.get("elo_context") or {}
    elo_diff = elo_ctx.get("elo_diff")
    try:
        from analysis.quant.poisson import build_poisson_matrix

        return build_poisson_matrix(
            context.get("home_team", ""),
            context.get("away_team", ""),
            club_form=club_form,
            elo_diff=elo_diff,
        )
    except Exception as exc:
        log.debug("score_range 现场计算泊松失败: %s", exc)
        return None


def _extract_similar(context: dict) -> dict | None:
    return context.get("history_similar") or context.get("similar")


def _sp_band(context: dict, model_p_1x2: dict[str, float] | None) -> dict[str, Any] | None:
    """用竞彩 SP / 欧赔找价值 1X2 方向。"""
    if not model_p_1x2:
        return None

    jingcai = context.get("jingcai") or {}
    sp = jingcai.get("sp") or {}
    market_source = "jingcai_sp"
    odds = sp
    if not odds or not all(odds.get(k) for k in ("home", "draw", "away")):
        eu = context.get("european") or {}
        odds = eu.get("odds") or {}
        market_source = "eu_closing"
    if not odds or not all(odds.get(k) for k in ("home", "draw", "away")):
        return None

    dv = devig_from_odds(odds)
    p_mkt = {"home": dv["p_home"], "draw": dv["p_draw"], "away": dv["p_away"]}

    best_pick = None
    best_edge = 0.0
    best_sp = None
    for d in DIRECTIONS:
        edge = model_p_1x2.get(d, 0.0) - p_mkt.get(d, 0.0)
        if edge > best_edge:
            best_edge = edge
            best_pick = d
            best_sp = odds.get(d)

    if best_pick is None:
        return None

    # half-Kelly 封顶
    p = model_p_1x2.get(best_pick, 0.0)
    q = 1.0 - p
    b = (best_sp or 1.0) - 1.0
    half_kelly = None
    if p > p_mkt.get(best_pick, 0.0) and b > 0 and p < 1.0:
        kelly = (b * p - q) / b if b != 0 else 0.0
        half_kelly = max(0.0, kelly / 2.0)
        if half_kelly > VALUE_EDGE_MAX_KELLY:
            half_kelly = VALUE_EDGE_MAX_KELLY

    actionable = best_edge > 0 and half_kelly is not None and half_kelly > 0
    return {
        "min": round(p_mkt.get(best_pick, 0.0), 4),
        "max": round(p, 4),
        "pick_1x2": best_pick,
        "sp": best_sp,
        "actionable": actionable,
        "market_source": market_source,
        "market_p": round(p_mkt.get(best_pick, 0.0), 4),
        "model_p": round(p, 4),
        "edge": round(best_edge, 4),
        "half_kelly": round(half_kelly, 4) if half_kelly is not None else None,
        "disclaimer": "研究用，非投注建议",
    }


def _ou_line_from_context(context: dict) -> float | None:
    mc = context.get("market_open_close") or {}
    latest = mc.get("latest") or {}
    line = latest.get("ou_line")
    if line is None:
        opening = mc.get("opening") or {}
        line = opening.get("ou_line")
    return line


def build_score_range_forecast(
    fixture_id: str,
    *,
    context: dict | None = None,
) -> dict[str, Any]:
    """对外 API：为某场比赛生成比分区间预测。

    Args:
        fixture_id: external_id
        context: 可选预计算的 forecast context；None 时自动构建。

    Returns:
        score_range_forecast 结构 dict。
    """
    missing: list[str] = []
    if context is None:
        try:
            from analysis.result_forecast.context import build_result_forecast_context

            context = build_result_forecast_context(str(fixture_id))
        except Exception as exc:
            log.warning("score_range 无法构建 context %s: %s", fixture_id, exc)
            return {"missing": ["context_unavailable"], "bands": [], "top_bands": []}

    if not context:
        return {"missing": ["context_unavailable"], "bands": [], "top_bands": []}

    poisson = _extract_poisson(context)
    similar = _extract_similar(context)

    # 构建 raw score 分布
    scores: dict[str, float] | None = None
    sources: list[str] = []
    if poisson:
        scores = _poisson_score_distribution(poisson)
        sources.append("poisson")
    if not scores and similar:
        scores = _similar_score_distribution(similar)
        sources.append("similar")

    if not scores:
        missing.append("no_score_distribution")
        return {
            "missing": missing,
            "bands": [],
            "top_bands": [],
            "exact_top": [],
            "sp_band": None,
        }

    if similar and len(similar.get("samples") or []) < SCORE_RANGE_MIN_SAMPLES:
        missing.append("similar_sample_small")

    cross = _aggregate_score_distribution(scores)
    cross = _normalize_cross(cross)

    # 用 1X2 去水概率校准方向
    p_1x2 = _extract_p_1x2(context)
    if p_1x2:
        sources.append("spf")
    cross = _apply_1x2_weighting(cross, p_1x2)

    bands = _cross_to_bands_list(cross, sources)
    top_bands = sorted(bands, key=lambda x: -x["p"])[:SCORE_RANGE_TOP_N]

    shape_bands = _derive_shape_bands(cross)
    total_bands = _derive_total_bands(cross)

    ou_line = _ou_line_from_context(context)
    ou_relative = _derive_ou_relative_bands(cross, ou_line) if ou_line is not None else None

    exact_top = _exact_top(poisson, similar)
    sp_band = _sp_band(context, p_1x2 or _direction_totals(cross))

    return {
        "bands": bands,
        "top_bands": top_bands,
        "shape_bands": shape_bands,
        "total_bands": total_bands,
        "ou_relative_bands": ou_relative,
        "exact_top": exact_top,
        "sp_band": sp_band,
        "missing": missing,
    }


def _direction_totals(cross: dict[tuple[str, str], float]) -> dict[str, float]:
    out = {d: 0.0 for d in DIRECTIONS}
    for (d, _), p in cross.items():
        out[d] += p
    return out


def band_hit(band_id: str, home_score: int, away_score: int) -> bool:
    """判断某 band 是否命中实际比分。"""
    direction = _direction_1x2(home_score, away_score)
    size = _total_size(home_score + away_score)
    if band_id == f"{direction}_{size}":
        return True
    bid_map = {
        "H_small": ("home", "low"),
        "H_big": ("home", ("mid", "high")),
        "D_low": ("draw", "low"),
        "A_small": ("away", "low"),
        "A_big": ("away", ("mid", "high")),
        "TG_0_1": (None, "low"),
        "TG_2_3": (None, "mid"),
        "TG_4+": (None, "high"),
    }
    if band_id not in bid_map:
        return False
    d_target, s_target = bid_map[band_id]
    if d_target is not None and direction != d_target:
        return False
    if isinstance(s_target, tuple):
        return size in s_target
    return size == s_target


def evaluate_score_bands(
    score_range: dict | None,
    home_score: int,
    away_score: int,
) -> list[dict[str, Any]]:
    """对 score_range 的 top_bands / shape_bands 计算命中。"""
    if not score_range:
        return []
    bands = score_range.get("top_bands") or score_range.get("shape_bands") or []
    return [
        {"id": b.get("id"), "hit": band_hit(b.get("id"), home_score, away_score)}
        for b in bands
    ]
