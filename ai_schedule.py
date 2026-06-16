"""Limit AI analysis to at most once per interval (save API cost)."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from time_utils import BEIJING, now_beijing, now_beijing_str

log = logging.getLogger(__name__)

DEFAULT_AI_INTERVAL_SEC = 3600  # 1 hour


def _path(output_root: str | Path) -> Path:
    return Path(output_root) / "ai_schedule.json"


def _load(output_root: str | Path) -> dict:
    p = _path(output_root)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save(output_root: str | Path, data: dict) -> None:
    p = _path(output_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def seconds_since_last_ai(output_root: str | Path) -> float | None:
    data = _load(output_root)
    ts = data.get("last_ai_at")
    if not ts:
        return None
    try:
        last = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=BEIJING)
    except ValueError:
        return None
    return max(0.0, (now_beijing() - last).total_seconds())


def should_run_ai(
    output_root: str | Path,
    *,
    interval_sec: int = DEFAULT_AI_INTERVAL_SEC,
    force: bool = False,
) -> bool:
    if force or interval_sec <= 0:
        return True
    elapsed = seconds_since_last_ai(output_root)
    if elapsed is None:
        return True
    if elapsed >= interval_sec:
        return True
    log.info(
        "AI 节流：距上次 %d 秒（需间隔 %d 秒），本轮跳过 AI",
        int(elapsed), interval_sec,
    )
    return False


def record_ai_run(output_root: str | Path, *, ai_called: int, run_id: str = "") -> None:
    if ai_called <= 0:
        return
    data = _load(output_root)
    data["last_ai_at"] = now_beijing_str()
    data["last_ai_run_id"] = run_id
    data["last_ai_called"] = ai_called
    _save(output_root, data)


def ai_schedule_info(output_root: str | Path) -> dict:
    data = _load(output_root)
    elapsed = seconds_since_last_ai(output_root)
    return {
        "last_ai_at": data.get("last_ai_at"),
        "last_ai_called": data.get("last_ai_called", 0),
        "seconds_since_last_ai": int(elapsed) if elapsed is not None else None,
    }
