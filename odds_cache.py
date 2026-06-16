"""Skip re-analysis when downloaded xls files are unchanged."""

from __future__ import annotations

import hashlib
import json
import logging
from copy import deepcopy
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

FINGERPRINTS_FILE = "fingerprints.json"
AI_SOURCES = frozenset({"ai_expert", "ai_locked", "ai_dual", "ai_multi"})


def is_ai_prediction(cached: dict | None) -> bool:
    if not cached:
        return False
    src = str(cached.get("recommendation_source") or "")
    if src in AI_SOURCES:
        return True
    if src.startswith("ai_expert_"):
        return True
    if cached.get("ai_analyses"):
        return True
    return False


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def match_fingerprint(ah_path: Path, eu_path: Path) -> dict[str, str]:
    return {
        "ah": file_sha256(ah_path),
        "eu": file_sha256(eu_path),
    }


def fingerprint_equal(a: dict[str, str] | None, b: dict[str, str] | None) -> bool:
    if not a or not b:
        return False
    return a.get("ah") == b.get("ah") and a.get("eu") == b.get("eu")


def load_fingerprints(output_root: str | Path) -> dict[str, dict[str, str]]:
    path = Path(output_root) / FINGERPRINTS_FILE
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {str(k): v for k, v in (data or {}).items()}
    except json.JSONDecodeError:
        return {}


def save_fingerprints(output_root: str | Path, store: dict[str, dict[str, str]]) -> None:
    path = Path(output_root) / FINGERPRINTS_FILE
    path.write_text(
        json.dumps(store, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_latest_predictions(output_root: str | Path) -> dict[str, dict]:
    path = Path(output_root) / "latest.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    out: dict[str, dict] = {}
    for m in data.get("matches") or []:
        fid = m.get("fixture_id")
        if fid:
            out[str(fid)] = m
    return out


def can_reuse_prediction(
    cached: dict | None,
    *,
    use_ai: bool,
    fp_match: bool,
) -> bool:
    if not fp_match or not cached:
        return False
    if not use_ai:
        return True
    return is_ai_prediction(cached)


def reuse_prediction(
    cached: dict,
    *,
    run_id: str,
    fixture_id: str,
    ah_path: Path,
    eu_path: Path,
    match_name: str,
) -> dict[str, Any]:
    pred = deepcopy(cached)
    pred["fixture_id"] = fixture_id
    pred["run_id"] = run_id
    pred["xls_asian"] = str(ah_path)
    pred["xls_european"] = str(eu_path)
    if match_name:
        pred["match"] = match_name
    pred["analysis_cached"] = True
    pred["cache_reason"] = "xls_unchanged"
    return pred


def bootstrap_fingerprints(output_root: str | Path) -> dict[str, dict[str, str]]:
    """Seed fingerprints from xls paths in latest.json (upgrade / first deploy)."""
    preds = load_latest_predictions(output_root)
    fps: dict[str, dict[str, str]] = {}
    for fid, pred in preds.items():
        ah = pred.get("xls_asian")
        eu = pred.get("xls_european")
        if not ah or not eu:
            continue
        ah_p, eu_p = Path(ah), Path(eu)
        if ah_p.is_file() and eu_p.is_file():
            fps[fid] = match_fingerprint(ah_p, eu_p)
    if fps:
        save_fingerprints(output_root, fps)
        log.info("从 latest.json 初始化 %d 条赔率文件指纹", len(fps))
    return fps
