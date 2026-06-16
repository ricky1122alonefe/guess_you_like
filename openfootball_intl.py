"""Free national-team fixtures from openfootball/worldcup (GitHub, no API key)."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests

log = logging.getLogger(__name__)

BASE_RAW = "https://raw.githubusercontent.com/openfootball/worldcup/master/2026--usa"
CACHE_DIR = Path(__file__).resolve().parent / "data" / "openfootball"
FILES = ("cup.txt", "quali_playoffs.txt")

# openfootball / FIFA normalized names -> wc2026_groups canonical CN
NAME_TO_CN: dict[str, str] = {
    "Mexico": "墨西哥",
    "Canada": "加拿大",
    "USA": "美国",
    "United States": "美国",
    "South Korea": "韩国",
    "Korea Republic": "韩国",
    "Czech Republic": "捷克",
    "Czechia": "捷克",
    "Bosnia & Herzegovina": "波黑",
    "Bosnia and Herzegovina": "波黑",
    "Ivory Coast": "科特迪瓦",
    "Côte d'Ivoire": "科特迪瓦",
    "Cote d'Ivoire": "科特迪瓦",
    "Cape Verde": "佛得角",
    "Cabo Verde": "佛得角",
    "DR Congo": "刚果(金)",
    "Congo DR": "刚果(金)",
    "Curaçao": "库拉索",
    "Curacao": "库拉索",
    "Turkey": "土耳其",
    "Türkiye": "土耳其",
    "Turkiye": "土耳其",
    "IR Iran": "伊朗",
    "Iran": "伊朗",
    "South Africa": "南非",
    "Saudi Arabia": "沙特",
    "New Zealand": "新西兰",
    "North Macedonia": "北马其顿",
    "Republic of Ireland": "爱尔兰",
    "Northern Ireland": "北爱尔兰",
    "New Caledonia": "新喀里多尼亚",
    "Jamaica": "牙买加",
    "Bolivia": "玻利维亚",
    "Suriname": "苏里南",
    "Albania": "阿尔巴尼亚",
    "Romania": "罗马尼亚",
    "Kosovo": "科索沃",
    "Slovakia": "斯洛伐克",
    "Denmark": "丹麦",
    "Poland": "波兰",
    "Sweden": "瑞典",
    "Italy": "意大利",
    "Ukraine": "乌克兰",
    "Wales": "威尔士",
    "Algeria": "阿尔及利亚",
    "Uzbekistan": "乌兹别克",
}


def _load_groups_aliases() -> dict[str, str]:
    path = Path(__file__).resolve().parent / "data" / "wc2026_groups.json"
    out = dict(NAME_TO_CN)
    if not path.is_file():
        return out
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        for cn, aliases in (data.get("aliases") or {}).items():
            out[cn] = cn
            for a in aliases or []:
                out[str(a)] = cn
    except json.JSONDecodeError:
        pass
    return out


_ALIASES = _load_groups_aliases()


def canonical_openfootball_team(name: str) -> str:
    s = (name or "").strip()
    if not s:
        return s
    if s in _ALIASES:
        return _ALIASES[s]
    return s


# e.g. "Mexico 2-0 (1-0) South Africa @ Mexico City"
# or "Italy 2-0 Northern Ireland @ Bergamo"
_MATCH_LINE = re.compile(
    r"(?P<home>[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s&\(\)\-\']{1,40}?)\s+"
    r"(?P<sh>\d+)-(?P<sa>\d+)"
    r"(?:\s*\([^)]+\))?"
    r"(?:\s+a\.e\.t\.[^@]*)?"
    r"(?:\s+\d+-\d+\s+pen\.)?"
    r"\s+(?P<away>[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s&\(\)\-\']{1,40}?)\s+@",
)


def _parse_date_prefix(line: str) -> str | None:
    m = re.search(r"(?:Th|Fr|Sa|Su|Tu|Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\d{1,2}/\d{1,2}/\d{2,4})", line)
    if m:
        raw = m.group(1)
        for fmt in ("%d/%m/%y", "%d/%m/%Y"):
            try:
                return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
    m = re.search(r"(?:June|Jun)\s+(\d{1,2})", line)
    if m:
        return f"2026-06-{int(m.group(1)):02d}"
    return None


def _fetch_text(name: str) -> str:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / name
    if cache.is_file() and (datetime.now().timestamp() - cache.stat().st_mtime) < 86400:
        return cache.read_text(encoding="utf-8")
    url = f"{BASE_RAW}/{name}"
    resp = requests.get(url, timeout=45)
    resp.raise_for_status()
    text = resp.text
    cache.write_text(text, encoding="utf-8")
    return text


@lru_cache(maxsize=1)
def load_openfootball_matches() -> list[dict[str, Any]]:
    """Parse 2026 WC group + qualifier results from openfootball text files."""
    rows: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for fname in FILES:
        try:
            text = _fetch_text(fname)
        except Exception as exc:
            log.warning("openfootball %s 下载失败: %s", fname, exc)
            continue
        for line in text.splitlines():
            m = _MATCH_LINE.search(line)
            if not m:
                continue
            home_raw = m.group("home").strip()
            away_raw = m.group("away").strip()
            sh, sa = int(m.group("sh")), int(m.group("sa"))
            key = (home_raw, away_raw, sh, sa)
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "date": _parse_date_prefix(line) or "—",
                "home_raw": home_raw,
                "away_raw": away_raw,
                "home_cn": canonical_openfootball_team(home_raw),
                "away_cn": canonical_openfootball_team(away_raw),
                "score_h": sh,
                "score_a": sa,
                "competition": "openfootball/2026",
                "source_file": fname,
            })
    rows.sort(key=lambda r: (r.get("date") or "", r.get("home_raw") or ""), reverse=True)
    return rows


def teams_in_openfootball() -> set[str]:
    out: set[str] = set()
    for r in load_openfootball_matches():
        out.add(r["home_cn"])
        out.add(r["away_cn"])
    return out
