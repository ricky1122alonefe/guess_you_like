"""Fetch Betfair (必发) volume / index from odds.500.com touzhu analysis page."""

from __future__ import annotations

import logging
import re
from typing import Any

from bs4 import BeautifulSoup

from download_500 import BASE, _decode, DEFAULT_TIMEOUT

log = logging.getLogger(__name__)

_OUTCOME_KEYS = ("home", "draw", "away")
_OUTCOME_CN = ("主胜", "平局", "客胜")


def _js_string(html: str, name: str) -> str | None:
    m = re.search(rf"{name}\s*=\s*\"([^\"]*)\"", html)
    return m.group(1) if m else None


def _parse_num(text: str) -> float | None:
    text = str(text or "").strip().replace(",", "")
    if not text or text in {"-", "—"}:
        return None
    text = text.rstrip("%")
    try:
        return float(text)
    except ValueError:
        return None


def _parse_int(text: str) -> int | None:
    v = _parse_num(text)
    if v is None:
        return None
    return int(v)


def _split_csv(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def _parse_outcome_table(soup: BeautifulSoup) -> list[dict[str, Any]]:
    for tbl in soup.find_all("table"):
        header = tbl.get_text("", strip=True)
        if "必发成交" not in header or "成交量" not in header:
            continue
        rows: list[dict[str, Any]] = []
        for tr in tbl.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all("td")]
            if len(cells) < 7:
                continue
            label = cells[0]
            if label in ("", "数据提点") or "VS" in label:
                continue
            rows.append({
                "label": label,
                "eu_odds": _parse_num(cells[1]),
                "eu_prob_pct": _parse_num(cells[2]),
                "bf_trade_pct": _parse_num(cells[4]) if len(cells) > 4 else None,
                "trade_price": _parse_num(cells[5]) if len(cells) > 5 else None,
                "volume": _parse_int(cells[6]) if len(cells) > 6 else None,
                "book_pl": _parse_int(cells[7]) if len(cells) > 7 else None,
                "hot_cold": _parse_num(cells[9]) if len(cells) > 9 else None,
                "bf_index": _parse_num(cells[10]) if len(cells) > 10 else None,
            })
        if len(rows) >= 3:
            return rows[:3]
    return []


def _build_trend(html: str) -> dict[str, Any]:
    times = _split_csv(_js_string(html, "trade_time"))
    win = [_parse_num(x) for x in _split_csv(_js_string(html, "trade_win"))]
    draw = [_parse_num(x) for x in _split_csv(_js_string(html, "trade_draw"))]
    lost = [_parse_num(x) for x in _split_csv(_js_string(html, "trade_lost"))]
    n = min(len(times), len(win), len(draw), len(lost))
    if n == 0:
        return {"labels": [], "home_pct": [], "draw_pct": [], "away_pct": []}
    return {
        "labels": times[:n],
        "home_pct": win[:n],
        "draw_pct": draw[:n],
        "away_pct": lost[:n],
    }


def parse_betfair_html(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    if "暂无数据" in html and "trade_list" not in html:
        return {"has_data": False}

    volumes = [_parse_int(x) for x in _split_csv(_js_string(html, "trade_list"))]
    while len(volumes) < 3:
        volumes.append(None)
    vol_h, vol_d, vol_a = volumes[0], volumes[1], volumes[2]

    trade_odds = [_parse_num(x) for x in _split_csv(_js_string(html, "trade_odds"))]
    while len(trade_odds) < 3:
        trade_odds.append(None)

    big_vol = [_parse_int(x) for x in _split_csv(_js_string(html, "big_list"))]
    big_buy = [_parse_int(x) for x in _split_csv(_js_string(html, "big_buy"))]
    big_sell = [_parse_int(x) for x in _split_csv(_js_string(html, "big_sell"))]
    while len(big_vol) < 3:
        big_vol.append(None)
    while len(big_buy) < 3:
        big_buy.append(None)
    while len(big_sell) < 3:
        big_sell.append(None)

    outcomes = _parse_outcome_table(soup)
    outcome_map: dict[str, dict] = {}
    for i, key in enumerate(_OUTCOME_KEYS):
        base = outcomes[i] if i < len(outcomes) else {}
        outcome_map[key] = {
            "label": base.get("label") or _OUTCOME_CN[i],
            "eu_odds": base.get("eu_odds"),
            "eu_prob_pct": base.get("eu_prob_pct"),
            "trade_pct": base.get("bf_trade_pct"),
            "trade_price": base.get("trade_price") or trade_odds[i],
            "volume": base.get("volume") or (vol_h if key == "home" else vol_d if key == "draw" else vol_a),
            "bf_index": base.get("bf_index"),
            "hot_cold": base.get("hot_cold"),
            "book_pl": base.get("book_pl"),
            "big_volume": big_vol[i],
            "big_buy": big_buy[i],
            "big_sell": big_sell[i],
        }

    total_vol = sum(v for v in (vol_h, vol_d, vol_a) if v)
    pct = {}
    if total_vol:
        for key, v in zip(_OUTCOME_KEYS, (vol_h, vol_d, vol_a)):
            pct[key] = round((v or 0) / total_vol * 100, 2) if v else None
    else:
        for key in _OUTCOME_KEYS:
            pct[key] = outcome_map[key].get("trade_pct")

    trend = _build_trend(html)
    has_data = total_vol > 0 or any(trend["labels"])

    summary = ""
    for em in soup.select("em.ying, em.shu"):
        parent = em.find_parent("td")
        if parent and "成交量" in parent.get_text():
            summary = parent.get_text(strip=True)
            break

    return {
        "has_data": has_data,
        "volume_home": vol_h,
        "volume_draw": vol_d,
        "volume_away": vol_a,
        "volume_total": total_vol or None,
        "volume_pct": {
            "home": pct.get("home"),
            "draw": pct.get("draw"),
            "away": pct.get("away"),
        },
        "trade_price": {
            "home": outcome_map["home"]["trade_price"],
            "draw": outcome_map["draw"]["trade_price"],
            "away": outcome_map["away"]["trade_price"],
        },
        "bf_index": {
            "home": outcome_map["home"]["bf_index"],
            "draw": outcome_map["draw"]["bf_index"],
            "away": outcome_map["away"]["bf_index"],
        },
        "outcomes": outcome_map,
        "big_trade": {
            "home": big_vol[0], "draw": big_vol[1], "away": big_vol[2],
            "buy": {"home": big_buy[0], "draw": big_buy[1], "away": big_buy[2]},
            "sell": {"home": big_sell[0], "draw": big_sell[1], "away": big_sell[2]},
        },
        "trend": trend,
        "summary": summary,
    }


def fetch_betfair_snapshot(session, fixture_id: str) -> dict[str, Any]:
    fid = str(fixture_id)
    url = f"{BASE}/fenxi/touzhu-{fid}.shtml"
    try:
        resp = session.get(url, timeout=DEFAULT_TIMEOUT, headers={"Referer": f"{BASE}/"})
        resp.raise_for_status()
        return parse_betfair_html(_decode(resp.content))
    except Exception as exc:
        log.warning("必发抓取失败 fid=%s: %s", fid, exc)
        return {"has_data": False, "error": str(exc)}
