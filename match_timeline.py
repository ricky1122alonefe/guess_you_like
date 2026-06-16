"""File-based per-match hourly odds + recommendation timeline (no DB)."""

from __future__ import annotations

import json
import logging
from time_utils import now_beijing_str
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

PICK_KEYS = (
    ("result_1x2_cn", "胜平负"),
    ("likely_scores_detail", "推荐比分"),
    ("asian_handicap_cn", "亚盘"),
    ("over_under_cn", "大小球"),
    ("confidence_cn", "置信度"),
)


def _match_dir(output_root: Path, fixture_id: str) -> Path:
    return output_root / "matches" / str(fixture_id)


def _odds_from_prediction(pred: dict) -> dict[str, Any]:
    snap = pred.get("odds_snapshot") or {}
    row = pred.get("predict_row") or {}
    eu = row.get("临盘欧赔")
    eu_open = row.get("初盘欧赔")
    eu_parts = str(eu).split("/") if eu else []
    eu_open_parts = str(eu_open).split("/") if eu_open else []
    out = {
        "ah_line": snap.get("ah_line") if snap.get("ah_line") is not None else row.get("临盘盘口"),
        "ah_open_line": snap.get("ah_open_line") if snap.get("ah_open_line") is not None else row.get("初盘盘口"),
        "ah_home_water": snap.get("ah_home_water"),
        "ah_away_water": snap.get("ah_away_water"),
        "ah_open_home_water": snap.get("ah_open_home_water"),
        "ah_open_away_water": snap.get("ah_open_away_water"),
        "eu_home": snap.get("eu_home"),
        "eu_draw": snap.get("eu_draw"),
        "eu_away": snap.get("eu_away"),
        "eu_open_home": snap.get("eu_open_home"),
        "eu_open_draw": snap.get("eu_open_draw"),
        "eu_open_away": snap.get("eu_open_away"),
    }
    if len(eu_parts) == 3 and out["eu_home"] is None:
        try:
            out["eu_home"], out["eu_draw"], out["eu_away"] = map(float, eu_parts)
        except ValueError:
            pass
    if len(eu_open_parts) == 3 and out["eu_open_home"] is None:
        try:
            out["eu_open_home"], out["eu_open_draw"], out["eu_open_away"] = map(float, eu_open_parts)
        except ValueError:
            pass
    return out


def compact_ai_analyses(pred: dict) -> dict[str, dict]:
    """Per-provider summary for storage / display."""
    analyses = pred.get("ai_analyses") or {}
    out: dict[str, dict] = {}
    if analyses:
        for pid, p in analyses.items():
            row = p.get("predict_row") or {}
            scores = p.get("likely_scores_detail") or p.get("likely_scores") or []
            if isinstance(scores, list):
                score_txt = "、".join(str(s) for s in scores[:3])
            else:
                score_txt = str(scores) if scores else str(row.get("推荐比分") or "")
            out[pid] = {
                "label": p.get("ai_provider_label") or pid,
                "result_1x2_cn": row.get("胜平负") or p.get("result_1x2_cn"),
                "likely_scores": score_txt,
                "asian_handicap_cn": row.get("亚盘") or p.get("asian_handicap_cn"),
                "confidence_cn": row.get("置信度") or p.get("confidence_cn"),
                "actuary_reasoning": (p.get("actuary_reasoning") or "")[:500],
            }
        return out
    src = pred.get("recommendation_source") or ""
    if "ai" not in src:
        return {}
    row = pred.get("predict_row") or {}
    scores = pred.get("likely_scores_detail") or pred.get("likely_scores") or []
    if isinstance(scores, list):
        score_txt = "、".join(str(s) for s in scores[:3])
    else:
        score_txt = str(scores) if scores else str(row.get("推荐比分") or "")
    pid = pred.get("ai_provider") or "ai"
    out[pid] = {
        "label": pred.get("ai_provider_label") or "精算师",
        "result_1x2_cn": row.get("胜平负") or pred.get("result_1x2_cn"),
        "likely_scores": score_txt,
        "asian_handicap_cn": row.get("亚盘") or pred.get("asian_handicap_cn"),
        "confidence_cn": row.get("置信度") or pred.get("confidence_cn"),
        "actuary_reasoning": (pred.get("actuary_reasoning") or "")[:500],
    }
    return out


