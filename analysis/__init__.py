"""Modular match analysis — orchestrated via analysis.pipeline."""

from analysis.pipeline import enrich_prediction, ensure_quant, ensure_similarity

__all__ = ["enrich_prediction", "ensure_quant", "ensure_similarity"]
