"""Fetch and enrich venue / weather / schedule — no API keys required."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from .web_lookup import (
    fetch_open_meteo_weather,
    fetch_wttr_weather,
    scrape_500_youliao,
    search_match_intel,
)

log = logging.getLogger(__name__)

_FACTOR_CACHE: dict[str, dict[str, Any]] = {}


def _catalog_path(output_root: str | Path | None = None) -> Path:
    base = Path(__file__).resolve().parents[1]
    return base / "data" / "match_venues.json"


def _load_venue_catalog(output_root: str | Path | None = None) -> dict[str, Any]:
    path = _catalog_path(output_root)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def parse_match_teams(pred: dict, index: dict | None = None) -> tuple[str, str]:
    home = str(pred.get("home_team") or (index or {}).get("home_team") or "").strip()
    away = str(pred.get("away_team") or (index or {}).get("away_team") or "").strip()
    if home and away:
        return home, away
    row = pred.get("predict_row") or {}
    home = home or str(row.get("主队") or "").strip()
    away = away or str(row.get("客队") or "").strip()
    if home and away:
        return home, away
    name = (
        pred.get("match")
        or row.get("比赛")
        or (index or {}).get("match_name")
        or ""
    )
    for sep in (" VS ", " vs ", "VS", "vs", " v ", "－", "—"):
        if sep in str(name):
            parts = str(name).split(sep, 1)
            if len(parts) == 2 and parts[0].strip() and parts[1].strip():
                return parts[0].strip(), parts[1].strip()
    return "", ""


def kickoff_value(pred: dict, index: dict | None = None) -> str:
    row = pred.get("predict_row") or {}
    return str(
        pred.get("kickoff_at")
        or pred.get("kickoff")
        or (index or {}).get("kickoff_at")
        or (index or {}).get("kickoff")
        or row.get("开球")
        or row.get("比赛时间")
        or ""
    ).strip()


def read_config_factor_source(
    source: str | None,
    pred: dict,
    index: dict | None,
) -> dict[str, Any] | None:
    if not source:
        return None
    try:
        path = Path(source).expanduser()
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[1] / source
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    fid = str(pred.get("fixture_id") or (index or {}).get("fixture_id") or "")
    name = pred.get("match") or (pred.get("predict_row") or {}).get("比赛") or (index or {}).get("match_name") or ""
    if isinstance(data, dict):
        matches = data.get("matches") if isinstance(data.get("matches"), dict) else data
        if fid and isinstance(matches, dict) and fid in matches:
            item = matches[fid]
            return item if isinstance(item, dict) else {"summary": str(item)}
        if name and isinstance(matches, dict) and name in matches:
            item = matches[name]
            return item if isinstance(item, dict) else {"summary": str(item)}
    return None


def _resolve_venue_from_catalog(
    pred: dict,
    index: dict | None,
    *,
    output_root: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Fixed stadium catalog → city / lat / lon / altitude (no API)."""
    catalog = _load_venue_catalog(output_root)
    venues = catalog.get("venues") or {}
    logs: list[str] = []
    fid = str(pred.get("fixture_id") or (index or {}).get("fixture_id") or "")
    overrides = catalog.get("fixture_overrides") or {}
    venue_key = overrides.get(fid) if fid else None
    if venue_key:
        logs.append(f"球场固定映射 fixture={fid} → {venue_key}")
    if not venue_key:
        home, _away = parse_match_teams(pred, index)
        team_map = catalog.get("team_default_venue") or {}
        venue_key = team_map.get(home) if home else None
        if venue_key:
            logs.append(f"球场固定映射：主队「{home}」→ catalog:{venue_key}")
    if not venue_key:
        row = pred.get("predict_row") or {}
        comp = str(
            pred.get("competition")
            or pred.get("league")
            or pred.get("league_name")
            or row.get("赛事")
            or row.get("联赛")
            or ""
        )
        comp_map = catalog.get("competition_default_venue") or {}
        for key, vk in comp_map.items():
            if key and key in comp:
                venue_key = vk
                logs.append(f"球场固定映射：赛事「{comp}」→ {venue_key}")
                break
    if not venue_key:
        logs.append("catalog 未匹配球场；可在 data/match_venues.json 的 fixture_overrides 指定")
        return {}, logs
    raw = venues.get(venue_key)
    if not isinstance(raw, dict):
        logs.append(f"catalog 键 {venue_key} 无效")
        return {}, logs
    venue = dict(raw)
    venue["source"] = "catalog"
    venue["catalog_key"] = venue_key
    city = venue.get("city") or ""
    stadium = venue.get("stadium") or ""
    logs.append(f"球场={stadium} · 城市={city}（固定目录，城市随球场确定）")
    return venue, logs


def _fetch_weather_no_key(
    venue: dict[str, Any],
    kickoff: str,
) -> tuple[dict[str, Any], list[str]]:
    lat = venue.get("lat")
    lon = venue.get("lon")
    city = str(venue.get("city") or "").strip()
    if lat is not None and lon is not None:
        wx, logs = fetch_open_meteo_weather(float(lat), float(lon), kickoff)
        if wx:
            return wx, logs
    if city:
        return fetch_wttr_weather(city)
    return {}, ["球场无坐标/城市，无法免 key 查天气"]


