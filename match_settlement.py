"""Settle finished fixtures — extended for World Cup tournament ledger."""

from __future__ import annotations

import json
import logging
import re
from datetime import timedelta
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from db.connection import cursor, ping
from db.repository import (
    get_closing_tick,
    get_fixture_by_external,
    get_opening_tick,
    list_fixtures_for_resettlement,
    list_fixtures_pending_settlement,
    list_match_results_map,
    upsert_match_result,
)
from download_500 import DEFAULT_LEAGUES, BASE, _session
from http_client import make_session
from live_scores_500 import LiveScore, align_score_to_fixture, fetch_live_scoreboard
from market_patterns import analyze_market_patterns
from match_status import (
    ah_settlement_to_label,
    evaluate_prediction_hits,
    match_phase,
    RESULT_CN,
)
from prediction_archive import load_best_prediction, prediction_snapshot
from time_utils import format_beijing, now_beijing_str
from worldcup_analytics import refresh_tournament_ledger

log = logging.getLogger(__name__)
SOURCE = "500"


from odds_utils import eu_favorite as _eu_favorite, odds_from_tick as _odds_from_tick

def _to_float(text: str | None) -> float | None:
    """Convert text to float; return None on failure."""
    if text is None:
        return None
    try:
        txt = str(text).strip().replace("↑", "").replace("↓", "")
        return float(txt)
    except (ValueError, TypeError):
        return None


def _pattern_meta(cur: dict) -> dict[str, Any]:
    mp = analyze_market_patterns(cur)
    return {
        "consistency": mp.consistency,
        "tags": [mp.consistency] + [p.get("id") for p in mp.patterns if p.get("id")],
        "conversion_summary": mp.conversion_summary,
        "routine_notes": mp.routine_notes[:3],
    }


def _closing_fields(tick: dict | None, fixture_db_id: int | None = None) -> dict[str, Any]:
    if not tick:
        return {}
    ou = _extract_ou(tick)
    if (ou.get("line") is None) and fixture_db_id:
        fallback = _last_ou_from_ticks(fixture_db_id)
        if fallback.get("line") is not None:
            ou = fallback
    return {
        "closing_captured_at": tick.get("captured_at"),
        "closing_ah_line": tick.get("ah_line"),
        "closing_ah_home_water": tick.get("ah_home_water"),
        "closing_ah_away_water": tick.get("ah_away_water"),
        "closing_eu_home": tick.get("eu_home"),
        "closing_eu_draw": tick.get("eu_draw"),
        "closing_eu_away": tick.get("eu_away"),
        "closing_eu_open_home": tick.get("eu_open_home"),
        "closing_eu_open_draw": tick.get("eu_open_draw"),
        "closing_eu_open_away": tick.get("eu_open_away"),
        "closing_ou_line": ou.get("line"),
        "closing_ou_over": ou.get("over"),
        "closing_ou_under": ou.get("under"),
        "closing_ou_open_line": ou.get("open_line"),
        "closing_ou_open_over": ou.get("open_over"),
        "closing_ou_open_under": ou.get("open_under"),
    }


def _extract_ou(tick: dict | None) -> dict[str, Any]:
    """从 tick 顶层或 raw_meta.ou 取大小球。"""
    if not tick:
        return {}
    raw = tick.get("raw_meta")
    raw_ou = raw.get("ou") if isinstance(raw, dict) else {}
    return {
        "line": _to_float(tick.get("ou_line") or (raw_ou or {}).get("ou_line")),
        "over": _to_float(tick.get("ou_over") or (raw_ou or {}).get("ou_over")),
        "under": _to_float(tick.get("ou_under") or (raw_ou or {}).get("ou_under")),
        "open_line": _to_float(tick.get("ou_open_line") or (raw_ou or {}).get("ou_open_line")),
        "open_over": _to_float(tick.get("ou_open_over") or (raw_ou or {}).get("ou_open_over")),
        "open_under": _to_float(tick.get("ou_open_under") or (raw_ou or {}).get("ou_open_under")),
    }


