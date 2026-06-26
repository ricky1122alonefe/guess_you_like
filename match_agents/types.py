"""Shared contracts for match-level expert agents."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Verdict = Literal["lean_home", "lean_draw", "lean_away", "skip", "risk", "neutral"]
Action = Literal["buy", "single_only", "skip", "watch"]


@dataclass
class AgentReport:
    agent_id: str
    name: str
    verdict: Verdict = "neutral"
    confidence: float = 0.0
    risk: float = 0.0
    weight: float = 1.0
    evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    recommended_action: Action = "watch"
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["confidence"] = round(float(data.get("confidence") or 0), 3)
        data["risk"] = round(float(data.get("risk") or 0), 3)
        return data


@dataclass
class AgentBoard:
    ok: bool
    fixture_id: str
    match_name: str
    generated_at: str
    scope: str = "cup"
    agents: list[AgentReport] = field(default_factory=list)
    hard_guards: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "fixture_id": self.fixture_id,
            "match_name": self.match_name,
            "generated_at": self.generated_at,
            "scope": self.scope,
            "agents": [a.to_dict() for a in self.agents],
            "hard_guards": self.hard_guards,
            "summary": self.summary,
        }