def _optional_openweather(
    venue: dict[str, Any],
    kickoff: str,
    cfg: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Only if user voluntarily configured OPENWEATHER_API_KEY."""
    logs: list[str] = []
    env_name = str(cfg.get("openweather_api_key_env") or "OPENWEATHER_API_KEY")
    api_key = os.environ.get(env_name) or os.environ.get("OPENWEATHER_API_KEY")
    if not api_key:
        return {}, logs
    lat, lon = venue.get("lat"), venue.get("lon")
    if lat is None or lon is None:
        return {}, logs
    try:
        import requests
    except ImportError:
        return {}, logs
    try:
        resp = requests.get(
            "https://api.openweathermap.org/data/2.5/forecast",
            params={
                "lat": lat,
                "lon": lon,
                "appid": api_key,
                "units": "metric",
                "lang": "zh_cn",
            },
            timeout=12,
            headers={"User-Agent": "guess-you-like/1.0"},
        )
        resp.raise_for_status()
        payload = resp.json()
        items = payload.get("list") or []
        if not items:
            return {}, logs
        chosen = items[0]
        main = chosen.get("main") or {}
        wind = chosen.get("wind") or {}
        wlist = chosen.get("weather") or []
        condition = wlist[0].get("description") if wlist else "预报"
        out = {
            "source": "openweather",
            "summary": condition,
            "condition": condition,
            "temperature_c": main.get("temp"),
            "humidity_pct": main.get("humidity"),
            "wind_kph": round(float(wind.get("speed") or 0) * 3.6, 1),
            "forecast_time": chosen.get("dt_txt"),
        }
        logs.append(f"OpenWeather（可选 key）已补充天气")
        return out, logs
    except Exception as exc:
        logs.append(f"OpenWeather 可选查询失败：{exc}")
        return {}, logs


def enrich_match_factors(
    pred: dict,
    index: dict | None = None,
    *,
    output_root: str | Path | None = None,
    cfg: dict[str, Any] | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """
    Resolve factors without requiring API keys:
    venue = fixed catalog; weather = Open-Meteo/wttr; intel = 500 scrape + web search.
    """
    from .config import load_match_agent_config

    fid = str(pred.get("fixture_id") or (index or {}).get("fixture_id") or "")
    if use_cache and fid and fid in _FACTOR_CACHE:
        return _FACTOR_CACHE[fid]

    cfg = cfg or load_match_agent_config(output_root)
    ext = cfg.get("external_factors") or {}
    auto_fetch = ext.get("auto_fetch", True)
    sources = ext.get("sources") or {}
    fetch_log: list[str] = []

    kickoff = kickoff_value(pred, index)
    schedule: dict[str, Any] = {}
    venue: dict[str, Any] = {}
    weather: dict[str, Any] = {}
    news: dict[str, Any] = {}

    if kickoff:
        schedule = {"kickoff_at": kickoff, "source": "prediction"}

    for key, bucket in (("schedule", schedule), ("venue", venue), ("weather", weather), ("news", news)):
        item = read_config_factor_source(sources.get(key), pred, index)
        if item:
            bucket.clear()
            bucket.update(item)
            bucket.setdefault("source", "config")
            fetch_log.append(f"{key} 来自本地配置文件")

    home, away = parse_match_teams(pred, index)

    if auto_fetch and not venue:
        resolved, logs = _resolve_venue_from_catalog(pred, index, output_root=output_root)
        fetch_log.extend(logs)
        if resolved:
            venue.update(resolved)

    if auto_fetch and fid:
        scraped, slogs = scrape_500_youliao(fid)
        fetch_log.extend(slogs)
        if scraped.get("snippets") and not news:
            news.update({
                "source": "500_youliao",
                "summary": scraped.get("summary") or scraped["snippets"][0],
                "snippets": scraped.get("snippets") or [],
            })
        if scraped.get("venue_line") and venue:
            venue.setdefault("notes_500", scraped.get("venue_line"))

    if auto_fetch and not news:
        intel, ilogs = search_match_intel(home, away, kickoff, city=str(venue.get("city") or ""))
        fetch_log.extend(ilogs)
        if intel:
            news.update(intel)

    if auto_fetch and not weather and venue:
        wx, wx_logs = _fetch_weather_no_key(venue, kickoff)
        fetch_log.extend(wx_logs)
        if wx:
            weather.update(wx)
        if not weather:
            ow, ow_logs = _optional_openweather(venue, kickoff, ext)
            fetch_log.extend(ow_logs)
            if ow:
                weather.update(ow)

    missing = []
    if not kickoff:
        missing.append("kickoff")
    if not venue:
        missing.append("venue")
    if not weather:
        missing.append("weather")
    if not news:
        missing.append("news")

    has_core = bool(venue and kickoff)
    status = "available"
    if missing:
        status = "partial" if has_core else "insufficient_data"
    if venue and weather and kickoff:
        status = "available" if news else "partial"

    result = {
        "schedule": schedule,
        "venue": venue,
        "weather": weather,
        "news": news,
        "fetch_log": fetch_log,
        "home_team": home,
        "away_team": away,
        "kickoff_at": kickoff,
        "missing": missing,
        "auto_fetch": auto_fetch,
        "status": status,
    }
    if fid and use_cache:
        _FACTOR_CACHE[fid] = result
    return result


def clear_factor_cache() -> None:
    _FACTOR_CACHE.clear()