def _last_ou_from_ticks(fixture_db_id: int) -> dict[str, Any]:
    """从所有历史 ticks 找最后一条带有效 OU 的数据；无则空。"""
    from db.repository import list_ticks

    try:
        ticks = list_ticks(fixture_db_id)
    except Exception as exc:
        log.debug("list_ticks failed for OU fallback %s: %s", fixture_db_id, exc)
        return {}
    for tick in reversed(ticks):
        ou = _extract_ou(tick)
        if ou.get("line") is not None:
            return ou
    return {}


def _extract_jingcai_sp(tick: dict | None) -> dict[str, Any]:
    """从 tick.raw_meta.jingcai 提取竞彩 SP。"""
    if not tick:
        return {}
    raw = tick.get("raw_meta") or {}
    jc = raw.get("jingcai") or {}
    sp = {}
    for k in ("sp_home", "sp_draw", "sp_away", "rqsp_home", "rqsp_draw", "rqsp_away"):
        v = jc.get(k)
        if v not in (None, "", "-"):
            sp[k] = v
    return sp


def _build_payload(
    pred: dict | None,
    *,
    opening_tick: dict | None,
    closing_tick: dict | None,
    hits: dict[str, Any] | None = None,
    score_source: str = "",
    score_range: dict | None = None,
    fixture_db_id: int | None = None,
    score: LiveScore | None = None,
) -> dict[str, Any]:
    opening = _odds_from_tick(opening_tick, opening=True)
    closing = _odds_from_tick(closing_tick, opening=False)
    open_ou = _extract_ou(opening_tick)
    close_ou = _extract_ou(closing_tick)
    if close_ou.get("line") is None and fixture_db_id:
        close_ou = _last_ou_from_ticks(fixture_db_id)
    open_cur = {**opening, **{f"ah_open_{k}": v for k, v in opening.items() if k.startswith("ah_")}}

    open_mp = _pattern_meta(open_cur) if opening.get("eu_home") else {}
    close_cur = {**closing, **opening}
    close_mp = _pattern_meta(close_cur) if closing.get("eu_home") else {}

    line_move = None
    if opening.get("ah_line") is not None and closing.get("ah_line") is not None:
        line_move = round(float(closing["ah_line"]) - float(opening["ah_line"]), 2)

    fav = _eu_favorite(opening.get("eu_home"), opening.get("eu_draw"), opening.get("eu_away"))

    snap = prediction_snapshot(pred)

    hits_obj: dict[str, Any] = {
        "1x2": hits.get("hit_1x2") if hits else None,
        "ah": ah_settlement_to_label(hits.get("ah_settlement")) if hits else None,
        "ou": hits.get("hit_ou") if hits else None,
        "jingcai": hits.get("hit_jingcai") if hits else None,
        "score_bands": hits.get("score_bands") if hits else None,
    }
    payload: dict[str, Any] = {
        "recommendation_source": snap.get("recommendation_source"),
        "run_id": snap.get("run_id"),
        "prediction": snap,
        "opening_odds": {**opening, "ou": open_ou},
        "closing_odds": {**closing, "ou": close_ou},
        "hits": hits_obj,
        "score_source": score_source,
        "score_range": score_range,
        "opening_favorite": fav,
        "opening_favorite_cn": RESULT_CN.get(fav) if fav else None,
        "opening_consistency": open_mp.get("consistency"),
        "opening_pattern_tags": open_mp.get("tags") or [],
        "closing_pattern_tags": close_mp.get("tags") or [],
        "opening_routines": open_mp.get("routine_notes") or [],
        "line_move": line_move,
    }
    jingcai_sp = _extract_jingcai_sp(closing_tick) or _extract_jingcai_sp(opening_tick)
    if jingcai_sp:
        payload["jingcai_sp"] = jingcai_sp
    # 0-0 完场二次可信度盖章
    if (
        score is not None
        and score.home_score == 0
        and score.away_score == 0
        and score.is_finished
    ):
        payload["verified_0_0"] = True
        payload["verified_at"] = now_beijing_str()
    return payload


