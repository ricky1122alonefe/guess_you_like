"""Historical similar-sample blocks for match detail."""

from __future__ import annotations

from core.context import EnrichmentContext
from similar_samples import build_similarity_analysis


class SimilarityEnricher:
    id = "similarity"

    def run(self, ctx: EnrichmentContext) -> None:
        if ctx.payload is None:
            return
        ctx.pred["similarity_analysis"] = build_similarity_analysis(ctx.payload)
