"""Persist user personal viewing notes per match."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from match_agents.storage import match_agent_dir

NOTE_FILE = "viewing_note.json"


def load_viewing_note(output_root: str | Path | None, fixture_id: str | None) -> str:
    if not output_root or not fixture_id:
        return ""
    path = match_agent_dir(output_root, fixture_id) / NOTE_FILE
    if not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ""
    return str(data.get("personal_note") or "").strip()


def save_viewing_note(
    output_root: str | Path,
    fixture_id: str,
    personal_note: str,
) -> dict[str, Any]:
    note = str(personal_note or "").strip()[:500]
    path = match_agent_dir(output_root, fixture_id) / NOTE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fixture_id": str(fixture_id),
        "personal_note": note,
        "updated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
