"""Read-only JSON API for predictions and analysis reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import config as app_cfg
from jingcai_pick import final_recommendation_cn


def load_prediction(output_root: Path, fixture_id: str) -> dict | None:
    fid = str(fixture_id).strip()
    if not fid:
        return None
    latest = output_root / "latest.json"
    if latest.is_file():
        try:
            data = json.loads(latest.read_text(encoding="utf-8"))
            rows = data if isinstance(data, list) else data.get("matches") or []
            for row in rows:
                if str(row.get("fixture_id")) == fid:
                    return row
        except (json.JSONDecodeError, TypeError):
            pass
    pred_path = output_root / "matches" / fid / "index.json"
    if pred_path.is_file():
        try:
            idx = json.loads(pred_path.read_text(encoding="utf-8"))
            pred = idx.get("latest_prediction") or idx.get("prediction")
            if pred:
                pred = dict(pred)
                pred.setdefault("fixture_id", fid)
                return pred
        except json.JSONDecodeError:
            pass
    return None


def prediction_summary(pred: dict | None) -> dict[str, Any]:
    if not pred:
        return {"ok": False, "error": "not_found"}
    scores = pred.get("likely_scores_detail") or pred.get("likely_scores") or []
    if isinstance(scores, list):
        scores_txt = "、".join(str(s) for s in scores[:3])
    else:
        scores_txt = str(scores)
    final_pick = final_recommendation_cn(pred)
    return {
        "ok": True,
        "fixture_id": pred.get("fixture_id"),
        "match": pred.get("match"),
        "final_pick_cn": final_pick,
        "result_1x2_cn": pred.get("result_1x2_cn"),
        "likely_scores": scores_txt,
        "asian_handicap_cn": pred.get("asian_handicap_cn"),
        "over_under_cn": pred.get("over_under_cn"),
        "confidence_cn": pred.get("confidence_cn"),
        "summary": pred.get("summary"),
        "recommendation_source": pred.get("recommendation_source"),
        "quant": pred.get("quant"),
        "similarity_analysis": pred.get("similarity_analysis"),
    }


def list_fixtures(output_root: Path, *, within_days: float | None = None) -> list[dict[str, Any]]:
    from daily_picks import load_dashboard_matches, load_kickoff_map

    days = within_days if within_days is not None else app_cfg.SERVICE_WITHIN_DAYS
    matches = load_dashboard_matches(output_root, within_days=days)
    kickoff_map = load_kickoff_map(within_days=days)
    rows: list[dict[str, Any]] = []
    for m in matches:
        fid = str(m.get("fixture_id") or "")
        if not fid:
            continue
        ko = kickoff_map.get(fid)
        rows.append({
            "fixture_id": fid,
            "match": m.get("match") or (m.get("predict_row") or {}).get("比赛"),
            "kickoff": ko.isoformat() if ko else None,
            "final_pick_cn": final_recommendation_cn(m),
            "confidence_cn": m.get("confidence_cn"),
        })
    return rows
