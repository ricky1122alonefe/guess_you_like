"""重点关注场次持久化与 API 辅助函数。

存储位置：{output_root}/cache/focus_watch.json
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_MAX_FOCUS = 10
FOCUS_WATCH_FILENAME = "focus_watch.json"


def _resolve_output_root(output_root: str | Path | None = None) -> Path:
    if output_root is None:
        # 兼容无 output_root 的调用（如 CLI 或测试），默认 output/service
        return Path("output/service")
    return Path(output_root)


def _focus_watch_path(output_root: str | Path | None = None) -> Path:
    return _resolve_output_root(output_root) / "cache" / FOCUS_WATCH_FILENAME


def load_focus_watch(output_root: str | Path | None = None) -> dict[str, Any]:
    """返回 {fids: list[str], updated_at: str|None, notes: dict[str,str]}"""
    path = _focus_watch_path(output_root)
    if not path.is_file():
        return {"fids": [], "updated_at": None, "notes": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"fids": [], "updated_at": None, "notes": {}}
        return {
            "fids": [str(x) for x in data.get("fids", []) if x],
            "updated_at": data.get("updated_at"),
            "notes": {str(k): str(v) for k, v in (data.get("notes") or {}).items()},
        }
    except Exception as exc:
        log.warning("读取 focus_watch 失败: %s", exc)
        return {"fids": [], "updated_at": None, "notes": {}}


def save_focus_watch(data: dict[str, Any], output_root: str | Path | None = None) -> None:
    path = _focus_watch_path(output_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def max_focus_limit() -> int:
    try:
        from config import FOCUS_WATCH

        cfg = FOCUS_WATCH or {}
    except Exception:
        cfg = {}
    return int(cfg.get("max", DEFAULT_MAX_FOCUS))


def is_focused(fid: str, output_root: str | Path | None = None) -> bool:
    return str(fid) in load_focus_watch(output_root)["fids"]


def focus_fids(output_root: str | Path | None = None) -> list[str]:
    return load_focus_watch(output_root)["fids"]


def add_focus_fid(
    fid: str,
    note: str | None = None,
    output_root: str | Path | None = None,
) -> tuple[bool, str]:
    data = load_focus_watch(output_root)
    fid = str(fid)
    if fid in data["fids"]:
        if note is not None:
            data["notes"][fid] = note
            save_focus_watch(data, output_root)
        return True, "已在关注列表"
    limit = max_focus_limit()
    if len(data["fids"]) >= limit:
        return False, f"最多关注 {limit} 场，请先取消其他场次"
    data["fids"].append(fid)
    if note:
        data["notes"][fid] = note
    save_focus_watch(data, output_root)
    return True, "已加入关注"


def remove_focus_fid(fid: str, output_root: str | Path | None = None) -> bool:
    data = load_focus_watch(output_root)
    fid = str(fid)
    if fid not in data["fids"]:
        return False
    data["fids"].remove(fid)
    data["notes"].pop(fid, None)
    save_focus_watch(data, output_root)
    return True


def set_focus_fids(
    fids: list[str],
    notes: dict[str, str] | None = None,
    output_root: str | Path | None = None,
) -> tuple[bool, str]:
    data = load_focus_watch(output_root)
    fids = [str(x) for x in fids if x]
    # 去重并保持顺序
    seen = set()
    unique = []
    for fid in fids:
        if fid not in seen:
            seen.add(fid)
            unique.append(fid)
    limit = max_focus_limit()
    if len(unique) > limit:
        return False, f"最多关注 {limit} 场"
    data["fids"] = unique
    if notes is not None:
        data["notes"] = {str(k): str(v) for k, v in notes.items() if k in unique}
    save_focus_watch(data, output_root)
    return True, "ok"


def clear_focus(output_root: str | Path | None = None) -> None:
    save_focus_watch({"fids": [], "updated_at": None, "notes": {}}, output_root)


def update_note(fid: str, note: str, output_root: str | Path | None = None) -> bool:
    data = load_focus_watch(output_root)
    fid = str(fid)
    if fid not in data["fids"]:
        return False
    data["notes"][fid] = note
    save_focus_watch(data, output_root)
    return True
