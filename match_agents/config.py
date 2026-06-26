"""Configurable weights and external-factor sources for match agents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_AGENT_WEIGHTS: dict[str, float] = {
    "intel": 0.5,
    "external_context": 0.6,
    "schedule_venue": 1.15,
    "opening_structure": 1.25,
    "goal_swing": 1.4,
    "cross_group_path": 1.45,
    "league_pressure": 1.25,
    "history": 0.7,
    "asian_handicap": 1.2,
    "european_odds": 1.1,
    "jingcai": 1.35,
    "cup_standing": 1.25,
    "motivation": 1.3,
}

DEFAULT_CONFIG: dict[str, Any] = {
    "default_profile": "cup",
    "profiles": {
        "cup": {
            "description": "杯赛：小组出线、跨组第三、淘汰赛路径、默契球/控分、一球杠杆。",
            "agents": [
                "intel",
                "external_context",
                "schedule_venue",
                "opening_structure",
                "goal_swing",
                "cross_group_path",
                "history",
                "asian_handicap",
                "european_odds",
                "jingcai",
                "cup_standing",
                "motivation",
            ],
        },
        "league": {
            "description": "联赛：赛程密度、多线战斗压力、球队战意、历史战绩、盘口与竞彩。",
            "agents": [
                "intel",
                "external_context",
                "schedule_venue",
                "league_pressure",
                "history",
                "asian_handicap",
                "european_odds",
                "jingcai",
                "motivation",
            ],
        },
    },
    "agent_weights": DEFAULT_AGENT_WEIGHTS,
    "external_factors": {
        "enabled": True,
        "default_weight": 0.6,
        "sources": {
            "news": None,
            "weather": None,
            "venue": None,
            "schedule": None,
        },
        "notes": [
            "外部因素只有在配置文件提供可靠数据源或本地数据文件时才参与研判。",
            "未提供数据时，总 Agent 必须写明暂无可靠新闻/天气/场地数据。",
        ],
    },
}


def config_path(output_root: str | Path | None = None) -> Path:
    base = Path(__file__).resolve().parents[1]
    return base / "data" / "match_agent_weights.json"


def load_match_agent_config(output_root: str | Path | None = None) -> dict[str, Any]:
    path = config_path(output_root)
    cfg = json.loads(json.dumps(DEFAULT_CONFIG, ensure_ascii=False))
    if not path.is_file():
        return cfg
    try:
        user_cfg = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return cfg
    weights = user_cfg.get("agent_weights") or {}
    cfg["agent_weights"].update({str(k): float(v) for k, v in weights.items()})
    if user_cfg.get("default_profile"):
        cfg["default_profile"] = str(user_cfg.get("default_profile"))
    profiles = user_cfg.get("profiles") or {}
    if isinstance(profiles, dict):
        for name, profile in profiles.items():
            if isinstance(profile, dict):
                cfg.setdefault("profiles", {}).setdefault(str(name), {}).update(profile)
    ext = user_cfg.get("external_factors") or {}
    if ext:
        cfg["external_factors"].update(ext)
        cfg["external_factors"]["sources"] = {
            **(DEFAULT_CONFIG["external_factors"].get("sources") or {}),
            **(ext.get("sources") or {}),
        }
    return cfg


def agent_weight(agent_id: str, output_root: str | Path | None = None) -> float:
    cfg = load_match_agent_config(output_root)
    return float((cfg.get("agent_weights") or {}).get(agent_id, 1.0))
