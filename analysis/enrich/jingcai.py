"""Jingcai SP alignment and recommendation overlay."""

from __future__ import annotations

from core.context import EnrichmentContext
from jingcai_pick import attach_jingcai_recommendation
from jingcai_tier import attach_buy_tier


class JingcaiEnricher:
    id = "jingcai"

    def run(self, ctx: EnrichmentContext) -> None:
        jc = (ctx.poll_meta or {}).get("jingcai")
        attach_jingcai_recommendation(ctx.pred, jc)
        attach_buy_tier(ctx.pred)
