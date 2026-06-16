"""Minimal smoke tests — no network, no API keys."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_groups_json_valid():
    path = ROOT / "data" / "wc2026_groups.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["format"]["teams"] == 48
    assert len(data["groups"]) == 12


def test_import_core_modules():
    import config  # noqa: F401
    import market_patterns  # noqa: F401
    import eu_implied_metrics  # noqa: F401
    import share_card  # noqa: F401


def test_long_image_export_helper():
    from share_card import long_image_export_script

    js = long_image_export_script(root_id="test-root", filename="demo")
    assert "savePageLongImage" in js
    assert "test-root" in js
