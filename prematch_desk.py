"""Pre-match desk: verified off-field factors, independent from the odds desk.

The pre-match desk only writes facts that have been verified through official or
reliable channels. It is intentionally NOT allowed to see odds, implied
probabilities, or betting markets, and it must not output a betting direction.

It consumes:
- sporttery_intel.py for verified injury / suspension data.
- match_agents.factor_fetch for venue/weather (Open-Meteo).
- existing club_form / recent_form for schedule density.

Supported leagues are the top-5 European leagues (short and long names from
config/jingcai_league_map.yaml).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from time_utils import now_beijing_str

log = logging.getLogger(__name__)

_TOP_FIVE_SHORT = {"英超", "西甲", "德甲", "意甲", "法甲"}
_TOP_FIVE_LONG = {
    "英格兰超级联赛",
    "西班牙甲级联赛",
    "德国甲级联赛",
    "意大利甲级联赛",
    "法国甲级联赛",
}
SUPPORTED_LEAGUES = _TOP_FIVE_SHORT | _TOP_FIVE_LONG

_DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("availability", "伤停/停赛"),
    ("schedule_fatigue", "轮换与赛程密度"),
    ("weather", "天气"),
    ("referee", "裁判"),
    ("motivation", "战意"),
)


def _load_league_map() -> dict[str, Any]:
    path = Path(__file__).resolve().parent / "config" / "jingcai_league_map.yaml"
    if not path.is_file():
        return {}
    try:
        import yaml

        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


_LEAGUE_MAP_CACHE: dict[str, Any] | None = None


def _league_map() -> dict[str, Any]:
    global _LEAGUE_MAP_CACHE
    if _LEAGUE_MAP_CACHE is None:
        _LEAGUE_MAP_CACHE = _load_league_map()
    return _LEAGUE_MAP_CACHE


def _empty_dimension(dim_id: str, label: str, *, note: str = "数据不足，本维降权/跳过") -> dict:
    return {
        "id": dim_id,
        "label": label,
        "score": 0,
        "confidence": "low",
        "evidence": [],
        "missing": True,
        "note": note,
    }


def _is_supported_league(league_name: str | None) -> bool:
    if not league_name:
        return False
    return str(league_name).strip() in SUPPORTED_LEAGUES


def build_prematch_desk(
    pred: dict | None = None,
    *,
    league_name: str | None = None,
    sporttery_intel: dict | None = None,
    factors: dict | None = None,
    schedule_ctx: dict | None = None,
) -> dict:
    """Return a pre-match desk dict for the given prediction.

    If the league is not in the supported set, the desk is unavailable with
    ``reason="league_not_supported"``. For supported leagues, verified facts
    from sporttery_intel / weather / schedule are filled in; missing data is
    explicitly marked as missing rather than fabricated.
    """
    pred = pred or {}
    league = league_name or pred.get("league_name") or ""

    if not _is_supported_league(league):
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

    # Start with all dimensions marked missing.
    dims: dict[str, dict] = {
        dim_id: _empty_dimension(dim_id, label)
        for dim_id, label in _DIMENSIONS
    }
    high_impact: list[str] = []

    _fill_availability(dims, sporttery_intel, high_impact)
    _fill_weather(dims, factors, high_impact)
    _fill_schedule_fatigue(dims, schedule_ctx)
    # referee / motivation intentionally kept missing this iteration.
    dims["referee"]["note"] = "裁判数据未接入，本维保持缺失"
    dims["motivation"]["note"] = "战意数据未接入，本维保持缺失"

    has_any_evidence = any(
        not d.get("missing") and d.get("evidence")
        for d in dims.values()
    )

    return {
        "available": True,
        "league_supported": True,
        "league_name": league,
        "as_of": now_beijing_str(),
        "dimensions": list(dims.values()),
        "high_impact_facts": high_impact,
        "rerun_triggers": ["若官方首发缺主力门将或核心球员则重跑"],
        "note": (
            "赛前桌不给投注方向。"
            + ("已有已核验事实。" if has_any_evidence else "当前部分维度数据不足，按 missing 处理。")
        ),
    }


def _fill_availability(
    dims: dict[str, dict],
    sporttery_intel: dict | None,
    high_impact: list[str],
) -> None:
    """Fill availability dimension from sporttery injury/suspension data."""
    dim = dims["availability"]
    if not sporttery_intel:
        return

    injury = (sporttery_intel.get("injury") or {})
    home = injury.get("home") or {}
    away = injury.get("away") or {}
    home_lines = _injury_lines(home)
    away_lines = _injury_lines(away)

    evidence: list[str] = []
    if home_lines:
        evidence.append("主队：" + "；".join(home_lines))
    if away_lines:
        evidence.append("客队：" + "；".join(away_lines))
    if evidence:
        dim["missing"] = False
        dim["confidence"] = "medium"
        dim["evidence"] = evidence
        dim["note"] = "来自体彩官方伤停/停赛名单"

    _extract_high_impact(home_lines, "主队", high_impact)
    _extract_high_impact(away_lines, "客队", high_impact)


def _injury_lines(side: dict[str, Any] | None) -> list[str]:
    """Convert sporttery injury side into readable evidence lines."""
    lines: list[str] = []
    for p in (side or {}).get("injuriesAndSuspensionsList") or []:
        if not isinstance(p, dict):
            continue
        name = str(p.get("personName") or "").strip()
        if not name:
            continue
        pos = str(p.get("playerPositionDesc") or "").strip()
        no = str(p.get("uniformNo") or "").strip()
        if str(p.get("suspensionFlag")) == "1":
            tag = "停赛"
        elif str(p.get("injuryFlag")) == "1":
            tag = "伤病"
        else:
            tag = "缺阵"
        prefix = f"{no}号" if no else ""
        pos_bit = f"（{pos}）" if pos else ""
        lines.append(f"{prefix}{name}{pos_bit}{tag}")
    return lines


def _extract_high_impact(lines: list[str], side_label: str, out: list[str]) -> None:
    """Only confirmed GK absence or explicit suspension count as high impact."""
    for line in lines:
        if "门将" in line and "伤病" in line:
            out.append(f"{side_label}主力门将确认伤病缺阵：{line}")
        elif "门将" in line and "缺阵" in line and "停赛" not in line:
            out.append(f"{side_label}主力门将确认缺阵：{line}")
        elif "停赛" in line:
            out.append(f"{side_label}确认停赛：{line}")


def _fill_weather(
    dims: dict[str, dict],
    factors: dict | None,
    high_impact: list[str],
) -> None:
    """Fill weather dimension from factor_fetch weather output."""
    dim = dims["weather"]
    wx = (factors or {}).get("weather") or {}
    if not wx:
        return

    condition = str(wx.get("summary") or wx.get("condition") or "").strip()
    temp = wx.get("temperature_c")
    wind = wx.get("wind_kph") or wx.get("wind_speed_kph")
    precip = wx.get("precipitation_mm")
    evidence_parts: list[str] = []
    if condition:
        evidence_parts.append(condition)
    if temp is not None:
        evidence_parts.append(f"气温约 {temp}°C")
    if wind is not None:
        evidence_parts.append(f"风速约 {wind} km/h")
    if precip is not None:
        evidence_parts.append(f"降水 {precip} mm")
    if not evidence_parts:
        return

    dim["missing"] = False
    dim["confidence"] = "medium"
    dim["evidence"] = evidence_parts
    dim["note"] = "来自 Open-Meteo 赛前预报"

    try:
        wind_val = float(wind) if wind is not None else 0
    except (TypeError, ValueError):
        wind_val = 0
    try:
        temp_val = float(temp) if temp is not None else 20
    except (TypeError, ValueError):
        temp_val = 20
    try:
        precip_val = float(precip) if precip is not None else 0
    except (TypeError, ValueError):
        precip_val = 0

    is_storm = "暴雨" in condition or "大暴雨" in condition or precip_val >= 10
    is_strong_wind = wind_val >= 40
    is_extreme_cold = temp_val <= -10
    if is_storm:
        high_impact.append(f"赛前天气：暴雨/大降水（{'，'.join(evidence_parts)}）")
    if is_strong_wind:
        high_impact.append(f"赛前天气：大风（{'，'.join(evidence_parts)}）")
    if is_extreme_cold:
        high_impact.append(f"赛前天气：极端低温（{'，'.join(evidence_parts)}）")


def _fill_schedule_fatigue(
    dims: dict[str, dict],
    schedule_ctx: dict | None,
) -> None:
    """Fill schedule density from recent-form date lists."""
    dim = dims["schedule_fatigue"]
    ctx = schedule_ctx or {}
    home_dates = ctx.get("home_dates") or []
    away_dates = ctx.get("away_dates") or []
    if not home_dates and not away_dates:
        return

    home_counts = _window_counts(home_dates)
    away_counts = _window_counts(away_dates)
    shortest_home = _shortest_gap_days(home_dates)
    shortest_away = _shortest_gap_days(away_dates)

    evidence: list[str] = []
    if home_dates:
        evidence.append(
            f"主队近7天{home_counts['d7']}场/近14天{home_counts['d14']}场"
        )
    if away_dates:
        evidence.append(
            f"客队近7天{away_counts['d7']}场/近14天{away_counts['d14']}场"
        )
    if shortest_home is not None and shortest_home < 3:
        evidence.append(f"主队最短间隔 {shortest_home:.1f} 天")
    if shortest_away is not None and shortest_away < 3:
        evidence.append(f"客队最短间隔 {shortest_away:.1f} 天")

    if evidence:
        dim["missing"] = False
        dim["confidence"] = "medium"
        dim["evidence"] = evidence
        dim["note"] = "基于近期正赛日期统计"


def _window_counts(dates: list[str]) -> dict[str, int]:
    """Count matches within 7 and 14 days from the most recent listed date."""
    from datetime import datetime, timedelta

    parsed: list[datetime] = []
    for d in dates:
        try:
            parsed.append(datetime.strptime(str(d)[:10], "%Y-%m-%d"))
        except (TypeError, ValueError):
            continue
    if not parsed:
        return {"d7": 0, "d14": 0}
    parsed.sort()
    ref = parsed[-1]
    d7 = sum(1 for dt in parsed if (ref - dt).days <= 7)
    d14 = sum(1 for dt in parsed if (ref - dt).days <= 14)
    return {"d7": d7, "d14": d14}


def _shortest_gap_days(dates: list[str]) -> float | None:
    """Return shortest gap in days between consecutive matches."""
    from datetime import datetime

    parsed: list[datetime] = []
    for d in dates:
        try:
            parsed.append(datetime.strptime(str(d)[:10], "%Y-%m-%d"))
        except (TypeError, ValueError):
            continue
    if len(parsed) < 2:
        return None
    parsed.sort()
    gaps = [(parsed[i] - parsed[i - 1]).days for i in range(1, len(parsed))]
    return min(gaps) if gaps else None


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


def _extract_schedule_dates(pred: dict) -> dict[str, list[str]]:
    """Collect recent match dates from club_form / recent_form for schedule density."""
    out: dict[str, list[str]] = {"home_dates": [], "away_dates": []}
    cf = pred.get("club_form") or {}
    rf = pred.get("recent_form") or {}
    team_recent = pred.get("team_recent_form") or {}

    def _from_samples(side: str) -> list[str]:
        key = f"{side}_all"
        samples = ((cf.get("samples") or {}).get(key) or [])[:10]
        dates: list[str] = []
        for s in samples:
            d = (s or {}).get("date") or (s or {}).get("match_date")
            if d:
                dates.append(str(d))
        return dates

    out["home_dates"] = _from_samples("home")
    out["away_dates"] = _from_samples("away")

    if not out["home_dates"] and not out["away_dates"]:
        home = (rf.get("home") or {}).get("recent_matches") or []
        away = (rf.get("away") or {}).get("recent_matches") or []
        out["home_dates"] = [str(m.get("date")) for m in home if m.get("date")]
        out["away_dates"] = [str(m.get("date")) for m in away if m.get("date")]

    if not out["home_dates"] or not out["away_dates"]:
        home_side = (team_recent.get("home") or {}).get("recent_matches") or []
        away_side = (team_recent.get("away") or {}).get("recent_matches") or []
        if not out["home_dates"]:
            out["home_dates"] = [str(m.get("date")) for m in home_side if m.get("date")]
        if not out["away_dates"]:
            out["away_dates"] = [str(m.get("date")) for m in away_side if m.get("date")]

    return out


def attach_prematch_and_summary(
    pred: dict,
    *,
    league_name: str | None = None,
    output_root: str | Path | None = None,
    fixture_id: str | None = None,
    sporttery_intel: dict | None = None,
    factors: dict | None = None,
) -> dict:
    """Mutate ``pred`` to attach both ``prematch_desk`` and ``comparison_summary``.

    If ``league_name`` is supplied, it is also written to ``pred["league_name"]``
    so that later reuse/cached predictions keep the league context.

    ``sporttery_intel`` and ``factors`` may be passed in if already fetched; otherwise
    this function will attempt to load/fetch them using existing helpers.
    """
    if not pred:
        return pred

    fid = fixture_id or pred.get("fixture_id")
    root = output_root
    if root is None and fid:
        root = pred.get("output_root") or "output/service"

    resolved_league = league_name or pred.get("league_name") or ""
    if resolved_league:
        pred["league_name"] = resolved_league

    # Try to load cached sporttery intel if not supplied.
    intel = sporttery_intel
    if intel is None and fid and root:
        try:
            from sporttery_intel import load_sporttery_intel

            intel = load_sporttery_intel(root, str(fid)) or {}
        except Exception as exc:
            log.debug("load_sporttery_intel failed fid=%s: %s", fid, exc)
            intel = {}
    if intel is None:
        intel = {}

    # Try to fetch fresh sporttery intel for supported leagues when cached empty.
    if _is_supported_league(resolved_league) and not intel and fid and root:
        try:
            from sporttery_intel import get_or_fetch_sporttery_intel

            home, away = _parse_teams(pred)
            if home and away:
                intel, _logs = get_or_fetch_sporttery_intel(
                    home, away, str(fid), root, prediction=pred
                )
                intel = intel or {}
        except Exception as exc:
            log.debug("fetch sporttery intel failed fid=%s: %s", fid, exc)
            intel = {}

    # Fetch venue/weather factors for supported leagues if not supplied.
    fac = factors
    if fac is None and _is_supported_league(resolved_league) and fid:
        try:
            from match_agents.factor_fetch import enrich_match_factors

            fac = enrich_match_factors(pred, use_cache=True)
        except Exception as exc:
            log.debug("enrich_match_factors failed fid=%s: %s", fid, exc)
            fac = {}
    if fac is None:
        fac = {}

    schedule_ctx = _extract_schedule_dates(pred)

    pred["prematch_desk"] = build_prematch_desk(
        pred,
        league_name=resolved_league,
        sporttery_intel=intel,
        factors=fac,
        schedule_ctx=schedule_ctx,
    )
    pred["comparison_summary"] = build_comparison_summary(pred, pred["prematch_desk"])
    return pred


def _parse_teams(pred: dict) -> tuple[str, str]:
    """Best-effort team name parsing from prediction dict."""
    home = str(pred.get("home_team") or "").strip()
    away = str(pred.get("away_team") or "").strip()
    if home and away:
        return home, away
    row = pred.get("predict_row") or {}
    home = home or str(row.get("主队") or "").strip()
    away = away or str(row.get("客队") or "").strip()
    if home and away:
        return home, away
    name = pred.get("match") or row.get("比赛") or ""
    for sep in (" VS ", " vs ", "VS", "vs"):
        if sep in str(name):
            parts = str(name).split(sep, 1)
            if len(parts) == 2 and parts[0].strip() and parts[1].strip():
                return parts[0].strip(), parts[1].strip()
    return home, away


def ensure_prematch_attached(
    pred: dict,
    *,
    output_root: str | Path | None = None,
    fixture_id: str | None = None,
) -> dict:
    """Idempotently attach pre-match desk and comparison summary to ``pred``.

    Used by the detail page to avoid requiring a full re-analysis just to show
    the comparison card.
    """
    if not pred:
        return pred
    if pred.get("comparison_summary") and pred.get("prematch_desk"):
        return pred
    return attach_prematch_and_summary(
        pred,
        output_root=output_root,
        fixture_id=fixture_id,
    )
