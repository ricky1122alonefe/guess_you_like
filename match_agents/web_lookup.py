"""Free web lookup: no API keys — Open-Meteo, wttr.in, DuckDuckGo, 500.com scrape."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any
from urllib.parse import quote_plus

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

WMO_ZH = {
    0: "晴",
    1: "大部晴朗",
    2: "局部多云",
    3: "多云",
    45: "雾",
    48: "雾凇",
    51: "小 drizzle",
    53: " drizzle",
    55: "大 drizzle",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    80: "小阵雨",
    81: "阵雨",
    82: "大阵雨",
    95: "雷暴",
    96: "雷暴伴小 hail",
    99: "强雷暴",
}


def _session():
    import requests

    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def search_web(query: str, *, max_results: int = 5) -> tuple[list[dict[str, str]], list[str]]:
    """DuckDuckGo HTML search — no API key."""
    logs: list[str] = []
    q = (query or "").strip()
    if not q:
        return [], logs
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logs.append("BeautifulSoup 不可用，跳过网页搜索")
        return [], logs
    try:
        resp = _session().post(
            "https://html.duckduckgo.com/html/",
            data={"q": q, "b": "", "kl": "cn-zh"},
            timeout=15,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as exc:
        log.warning("DuckDuckGo 搜索失败 q=%s: %s", q, exc)
        logs.append(f"网页搜索失败：{exc}")
        return [], logs

    out: list[dict[str, str]] = []
    for block in soup.select(".result")[:max_results]:
        a = block.select_one("a.result__a")
        sn = block.select_one(".result__snippet")
        title = a.get_text(" ", strip=True) if a else ""
        snippet = sn.get_text(" ", strip=True) if sn else ""
        url = a.get("href", "") if a else ""
        if title or snippet:
            out.append({"title": title, "snippet": snippet, "url": url, "query": q})
    if out:
        logs.append(f"网页搜索「{q[:40]}…」命中 {len(out)} 条" if len(q) > 40 else f"网页搜索「{q}」命中 {len(out)} 条")
    else:
        logs.append(f"网页搜索「{q[:40]}」无结果" if len(q) > 40 else f"网页搜索「{q}」无结果")
    return out, logs


def fetch_open_meteo_weather(
    lat: float,
    lon: float,
    kickoff: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Open-Meteo forecast — free, no API key."""
    logs: list[str] = []
    try:
        resp = _session().get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "hourly": "temperature_2m,relativehumidity_2m,windspeed_10m,weathercode",
                "timezone": "auto",
                "forecast_days": 16,
            },
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        logs.append(f"Open-Meteo 查询失败：{exc}")
        return {}, logs

    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        logs.append("Open-Meteo 返回空预报")
        return {}, logs

    idx = 0
    ko_dt = None
    if kickoff:
        for fmt, size in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d %H:%M", 16)):
            try:
                ko_dt = datetime.strptime(kickoff.strip()[:size], fmt)
                break
            except ValueError:
                continue
    if ko_dt:
        target = ko_dt.strftime("%Y-%m-%dT%H:00")
        best_i, best_delta = 0, None
        for i, t in enumerate(times):
            try:
                fdt = datetime.strptime(t[:16], "%Y-%m-%dT%H:%M")
            except ValueError:
                continue
            delta = abs((fdt - ko_dt).total_seconds())
            if best_delta is None or delta < best_delta:
                best_delta = delta
                best_i = i
        idx = best_i

    def _at(key: str):
        arr = hourly.get(key) or []
        return arr[idx] if idx < len(arr) else None

    code = _at("weathercode")
    temp = _at("temperature_2m")
    humidity = _at("relativehumidity_2m")
    wind = _at("windspeed_10m")
    condition = WMO_ZH.get(int(code) if code is not None else -1, f"代码{code}")
    out = {
        "source": "open_meteo",
        "summary": condition,
        "condition": condition,
        "temperature_c": temp,
        "humidity_pct": humidity,
        "wind_kph": round(float(wind or 0), 1),
        "forecast_time": times[idx] if idx < len(times) else None,
    }
    logs.append(
        f"Open-Meteo（免 key）：{out.get('forecast_time')} · {condition} · {temp}°C · 风{out.get('wind_kph')}km/h"
    )
    return out, logs


