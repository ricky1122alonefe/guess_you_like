"""Load / save AI provider registry (non-secret fields). Keys stay in env / local_secrets."""

from __future__ import annotations

import copy
import json
import logging
import os
from pathlib import Path
from typing import Any

import config as app_cfg

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent
EXAMPLE_PATH = ROOT / "data" / "ai_providers.example.json"
LOCAL_PATH = ROOT / "data" / "ai_providers.json"

_BUILTIN_DEFAULT: dict[str, Any] | None = None


def _builtin_default() -> dict[str, Any]:
    global _BUILTIN_DEFAULT
    if _BUILTIN_DEFAULT is None:
        if EXAMPLE_PATH.is_file():
            _BUILTIN_DEFAULT = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        else:
            _BUILTIN_DEFAULT = {
                "version": 1,
                "primary_id": "deepseek",
                "predict_mode": "multi",
                "providers": [],
                "multi": {"on_disagreement": "skip"},
            }
    return copy.deepcopy(_BUILTIN_DEFAULT)


def config_paths(output_root: str | Path | None = None) -> list[Path]:
    paths: list[Path] = []
    if output_root:
        paths.append(Path(output_root) / "ai_config.json")
    paths.append(LOCAL_PATH)
    return paths


def resolve_config_path(output_root: str | Path | None = None) -> Path | None:
    for path in config_paths(output_root):
        if path.is_file():
            return path
    return None


def load_raw_config(output_root: str | Path | None = None) -> dict[str, Any]:
    """Merged config: runtime file > data/ai_providers.json > example defaults."""
    base = _builtin_default()
    for path in reversed(config_paths(output_root)):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            base = _merge_config(base, data)
        except json.JSONDecodeError as exc:
            log.warning("AI 配置 JSON 无效 %s: %s", path, exc)
    env_mode = os.environ.get("AI_PREDICT_MODE", "").strip().lower()
    if env_mode in ("single", "multi", "primary_only"):
        base["predict_mode"] = env_mode
    env_primary = os.environ.get("AI_PRIMARY_ID", "").strip()
    if env_primary:
        base["primary_id"] = env_primary
    return base


def _merge_config(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key in ("version", "primary_id", "predict_mode", "multi"):
        if key in patch:
            out[key] = patch[key]
    if patch.get("providers"):
        by_id = {p["id"]: p for p in out.get("providers") or [] if p.get("id")}
        for item in patch["providers"]:
            pid = item.get("id")
            if not pid:
                continue
            if pid in by_id:
                merged = copy.deepcopy(by_id[pid])
                merged.update(item)
                by_id[pid] = merged
            else:
                by_id[pid] = copy.deepcopy(item)
        out["providers"] = sorted(by_id.values(), key=lambda p: p.get("order", 999))
    return out


def save_config(data: dict[str, Any], output_root: str | Path) -> Path:
    """Persist non-secret AI config under output_root/ai_config.json."""
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "ai_config.json"
    cleaned = sanitize_config_for_save(data)
    path.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("已保存 AI 配置 %s", path)
    return path


def sanitize_config_for_save(data: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(data)
    for prov in out.get("providers") or []:
        prov.pop("api_key", None)
        prov.pop("configured", None)
    return out


def _env_enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def provider_entry(config: dict[str, Any], provider_id: str) -> dict[str, Any] | None:
    for p in config.get("providers") or []:
        if str(p.get("id")) == provider_id:
            return p
    return None


def resolve_api_key(entry: dict[str, Any]) -> str | None:
    from ai_profiles import AiProfile

    prof = AiProfile(
        provider_id=str(entry.get("id") or ""),
        label=str(entry.get("label") or entry.get("id") or ""),
        model=str(entry.get("model") or ""),
        base_url=str(entry.get("base_url") or ""),
        api_key_env=str(entry.get("api_key_env") or ""),
        alt_api_key_envs=list(entry.get("alt_api_key_envs") or []),
    )
    return prof.resolve_api_key()


def entry_requires_env(entry: dict[str, Any]) -> bool:
    for name in entry.get("requires_env") or []:
        if not _env_enabled(str(name)):
            return False
    return True


def is_provider_configured(entry: dict[str, Any]) -> bool:
    if not entry.get("enabled", True):
        return False
    if not entry_requires_env(entry):
        return False
    return bool(resolve_api_key(entry))


def list_provider_entries(
    config: dict[str, Any] | None = None,
    *,
    output_root: str | Path | None = None,
    role: str | None = None,
    configured_only: bool = False,
) -> list[dict[str, Any]]:
    cfg = config or load_raw_config(output_root)
    rows: list[dict[str, Any]] = []
    for entry in cfg.get("providers") or []:
        if not entry.get("enabled", True):
            continue
        roles = entry.get("roles") or []
        if role and role not in roles:
            continue
        if not entry_requires_env(entry):
            continue
        configured = bool(resolve_api_key(entry))
        if configured_only and not configured:
            continue
        rows.append({
            "id": entry.get("id"),
            "label": entry.get("label") or entry.get("id"),
            "model": entry.get("model"),
            "base_url": entry.get("base_url"),
            "client": entry.get("client", "openai"),
            "roles": roles,
            "enabled": bool(entry.get("enabled", True)),
            "configured": configured,
            "api_key_env": entry.get("api_key_env"),
            "order": entry.get("order", 999),
        })
    rows.sort(key=lambda r: (r.get("order", 999), str(r.get("id"))))
    return rows


def public_config_summary(output_root: str | Path | None = None) -> dict[str, Any]:
    cfg = load_raw_config(output_root)
    return {
        "version": cfg.get("version", 1),
        "primary_id": cfg.get("primary_id"),
        "predict_mode": cfg.get("predict_mode", "multi"),
        "multi": cfg.get("multi") or {},
        "config_path": str(resolve_config_path(output_root) or ""),
        "providers": list_provider_entries(cfg, role=None, configured_only=False),
    }


def validate_config_patch(patch: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if "predict_mode" in patch:
        if patch["predict_mode"] not in ("single", "multi", "primary_only"):
            errors.append("predict_mode 须为 single / multi / primary_only")
    if "providers" in patch:
        if not isinstance(patch["providers"], list):
            errors.append("providers 必须是数组")
        else:
            for i, p in enumerate(patch["providers"]):
                if not p.get("id"):
                    errors.append(f"providers[{i}] 缺少 id")
    return errors
