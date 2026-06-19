"""Context passed through post-prediction enrichment steps."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class EnrichmentContext:
    """Inputs for odds / similarity / jingcai / quant enrichers."""

    pred: dict[str, Any]
    ah_path: Path | str | None = None
    eu_path: Path | str | None = None
    payload: dict[str, Any] | None = None
    poll_meta: dict[str, Any] | None = None
    cur: dict[str, Any] | None = None
    history: Any = None
    extra: dict[str, Any] = field(default_factory=dict)
