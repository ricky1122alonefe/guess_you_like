"""Find the best pre-kickoff prediction snapshot for a fixture from run history."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from time_utils import coerce_beijing_dt

log = logging.getLogger(__name__)


def _pred_ts(pred: dict, fallback: str = "") -> datetime | None:
    for key in ("generated_at", "predict_ts"):
        raw = pred.get(key)
        if raw:
            dt = coerce_beijing_dt(raw if isinstance(raw, datetime) else str(raw))
            if dt:
                return dt
    run_id = pred.get("run_id") or fallback
    if run_id and len(run_id) >= 16:
        try:
            dt = datetime.strptime(run_id[:16], "%Y-%m-%d_%H%M")
            return coerce_beijing_dt(dt)
        except ValueError:
            pass
    return None


def _load_run_predictions(path: Path) -> tuple[str, list[dict]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return "", []
    run_id = (data.get("summary") or {}).get("run_id") or path.parent.name
    gen = data.get("generated_at") or ""
    matches = data.get("matches") or []
    if gen:
        for m in matches:
            m.setdefault("predict_ts", gen)
    return run_id, matches


def load_best_prediction(
    output_root: str | Path,
    fixture_id: str,
    *,
    kickoff_at: datetime | str | None = None,
) -> dict | None:
    """
    Last prediction before kickoff: scan latest.json + all runs/*/predictions.json.
    Falls back to latest entry if no kickoff time.
    """
    fid = str(fixture_id)
    root = Path(output_root)
    candidates: list[tuple[datetime | None, dict, str]] = []

    latest_path = root / "latest.json"
    if latest_path.is_file():
        _, matches = _load_run_predictions(latest_path)
        for m in matches:
            if str(m.get("fixture_id")) == fid:
                candidates.append((_pred_ts(m), m, "latest"))

    runs_dir = root / "runs"
    if runs_dir.is_dir():
        for run_dir in sorted(runs_dir.iterdir(), reverse=True):
            pred_path = run_dir / "predictions.json"
            if not pred_path.is_file():
                continue
            run_id, matches = _load_run_predictions(pred_path)
            for m in matches:
                if str(m.get("fixture_id")) != fid:
                    continue
                ts = _pred_ts(m, run_id)
                candidates.append((ts, m, run_id))

    if not candidates:
        return None

    ko = coerce_beijing_dt(kickoff_at)

    if ko:
        before = [(ts, m, rid) for ts, m, rid in candidates if ts and ts <= ko]
        if before:
            before.sort(key=lambda x: x[0], reverse=True)
            return dict(before[0][1])

    with_ts = [(ts, m, rid) for ts, m, rid in candidates if ts]
    if with_ts:
        with_ts.sort(key=lambda x: x[0], reverse=True)
        return dict(with_ts[0][1])

    return dict(candidates[0][1])


def prediction_snapshot(pred: dict | None) -> dict[str, Any]:
    if not pred:
        return {}
    from jingcai_pick import final_recommendation_cn

    row = pred.get("predict_row") or {}
    return {
        "recommendation_source": pred.get("recommendation_source"),
        "run_id": pred.get("run_id"),
        "pick_jingcai_cn": final_recommendation_cn(pred),
        "pick_1x2_cn": row.get("胜平负") or pred.get("result_1x2_cn"),
        "recommended_scores": row.get("推荐比分") or "",
        "asian_handicap_cn": row.get("亚盘") or pred.get("asian_handicap_cn"),
        "asian_handicap_pick": pred.get("asian_handicap_pick"),
        "confidence_cn": row.get("置信度") or pred.get("confidence_cn"),
        "risk_level_cn": pred.get("risk_level_cn"),
        "control_level_cn": pred.get("control_level_cn"),
        "value_bet": pred.get("value_bet"),
        "ai_consensus": pred.get("ai_consensus"),
        "ai_disagreement": pred.get("ai_disagreement"),
        "jingcai_market": row.get("竞彩玩法"),
    }