def _result_row(
    fixture_db_id: int,
    score: LiveScore,
    *,
    pred: dict | None,
    opening_tick: dict | None,
    closing_tick: dict | None,
    external_id: str | None = None,
) -> dict[str, Any]:
    closing_ou = _extract_ou(closing_tick)
    if closing_ou.get("line") is None and fixture_db_id:
        closing_ou = _last_ou_from_ticks(fixture_db_id)
    score_range = None
    if external_id:
        try:
            from analysis.market.score_range import build_score_range_forecast

            score_range = build_score_range_forecast(str(external_id))
        except Exception as exc:
            log.debug("settle 时计算 score_range 失败 %s: %s", external_id, exc)
    hits = evaluate_prediction_hits(
        pred,
        home_score=score.home_score,
        away_score=score.away_score,
        ah_line=(closing_tick or {}).get("ah_line"),
        ou_line=closing_ou.get("line"),
        score_range=score_range,
    )
    payload = _build_payload(
        pred,
        opening_tick=opening_tick,
        closing_tick=closing_tick,
        hits=hits,
        score_source=score.score_source or score.source,
        score_range=score_range,
        fixture_db_id=fixture_db_id,
        score=score,
    )
    row = {
        "fixture_id": fixture_db_id,
        "status": score.status,
        "home_score": score.home_score,
        "away_score": score.away_score,
        "score_text": hits["score_text"],
        "result_1x2": hits["result_1x2"],
        "result_1x2_cn": hits["result_1x2_cn"],
        "pick_1x2_cn": hits.get("pick_1x2_cn") or payload.get("prediction", {}).get("pick_1x2_cn"),
        "pick_jingcai_cn": hits.get("pick_jingcai_cn") or payload.get("prediction", {}).get("pick_jingcai_cn"),
        "recommended_scores": hits.get("recommended_scores") or payload.get("prediction", {}).get("recommended_scores"),
        "hit_1x2": hits.get("hit_1x2"),
        "hit_score": hits.get("hit_score"),
        "pick_ah": hits.get("pick_ah"),
        "pick_ah_cn": hits.get("pick_ah_cn"),
        "hit_ah": hits.get("hit_ah"),
        "ah_settlement": hits.get("ah_settlement"),
        "hit_ou": hits.get("hit_ou"),
        "ou_settlement": hits.get("ou_settlement"),
        "hit_jingcai": hits.get("hit_jingcai"),
        "score_bands": hits.get("score_bands"),
        "payload": payload,
        "source": SOURCE,
    }
    row.update(_closing_fields(closing_tick, fixture_db_id))
    return row


# ---------------------------------------------------------------------------
# score resolution (500.com data page fallback)
# ---------------------------------------------------------------------------

def _parse_shuju_score(html: str) -> LiveScore | None:
    """从 500 数据页（shuju-{fid}.shtml）顶部「比赛时间」行解析完场比分。

    世界杯结构：['英格兰', '', '26世界杯半决赛比赛时间2026-07-16 03:001:2', '阿根廷', '阿根廷']
    联赛结构：['主队', ..., '比赛时间2026-06-14 00:00', '0:3', '客队', ...]
    策略：扫描所有单元格文本，找到含「比赛时间」的单元格后，从中提取 `时间后的比分`，
    若单元格本身没有比分，再取下一个单元格。

    同时检测页面是否有终场/完场标记，未终场返回 None，避免把临时比分当完场写入。
    """
    text = re.sub(r"\s+", "", html)
    finished_markers = ("比赛结束", "终场", "已结束", "完场")
    page_finished = any(m in text for m in finished_markers)

    soup = BeautifulSoup(html, "html.parser")
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
            for idx, cell in enumerate(cells):
                if "比赛时间" not in cell:
                    continue
                # 先尝试在同一单元格提取：去掉比赛时间本身后再取比分
                rest = re.sub(r"比赛时间\s*\d{4}-\d{2}-\d{2}\s*\d{2}:\d{2}", "", cell)
                m = re.search(r"(\d+)\s*[:：]\s*(\d+)", rest)
                same_cell_score = bool(m)
                if not m and idx + 1 < len(cells):
                    m = re.search(r"(\d+)\s*[:：]\s*(\d+)", cells[idx + 1])
                if not m:
                    continue
                home = int(m.group(1))
                away = int(m.group(2))
                # 数据页「比赛时间」单元格内直接跟比分 = 完场证据；
                # 跨单元格比分需要页面级终场标记。
                is_finished = same_cell_score or page_finished
                if not is_finished:
                    return None
                return LiveScore(
                    fixture_id="",
                    home_score=home,
                    away_score=away,
                    score_text=f"{home}-{away}",
                    status="finished",
                    source="500_data_page",
                    is_finished=True,
                    score_source="500_data_page",
                )
    return None


