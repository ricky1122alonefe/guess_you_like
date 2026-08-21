"""Orchestrate post-prediction enrichment steps."""

from __future__ import annotations

import logging
from typing import Sequence

from analysis.enrich.jingcai import JingcaiEnricher
from analysis.enrich.odds_snapshot import OddsSnapshotEnricher
from analysis.enrich.similarity import SimilarityEnricher
from analysis.quant.bundle import run_quant_analysis
from analysis.registry import enrichment_steps
from core.context import EnrichmentContext

log = logging.getLogger(__name__)

DEFAULT_STEPS: tuple[str, ...] = enrichment_steps("default")
REUSE_STEPS: tuple[str, ...] = enrichment_steps("reuse")
REUSE_STEPS: tuple[str, ...] = enrichment_steps("reuse")

_ENRICHERS = {
    "odds_snapshot": OddsSnapshotEnricher(),
    "similarity": SimilarityEnricher(),
    "jingcai": JingcaiEnricher(),
}


def enrich_prediction(
    ctx: EnrichmentContext,
    steps: Sequence[str] | None = None,
    *,
    output_root=None,
) -> dict:
    """Run selected enrichment steps; returns the same pred dict (mutated)."""
    resolved = tuple(steps) if steps is not None else enrichment_steps("default", output_root)
    for step_id in resolved:
        if step_id == "quant":
            run_quant_analysis(ctx.pred, cur=ctx.cur, output_root=output_root)
            continue
        enricher = _ENRICHERS.get(step_id)
        if enricher:
            enricher.run(ctx)
    return ctx.pred


def ensure_similarity(
    pred: dict,
    *,
    ah_path,
    eu_path,
    history,
    output_root=None,
) -> None:
    if not pred or pred.get("similarity_analysis"):
        return
    if not ah_path or not eu_path:
        return
    from predict import build_payload

    payload = build_payload(str(ah_path), str(eu_path), history=history, sample_limit=10)
    enrich_prediction(
        EnrichmentContext(pred=pred, payload=payload),
        steps=("similarity",),
        output_root=output_root,
    )


def ensure_quant(pred: dict, *, cur: dict | None = None, output_root=None) -> None:
    if not pred:
        return
    if not pred.get("quant"):
        run_quant_analysis(pred, cur=cur, output_root=output_root)
        return
    # quant 已有（如仅 elo）但缺比分模型：只补 poisson 一步，保留已有字段（elo/ev/mc 等）
    quant = pred.get("quant")
    if isinstance(quant, dict) and not quant.get("score_model"):
        backfill_score_model(pred, cur, output_root=output_root)


def backfill_score_model(
    pred: dict,
    cur: dict | None = None,
    *,
    output_root=None,
) -> None:
    """补写 quant.score_model（泊松比分模型）。无欧赔时诚实缺省，不编 λ。"""
    from analysis.quant.common import (
        avg_goals_from_similarity,
        coerce_odds_dict,
        ensure_eu_implied,
        fill_eu_from_books_major,
    )
    from analysis.quant.poisson import apply_poisson
    from analysis.registry import quant_steps

    if "poisson" not in quant_steps(output_root):
        return
    if not isinstance(pred, dict):
        return
    quant = pred.get("quant")
    if not isinstance(quant, dict) or quant.get("score_model"):
        return
    try:
        cur = coerce_odds_dict(cur or pred.get("odds_snapshot") or {})
        # snapshot/timeline 欧赔 0/缺失 → 回退 major 均值（与 three_lane 同源），无 major 仍诚实 missing
        cur = fill_eu_from_books_major(
            pred, cur, output_root=output_root, fixture_id=pred.get("fixture_id")
        )
        eu_imp = ensure_eu_implied(pred, cur)
        avg_goals = avg_goals_from_similarity(pred)
        apply_poisson(pred, cur, eu_imp, avg_goals, quant)
    except Exception:  # noqa: BLE001 - 补算失败不阻塞详情页
        log.exception("score_model 补算失败")