def _pick_from_prediction(pred: dict) -> dict[str, Any]:
    scores = pred.get("likely_scores_detail") or pred.get("likely_scores") or []
    if isinstance(scores, list):
        score_txt = "、".join(str(s) for s in scores[:3])
    else:
        score_txt = str(scores)
    pick: dict[str, Any] = {
        "result_1x2": pred.get("result_1x2"),
        "result_1x2_cn": pred.get("result_1x2_cn"),
        "likely_scores": score_txt,
        "asian_handicap_cn": pred.get("asian_handicap_cn"),
        "over_under_cn": pred.get("over_under_cn"),
        "confidence_cn": pred.get("confidence_cn"),
        "confidence_reason": pred.get("confidence_reason"),
        "recommendation_source": pred.get("recommendation_source", "rule_engine"),
    }
    ai_compact = compact_ai_analyses(pred)
    if ai_compact:
        pick["ai_analyses"] = ai_compact
    return pick


def hourly_point(pred: dict, *, run_id: str, ts: str | None = None) -> dict:
    ts = ts or now_beijing_str()
    return {
        "run_id": run_id,
        "ts": ts,
        "hour": ts[:13],
        "odds": _odds_from_prediction(pred),
        "pick": _pick_from_prediction(pred),
    }


def _compute_changes(timeline: list[dict]) -> list[dict]:
    changes: list[dict] = []
    for i in range(1, len(timeline)):
        prev, cur = timeline[i - 1], timeline[i]
        for key, label in PICK_KEYS:
            pv = prev["pick"].get(key if key != "likely_scores_detail" else "likely_scores")
            cv = cur["pick"].get(key if key != "likely_scores_detail" else "likely_scores")
            if pv != cv:
                changes.append({
                    "ts": cur["ts"],
                    "hour": cur["hour"],
                    "field": label,
                    "from": pv,
                    "to": cv,
                    "run_id": cur["run_id"],
                })
        # significant odds moves (>3% implied shift on EU home)
        po, co = prev.get("odds") or {}, cur.get("odds") or {}
        for label, k in (("欧赔主胜", "eu_home"), ("欧赔平局", "eu_draw"), ("欧赔客胜", "eu_away")):
            a, b = po.get(k), co.get(k)
            if a and b and abs(float(b) - float(a)) / float(a) >= 0.03:
                changes.append({
                    "ts": cur["ts"],
                    "hour": cur["hour"],
                    "field": f"{label}变动",
                    "from": a,
                    "to": b,
                    "run_id": cur["run_id"],
                })
        al, bl = po.get("ah_line"), co.get("ah_line")
        if al is not None and bl is not None and al != bl:
            changes.append({
                "ts": cur["ts"],
                "hour": cur["hour"],
                "field": "亚盘盘口",
                "from": al,
                "to": bl,
                "run_id": cur["run_id"],
            })
    return changes


