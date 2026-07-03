"""Fetch injury, scorers and style stats from sporttery.cn match data API."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from match_agents.storage import match_agent_dir

log = logging.getLogger(__name__)

SPORTTERY_API = "https://webapi.sporttery.cn"
INTEL_FILE = "sporttery_intel.json"

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_REFERER = "https://www.sporttery.cn/jc/zqdz/index.html"


def _session():
    import requests

    s = requests.Session()
    s.headers.update({
        "User-Agent": _USER_AGENT,
        "Referer": _REFERER,
        "Accept": "application/json",
    })
    return s


def _get_json(path: str, *, params: dict | None = None) -> dict[str, Any]:
    url = f"{SPORTTERY_API}{path}"
    try:
        resp = _session().get(url, params=params or {}, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        if str(data.get("errorCode")) != "0":
            log.warning("sporttery API %s: %s", path, data.get("errorMessage"))
            return {}
        return data.get("value") or {}
    except Exception as exc:
        log.warning("sporttery fetch failed %s: %s", path, exc)
        return {}


def fetch_match_calculator() -> list[dict[str, Any]]:
    raw = _get_json(
        "/gateway/jc/football/getMatchCalculatorV1.qry",
        params={"poolCode": "had", "channel": "c"},
    )
    out: list[dict[str, Any]] = []
    for group in raw.get("matchInfoList") or []:
        for row in group.get("subMatchList") or []:
            if isinstance(row, dict):
                out.append(row)
    return out


def _team_hit(row: dict[str, Any], home_cn: str, away_cn: str) -> bool:
    h = str(row.get("homeTeamAbbName") or row.get("homeTeamAllName") or "")
    a = str(row.get("awayTeamAbbName") or row.get("awayTeamAllName") or "")
    if not h or not a:
        return False
    return home_cn in h and away_cn in a


def discover_sporttery_match_id(
    home_cn: str,
    away_cn: str,
    *,
    match_num: str = "",
) -> tuple[str, list[str]]:
    logs: list[str] = []
    rows = fetch_match_calculator()
    logs.append(f"体彩在售场次 {len(rows)} 场")
    digits = re.sub(r"\D", "", str(match_num or ""))
    for row in rows:
        mid = str(row.get("matchId") or "")
        if not mid:
            continue
        if digits and digits in str(row.get("matchNum") or ""):
            if _team_hit(row, home_cn, away_cn):
                logs.append(f"按场次号命中 sportteryMatchId={mid}")
                return mid, logs
        if _team_hit(row, home_cn, away_cn):
            logs.append(f"按队名命中 sportteryMatchId={mid}")
            return mid, logs
    logs.append("未在体彩在售列表找到对阵")
    return "", logs


def fetch_injury_suspension(sporttery_match_id: str) -> dict[str, Any]:
    return _get_json(
        "/gateway/uniform/football/getInjurySuspensionV1.qry",
        params={"sportteryMatchId": sporttery_match_id},
    )


def fetch_match_players(sporttery_match_id: str, *, term_limits: int = 3) -> dict[str, Any]:
    return _get_json(
        "/gateway/uniform/football/getMatchPlayerV1.qry",
        params={"sportteryMatchId": sporttery_match_id, "termLimits": term_limits},
    )


def fetch_match_feature(sporttery_match_id: str, *, term_limits: int = 10) -> dict[str, Any]:
    return _get_json(
        "/gateway/uniform/football/getMatchFeatureV1.qry",
        params={"sportteryMatchId": sporttery_match_id, "termLimits": term_limits},
    )


def _injury_lines(side: dict[str, Any] | None) -> list[str]:
    lines: list[str] = []
    try:
        from fifa_translate import translate_player_name
    except Exception:
        translate_player_name = lambda x: x  # type: ignore
    for p in (side or {}).get("injuriesAndSuspensionsList") or []:
        if not isinstance(p, dict):
            continue
        name = translate_player_name(str(p.get("personName") or "").strip())
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
    return lines[:4]


def _scorer_lines(side: dict[str, Any] | None) -> list[str]:
    lines: list[str] = []
    try:
        from fifa_translate import translate_player_name
    except Exception:
        translate_player_name = lambda x: x  # type: ignore
    for p in (side or {}).get("playerList") or []:
        if not isinstance(p, dict):
            continue
        name = translate_player_name(str(p.get("personName") or "").strip())
        if not name:
            continue
        pos = str(p.get("playerPositionDesc") or "").strip()
        apps = p.get("appearanceCnt")
        goals = p.get("goalCnt")
        assists = p.get("assistCnt")
        gp = str(p.get("goalProbability") or "").strip()
        pos_bit = f"（{pos}）" if pos else ""
        stat = f"{apps}场{goals}球"
        if assists not in (None, "", 0, "0"):
            stat += f"{assists}助"
        if gp:
            stat += f"，进球占比{gp}"
        lines.append(f"{name}{pos_bit}{stat}")
    return lines[:3]


def _style_lines(feature: dict[str, Any] | None, *, side: str) -> list[str]:
    feat = feature or {}
    goal = feat.get("goalAvg") or {}
    loss = feat.get("lossGoalAvg") or {}
    last = feat.get("last") or {}
    prefix = "home" if side == "home" else "away"
    lines: list[str] = []
    try:
        ga = float(goal.get(f"{prefix}GoalAvgCnt") or 0)
        la = float(loss.get(f"{prefix}LossGoalAvgCnt") or 0)
        ratio = int(float(last.get(f"{prefix}ScoreRatio") or 0))
    except (TypeError, ValueError):
        ga = la = 0.0
        ratio = 0
    if ga >= 2.0:
        lines.append(f"近10场场均进{ga:g}球，进攻火力强")
    elif ga >= 1.0:
        lines.append(f"近10场场均进{ga:g}球")
    if la and la <= 0.8:
        lines.append(f"场均失球{la:g}，防线较稳")
    elif la >= 1.5:
        lines.append(f"场均失球{la:g}，防守端有隐患")
    if ratio >= 65:
        lines.append(f"近期取分率约{ratio}%")
    elif ratio and ratio <= 35:
        lines.append(f"近期状态偏冷（取分率约{ratio}%）")
    return lines[:2]


def build_viewing_overlay(intel: dict[str, Any] | None) -> dict[str, Any]:
    """Map sporttery_intel.json → poster team module patches."""
    if not intel:
        return {}
    inj = intel.get("injury") or {}
    players = intel.get("players") or {}
    feature = intel.get("feature") or {}
    return {
        "team_modules": {
            "home": {
                "injuries": _injury_lines(inj.get("home")),
                "key_players": _scorer_lines(players.get("home")),
                "tactics_lines": _style_lines(feature, side="home"),
            },
            "away": {
                "injuries": _injury_lines(inj.get("away")),
                "key_players": _scorer_lines(players.get("away")),
                "tactics_lines": _style_lines(feature, side="away"),
            },
        },
        "source_url": intel.get("source_url") or "",
        "sporttery_match_id": intel.get("sporttery_match_id") or "",
    }


def intel_path(output_root: str | Path, fixture_id: str) -> Path:
    return match_agent_dir(output_root, fixture_id) / INTEL_FILE


def load_sporttery_intel(output_root: str | Path | None, fixture_id: str | None) -> dict[str, Any] | None:
    if not output_root or not fixture_id:
        return None
    path = intel_path(output_root, fixture_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("读取体彩情报失败 %s: %s", path, exc)
        return None


def save_sporttery_intel(output_root: str | Path, fixture_id: str, payload: dict[str, Any]) -> Path:
    path = intel_path(output_root, fixture_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _jingcai_match_num(prediction: dict | None) -> str:
    for p in reversed((prediction or {}).get("timeline") or []):
        jc = (p.get("odds") or {}).get("jingcai") or {}
        num = str(jc.get("match_num") or "").strip()
        if num:
            return num
    jc = (prediction or {}).get("jingcai_snapshot") or {}
    return str(jc.get("match_num") or "").strip()


def fetch_sporttery_intel_for_match(
    home_cn: str,
    away_cn: str,
    *,
    sporttery_match_id: str = "",
    match_num: str = "",
) -> tuple[dict[str, Any], list[str]]:
    logs: list[str] = []
    mid = str(sporttery_match_id or "").strip()
    if not mid:
        mid, dlogs = discover_sporttery_match_id(home_cn, away_cn, match_num=match_num)
        logs.extend(dlogs)
    if not mid:
        return {}, logs

    injury = fetch_injury_suspension(mid)
    players = fetch_match_players(mid)
    feature = fetch_match_feature(mid)
    if not injury and not players and not feature:
        logs.append("体彩 API 未返回可用数据")
        return {}, logs

    payload = {
        "sporttery_match_id": mid,
        "home_cn": home_cn,
        "away_cn": away_cn,
        "source_url": f"https://www.sporttery.cn/jc/zqdz/index.html?showType=2&mid={mid}",
        "injury": injury,
        "players": players,
        "feature": feature,
        "fetched_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "fetch_log": logs,
    }
    logs.append(f"体彩情报 OK mid={mid}")
    return payload, logs


def get_or_fetch_sporttery_intel(
    home_cn: str,
    away_cn: str,
    fixture_id: str,
    output_root: str | Path,
    *,
    prediction: dict | None = None,
    sporttery_match_id: str = "",
    force: bool = False,
) -> tuple[dict[str, Any] | None, list[str]]:
    logs: list[str] = []
    if not force:
        cached = load_sporttery_intel(output_root, fixture_id)
        if cached:
            logs.append("使用已缓存体彩情报")
            return cached, logs

    match_num = _jingcai_match_num(prediction)
    data, flogs = fetch_sporttery_intel_for_match(
        home_cn,
        away_cn,
        sporttery_match_id=sporttery_match_id,
        match_num=match_num,
    )
    logs.extend(flogs)
    if not data:
        return load_sporttery_intel(output_root, fixture_id), logs
    data["fixture_id"] = str(fixture_id)
    save_sporttery_intel(output_root, fixture_id, data)
    logs.append(f"已保存 {INTEL_FILE}")
    return data, logs
