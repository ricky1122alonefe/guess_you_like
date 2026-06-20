"""Orchestrate post-prediction enrichment steps."""

from __future__ import annotations

from typing import Sequence

from analysis.enrich.jingcai import JingcaiEnricher
from analysis.enrich.odds_snapshot import OddsSnapshotEnricher
from analysis.enrich.similarity import SimilarityEnricher
from analysis.quant.bundle import run_quant_analysis
from analysis.registry import enrichment_steps
from core.context import EnrichmentContext

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
    if not pred or pred.get("quant"):
        return
    run_quant_analysis(pred, cur=cur, output_root=output_root)
