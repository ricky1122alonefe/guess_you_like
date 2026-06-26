"""Match-agent profile selection and role registry."""

from __future__ import annotations

from typing import Callable

from .config import load_match_agent_config
from . import experts

AgentFn = Callable[..., object]

AGENT_REGISTRY: dict[str, AgentFn] = {
    "intel": experts.intel_agent,
    "external_context": experts.external_context_agent,
    "schedule_venue": experts.schedule_venue_agent,
    "opening_structure": experts.opening_structure_agent,
    "goal_swing": experts.goal_swing_agent,
    "cross_group_path": experts.cross_group_path_agent,
    "history": experts.history_agent,
    "asian_handicap": experts.asian_handicap_agent,
    "european_odds": experts.european_odds_agent,
    "jingcai": experts.jingcai_agent,
    "cup_standing": experts.cup_standing_agent,
    "motivation": experts.motivation_agent,
    "league_pressure": experts.league_pressure_agent,
}

CUP_HINTS = ("世界杯", "欧洲杯", "亚洲杯", "美洲杯", "杯", "World Cup", "Cup")
LEAGUE_HINTS = (
    "英超",
    "西甲",
    "意甲",
    "德甲",
    "法甲",
    "Premier League",
    "La Liga",
    "Serie A",
    "Bundesliga",
    "Ligue 1",
)


def resolve_match_profile(prediction: dict | None, *, explicit: str | None = None, output_root=None) -> str:
    if explicit in ("cup", "league"):
        return explicit
    pred = prediction or {}
    row = pred.get("predict_row") or {}
    texts = [
        pred.get("profile"),
        pred.get("competition"),
        pred.get("league"),
        pred.get("league_name"),
        row.get("赛事"),
        row.get("联赛"),
        row.get("比赛"),
        pred.get("match"),
    ]
    blob = " ".join(str(x or "") for x in texts)
    if any(x in blob for x in LEAGUE_HINTS):
        return "league"
    if any(x in blob for x in CUP_HINTS):
        return "cup"
    cfg = load_match_agent_config(output_root)
    default = str(cfg.get("default_profile") or "cup")
    return default if default in ("cup", "league") else "cup"


def agents_for_profile(profile: str, *, output_root=None) -> list[AgentFn]:
    cfg = load_match_agent_config(output_root)
    profiles = cfg.get("profiles") or {}
    ids = ((profiles.get(profile) or {}).get("agents") or [])
    out: list[AgentFn] = []
    for agent_id in ids:
        fn = AGENT_REGISTRY.get(str(agent_id))
        if fn:
            out.append(fn)
    if out:
        return out
    return [AGENT_REGISTRY[x] for x in (profiles.get("cup") or {}).get("agents", []) if x in AGENT_REGISTRY]


def profile_description(profile: str, *, output_root=None) -> str:
    cfg = load_match_agent_config(output_root)
    return str(((cfg.get("profiles") or {}).get(profile) or {}).get("description") or profile)
