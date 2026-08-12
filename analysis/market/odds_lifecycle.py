"""统一读取初盘/临盘 lifecycle（给统计/复盘用）。

观测初盘 = 本站最早有效 tick（get_opening_tick）。
观测临盘 = kickoff 前最后有效 tick（get_closing_tick）；无 kickoff 取赛前最后一条。
页内 eu_open_*/ah_open_* 仅辅助看「庄家初」。

已 settle：优先 match_results.payload.odds_snapshots + closing 列。
未完场：live 算 opening/closing（closing = 当前最新，标注 provisional）。
"""
from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)


def _safe_float(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _tick_summary(tick: dict | None) -> dict | None:
    """从 tick 提取欧亚精简摘要（含 OU，优先 raw_meta.ou）。"""
    if not tick:
        return None
    raw = tick.get("raw_meta") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {}
    raw_ou = raw.get("ou") or {}
    return {
        "captured_at": str(tick.get("captured_at", "")),
        "eu_home": _safe_float(tick.get("eu_home")),
        "eu_draw": _safe_float(tick.get("eu_draw")),
        "eu_away": _safe_float(tick.get("eu_away")),
        "eu_open_home": _safe_float(tick.get("eu_open_home")),
        "eu_open_draw": _safe_float(tick.get("eu_open_draw")),
        "eu_open_away": _safe_float(tick.get("eu_open_away")),
        "ah_line": tick.get("ah_line"),
        "ah_home_water": _safe_float(tick.get("ah_home_water")),
        "ah_away_water": _safe_float(tick.get("ah_away_water")),
        "ah_open_line": tick.get("ah_open_line"),
        "ah_open_home_water": _safe_float(tick.get("ah_open_home_water")),
        "ah_open_away_water": _safe_float(tick.get("ah_open_away_water")),
        "ou_line": _safe_float(tick.get("ou_line") or raw_ou.get("ou_line")),
        "ou_over": _safe_float(tick.get("ou_over") or raw_ou.get("ou_over")),
        "ou_under": _safe_float(tick.get("ou_under") or raw_ou.get("ou_under")),
    }


def _jingcai_from_raw(raw_meta: dict | None) -> dict | None:
    """从 raw_meta 提取竞彩 SP 快照。"""
    if not raw_meta:
        return None
    if isinstance(raw_meta, str):
        try:
            raw_meta = json.loads(raw_meta)
        except json.JSONDecodeError:
            return None
    jc = raw_meta.get("jingcai") or {}
    if not jc.get("has_sp") and not jc.get("sp_home"):
        return None
    return {
        "match_num": jc.get("match_num", ""),
        "has_sp": jc.get("has_sp", False),
        "sp_home": _safe_float(jc.get("sp_home")),
        "sp_draw": _safe_float(jc.get("sp_draw")),
        "sp_away": _safe_float(jc.get("sp_away")),
        "has_rqsp": jc.get("has_rqsp", False),
        "rqsp_home": _safe_float(jc.get("rqsp_home")),
        "rqsp_draw": _safe_float(jc.get("rqsp_draw")),
        "rqsp_away": _safe_float(jc.get("rqsp_away")),
    }


def _betfair_from_raw(raw_meta: dict | None) -> dict | None:
    """从 raw_meta 提取必发快照。"""
    if not raw_meta:
        return None
    if isinstance(raw_meta, str):
        try:
            raw_meta = json.loads(raw_meta)
        except json.JSONDecodeError:
            return None
    bf = raw_meta.get("betfair") or {}
    if not bf.get("has_data") and not bf.get("volume_total"):
        return None
    return {
        "has_data": bf.get("has_data", False),
        "volume_total": bf.get("volume_total", 0),
        "volume_pct": bf.get("volume_pct"),
        "trade_price": bf.get("trade_price"),
    }


def _compute_move(opening: dict | None, closing: dict | None) -> dict[str, Any]:
    """开盘→临盘 线/水漂移。"""
    move: dict[str, Any] = {}
    if not opening or not closing:
        return move
    o_h = opening.get("eu_home")
    c_h = closing.get("eu_home")
    o_a = opening.get("eu_away")
    c_a = closing.get("eu_away")
    if o_h and c_h:
        move["eu_home_delta"] = round(c_h - o_h, 3)
    if o_a and c_a:
        move["eu_away_delta"] = round(c_a - o_a, 3)
    o_l = opening.get("ah_line")
    c_l = closing.get("ah_line")
    try:
        if o_l is not None and c_l is not None:
            move["ah_line_delta"] = round(float(c_l) - float(o_l), 2)
    except (TypeError, ValueError):
        pass
    o_w = opening.get("ah_home_water")
    c_w = closing.get("ah_home_water")
    if o_w and c_w:
        move["ah_home_water_delta"] = round(c_w - o_w, 3)
    return move


def get_match_odds_lifecycle(external_id: str) -> dict[str, Any]:
    """获取单场初盘/临盘 lifecycle。

    Args:
        external_id: 500.com fixture ID

    Returns:
        {opening, closing, book_open, kickoff_at, result_1x2, scores,
         p_open_devig, p_close_devig, provisional}
    """
    from db.connection import cursor
    from db.repository import get_opening_tick, get_closing_tick
    from analysis.market.devig import devig_1x2

    with cursor() as cur:
        cur.execute(
            "SELECT id, kickoff_at, home_team, away_team FROM fixtures WHERE external_id = %s",
            (external_id,),
        )
        fx = cur.fetchone()
        if not fx:
            return {"error": "fixture not found", "external_id": external_id}

        db_id = fx["id"]
        kickoff_at = fx.get("kickoff_at")

        # 检查是否已 settle
        cur.execute(
            """SELECT mr.home_score, mr.away_score, mr.result_1x2, mr.payload
               FROM match_results mr WHERE mr.fixture_id = %s""",
            (db_id,),
        )
        mr = cur.fetchone()

    opening_tick = get_opening_tick(db_id)
    closing_tick = get_closing_tick(db_id, kickoff_at)

    # 从 closing tick 的 raw_meta 取竞彩/必发
    opening_raw = (opening_tick or {}).get("raw_meta")
    closing_raw = (closing_tick or {}).get("raw_meta")
    if isinstance(opening_raw, str):
        try:
            opening_raw = json.loads(opening_raw)
        except json.JSONDecodeError:
            opening_raw = None
    if isinstance(closing_raw, str):
        try:
            closing_raw = json.loads(closing_raw)
        except json.JSONDecodeError:
            closing_raw = None

    opening = _tick_summary(opening_tick)
    closing = _tick_summary(closing_tick)
    if opening:
        opening["jingcai_sp"] = _jingcai_from_raw(opening_raw)
        opening["betfair"] = _betfair_from_raw(opening_raw)
        opening["source"] = "first_tick"
    if closing:
        closing["jingcai_sp"] = _jingcai_from_raw(closing_raw)
        closing["betfair"] = _betfair_from_raw(closing_raw)
        closing["source"] = "pre_kickoff_last_tick" if kickoff_at else "latest_tick_no_kickoff"

    # book_open：页内庄家初盘（在 closing tick 上）
    book_open = None
    if closing_tick:
        book_open = {
            "eu_open_home": _safe_float(closing_tick.get("eu_open_home")),
            "eu_open_draw": _safe_float(closing_tick.get("eu_open_draw")),
            "eu_open_away": _safe_float(closing_tick.get("eu_open_away")),
            "ah_open_line": closing_tick.get("ah_open_line"),
            "ah_open_home_water": _safe_float(closing_tick.get("ah_open_home_water")),
            "ah_open_away_water": _safe_float(closing_tick.get("ah_open_away_water")),
        }

    # 已 settle 场：优先 match_results.payload.opening_odds / closing_odds
    payload_opening = None
    payload_closing = None
    source = "first_tick"
    if mr:
        payload = mr.get("payload") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = {}
        po = payload.get("opening_odds") or {}
        pc = payload.get("closing_odds") or {}
        if po and (po.get("eu_home") or po.get("ah_line")):
            payload_opening = _tick_summary(po)
            if payload_opening:
                payload_opening["source"] = "payload"
        if pc and (pc.get("eu_home") or pc.get("ah_line")):
            payload_closing = _tick_summary(pc)
            if payload_closing:
                payload_closing["source"] = "payload"

    final_opening = payload_opening if payload_opening else opening
    final_closing = payload_closing if payload_closing else closing
    if payload_opening or payload_closing:
        source = "payload"

    # devig 概率：基于最终采用的开盘/临盘
    p_open_devig = None
    p_close_devig = None
    if final_opening and final_opening.get("eu_home") and final_opening.get("eu_away"):
        p_open_devig = devig_1x2(
            final_opening["eu_home"], final_opening.get("eu_draw") or 3.0, final_opening["eu_away"],
        )
    if final_closing and final_closing.get("eu_home") and final_closing.get("eu_away"):
        p_close_devig = devig_1x2(
            final_closing["eu_home"], final_closing.get("eu_draw") or 3.0, final_closing["eu_away"],
        )

    # provisional：未完场时 closing 是当前最新（非赛前最后）
    provisional = mr is None
    if kickoff_at is None and closing:
        log.warning("fixture %s has no kickoff_at; closing may be unreliable", external_id)

    move = _compute_move(final_opening, final_closing)

    result = {
        "external_id": external_id,
        "home_team": fx.get("home_team"),
        "away_team": fx.get("away_team"),
        "kickoff_at": str(kickoff_at) if kickoff_at else None,
        "opening": final_opening,
        "closing": final_closing,
        "latest": final_closing,
        "move": move,
        "source": source,
        "book_open": book_open,
        "result_1x2": mr.get("result_1x2") if mr else None,
        "scores": {
            "home": mr.get("home_score") if mr else None,
            "away": mr.get("away_score") if mr else None,
        },
        "p_open_devig": p_open_devig,
        "p_close_devig": p_close_devig,
        "provisional": provisional,
        "settled": mr is not None,
    }
    return result