def fetch_wttr_weather(city: str) -> tuple[dict[str, Any], list[str]]:
    """wttr.in JSON — free, by city name."""
    logs: list[str] = []
    city = (city or "").strip()
    if not city:
        return {}, logs
    try:
        resp = _session().get(
            f"https://wttr.in/{quote_plus(city)}",
            params={"format": "j1", "lang": "zh"},
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        logs.append(f"wttr.in 查询失败：{exc}")
        return {}, logs

    cur = ((payload.get("current_condition") or [{}])[0]) or {}
    descs = cur.get("lang_zh") or cur.get("weatherDesc") or []
    condition = descs[0].get("value") if descs else "未知"
    out = {
        "source": "wttr.in",
        "summary": condition,
        "condition": condition,
        "temperature_c": cur.get("temp_C"),
        "humidity_pct": cur.get("humidity"),
        "wind_kph": cur.get("windspeedKmph"),
        "forecast_time": "current",
        "city": city,
    }
    logs.append(f"wttr.in（免 key）：{city} · {condition} · {out.get('temperature_c')}°C")
    return out, logs


def search_match_intel(
    home: str,
    away: str,
    kickoff: str,
    *,
    city: str = "",
) -> tuple[dict[str, Any], list[str]]:
    """Web search for injuries / lineup hints — snippets only, no fabrication."""
    logs: list[str] = []
    if not home or not away:
        logs.append("缺少主客队，跳过伤停网页搜索")
        return {}, logs

    date_part = kickoff[:10] if kickoff else ""
    queries = [
        f"{home} {away} 伤停 首发 {date_part}".strip(),
        f"{home} vs {away} injury lineup {date_part}".strip(),
    ]
    if city:
        queries.append(f"{city} {date_part} 足球 比赛 天气")

    hits: list[dict[str, str]] = []
    for q in queries:
        rows, qlogs = search_web(q, max_results=3)
        logs.extend(qlogs)
        hits.extend(rows)
        if len(hits) >= 6:
            break

    if not hits:
        return {}, logs

    snippets = []
    for h in hits[:6]:
        bit = h.get("snippet") or h.get("title") or ""
        if bit and bit not in snippets:
            snippets.append(bit[:200])

    summary = snippets[0][:120] if snippets else ""
    return {
        "source": "web_search",
        "summary": summary,
        "snippets": snippets,
        "queries": queries,
        "hits": hits[:6],
    }, logs


def scrape_500_youliao(fixture_id: str) -> tuple[dict[str, Any], list[str]]:
    """Scrape odds.500.com 情报页 for venue/weather hints."""
    logs: list[str] = []
    fid = str(fixture_id or "").strip()
    if not fid or not fid.isdigit():
        return {}, logs
    try:
        from bs4 import BeautifulSoup
        from download_500 import BASE, _decode
    except ImportError:
        logs.append("无法加载 500.com 解析模块")
        return {}, logs

    url = f"{BASE}/fenxi/youliao-{fid}.shtml"
    try:
        resp = _session().get(url, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(_decode(resp.content), "html.parser")
    except Exception as exc:
        logs.append(f"500.com 情报页抓取失败：{exc}")
        return {}, logs

    text = soup.get_text("\n", strip=True)
    out: dict[str, Any] = {"source": "500_youliao", "url": url}
    snippets: list[str] = []

    patterns = (
        (r"(?:球场|场地|场馆|体育场)[：:\s]*([^\n，。；]{2,40})", "venue_line"),
        (r"(?:天气|气温|温度)[：:\s]*([^\n，。；]{2,40})", "weather_line"),
        (r"(?:海拔|伤停|缺阵|首发)[：:\s]*([^\n，。；]{2,60})", "intel_line"),
    )
    for pat, key in patterns:
        m = re.search(pat, text)
        if m:
            val = m.group(1).strip()
            out[key] = val
            snippets.append(f"{key}: {val}")

    for kw in ("球场", "天气", "伤停", "首发", "海拔", "场地"):
        for line in text.splitlines():
            if kw in line and 4 < len(line) < 120:
                if line not in snippets:
                    snippets.append(line.strip())
                if len(snippets) >= 8:
                    break

    if snippets:
        out["snippets"] = snippets[:8]
        out["summary"] = snippets[0]
        logs.append(f"500.com 情报页已抓取 {len(snippets)} 条线索")
    else:
        logs.append("500.com 情报页未解析到场地/天气/伤停线索")
    return out, logs
