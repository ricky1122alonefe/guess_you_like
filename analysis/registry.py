"""Load analysis plugin enablement (non-secret JSON config)."""

from __future__ import annotations

import copy
import json
import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PATH = ROOT / "data" / "analysis_plugins.example.json"
LOCAL_PATH = ROOT / "data" / "analysis_plugins.json"

_BUILTIN: dict[str, Any] | None = None
_KNOWN_ENRICH = frozenset({"odds_snapshot", "similarity", "jingcai", "quant"})
_KNOWN_QUANT = frozenset({"poisson", "elo", "ev", "mc"})


def _builtin_default() -> dict[str, Any]:
    global _BUILTIN
    if _BUILTIN is None:
        if EXAMPLE_PATH.is_file():
            _BUILTIN = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        else:
            _BUILTIN = {
                "version": 1,
                "enrichment": {
                    "default_steps": list(_KNOWN_ENRICH),
                    "reuse_steps": ["jingcai", "quant"],
                    "enabled": {k: True for k in _KNOWN_ENRICH},
                },
                "quant": {"enabled": {k: True for k in _KNOWN_QUANT}},
            }
    return copy.deepcopy(_BUILTIN)


def config_paths(output_root: str | Path | None = None) -> list[Path]:
    paths: list[Path] = []
    if output_root:
        paths.append(Path(output_root) / "analysis_plugins.json")
    paths.append(LOCAL_PATH)
    return paths


def resolve_config_path(output_root: str | Path | None = None) -> Path | None:
    for path in config_paths(output_root):
        if path.is_file():
            return path
    return None


def load_raw_config(output_root: str | Path | None = None) -> dict[str, Any]:
    base = _builtin_default()
    for path in reversed(config_paths(output_root)):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            base = _merge_config(base, data)
        except json.JSONDecodeError as exc:
            log.warning("分析插件配置 JSON 无效 %s: %s", path, exc)
    return base


def _merge_config(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    if "version" in patch:
        out["version"] = patch["version"]
    if patch.get("enrichment"):
        en = out.setdefault("enrichment", {})
        src = patch["enrichment"]
        for key in ("default_steps", "reuse_steps"):
            if key in src and isinstance(src[key], list):
                en[key] = list(src[key])
        if src.get("enabled"):
            en.setdefault("enabled", {}).update(src["enabled"])
    if patch.get("quant") and patch["quant"].get("enabled"):
        out.setdefault("quant", {}).setdefault("enabled", {}).update(patch["quant"]["enabled"])
    return out


def _filter_enabled(step_ids: list[str], enabled_map: dict[str, Any]) -> tuple[str, ...]:
    out: list[str] = []
    for step_id in step_ids:
        if step_id not in _KNOWN_ENRICH:
            continue
        if enabled_map.get(step_id, True):
            out.append(step_id)
    return tuple(out)


def enrichment_steps(
    mode: str = "default",
    output_root: str | Path | None = None,
) -> tuple[str, ...]:
    cfg = load_raw_config(output_root)
    en = cfg.get("enrichment") or {}
    enabled = en.get("enabled") or {}
    if mode == "reuse":
        raw = en.get("reuse_steps") or ["jingcai", "quant"]
    else:
        raw = en.get("default_steps") or list(_KNOWN_ENRICH)
    return _filter_enabled(list(raw), enabled)


def quant_steps(output_root: str | Path | None = None) -> tuple[str, ...]:
    cfg = load_raw_config(output_root)
    enabled = (cfg.get("quant") or {}).get("enabled") or {}
    order = ("poisson", "elo", "ev", "mc")
    return tuple(step for step in order if enabled.get(step, True))


def public_config_summary(output_root: str | Path | None = None) -> dict[str, Any]:
    cfg = load_raw_config(output_root)
    return {
        "version": cfg.get("version", 1),
        "config_path": str(resolve_config_path(output_root) or ""),
        "enrichment_default": list(enrichment_steps("default", output_root)),
        "enrichment_reuse": list(enrichment_steps("reuse", output_root)),
        "quant_steps": list(quant_steps(output_root)),
        "enrichment": cfg.get("enrichment") or {},
        "quant": cfg.get("quant") or {},
    }


def save_config(data: dict[str, Any], output_root: str | Path) -> Path:
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "analysis_plugins.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
