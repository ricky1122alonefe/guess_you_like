"""Analyzer protocol for enrichment steps."""

from __future__ import annotations

from typing import Protocol

from core.context import EnrichmentContext


class Enricher(Protocol):
    id: str

    def run(self, ctx: EnrichmentContext) -> None:
        ...
