"""Configurable agent pipeline stages (sequential + parallel groups)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from .profiles import AGENT_REGISTRY

BUILTIN_IDS = frozenset({"input", "hard_guards", "archive", "chief"})

AGENT_LABELS: dict[str, str] = {
    "intel": "情报 Agent",
    "external_context": "外部因素 Agent",
    "schedule_venue": "赛程球馆 Agent",
    "late_confirmation": "临场确认 Agent",
    "opening_structure": "开盘结构 Agent",
    "scenario_simulator": "杯赛场景模拟 Agent",
    "goal_swing": "一球杠杆 Agent",
    "cross_group_path": "跨组出线路径 Agent",
    "market_consistency": "欧亚一致性 Agent",
    "contrarian": "反方辩手 Agent",
    "memory": "成长记忆库 Agent",
    "history": "历史战绩 Agent",
    "result_1x2": "胜负研判 Agent",
    "scoreline": "比分研判 Agent",
    "asian_handicap": "亚洲盘口 Agent",
    "european_odds": "欧洲盘口 Agent",
    "jingcai": "竞彩 Agent",
    "cup_standing": "积分出线 Agent",
    "motivation": "战意 Agent",
    "league_pressure": "联赛压力 Agent",
}

DEFAULT_PIPELINE: dict[str, Any] = {
    "version": 1,
    "profiles": {},
}


def agent_label(agent_id: str) -> str:
    return AGENT_LABELS.get(agent_id, agent_id)


def _data_path(output_root: str | Path | None = None) -> Path:
    from .config import config_path

    return config_path(output_root)


def _legacy_agent_ids(cfg: dict[str, Any], profile_id: str) -> list[str]:
    profiles = cfg.get("profiles") or {}
    return list((profiles.get(profile_id) or {}).get("agents") or [])


def stages_from_legacy_agents(agent_ids: list[str]) -> list[dict[str, Any]]:
    """Build a sensible default pipeline from flat agent list."""
    stages: list[dict[str, Any]] = [
        {"id": "input", "type": "builtin", "title": "输入数据校验", "enabled": True},
    ]
    remaining = list(agent_ids)
    trio = ["intel", "external_context", "schedule_venue"]
    if all(x in remaining for x in trio):
        stages.append({
            "id": "data_collect",
            "type": "parallel",
            "title": "并行数据采集",
            "agents": trio,
            "enabled": True,
        })
        remaining = [x for x in remaining if x not in trio]

    market_ids = [x for x in remaining if x in ("asian_handicap", "european_odds", "jingcai", "market_consistency")]
    if len(market_ids) >= 2:
        stages.append({
            "id": "market_parallel",
            "type": "parallel",
            "title": "盘口并行分析",
            "agents": market_ids,
            "enabled": True,
        })
        remaining = [x for x in remaining if x not in market_ids]

    pick_pair = [x for x in ("result_1x2", "scoreline") if x in remaining]
    if len(pick_pair) == 2:
        stages.append({
            "id": "pick_parallel",
            "type": "parallel",
            "title": "胜负比分并行研判",
            "agents": pick_pair,
            "enabled": True,
        })
        remaining = [x for x in remaining if x not in pick_pair]

    if remaining:
        stages.append({
            "id": "experts_seq",
            "type": "sequential",
            "title": "专家顺序分析",
            "agents": remaining,
            "enabled": True,
        })

    stages.extend([
        {"id": "hard_guards", "type": "builtin", "title": "硬风险闸门", "enabled": True},
        {"id": "archive", "type": "builtin", "title": "归档证据板", "enabled": True},
        {"id": "chief", "type": "builtin", "title": "Chief AI 总 Agent", "enabled": True, "optional": True},
    ])
    return stages


def normalize_stage(raw: dict[str, Any]) -> dict[str, Any]:
    st = dict(raw or {})
    typ = str(st.get("type") or "agent").lower()
    if typ == "agent":
        aid = str(st.get("agent") or st.get("id") or "").strip()
        if aid in BUILTIN_IDS:
            typ = "builtin"
            st["id"] = aid
        else:
            st["agent"] = aid
            st.setdefault("id", aid)
    st["type"] = typ
    st["enabled"] = st.get("enabled", True) is not False
    if typ in ("parallel", "sequential"):
        agents = [str(x).strip() for x in (st.get("agents") or []) if str(x).strip()]
        st["agents"] = [a for a in agents if a in AGENT_REGISTRY]
    if typ == "agent":
        aid = str(st.get("agent") or "").strip()
        if aid not in AGENT_REGISTRY:
            st["enabled"] = False
    if typ == "builtin":
        bid = str(st.get("id") or "").strip()
        if bid not in BUILTIN_IDS:
            st["enabled"] = False
    st.setdefault("title", agent_label(st.get("agent") or st.get("id") or "阶段"))
    return st


def normalize_stages(stages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [normalize_stage(s) for s in (stages or []) if isinstance(s, dict)]


def flatten_agents_from_stages(stages: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for st in normalize_stages(stages):
        if not st.get("enabled", True):
            continue
        typ = st.get("type")
        if typ == "agent":
            aid = st.get("agent")
            if aid and aid not in seen:
                seen.add(aid)
                out.append(aid)
        elif typ in ("parallel", "sequential"):
            for aid in st.get("agents") or []:
                if aid not in seen:
                    seen.add(aid)
                    out.append(aid)
    return out


def count_executable_steps(stages: list[dict[str, Any]], *, run_chief: bool) -> int:
    n = 0
    for st in normalize_stages(stages):
        if not st.get("enabled", True):
            continue
        typ = st.get("type")
        if typ == "builtin":
            bid = st.get("id")
            if bid == "chief" and not run_chief:
                continue
            if bid == "chief" and st.get("optional") and not run_chief:
                continue
            n += 1
        elif typ == "agent":
            n += 1
        elif typ in ("parallel", "sequential"):
            n += len(st.get("agents") or [])
    return n


def load_pipeline_profile(
    profile_id: str,
    *,
    output_root: str | Path | None = None,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from .config import load_match_agent_config

    cfg = cfg or load_match_agent_config(output_root)
    pipe = cfg.get("pipeline") or {}
    prof = ((pipe.get("profiles") or {}).get(profile_id) or {})
    stages = prof.get("stages")
    if not stages:
        stages = stages_from_legacy_agents(_legacy_agent_ids(cfg, profile_id))
    stages = normalize_stages(stages)
    return {
        "profile_id": profile_id,
        "description": str(((cfg.get("profiles") or {}).get(profile_id) or {}).get("description") or ""),
        "stages": stages,
        "agents_flat": flatten_agents_from_stages(stages),
        "config_path": str(_data_path(output_root)),
    }


def load_pipeline_editor_payload(*, output_root: str | Path | None = None) -> dict[str, Any]:
    from .config import load_match_agent_config

    cfg = load_match_agent_config(output_root)
    profiles = {}
    for pid in ("cup", "league"):
        if pid in (cfg.get("profiles") or {}) or pid in ((cfg.get("pipeline") or {}).get("profiles") or {}):
            profiles[pid] = load_pipeline_profile(pid, output_root=output_root, cfg=cfg)
    return {
        "version": (cfg.get("pipeline") or {}).get("version") or 1,
        "default_profile": cfg.get("default_profile") or "cup",
        "profiles": profiles,
        "agent_registry": [
            {"id": aid, "label": agent_label(aid)}
            for aid in sorted(AGENT_REGISTRY.keys())
        ],
        "builtin_registry": [
            {"id": "input", "label": "输入数据校验"},
            {"id": "hard_guards", "label": "硬风险闸门"},
            {"id": "archive", "label": "归档证据板"},
            {"id": "chief", "label": "Chief AI 总 Agent", "optional": True},
        ],
        "config_path": str(_data_path(output_root)),
    }


def save_pipeline_profile(
    profile_id: str,
    stages: list[dict[str, Any]],
    *,
    output_root: str | Path | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    path = _data_path(output_root)
    if not path.is_file():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    cfg = json.loads(path.read_text(encoding="utf-8"))
    stages = normalize_stages(stages)
    pipe = cfg.setdefault("pipeline", {"version": 1, "profiles": {}})
    pipe.setdefault("profiles", {})[profile_id] = {
        "stages": stages,
        "description": description or ((cfg.get("profiles") or {}).get(profile_id) or {}).get("description"),
    }
    flat = flatten_agents_from_stages(stages)
    if flat:
        cfg.setdefault("profiles", {}).setdefault(profile_id, {})["agents"] = flat
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return load_pipeline_profile(profile_id, output_root=output_root, cfg=cfg)


def reset_pipeline_profile(
    profile_id: str,
    *,
    output_root: str | Path | None = None,
) -> dict[str, Any]:
    """Rebuild pipeline stages from the legacy flat agents list."""
    from .config import load_match_agent_config

    cfg = load_match_agent_config(output_root)
    stages = stages_from_legacy_agents(_legacy_agent_ids(cfg, profile_id))
    return save_pipeline_profile(profile_id, stages, output_root=output_root)


def save_all_pipeline_profiles(
    profiles: dict[str, dict[str, Any]],
    *,
    output_root: str | Path | None = None,
) -> dict[str, Any]:
    saved: dict[str, Any] = {}
    for pid, body in (profiles or {}).items():
        if not isinstance(body, dict):
            continue
        saved[pid] = save_pipeline_profile(
            pid,
            list(body.get("stages") or []),
            output_root=output_root,
            description=body.get("description"),
        )
    return {
        "ok": True,
        "profiles": {k: load_pipeline_profile(k, output_root=output_root) for k in saved},
        "path": str(_data_path(output_root)),
    }


def iter_execution_blocks(
    stages: list[dict[str, Any]],
    *,
    run_chief: bool = False,
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for st in normalize_stages(stages):
        if not st.get("enabled", True):
            continue
        typ = st.get("type")
        if typ == "builtin":
            bid = str(st.get("id") or "")
            if bid == "chief" and not run_chief:
                continue
            blocks.append({"block": "builtin", "id": bid, "stage": st})
        elif typ == "agent":
            aid = st.get("agent")
            if aid:
                blocks.append({"block": "sequential", "agents": [aid], "stage": st})
        elif typ == "sequential":
            agents = list(st.get("agents") or [])
            if agents:
                blocks.append({"block": "sequential", "agents": agents, "stage": st})
        elif typ == "parallel":
            agents = list(st.get("agents") or [])
            if agents:
                blocks.append({"block": "parallel", "agents": agents, "stage": st})
    return blocks


def iter_stage_agent_ids(stages: list[dict[str, Any]]) -> list[tuple[str, str, dict[str, Any]]]:
    """
    Expand stages to execution units: (mode, agent_id, stage_meta)
    mode: sequential | parallel_member
    """
    units: list[tuple[str, str, dict[str, Any]]] = []
    for st in normalize_stages(stages):
        if not st.get("enabled", True):
            continue
        typ = st.get("type")
        if typ == "agent":
            aid = st.get("agent")
            if aid:
                units.append(("sequential", aid, st))
        elif typ == "sequential":
            for aid in st.get("agents") or []:
                units.append(("sequential", aid, st))
        elif typ == "parallel":
            for aid in st.get("agents") or []:
                units.append(("parallel", aid, st))
    return units
