"""Fetch and cache league standings from football-data.org.

Only the top-5 European leagues are supported.  Data is cached under
``output/service/standings/{league}.json`` with a short TTL to avoid hitting
rate limits on the free tier.
"""

from __future__ import annotations

import difflib
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
import yaml

log = logging.getLogger(__name__)

# football-data.org competition codes for the supported top-5 leagues.
_LEAGUE_CODES: dict[str, str] = {
    "英超": "PL",
    "西甲": "PD",
    "德甲": "BL1",
    "意甲": "SA",
    "法甲": "FL1",
}

# Number of automatic relegation places assumed for high-impact detection.
_RELEGATION_PLACES = 3

# Cache TTL for standings.
_CACHE_TTL_HOURS = 6


_LEAGUE_MAP: dict[str, Any] | None = None


def _load_league_map() -> dict[str, Any]:
    global _LEAGUE_MAP
    if _LEAGUE_MAP is None:
        path = Path(__file__).resolve().parents[2] / "config" / "jingcai_league_map.yaml"
        if path.is_file():
            try:
                _LEAGUE_MAP = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except Exception:
                _LEAGUE_MAP = {}
        else:
            _LEAGUE_MAP = {}
    return _LEAGUE_MAP


def _api_key() -> str | None:
    return os.environ.get("FOOTBALL_DATA_API_KEY") or os.environ.get("FOOTBALL_DATA_API_TOKEN")


def _cache_path(output_root: str | Path, league_name: str) -> Path:
    return Path(output_root) / "standings" / f"{league_name}.json"


def _normalize_name(name: str) -> str:
    return "".join(c for c in str(name).lower() if c.isalnum())


def _team_aliases(league_name: str, team_cn: str) -> list[str]:
    """Return possible names for a Chinese team in the league map."""
    aliases: list[str] = [team_cn]
    league_map = _load_league_map()
    teams = ((league_map.get("leagues") or {}).get(league_name, {}).get("teams") or {})
    for cn, en in teams.items():
        if cn == team_cn:
            aliases.append(str(en))
            aliases.append(cn)
    return aliases


def _find_team_row(team_cn: str, table: list[dict[str, Any]], league_name: str) -> dict[str, Any] | None:
    """Find the standings row for ``team_cn`` using fuzzy name matching."""
    aliases = [_normalize_name(a) for a in _team_aliases(league_name, team_cn)]
    if not aliases:
        return None

    best: tuple[float, dict[str, Any]] = (0.0, {})
    for row in table:
        team_name = str((row.get("team") or {}).get("name") or "")
        norm_row = _normalize_name(team_name)
        for alias in aliases:
            ratio = difflib.SequenceMatcher(None, alias, norm_row).ratio()
            # substring matches get a small boost
            if alias in norm_row or norm_row in alias:
                ratio = max(ratio, 0.6)
            if ratio > best[0]:
                best = (ratio, row)

    return best[1] if best[0] >= 0.5 else None


