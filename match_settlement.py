"""Settle finished fixtures — extended for World Cup tournament ledger."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from db.connection import ping
from db.repository import (
    get_closing_tick,
    get_opening_tick,
    list_fixtures_for_resettlement,
    list_fixtures_pending_settlement,
    list_match_results_map,
    upsert_match_result,
)
from download_500 import DEFAULT_LEAGUES, _session
from live_scores_500 import LiveScore, align_score_to_fixture, fetch_live_scoreboard
from market_patterns import analyze_market_patterns
from match_status import evaluate_prediction_hits, match_phase, RESULT_CN
from prediction_archive import load_best_prediction, prediction_snapshot
from time_utils import format_beijing, now_beijing_str
from worldcup_analytics import refresh_tournament_ledger

log = logging.getLogger(__name__)
SOURCE = "500"


from odds_utils import eu_favorite as _eu_favorite, odds_from_tick as _odds_from_tick


def _pattern_meta(cur: dict) -> dict[str, Any]:
    mp = analyze_market_patterns(cur)
    return {
        "consistency": mp.consistency,
        "tags": [mp.consistency] + [p.get("id") for p in mp.patterns if p.get("id")],
        "conversion_summary": mp.conversion_summary,
        "routine_notes": mp.routine_notes[:3],
    }


def _closing_fields(tick: dict | None) -> dict[str, Any]:
    if not tick:
        return {}
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
    }


def _build_payload(
    pred: dict | None,
    *,
    opening_tick: dict | None,
    closing_tick: dict | None,
) -> dict[str, Any]:
    opening = _odds_from_tick(opening_tick, opening=True)
    closing = _odds_from_tick(closing_tick, opening=False)
    open_cur = {**opening, **{f"ah_open_{k}": v for k, v in opening.items() if k.startswith("ah_")}}

    open_mp = _pattern_meta(open_cur) if opening.get("eu_home") else {}
    close_cur = {**closing, **opening}
    close_mp = _pattern_meta(close_cur) if closing.get("eu_home") else {}

    line_move = None
    if opening.get("ah_line") is not None and closing.get("ah_line") is not None:
        line_move = round(float(closing["ah_line"]) - float(opening["ah_line"]), 2)

    fav = _eu_favorite(opening.get("eu_home"), opening.get("eu_draw"), opening.get("eu_away"))

    snap = prediction_snapshot(pred)
    return {
        "recommendation_source": snap.get("recommendation_source"),
        "run_id": snap.get("run_id"),
        "prediction": snap,
        "opening_odds": opening,
        "closing_odds": closing,
        "opening_favorite": fav,
        "opening_favorite_cn": RESULT_CN.get(fav) if fav else None,
        "opening_consistency": open_mp.get("consistency"),
        "opening_pattern_tags": open_mp.get("tags") or [],
        "closing_pattern_tags": close_mp.get("tags") or [],
        "opening_routines": open_mp.get("routine_notes") or [],
        "line_move": line_move,
    }


def _result_row(
    fixture_db_id: int,
    score: LiveScore,
    *,
    pred: dict | None,
    opening_tick: dict | None,
    closing_tick: dict | None,
) -> dict[str, Any]:
    hits = evaluate_prediction_hits(
        pred,
        home_score=score.home_score,
        away_score=score.away_score,
        ah_line=(closing_tick or {}).get("ah_line"),
    )
    payload = _build_payload(pred, opening_tick=opening_tick, closing_tick=closing_tick)
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
        "payload": payload,
        "source": SOURCE,
    }
    row.update(_closing_fields(closing_tick))
    return row


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


def settle_fixture(
    fixture: dict,
    score: LiveScore,
    *,
    pred: dict | None = None,
    output_root: str | Path | None = None,
) -> bool:
    db_id = int(fixture["id"])
    ext = str(fixture.get("external_id") or score.fixture_id)

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
    row = _result_row(db_id, score, pred=pred, opening_tick=opening_tick, closing_tick=closing_tick)
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


def run_settlement(
    output_root: str | Path,
    *,
    leagues=DEFAULT_LEAGUES,
    resettle: bool = False,
) -> dict[str, Any]:
    root = Path(output_root)
    summary: dict[str, Any] = {
        "ok": False,
        "settled": 0,
        "skipped_no_score": 0,
        "resettle": resettle,
        "errors": [],
    }
    if not ping():
        log.debug("数据库未连接，跳过赛果结算")
        return summary

    pending = list_fixtures_pending_settlement(source=SOURCE)
    if resettle:
        seen = {int(fx["id"]) for fx in pending}
        for fx in list_fixtures_for_resettlement(source=SOURCE):
            if int(fx["id"]) not in seen:
                pending.append(fx)
                seen.add(int(fx["id"]))
    if not pending:
        summary["ok"] = True
        try:
            refresh_tournament_ledger(root)
        except Exception as exc:
            log.debug("账本刷新: %s", exc)
        return summary

    try:
        board = fetch_live_scoreboard(_session(), leagues=leagues)
    except Exception as exc:
        log.warning("拉取 live.500 比分失败: %s", exc)
        summary["errors"].append(str(exc))
        return summary

    for fx in pending:
        ext = str(fx["external_id"])
        score = board.get(ext)
        if not score:
            summary["skipped_no_score"] += 1
            continue
        if score.source != "wc_api":
            score = align_score_to_fixture(score, fx)
        try:
            settle_fixture(fx, score, output_root=root)
            summary["settled"] += 1
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
            from quant_analytics import refresh_elo_from_settled

            refresh_elo_from_settled(root)
        except Exception as exc:
            log.debug("Elo 更新: %s", exc)

    log.info(
        "赛果结算完成：写入 %d 场，待结算无比分 %d 场",
        summary["settled"], summary["skipped_no_score"],
    )
    return summary


def load_settled_map(output_root: str | Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if ping():
        try:
            out.update(list_match_results_map(source=SOURCE))
        except Exception as exc:
            log.debug("读取 DB 赛果失败: %s", exc)

    settled_dir = Path(output_root) / "settled"
    if settled_dir.is_dir():
        for p in settled_dir.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                fid = str(data.get("fixture_id") or p.stem)
                if fid not in out:
                    out[fid] = data
            except json.JSONDecodeError:
                continue
    return out


def classify_matches(
    matches: list[dict],
    *,
    kickoff_map: dict,
    settled_map: dict[str, dict],
) -> tuple[list[dict], list[dict], list[dict]]:
    upcoming: list[dict] = []
    live: list[dict] = []
    finished: list[dict] = []

    seen_finished: set[str] = set()
    for m in matches:
        fid = str(m.get("fixture_id") or "")
        settled = settled_map.get(fid)
        ko = kickoff_map.get(fid)
        phase = match_phase(ko, has_result=bool(settled))
        enriched = dict(m)
        if settled:
            enriched["settled"] = settled
            enriched["match_phase"] = "finished"
            finished.append(enriched)
            seen_finished.add(fid)
        elif phase == "finished":
            enriched["match_phase"] = "finished_pending"
            finished.append(enriched)
            seen_finished.add(fid)
        elif phase == "live":
            enriched["match_phase"] = "live"
            live.append(enriched)
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
