"""Persistence helpers for match-agent artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def match_agent_dir(output_root: str | Path, fixture_id: str) -> Path:
    return Path(output_root) / "matches" / str(fixture_id)


def append_agent_artifact(
    output_root: str | Path,
    fixture_id: str,
    filename: str,
    payload: dict[str, Any],
) -> None:
    mdir = match_agent_dir(output_root, fixture_id)
    mdir.mkdir(parents=True, exist_ok=True)
    path = mdir / filename
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def load_agent_artifacts(
    output_root: str | Path,
    fixture_id: str,
    filename: str,
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    path = match_agent_dir(output_root, fixture_id) / filename
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    rows.reverse()
    return rows[:limit] if limit is not None else rows


def load_latest_artifact(
    output_root: str | Path,
    fixture_id: str,
    filename: str,
) -> dict[str, Any] | None:
    rows = load_agent_artifacts(output_root, fixture_id, filename, limit=1)
    return rows[0] if rows else None
