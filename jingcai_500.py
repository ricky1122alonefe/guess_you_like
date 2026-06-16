"""Fetch 竞彩 SP from live.500.com (liveOddsList) + trade.500.com metadata."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests
from bs4 import BeautifulSoup

from download_500 import _decode, DEFAULT_TIMEOUT

log = logging.getLogger(__name__)


def parse_live_odds_list(html: str) -> dict[str, dict]:
    m = re.search(r"var liveOddsList\s*=\s*(\{.*?\});", html, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}


def fetch_live_odds_list(session: requests.Session) -> dict[str, dict]:
    resp = session.get("https://live.500.com/", timeout=DEFAULT_TIMEOUT)
    resp.raise_for_status()
    return parse_live_odds_list(_decode(resp.content))


def fetch_jczq_meta_by_order(session: requests.Session) -> dict[str, dict[str, Any]]:
    """Map process order (e.g. 6005) -> match_num, handicap."""
    resp = session.get(
        "https://trade.500.com/jczq/?playid=269&g=2",
        timeout=DEFAULT_TIMEOUT,
        headers={"Referer": "https://live.500.com/"},
    )
    resp.raise_for_status()
    soup = BeautifulSoup(_decode(resp.content), "html.parser")
    out: dict[str, dict[str, Any]] = {}
    for tr in soup.find_all("tr", attrs={"data-processname": True}):
        order = str(tr.get("data-processname", "")).strip()
        if not order:
            continue
        handicap = tr.get("data-rangqiu")
        try:
            handicap = int(handicap) if handicap not in (None, "") else None
        except ValueError:
            handicap = None
        out[order] = {
            "match_num": tr.get("data-matchnum") or "",
            "handicap": handicap,
            "home": tr.get("data-homesxname") or "",
            "away": tr.get("data-awaysxname") or "",
        }
    return out


def _sp_triple(values: list | None) -> tuple[float | None, float | None, float | None]:
    if not values or len(values) < 3:
        return None, None, None
    out = []
    for v in values[:3]:
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            out.append(None)
    return out[0], out[1], out[2]


def build_jingcai_snapshot(
    fixture_id: str,
    live_odds: dict[str, dict],
    *,
    order_id: str = "",
    jczq_meta: dict[str, dict] | None = None,
) -> dict[str, Any]:
    item = live_odds.get(str(fixture_id)) or {}
    sp_h, sp_d, sp_a = _sp_triple(item.get("sp"))
    rq_h, rq_d, rq_a = _sp_triple(item.get("rqsp"))

    meta = (jczq_meta or {}).get(order_id, {}) if order_id else {}
    handicap = meta.get("handicap")
    match_num = meta.get("match_num") or ""

    handicap_label = ""
    if handicap is not None:
        if handicap > 0:
            handicap_label = f"+{handicap}"
        elif handicap < 0:
            handicap_label = str(handicap)
        else:
            handicap_label = "0"

    return {
        "match_num": match_num,
        "handicap": handicap,
        "handicap_label": handicap_label,
        "sp_home": sp_h,
        "sp_draw": sp_d,
        "sp_away": sp_a,
        "rqsp_home": rq_h,
        "rqsp_draw": rq_d,
        "rqsp_away": rq_a,
        "has_sp": sp_h is not None,
        "has_rqsp": rq_h is not None,
    }