def fetch_match_score_from_pages(fid: str) -> LiveScore | None:
    """从 500 数据页抓完场比分；未终场或失败返回 None。"""
    from http_client import get_text, ScraperGuard

    session = make_session()
    guard = ScraperGuard(min_delay=0.5, max_delay=1.0)
    url = f"{BASE}/fenxi/shuju-{fid}.shtml"
    try:
        html = get_text(session, url, source="500", guard=guard)
    except Exception as exc:
        log.debug("shuju 页获取比分失败 fid=%s: %s", fid, exc)
        return None
    return _parse_shuju_score(html)


def _resolve_score(
    fixture: dict,
    scoreboard: dict[str, LiveScore],
) -> LiveScore | None:
    """优先取 scoreboard；不在 scoreboard 时尝试 500 数据页/分析页。"""
    fid = fixture["external_id"]
    score = scoreboard.get(fid)
    if score and score.home_score is not None and score.away_score is not None:
        return score

    try:
        result = fetch_match_score_from_pages(str(fid))
        if result is not None and result.home_score is not None:
            return result
    except Exception as exc:
        log.warning("fetch_match_score_from_pages fid=%s: %s", fid, exc)

    return None


def _save_result_file(output_root: Path, external_id: str, row: dict, fixture: dict) -> None:
    out_dir = output_root / "settled"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "fixture_id": external_id,
        "match_name": fixture.get("match_name"),
        "kickoff_at": format_beijing(fixture.get("kickoff_at")) if fixture.get("kickoff_at") else None,
        "settled_at": now_beijing_str(),
        **{k: v for k, v in row.items() if k != "fixture_id"},
    }
    for key in ("closing_captured_at",):
        if payload.get(key) is not None:
            payload[key] = format_beijing(payload[key])
    (out_dir / f"{external_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    wc_dir = output_root / "worldcup"
    wc_dir.mkdir(parents=True, exist_ok=True)
    with (wc_dir / "records.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def _is_dirty_name(name: str | None) -> bool:
    if not name:
        return True
    dirty_exact = (
        "亚冠杯","欧冠","欧联","欧会","欧超杯","解放者杯","南美杯",
        "附加赛","决赛","半决赛","四分之一决赛","八强","四强",
    )
    dirty_substr = (
        "资格赛", "附加赛", "预选赛", "季后赛", "小组赛", "淘汰赛",
        "第三轮", "第二轮", "第一轮", "第1轮", "第2轮", "第3轮",
    )
    name = str(name).strip()
    if name in dirty_exact:
        return True
    return any(s in name for s in dirty_substr)


def ensure_fixture_identity(fixture_id: str, output_root: str | Path | None = None) -> dict | None:
    """如果 fixtures 表中的队名被识别为脏名，尝试从 500 亚盘分析页回填真实队名。

    返回更新后的 fixture 字典；回填失败或队名不脏则返回 None（表示无需修正）。
    """
    from download_500 import _session, fetch_match_info

    with cursor() as cur:
        cur.execute(
            "SELECT id, external_id, home_team, away_team, match_name, kickoff_at FROM fixtures WHERE external_id=%s",
            (str(fixture_id),),
        )
        row = cur.fetchone()
    if not row:
        return None

    home, away = row["home_team"], row["away_team"]
    if not (_is_dirty_name(home) or _is_dirty_name(away)):
        return None

    try:
        session = _session()
        info = fetch_match_info(session, str(fixture_id))
    except Exception as exc:
        log.warning("无法从 500 回填 %s 队名: %s", fixture_id, exc)
        return None

    real_home = info.home or ""
    real_away = info.away or ""
    if not real_home or not real_away:
        return None
    if _is_dirty_name(real_home) or _is_dirty_name(real_away):
        log.warning("500 回填队名仍脏 %s: %s vs %s", fixture_id, real_home, real_away)
        return None

    match_name = f"{real_home} vs {real_away}"
    with cursor() as cur:
        cur.execute(
            "UPDATE fixtures SET home_team=%s, away_team=%s, match_name=%s, updated_at=NOW() WHERE id=%s",
            (real_home, real_away, match_name, row["id"]),
        )
    log.info("已回填 %s 队名: %s", fixture_id, match_name)
    row["home_team"] = real_home
    row["away_team"] = real_away
    row["match_name"] = match_name
    return dict(row)


def settle_fixture(
    fixture: dict,
    score: LiveScore,
    *,
    pred: dict | None = None,
    output_root: str | Path | None = None,
) -> bool:
    db_id = int(fixture["id"])
    ext = str(fixture.get("external_id") or score.fixture_id)

    # 完场可信度：必须有完场证据
    if not score.is_finished and score.status not in ("finished", "完", "完场", "终场"):
        log.info("跳过未确认完场场次 %s (status=%s)", ext, score.status)
        return False

    # 0-0 必须二次确认完场证据
    if score.home_score == 0 and score.away_score == 0 and not score.is_finished:
        log.warning("跳过 0-0 未确认完场场次 %s", ext)
        return False

    # 身份修正：脏队名先尝试从 500 回填真实队名
    refreshed = ensure_fixture_identity(ext, output_root=output_root)
    if refreshed:
        fixture = refreshed
        db_id = int(fixture["id"])

    # 脏队名不得 settle/覆盖
    if _is_dirty_name(fixture.get("home_team")) or _is_dirty_name(fixture.get("away_team")):
        log.warning("脏队名不得结算 %s: %s vs %s", ext, fixture.get("home_team"), fixture.get("away_team"))
        return False

    if output_root and pred is None:
        pred = load_best_prediction(
            output_root, ext, kickoff_at=fixture.get("kickoff_at"),
        )
    elif output_root and pred:
        archived = load_best_prediction(
            output_root, ext, kickoff_at=fixture.get("kickoff_at"),
        )
        if archived:
            pred = archived

    opening_tick = get_opening_tick(db_id)
    closing_tick = get_closing_tick(db_id, fixture.get("kickoff_at"))
    row = _result_row(
        db_id,
        score,
        pred=pred,
        opening_tick=opening_tick,
        closing_tick=closing_tick,
        external_id=ext,
    )
    upsert_match_result(db_id, row)
    if output_root:
        _save_result_file(Path(output_root), ext, row, fixture)
    log.info(
        "已结算 %s %s → %s 竞彩%s %s",
        fixture.get("match_name") or ext,
        score.score_text,
        row["result_1x2_cn"],
        row.get("pick_jingcai_cn") or "—",
        "✓" if row.get("hit_1x2") else ("✗" if row.get("hit_1x2") is False else "—"),
    )
    return True


def _fixture_status_row(
    fx: dict,
    *,
    kind: str,
    live_status_map: dict[str, dict],
    settled_map: dict[str, dict],
) -> dict[str, Any]:
    ext = str(fx.get("external_id") or "")
    live = live_status_map.get(ext) or {}
    settled = settled_map.get(ext) or {}
    return {
        "fixture_id": ext,
        "match_name": fx.get("match_name"),
        "kickoff_at": format_beijing(fx.get("kickoff_at")) if fx.get("kickoff_at") else None,
        "kind": kind,
        "live_phase": live.get("phase"),
        "live_label": live.get("label"),
        "live_score": live.get("score"),
        "settled_score": settled.get("score_text"),
        "has_settled": bool(settled),
    }


def _collect_pending_fixtures(
    *,
    resettle: bool = False,
    fixture_ids: list[str] | None = None,
) -> list[dict]:
    pending = list_fixtures_pending_settlement(source=SOURCE)
    seen = {int(fx["id"]) for fx in pending}
    if resettle:
        for fx in list_fixtures_for_resettlement(source=SOURCE):
            if int(fx["id"]) not in seen:
                pending.append(fx)
                seen.add(int(fx["id"]))
    if not fixture_ids:
        return pending

    wanted = {str(x).strip() for x in fixture_ids if str(x).strip()}
    if not wanted:
        return pending

    filtered = [fx for fx in pending if str(fx.get("external_id")) in wanted]
    found = {str(fx.get("external_id")) for fx in filtered}
    for ext in wanted - found:
        fx = get_fixture_by_external(SOURCE, ext)
        if fx and int(fx["id"]) not in seen:
            filtered.append(fx)
            seen.add(int(fx["id"]))
    return filtered


def build_settlement_status(
    output_root: str | Path,
    *,
    resettle: bool = False,
    limit: int = 50,
) -> dict[str, Any]:
    """Preview fixtures waiting for manual settlement."""
    root = Path(output_root)
    out: dict[str, Any] = {
        "ok": False,
        "db_connected": ping(),
        "pending_count": 0,
        "resettlement_count": 0,
        "settled_count": 0,
        "pending": [],
        "resettlement": [],
        "resettle": resettle,
        "usage": {
            "preview": "GET /api/settle",
            "run_all": "POST /api/settle",
            "run_resettle": "POST /api/settle?resettle=1 或 {\"resettle\": true}",
            "run_one": "POST /api/settle {\"fixture_id\": \"1359237\"}",
            "run_many": "POST /api/settle {\"fixture_ids\": [\"1359237\", \"1359238\"]}",
        },
    }
    if not ping():
        out["error"] = "数据库未连接，无法结算赛果"
        return out

    settled_map = load_settled_map(root)
    out["settled_count"] = len(settled_map)

    from daily_picks import load_live_status_map

    live_status = load_live_status_map(within_days=14)
    pending = list_fixtures_pending_settlement(source=SOURCE)
    out["pending_count"] = len(pending)
    out["pending"] = [
        _fixture_status_row(fx, kind="pending", live_status_map=live_status, settled_map=settled_map)
        for fx in pending[:limit]
    ]

    resettle_rows = list_fixtures_for_resettlement(source=SOURCE)
    out["resettlement_count"] = len(resettle_rows)
    if resettle:
        out["resettlement"] = [
            _fixture_status_row(fx, kind="resettle", live_status_map=live_status, settled_map=settled_map)
            for fx in resettle_rows[:limit]
        ]

    out["ok"] = True
    return out


def run_settlement(
    output_root: str | Path,
    *,
    leagues=DEFAULT_LEAGUES,
    resettle: bool = False,
    fixture_ids: list[str] | None = None,
) -> dict[str, Any]:
    root = Path(output_root)
    summary: dict[str, Any] = {
        "ok": False,
        "settled": 0,
        "skipped_no_score": 0,
        "skipped_live": 0,
        "pending_before": 0,
        "resettle": resettle,
        "fixture_ids": fixture_ids or [],
        "errors": [],
        "settled_matches": [],
    }
    if not ping():
        summary["error"] = "数据库未连接，无法写入 match_results"
        log.debug("数据库未连接，跳过赛果结算")
        return summary

    pending = _collect_pending_fixtures(resettle=resettle, fixture_ids=fixture_ids)
    summary["pending_before"] = len(pending)
    if not pending:
        summary["ok"] = True
        summary["message"] = "没有待结算场次"
        try:
            refresh_tournament_ledger(root)
        except Exception as exc:
            log.debug("账本刷新: %s", exc)
        return summary

    # 快速路径：指定了 fixture_ids 时不拉取全量 scoreboard，直接走 500 数据页
    if fixture_ids:
        board: dict[str, LiveScore] = {}
        live_status: dict[str, Any] = {}
    else:
        try:
            board = fetch_live_scoreboard(_session(), leagues=leagues)
        except Exception as exc:
            log.warning("拉取 live.500 比分失败: %s", exc)
            summary["errors"].append(str(exc))
            return summary

        from daily_picks import load_live_status_map

        live_status = load_live_status_map(within_days=14)

    for fx in pending:
        ext = str(fx["external_id"])
        if live_status.get(ext, {}).get("phase") == "live":
            summary["skipped_live"] += 1
            log.info("跳过进行中场次 %s（live.500 未终场）", ext)
            continue
        score = board.get(ext)
        if not score:
            # scoreboard 没有时尝试 500 数据页 / 分析页
            score = _resolve_score(fx, board)
            if score is None:
                summary["skipped_no_score"] += 1
                continue
            score.fixture_id = ext
            if not score.score_text:
                score.score_text = f"{score.home_score}-{score.away_score}"
        if score.source != "wc_api" and score.source != "500_data_page":
            score = align_score_to_fixture(score, fx)
            # align 后必须仍有完场证据（HTML scoreboard 默认已带）
            if not score.is_finished:
                score.is_finished = True
                score.score_source = score.score_source or score.source
        try:
            settle_fixture(fx, score, output_root=root)
            summary["settled"] += 1
            summary["settled_matches"].append({
                "fixture_id": ext,
                "match_name": fx.get("match_name"),
                "score_text": score.score_text,
            })
        except Exception as exc:
            msg = f"{ext}: {exc}"
            summary["errors"].append(msg)
            log.exception("结算失败 %s", ext)

    summary["ok"] = True
    if summary["settled"]:
        try:
            ledger = refresh_tournament_ledger(root)
            summary["ledger_matches"] = ledger.get("accuracy", {}).get("total_settled", 0)
        except Exception as exc:
            log.warning("世界杯账本更新失败: %s", exc)
        try:
            from ah_analytics import refresh_ah_ledger
            ah_ledger = refresh_ah_ledger(root)
            summary["ah_ledger_matches"] = len(ah_ledger.get("records") or [])
        except Exception as exc:
            log.warning("亚盘账本更新失败: %s", exc)
        try:
            from elo_ratings import refresh_elo_from_match_results

            refresh_elo_from_match_results()
        except Exception as exc:
            log.debug("Elo 更新: %s", exc)

    log.info(
        "赛果结算完成：写入 %d 场，待结算无比分 %d 场，跳过进行中 %d 场",
        summary["settled"], summary["skipped_no_score"], summary["skipped_live"],
    )
    return summary


def load_settled_map(output_root: str | Path) -> dict[str, dict]:
    out: dict[str, dict] = {}

    settled_dir = Path(output_root) / "settled"
    if settled_dir.is_dir():
        for p in settled_dir.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                fid = str(data.get("fixture_id") or data.get("external_id") or p.stem)
                data["fixture_id"] = fid
                out[fid] = data
            except json.JSONDecodeError:
                continue

    if ping():
        try:
            for fid, row in list_match_results_map(source=SOURCE).items():
                row = dict(row)
                row["fixture_id"] = str(fid)
                if fid not in out:
                    out[fid] = row
        except Exception as exc:
            log.debug("读取 DB 赛果失败: %s", exc)

    return out


def classify_matches(
    matches: list[dict],
    *,
    kickoff_map: dict,
    settled_map: dict[str, dict],
    live_status_map: dict[str, dict] | None = None,
) -> tuple[list[dict], list[dict], list[dict]]:
    upcoming: list[dict] = []
    live: list[dict] = []
    finished: list[dict] = []

    seen_finished: set[str] = set()
    live_status_map = live_status_map or {}
    for m in matches:
        fid = str(m.get("fixture_id") or "")
        settled = settled_map.get(fid)
        ko = kickoff_map.get(fid)
        ext = live_status_map.get(fid) or {}
        phase = match_phase(ko, has_result=bool(settled))
        enriched = dict(m)
        if ext.get("score"):
            enriched["live_score"] = ext["score"]
        if ext.get("label"):
            enriched["live_status_label"] = ext["label"]

        ext_phase = ext.get("phase")
        # live.500 进行中优先：避免 API status=4 误结算后仍显示在已完场
        if ext_phase == "live":
            enriched["match_phase"] = "live"
            if not enriched.get("live_status_label"):
                enriched["live_status_label"] = "进行中"
            live.append(enriched)
            continue

        if settled:
            enriched["settled"] = settled
            enriched["match_phase"] = "finished"
            finished.append(enriched)
            seen_finished.add(fid)
        elif ext.get("phase") == "finished" or phase == "finished":
            enriched["match_phase"] = "finished_pending"
            finished.append(enriched)
            seen_finished.add(fid)
        elif ext.get("phase") == "live" or phase == "live":
            enriched["match_phase"] = "live"
            if not enriched.get("live_status_label"):
                enriched["live_status_label"] = "进行中"
            live.append(enriched)
        elif ext.get("phase") == "upcoming":
            enriched["match_phase"] = "upcoming"
            upcoming.append(enriched)
        elif phase == "upcoming":
            enriched["match_phase"] = "upcoming"
            upcoming.append(enriched)
        else:
            enriched["match_phase"] = phase
            upcoming.append(enriched)

    for fid, settled in settled_map.items():
        if fid in seen_finished:
            continue
        finished.append({
            "fixture_id": fid,
            "match": settled.get("match_name") or f"FID {fid}",
            "settled": settled,
            "match_phase": "finished",
            "predict_row": {},
        })

    return upcoming, live, finished
