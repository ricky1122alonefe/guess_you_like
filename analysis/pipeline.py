"""Orchestrate post-prediction enrichment steps."""

from __future__ import annotations

from typing import Sequence

from analysis.enrich.jingcai import JingcaiEnricher
from analysis.enrich.odds_snapshot import OddsSnapshotEnricher
from analysis.enrich.similarity import SimilarityEnricher
from analysis.quant.bundle import run_quant_analysis
from core.context import EnrichmentContext

DEFAULT_STEPS: tuple[str, ...] = ("odds_snapshot", "similarity", "jingcai", "quant")
REUSE_STEPS: tuple[str, ...] = ("jingcai", "quant")

_ENRICHERS = {
    "odds_snapshot": OddsSnapshotEnricher(),
    "similarity": SimilarityEnricher(),
    "jingcai": JingcaiEnricher(),
}


def enrich_prediction(
    ctx: EnrichmentContext,
    steps: Sequence[str] | None = None,
) -> dict:
    """Run selected enrichment steps; returns the same pred dict (mutated)."""
    for step_id in steps or DEFAULT_STEPS:
        if step_id == "quant":
            run_quant_analysis(ctx.pred, cur=ctx.cur)
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
    )


def ensure_quant(pred: dict, *, cur: dict | None = None) -> None:
    if not pred or pred.get("quant"):
        return
    run_quant_analysis(pred, cur=cur)
