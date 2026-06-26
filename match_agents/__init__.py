"""Multi-agent match analysis for cup fixtures."""

from .board import build_agent_board, build_and_archive_agent_board
from .chief import run_chief_match_agent, load_latest_chief_report
from .growth import build_and_archive_growth_report, build_growth_report, load_latest_growth_report
from .types import AgentBoard, AgentReport

__all__ = [
    "AgentBoard",
    "AgentReport",
    "build_agent_board",
    "build_and_archive_agent_board",
    "run_chief_match_agent",
    "load_latest_chief_report",
    "build_growth_report",
    "build_and_archive_growth_report",
    "load_latest_growth_report",
]
