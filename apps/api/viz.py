"""Unified visualization data API for a single fixture."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from analysis.market.eu_ah_divergence_ctx import build_eu_ah_divergence
from analysis.market.odds_lifecycle import get_match_odds_lifecycle
from analysis.market.score_range import build_score_range_forecast
from analysis.market.value_edge import build_model_edges
from analysis.result_forecast.context import build_result_forecast_context
from analysis.result_forecast.engine import forecast_for_match
from db.connection import ping
from db.repository import get_fixture_by_external, get_match_result_by_external
from db_timeline import load_match_index_from_db
from match_timeline import load_match_index as _load_match_index_file

log = logging.getLogger(__name__)


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_index(output_root: Path, fixture_id: str) -> dict | None:
    """Prefer DB timeline, fallback to file-based index."""
    if ping():
        try:
            idx = load_match_index_from_db(fixture_id)
            if idx:
                return idx
        except Exception as exc:
            log.debug("db timeline load failed fid=%s: %s", fixture_id, exc)
    try:
        return _load_match_index_file(output_root, fixture_id)
    except Exception as exc:
        log.debug("file timeline load failed fid=%s: %s", fixture_id, exc)
    return None


def _timeline_arrays(index: dict | None) -> dict[str, list[dict]]:
    """Convert a match index timeline into chart-ready arrays."""
    empty: dict[str, list[dict]] = {"eu": [], "ah": [], "ou": [], "betfair": []}
    if not index:
        return empty
    timeline = index.get("timeline") or []
    eu, ah, ou, betfair = [], [], [], []
    for point in timeline:
        odds = point.get("odds") or {}
        ts = point.get("ts") or point.get("hour") or ""
        if any(odds.get(k) is not None for k in ("eu_home", "eu_draw", "eu_away")):
            eu.append(
                {
                    "t": ts,
                    "h": _safe_float(odds.get("eu_home")),
                    "d": _safe_float(odds.get("eu_draw")),
                    "a": _safe_float(odds.get("eu_away")),
                }
            )
        if any(
            odds.get(k) is not None
            for k in ("ah_line", "ah_home_water", "ah_away_water")
        ):
            ah.append(
                {
                    "t": ts,
                    "line": _safe_float(odds.get("ah_line")),
                    "home": _safe_float(odds.get("ah_home_water")),
                    "away": _safe_float(odds.get("ah_away_water")),
                }
            )
        if any(odds.get(k) is not None for k in ("ou_line", "ou_over", "ou_under")):
            ou.append(
                {
                    "t": ts,
                    "line": _safe_float(odds.get("ou_line")),
                    "over": _safe_float(odds.get("ou_over")),
                    "under": _safe_float(odds.get("ou_under")),
                }
            )
        bf = odds.get("betfair") or {}
        if bf and any(
            bf.get(k) is not None
            for k in ("back_home", "back_draw", "back_away", "lay_home", "volume_total")
        ):
            betfair.append(
                {
                    "t": ts,
                    "back_home": _safe_float(bf.get("back_home")),
                    "back_draw": _safe_float(bf.get("back_draw")),
                    "back_away": _safe_float(bf.get("back_away")),
                    "lay_home": _safe_float(bf.get("lay_home")),
                    "volume_total": _safe_float(bf.get("volume_total")),
                }
            )
    return {"eu": eu, "ah": ah, "ou": ou, "betfair": betfair}


def _open_close(fixture_id: str) -> dict | None:
    try:
        oc = get_match_odds_lifecycle(fixture_id)
        if not oc or oc.get("error"):
            return None
        return oc
    except Exception as exc:
        log.debug("open_close failed fid=%s: %s", fixture_id, exc)
        return None


def _divergence(fixture_id: str) -> dict | None:
    try:
        return build_eu_ah_divergence(fixture_id)
    except Exception as exc:
        log.debug("divergence failed fid=%s: %s", fixture_id, exc)
        return None


def _score_range(fixture_id: str, context: dict | None) -> dict:
    try:
        return build_score_range_forecast(fixture_id, context=context)
    except Exception as exc:
        log.debug("score_range failed fid=%s: %s", fixture_id, exc)
        return {"missing": ["score_range_build_error"]}


def _poisson_heatmap(poisson: dict | None) -> list[list] | None:
    """Trim poisson score matrix to 0..5 goals."""
    if not poisson:
        return None
    matrix = poisson.get("score_matrix") or poisson.get("matrix") or []
    if not matrix:
        return None
    # Normalize { "i-j": p } dict into list of [i, j, p].
    if isinstance(matrix, dict):
        matrix = [
            [*key.split("-"), value]
            for key, value in matrix.items()
            if isinstance(key, str) and "-" in key
        ]
    if not matrix:
        return None
    heat = []
    for item in matrix:
        if isinstance(item, (list, tuple)) and len(item) >= 3:
            i, j, p = item[0], item[1], item[2]
        elif isinstance(item, dict):
            i = item.get("home")
            j = item.get("away")
            p = item.get("p")
        else:
            continue
        try:
            i = int(i)
            j = int(j)
        except (TypeError, ValueError):
            continue
        if 0 <= i <= 5 and 0 <= j <= 5:
            heat.append([i, j, round(float(p), 5)])
    return heat or None


def _edge_bars(
    context: dict, result_forecast: dict, poisson: dict | None
) -> list[dict] | None:
    try:
        edges = build_model_edges(context, result_forecast, poisson, prediction=None)
    except Exception as exc:
        log.debug("edge build failed: %s", exc)
        return None
    if not edges:
        return None
    bars = []
    for model_key in ("result_forecast", "poisson"):
        entry = edges.get(model_key)
        if not entry:
            continue
        p_model = entry.get("p_model") or {}
        p_mkt = entry.get("p_mkt") or {}
        edge_vals = entry.get("edge") or {}
        market_source = entry.get("market_source")
        for outcome in ("home", "draw", "away"):
            pm = p_model.get(outcome)
            if pm is None:
                continue
            bars.append(
                {
                    "model_source": entry.get("model_source", model_key),
                    "outcome": outcome,
                    "p_model": round(float(pm), 4),
                    "p_mkt": round(float(p_mkt.get(outcome) or 0), 4),
                    "edge": round(float(edge_vals.get(outcome) or 0), 4),
                    "market_source": market_source,
                }
            )
    return bars or None


def _settled_hits(fixture_id: str) -> dict | None:
    try:
        mr = get_match_result_by_external("500", fixture_id)
        if not mr:
            return None
        payload = mr.get("payload") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        return payload.get("hits") or None
    except Exception as exc:
        log.debug("settled_hits failed fid=%s: %s", fixture_id, exc)
        return None


def _fixture_exists(fixture_id: str) -> bool:
    try:
        return get_fixture_by_external("500", fixture_id) is not None
    except Exception:
        return False


def build_viz_data(output_root: str | Path, fixture_id: str) -> dict[str, Any]:
    """Build the complete visualization payload for a fixture."""
    output_root = Path(output_root)
    fid = str(fixture_id)
    missing: list[str] = []

    context: dict | None = None
    result_forecast: dict | None = None
    try:
        context = build_result_forecast_context(fid) or {}
        result_forecast = forecast_for_match(fid)
    except Exception as exc:
        log.warning("result forecast context failed fid=%s: %s", fid, exc)
        missing.append("result_forecast_context")

    # Score range: prefer context, rebuild on failure.
    score_range: dict | None = None
    if context:
        score_range = context.get("score_range") or _score_range(fid, context)
    else:
        score_range = _score_range(fid, None)
    if not score_range or score_range.get("missing"):
        missing.append("score_range")

    divergence = _divergence(fid)
    if not divergence or divergence.get("missing"):
        missing.append("divergence")

    open_close = _open_close(fid)
    if not open_close:
        missing.append("open_close")

    index = _load_index(output_root, fid)
    timeline = _timeline_arrays(index)
    if not any(timeline.values()):
        missing.append("timeline")

    poisson = (context or {}).get("poisson") or (result_forecast or {}).get("poisson")
    if not poisson and result_forecast:
        secondary = result_forecast.get("secondary") or {}
        models = secondary.get("models") or {}
        poisson = models.get("poisson_matrix")
    heatmap = _poisson_heatmap(poisson)
    if not heatmap:
        missing.append("poisson_heatmap")

    edge_bars = None
    if context and result_forecast:
        edge_bars = _edge_bars(context, result_forecast, poisson)
    if not edge_bars:
        missing.append("edge_bars")

    settled_hits = _settled_hits(fid)

    sr_out: dict[str, Any] = {
        "top_bands": [],
        "total_bands": [],
        "exact_top": [],
        "missing": [],
    }
    if isinstance(score_range, dict):
        bands = score_range.get("bands") or []
        sr_out["top_bands"] = bands[:5]
        sr_out["total_bands"] = score_range.get("total_bands") or []
        sr_out["exact_top"] = score_range.get("exact_top") or []
        sr_out["missing"] = score_range.get("missing") or []

    return {
        "fixture_id": fid,
        "timeline": timeline,
        "open_close": open_close,
        "divergence": divergence,
        "score_range": sr_out,
        "poisson_heatmap": heatmap,
        "edge_bars": edge_bars,
        "settled_hits": settled_hits,
        "missing": missing,
    }


def get_viz_or_404(output_root: str | Path, fixture_id: str) -> tuple[dict, int]:
    """Return (payload, status). 404 when fixture and data are both absent."""
    fid = str(fixture_id)
    if not _fixture_exists(fid):
        # Allow missing DB fixture only if we have timeline file data.
        index = _load_index(Path(output_root), fid)
        if not index:
            return (
                {"error": "not found", "fixture_id": fid, "missing": ["fixture"]},
                404,
            )
    try:
        data = build_viz_data(output_root, fid)
    except Exception as exc:
        log.exception("viz build failed fid=%s", fid)
        return ({"error": str(exc), "fixture_id": fid}, 500)

    if not data.get("open_close") and not data.get("timeline") and not data.get("score_range"):
        return (
            {"error": "no data", "fixture_id": fid, "missing": data.get("missing", [])},
            404,
        )
    return data, 200