def fetch_standings(league_name: str, api_key: str | None = None) -> dict[str, Any] | None:
    """Fetch standings from football-data.org; return raw payload or None."""
    code = _LEAGUE_CODES.get(league_name)
    if not code:
        return None
    key = api_key or _api_key()
    if not key:
        log.debug("football-data.org API key not configured")
        return None

    url = f"https://api.football-data.org/v4/competitions/{code}/standings"
    try:
        resp = requests.get(
            url,
            headers={"X-Auth-Token": key},
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        log.warning("football-data.org standings fetch failed for %s: %s", league_name, exc)
        return None


def save_standings_cache(output_root: str | Path, league_name: str, payload: dict[str, Any]) -> Path:
    path = _cache_path(output_root, league_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    cache = {
        "league_name": league_name,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_standings(
    league_name: str,
    output_root: str | Path,
    *,
    use_cache: bool = True,
    max_age_hours: float = _CACHE_TTL_HOURS,
    api_key: str | None = None,
) -> list[dict[str, Any]] | None:
    """Return the ``total`` standings table for ``league_name``.

    Uses the on-disk cache if fresh; otherwise fetches from football-data.org
    when an API key is available.  Returns ``None`` on any failure.
    """
    code = _LEAGUE_CODES.get(league_name)
    if not code:
        return None

    path = _cache_path(output_root, league_name)
    now = datetime.now(timezone.utc)

    if use_cache and path.is_file():
        try:
            cache = json.loads(path.read_text(encoding="utf-8"))
            fetched = datetime.fromisoformat(str(cache.get("fetched_at") or ""))
            if now - fetched < timedelta(hours=max_age_hours):
                payload = cache.get("payload") or {}
                table = (payload.get("standings") or [{}])[0].get("table")
                if isinstance(table, list) and table:
                    return table
        except Exception:
            pass

    payload = fetch_standings(league_name, api_key=api_key)
    if not payload:
        return None

    try:
        save_standings_cache(output_root, league_name, payload)
    except Exception:
        pass

    table = (payload.get("standings") or [{}])[0].get("table")
    return table if isinstance(table, list) and table else None


def _safety_points(table: list[dict[str, Any]]) -> tuple[int, int]:
    """Return (safety_position, safety_points) for the bottom third of the table."""
    total = len(table)
    safety_pos = max(total - _RELEGATION_PLACES + 1, 1)
    for row in table:
        if int(row.get("position") or 0) == safety_pos:
            return safety_pos, int(row.get("points") or 0)
    # fallback: sort by position
    sorted_table = sorted(table, key=lambda r: int(r.get("position") or 999))
    idx = max(safety_pos - 1, 0)
    if idx < len(sorted_table):
        return safety_pos, int(sorted_table[idx].get("points") or 0)
    return safety_pos, 0


def build_standings_context(
    table: list[dict[str, Any]] | None,
    home_cn: str,
    away_cn: str,
    league_name: str,
) -> dict[str, Any]:
    """Build a read-only motivation context from the standings table.

    The context contains verified facts only: rank, points, gap to safety,
    and whether the season is in its final round.  It never invents news.
    """
    if not table:
        return {}

    home_row = _find_team_row(home_cn, table, league_name)
    away_row = _find_team_row(away_cn, table, league_name)
    if not home_row or not away_row:
        return {}

    home_pos = int(home_row.get("position") or 0)
    away_pos = int(away_row.get("position") or 0)
    home_pts = int(home_row.get("points") or 0)
    away_pts = int(away_row.get("points") or 0)

    total_teams = len(table)
    played = max(int(r.get("playedGames") or 0) for r in table)
    total_rounds = (total_teams - 1) * 2
    is_final = played >= total_rounds

    safety_pos, safety_pts = _safety_points(table)
    home_gap = safety_pts - home_pts if home_pos >= safety_pos else None
    away_gap = safety_pts - away_pts if away_pos >= safety_pos else None

    evidence: list[str] = [
        f"主队排名第{home_pos}，积{home_pts}分",
        f"客队排名第{away_pos}，积{away_pts}分",
    ]
    if home_gap is not None:
        if home_gap > 0:
            evidence.append(f"主队距安全区（第{safety_pos}名）{home_gap}分")
        else:
            evidence.append(f"主队与安全区（第{safety_pos}名）同分")
    if away_gap is not None:
        if away_gap > 0:
            evidence.append(f"客队距安全区（第{safety_pos}名）{away_gap}分")
        else:
            evidence.append(f"客队与安全区（第{safety_pos}名）同分")
    if is_final:
        evidence.append(f"联赛末轮（已赛{played}/{total_rounds}轮）")

    return {
        "home_rank": home_pos,
        "away_rank": away_pos,
        "home_points": home_pts,
        "away_points": away_pts,
        "safety_position": safety_pos,
        "home_gap_to_safety": home_gap,
        "away_gap_to_safety": away_gap,
        "is_final_round": is_final,
        "played_games": played,
        "total_rounds": total_rounds,
        "total_teams": total_teams,
        "evidence": evidence,
    }


def is_relegation_battle(ctx: dict[str, Any]) -> bool:
    """Return True if both teams are in a relegation battle."""
    if not ctx:
        return False
    total = ctx.get("total_teams")
    home_pos = ctx.get("home_rank")
    away_pos = ctx.get("away_rank")
    home_gap = ctx.get("home_gap_to_safety")
    away_gap = ctx.get("away_gap_to_safety")
    if home_pos is None or away_pos is None:
        return False

    if total is None:
        # infer from rounds
        total = (ctx.get("total_rounds") or 38) // 2 + 1

    def _battle(pos: int, gap: int | None) -> bool:
        if pos > total - _RELEGATION_PLACES:
            return True
        if gap is not None and gap <= 3:
            return True
        return False

    return _battle(int(home_pos), home_gap) and _battle(int(away_pos), away_gap)


def refresh_standings_cache(
    output_root: str | Path,
    *,
    api_key: str | None = None,
    force: bool = False,
) -> dict[str, str]:
    """拉取/刷新五大联赛积分榜缓存。

    返回 ``{league_name: status}``，status ∈ {"ok", "no_key", "failed"}。
    - 无 API key：全部 "no_key"，不拉取也不写缓存（诚实 missing，不编数据）。
    - ``force=False`` 时复用新鲜缓存（TTL 见 ``_CACHE_TTL_HOURS``），仅过期/缺失才拉取。
    """
    key = api_key or _api_key()
    statuses: dict[str, str] = {}
    if not key:
        for league in _LEAGUE_CODES:
            statuses[league] = "no_key"
        return statuses

    for league in _LEAGUE_CODES:
        if not force:
            table = load_standings(league, output_root, api_key=key)
            statuses[league] = "ok" if table else "failed"
            continue
        payload = fetch_standings(league, key)
        if not payload:
            statuses[league] = "failed"
            continue
        try:
            save_standings_cache(output_root, league, payload)
            statuses[league] = "ok"
        except Exception as exc:
            log.warning("save standings cache failed for %s: %s", league, exc)
            statuses[league] = "failed"
    return statuses


def main(argv: list[str] | None = None) -> int:
    """CLI：拉取/刷新五大联赛积分榜缓存。

    Usage:
      guess-you-like standings                 # 仅刷新过期/缺失缓存（TTL 复用）
      guess-you-like standings --refresh       # 强制重新拉取五大联赛
      guess-you-like standings -o output/data  # 指定缓存目录
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="guess-you-like standings",
        description="拉取/刷新五大联赛积分榜缓存（football-data.org，motivation 战意维）",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="忽略 TTL 强制重新拉取五大联赛",
    )
    parser.add_argument(
        "-o", "--output",
        default="output/service",
        help="缓存目录（默认 output/service）",
    )
    args = parser.parse_args(argv)

    statuses = refresh_standings_cache(args.output, force=args.refresh)
    for league, status in statuses.items():
        label = {
            "ok": "已更新",
            "no_key": "未配置 FOOTBALL_DATA_API_KEY，跳过（诚实 missing）",
            "failed": "拉取失败",
        }.get(status, status)
        print(f"{league}: {label}")
    if not _api_key():
        print(
            "提示：设置环境变量 FOOTBALL_DATA_API_KEY（https://www.football-data.org/）"
            " 后重跑本命令即可填充战意维。",
            file=sys.stderr,
        )
    return 0 if all(s == "ok" for s in statuses.values()) else 1