def append_hourly_snapshot(
    output_root: str | Path,
    fixture_id: str,
    pred: dict,
    *,
    run_id: str,
    ts: str | None = None,
    match_name: str | None = None,
) -> dict:
    """Append one hourly point to match dir; dedupe same hour (overwrite latest in hour)."""
    root = Path(output_root)
    mdir = _match_dir(root, fixture_id)
    mdir.mkdir(parents=True, exist_ok=True)

    meta_path = mdir / "meta.json"
    meta = {"fixture_id": str(fixture_id), "match_name": match_name or pred.get("match", "")}
    if meta_path.is_file():
        try:
            meta.update(json.loads(meta_path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            pass
    if match_name or pred.get("match"):
        meta["match_name"] = match_name or pred.get("match") or meta.get("match_name", "")
    meta["updated_at"] = now_beijing_str()
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    point = hourly_point(pred, run_id=run_id, ts=ts)
    timeline = load_timeline(root, fixture_id)
    if timeline and timeline[-1].get("hour") == point["hour"]:
        timeline[-1] = point
    else:
        timeline.append(point)

    index = {
        "fixture_id": str(fixture_id),
        "match_name": meta.get("match_name", ""),
        "updated_at": meta["updated_at"],
        "point_count": len(timeline),
        "timeline": timeline,
        "changes": _compute_changes(timeline),
    }
    (mdir / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    with (mdir / "hourly.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(point, ensure_ascii=False, default=str) + "\n")
    return index


def append_ai_record(
    output_root: str | Path,
    fixture_id: str,
    pred: dict,
    *,
    run_id: str,
    ts: str | None = None,
) -> dict | None:
    """Persist one AI analysis run (supports dual-model) to ai_records.jsonl."""
    analyses = compact_ai_analyses(pred)
    if not analyses:
        return None
    root = Path(output_root)
    mdir = _match_dir(root, fixture_id)
    mdir.mkdir(parents=True, exist_ok=True)
    ts = ts or now_beijing_str()
    record = {
        "ts": ts,
        "run_id": run_id,
        "manual_ai": bool(pred.get("manual_ai")),
        "recommendation_source": pred.get("recommendation_source"),
        "analyses": analyses,
    }
    path = mdir / "ai_records.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    return record


def _backfill_ai_records_from_runs(root: Path, fixture_id: str) -> list[dict]:
    """One-time rebuild of ai_records from historical run files."""
    runs_dir = root / "runs"
    if not runs_dir.is_dir():
        return []
    fid = str(fixture_id)
    records: list[dict] = []
    for rf in sorted(runs_dir.glob("*/predictions.json")):
        try:
            data = json.loads(rf.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        summary = data.get("summary") or {}
        run_id = summary.get("run_id") or rf.parent.name
        ts = data.get("generated_at") or summary.get("started_at") or run_id.replace("_", " ")
        for pred in data.get("matches") or []:
            if str(pred.get("fixture_id")) != fid:
                continue
            analyses = compact_ai_analyses(pred)
            if not analyses:
                continue
            records.append({
                "ts": ts,
                "run_id": run_id,
                "manual_ai": bool(pred.get("manual_ai")),
                "recommendation_source": pred.get("recommendation_source"),
                "analyses": analyses,
            })
    if records:
        path = _match_dir(root, fid) / "ai_records.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        log.info("从 runs 回填 %d 条 AI 记录 fid=%s", len(records), fid)
    return records


def load_ai_records(output_root: str | Path, fixture_id: str, *, limit: int = 30) -> list[dict]:
    """Load AI history newest-first."""
    root = Path(output_root)
    path = _match_dir(root, fixture_id) / "ai_records.jsonl"
    records: list[dict] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if not records:
        records = _backfill_ai_records_from_runs(root, fixture_id)
    records.sort(key=lambda r: r.get("ts") or "", reverse=True)
    return records[:limit]


def append_deep_analysis(
    output_root: str | Path,
    fixture_id: str,
    record: dict,
) -> dict:
    """Persist one deep-analysis run to deep_analysis.jsonl."""
    root = Path(output_root)
    mdir = _match_dir(root, fixture_id)
    mdir.mkdir(parents=True, exist_ok=True)
    path = mdir / "deep_analysis.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    return record


def load_deep_analyses(output_root: str | Path, fixture_id: str, *, limit: int = 10) -> list[dict]:
    """Load deep analysis records newest-first."""
    root = Path(output_root)
    path = _match_dir(root, fixture_id) / "deep_analysis.jsonl"
    records: list[dict] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    records.sort(key=lambda r: r.get("ts") or "", reverse=True)
    return records[:limit]


def load_timeline(output_root: str | Path, fixture_id: str) -> list[dict]:
    idx = _match_dir(Path(output_root), fixture_id) / "index.json"
    if idx.is_file():
        try:
            data = json.loads(idx.read_text(encoding="utf-8"))
            return data.get("timeline") or []
        except json.JSONDecodeError:
            pass
    return []


def load_match_index(output_root: str | Path, fixture_id: str) -> dict | None:
    idx = _match_dir(Path(output_root), fixture_id) / "index.json"
    if not idx.is_file():
        return None
    try:
        return json.loads(idx.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def list_match_indexes(output_root: str | Path) -> list[dict]:
    base = Path(output_root) / "matches"
    if not base.is_dir():
        return []
    out = []
    for d in sorted(base.iterdir()):
        if not d.is_dir():
            continue
        idx = d / "index.json"
        if idx.is_file():
            try:
                out.append(json.loads(idx.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                continue
    return out


def rebuild_from_runs(output_root: str | Path) -> int:
    """Rebuild match timelines from runs/*/predictions.json (sorted by time)."""
    root = Path(output_root)
    runs_dir = root / "runs"
    if not runs_dir.is_dir():
        return 0
    run_files = sorted(runs_dir.glob("*/predictions.json"))
    count = 0
    for rf in run_files:
        try:
            data = json.loads(rf.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        summary = data.get("summary") or {}
        run_id = summary.get("run_id") or rf.parent.name
        ts = data.get("generated_at") or summary.get("started_at") or run_id.replace("_", " ")
        for pred in data.get("matches") or []:
            fid = pred.get("fixture_id")
            if not fid:
                continue
            append_hourly_snapshot(
                root, fid, pred,
                run_id=run_id,
                ts=ts,
                match_name=pred.get("match"),
            )
            count += 1
    log.info("从 %d 个 run 文件重建了 %d 条时间线记录", len(run_files), count)
    return count
