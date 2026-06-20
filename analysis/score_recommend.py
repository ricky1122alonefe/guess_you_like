"""Score recommendation from rule-engine + quant (historical + Poisson) tracks."""

from __future__ import annotations

import re
from typing import Any

from jingcai_pick import final_pick_key, final_recommendation_cn

_SCORE_DETAIL_RE = re.compile(r"^(\d+-\d+)\(([\d.]+)%\)$")
_OUTCOME_CN = {"home": "主胜", "draw": "平局", "away": "客胜"}


def _score_outcome(score: str) -> str | None:
    try:
        h, a = (int(x) for x in score.split("-", 1))
    except (ValueError, AttributeError):
        return None
    if h > a:
        return "home"
    if h < a:
        return "away"
    return "draw"


def _parse_prob_pct(raw: str | None) -> float | None:
    if not raw:
        return None
    m = _SCORE_DETAIL_RE.match(str(raw).strip())
    if m:
        return float(m.group(2))
    if str(raw).endswith("%"):
        try:
            return float(str(raw).rstrip("%"))
        except ValueError:
            return None
    return None


def _parse_track(
    scores: list[str] | None,
    detail: list[str] | None = None,
    *,
    source: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    detail = detail or []
    for i, sc in enumerate(scores or []):
        sc = str(sc).strip()
        if not sc:
            continue
        pct = None
        if i < len(detail):
            pct = _parse_prob_pct(detail[i])
        if pct is None:
            m = _SCORE_DETAIL_RE.match(sc)
            if m:
                sc = m.group(1)
                pct = float(m.group(2))
        outcome = _score_outcome(sc)
        out.append({
            "score": sc,
            "prob_pct": pct,
            "outcome": outcome,
            "outcome_cn": _OUTCOME_CN.get(outcome or "", "—"),
            "source": source,
        })
    return out


def _entries_from_score_model(sm: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key in ("top_scores", "all_scores"):
        for item in sm.get(key) or []:
            if isinstance(item, dict) and item.get("score"):
                out.append({
                    "score": item["score"],
                    "prob_pct": item.get("prob_pct"),
                    "outcome": item.get("outcome") or _score_outcome(item["score"]),
                    "outcome_cn": _OUTCOME_CN.get(item.get("outcome") or _score_outcome(item["score"]) or "", "—"),
                    "source": "model",
                })
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for e in out:
        if e["score"] in seen:
            continue
        seen.add(e["score"])
        deduped.append(e)
    return deduped[:5]


def _merge_primary(
    hist: list[dict[str, Any]],
    model: list[dict[str, Any]],
    *,
    pick_key: str | None,
    hist_weight: float = 0.55,
    model_weight: float = 0.45,
) -> list[dict[str, Any]]:
    pool: dict[str, dict[str, Any]] = {}

    def _add(entries: list[dict[str, Any]], track_weight: float) -> None:
        for rank, e in enumerate(entries):
            sc = e["score"]
            base = e.get("prob_pct")
            if base is None:
                base = max(8.0, 22.0 - rank * 4.0)
            aligned = pick_key and e.get("outcome") == pick_key
            align_mul = 1.12 if aligned else 0.88
            rank_mul = 1.0 - rank * 0.08
            w = base * track_weight * align_mul * rank_mul
            slot = pool.setdefault(sc, {
                "score": sc,
                "weight": 0.0,
                "prob_pct": e.get("prob_pct"),
                "outcome": e.get("outcome"),
                "outcome_cn": e.get("outcome_cn"),
                "sources": set(),
                "aligned": bool(aligned),
            })
            slot["weight"] += w
            slot["sources"].add(e.get("source") or "unknown")
            if slot["prob_pct"] is None and e.get("prob_pct") is not None:
                slot["prob_pct"] = e["prob_pct"]
            if aligned:
                slot["aligned"] = True

    _add(hist, hist_weight)
    _add(model, model_weight)

    ranked = sorted(pool.values(), key=lambda x: (-x["weight"], x["score"]))
    primary: list[dict[str, Any]] = []
    for item in ranked[:3]:
        sources = sorted(item["sources"])
        src_label = "双轨" if len(sources) > 1 else ("历史" if sources == ["historical"] else "模型")
        primary.append({
            "score": item["score"],
            "prob_pct": item.get("prob_pct"),
            "weight": round(item["weight"], 2),
            "outcome": item.get("outcome"),
            "outcome_cn": item.get("outcome_cn"),
            "aligned": item.get("aligned"),
            "source": src_label,
            "sources": sources,
        })
    return primary


def _total_goals_hint(pred: dict, sm: dict | None) -> str:
    avg = None
    if sm and sm.get("avg_total_goals") is not None:
        avg = float(sm["avg_total_goals"])
    elif pred.get("open_probability_summary"):
        pass
    sim = pred.get("similarity_analysis") or {}
    pools = (sim.get("asian") or {}, sim.get("european") or {})
    for pool in pools:
        if pool.get("avg_total_goals") is not None:
            avg = float(pool["avg_total_goals"])
            break
    if avg is None:
        return "—"
    if avg >= 2.8:
        return f"偏高（约 {avg:.1f} 球/场）"
    if avg <= 2.2:
        return f"偏低（约 {avg:.1f} 球/场）"
    return f"中等（约 {avg:.1f} 球/场）"


def build_score_recommendation(pred: dict | None) -> dict[str, Any]:
    """Consolidate historical + model score tracks into one actionable bundle."""
    if not pred:
        return {"ok": False, "reason": "无预测数据"}

    pick_key = pred.get("result_1x2")
    if pick_key not in ("home", "draw", "away"):
        pick_key = final_pick_key(pred)
    pick_cn = pred.get("result_1x2_cn") or pred.get("reference_result_1x2_cn") or "—"
    jc_cn = final_recommendation_cn(pred)
    if jc_cn and jc_cn not in ("—", "暂无竞彩", "观望"):
        pick_cn = jc_cn
        if pick_key not in ("home", "draw", "away"):
            pick_key = final_pick_key(pred)

    hist = _parse_track(
        pred.get("likely_scores"),
        pred.get("likely_scores_detail"),
        source="historical",
    )
    quant = pred.get("quant") or {}
    sm = quant.get("score_model") or {}
    model = _parse_track(
        pred.get("model_likely_scores"),
        pred.get("model_likely_scores_detail"),
        source="model",
    )
    if not model and sm:
        model = _entries_from_score_model(sm)

    primary = _merge_primary(hist, model, pick_key=pick_key if pick_key in ("home", "draw", "away") else None)

    stretch = []
    for item in sm.get("stretch_scores") or []:
        sc = item.get("score") if isinstance(item, dict) else item
        if sc and sc not in {p["score"] for p in primary}:
            stretch.append(str(sc))

    headline = " · ".join(p["score"] for p in primary) if primary else "—"
    headline_detail = " · ".join(
        f"{p['score']}({p['prob_pct']}%)" if p.get("prob_pct") is not None else p["score"]
        for p in primary
    ) if primary else "—"

    ou_cn = pred.get("over_under_cn") or (pred.get("predict_row") or {}).get("大小球") or "—"
    conf = pred.get("confidence_cn") or (pred.get("predict_row") or {}).get("置信度") or "—"

    hist_txt = "、".join(
        f"{e['score']}" + (f"({e['prob_pct']}%)" if e.get("prob_pct") is not None else "")
        for e in hist[:3]
    ) or "—"
    model_txt = "、".join(
        f"{e['score']}" + (f"({e['prob_pct']}%)" if e.get("prob_pct") is not None else "")
        for e in model[:3]
    ) or "—"

    aligned_n = sum(1 for p in primary if p.get("aligned"))
    summary_parts = [f"参考赛果 {pick_cn}"]
    if primary:
        summary_parts.append(f"主推 {' / '.join(p['score'] for p in primary[:2])}")
    if aligned_n >= 2:
        summary_parts.append("前三与赛果方向一致")
    elif aligned_n == 1 and len(primary) >= 2:
        summary_parts.append("含 1 个备选赛果比分")
    if hist and model:
        summary_parts.append("历史样本 + Dixon-Coles 双轨综合")
    elif hist:
        summary_parts.append("基于相似样本历史比分")
    elif model:
        summary_parts.append("基于去水欧赔 Poisson 模型")

    return {
        "ok": bool(primary),
        "pick_1x2": pick_key,
        "pick_1x2_cn": pick_cn,
        "headline": headline,
        "headline_detail": headline_detail,
        "primary": primary,
        "stretch": stretch[:2],
        "tracks": {
            "historical": hist[:5],
            "model": model[:5],
        },
        "track_summary": {
            "historical": hist_txt,
            "model": model_txt,
        },
        "total_goals_hint": _total_goals_hint(pred, sm),
        "over_under_cn": ou_cn,
        "confidence_cn": conf,
        "model_meta": {
            "lambda_home": sm.get("lambda_home"),
            "lambda_away": sm.get("lambda_away"),
            "avg_total_goals": sm.get("avg_total_goals"),
            "prob_1x2_pct": sm.get("prob_1x2_pct"),
        } if sm else None,
        "summary": "；".join(summary_parts),
        "reason": None if primary else "样本或模型数据不足，暂无比分推荐",
    }


def attach_score_recommendation(pred: dict) -> dict:
    """Attach score_recommend block to prediction dict."""
    pred["score_recommend"] = build_score_recommendation(pred)
    return pred
