"""Pre-match desk: verified off-field factors, independent from the odds desk.

The pre-match desk only writes facts that have been verified through official or
reliable channels. It is intentionally NOT allowed to see odds, implied
probabilities, or betting markets, and it must not output a betting direction.

Current implementation is a code-only stub: it marks every dimension as missing
unless a downstream factor-fetch agent fills it. Supported leagues are limited to
the top-5 European leagues.
"""

from __future__ import annotations

from time_utils import now_beijing_str

SUPPORTED_LEAGUES = frozenset({"英超", "西甲", "德甲", "意甲", "法甲"})

_DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("availability", "伤停/停赛"),
    ("schedule_fatigue", "轮换与赛程密度"),
    ("weather", "天气"),
    ("referee", "裁判"),
    ("motivation", "战意"),
)


def _empty_dimension(dim_id: str, label: str) -> dict:
    return {
        "id": dim_id,
        "label": label,
        "score": 0,
        "confidence": "low",
        "evidence": [],
        "missing": True,
        "note": "数据不足，本维降权/跳过",
    }


def build_prematch_desk(
    pred: dict | None = None,
    *,
    league_name: str | None = None,
) -> dict:
    """Return a pre-match desk dict for the given prediction.

    If the league is not in the supported set, the desk is unavailable with
    ``reason="league_not_supported"``. For supported leagues, all dimensions
    are explicitly marked missing until verified data is injected.
    """
    pred = pred or {}
    league = league_name or pred.get("league_name") or ""

    if league not in SUPPORTED_LEAGUES:
        return {
            "available": False,
            "league_supported": False,
            "reason": "league_not_supported",
            "league_name": league,
            "as_of": now_beijing_str(),
            "dimensions": [],
            "high_impact_facts": [],
            "rerun_triggers": [],
            "note": "赛前桌暂只覆盖五大联赛（英超/西甲/德甲/意甲/法甲），本场不在支持范围。",
        }

    return {
        "available": True,
        "league_supported": True,
        "league_name": league,
        "as_of": now_beijing_str(),
        "dimensions": [_empty_dimension(dim_id, label) for dim_id, label in _DIMENSIONS],
        "high_impact_facts": [],
        "rerun_triggers": ["若官方首发缺主力门将或核心球员则重跑"],
        "note": "赛前桌不给投注方向；当前无已核验数据，全部维度标记为缺失。",
    }


def _odds_desk_pick(pred: dict) -> str:
    """Human-readable odds-desk pick + sizing, falling back to result_1x2_cn."""
    judgment = (pred.get("judgment") or "").strip()
    rec = (pred.get("recommendation") or pred.get("result_1x2_cn") or "").strip()
    if "放弃" in judgment or "放弃" in rec:
        return "放弃"
    if judgment:
        return judgment
    return rec or "观望"


def _action(odds_pick: str, prematch: dict) -> str:
    """Comparison action: hold / size_down / skip.

    The pre-match desk can never flip the odds-desk direction; it may only
    reduce sizing or recommend skipping when verified high-impact facts exist.
    """
    if odds_pick in ("放弃", "观望", "skip"):
        return "skip"
    if prematch.get("high_impact_facts"):
        return "size_down"
    return "hold"


def build_comparison_summary(
    pred: dict,
    prematch: dict | None = None,
) -> dict:
    """Generate the third comparison summary purely from JSON (no LLM call)."""
    pred = pred or {}
    prematch = prematch or pred.get("prematch_desk") or build_prematch_desk(pred)
    odds_pick = _odds_desk_pick(pred)
    action = _action(odds_pick, prematch)
    high_impact = bool(prematch.get("high_impact_facts"))

    if action == "skip":
        if odds_pick in ("放弃", "观望"):
            summary = f"盘口桌已建议{odds_pick}；赛前桌不改方向。"
        else:
            summary = (
                f"盘口桌倾向{odds_pick}，但赛前桌出现已确认高影响变数；放弃。"
            )
    elif action == "size_down":
        summary = f"盘口桌倾向{odds_pick}；赛前桌有已确认高影响变数；降成小注。"
    else:
        summary = f"盘口桌倾向{odds_pick}；赛前桌无已确认高影响变数；维持。"

    return {
        "odds_desk_pick": odds_pick,
        "prematch_available": prematch.get("available", False),
        "prematch_high_impact": high_impact,
        "action": action,
        "summary": summary,
        "cannot_flip_direction": True,
    }


def attach_prematch_and_summary(
    pred: dict,
    *,
    league_name: str | None = None,
) -> dict:
    """Mutate ``pred`` to attach both ``prematch_desk`` and ``comparison_summary``.

    If ``league_name`` is supplied, it is also written to ``pred["league_name"]``
    so that later reuse/cached predictions keep the league context.
    """
    if not pred:
        return pred
    if league_name:
        pred["league_name"] = league_name
    pred["prematch_desk"] = build_prematch_desk(pred, league_name=league_name)
    pred["comparison_summary"] = build_comparison_summary(pred, pred["prematch_desk"])
    return pred
