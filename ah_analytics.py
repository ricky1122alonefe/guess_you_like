"""Asian handicap win-rate analytics and recommendation backtest."""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from ah import ah_settle
from ah import format_ah_pick_cn
from time_utils import now_beijing_str

log = logging.getLogger(__name__)


def ah_win_rate_from_net(net: float | None) -> float | None:
    if net is None:
        return None
    return (net + 1) / 2


def ah_rate_text(stats: dict) -> str | None:
    upper = ah_win_rate_from_net(stats.get("ah_home_net"))
    lower = ah_win_rate_from_net(stats.get("ah_away_net"))
    if upper is None or lower is None:
        return None

    def _pct(v: float) -> str:
        return f"{v * 100:.1f}%"

    return f"上盘赢 {_pct(upper)} · 下盘赢 {_pct(lower)}"


def ah_breakdown(stats: dict) -> dict[str, Any]:
    """Compact AH distribution from match.summarize() output."""
    upper = ah_win_rate_from_net(stats.get("ah_home_net"))
    lower = ah_win_rate_from_net(stats.get("ah_away_net"))
    return {
        "ah_upper_win_rate": upper,
        "ah_lower_win_rate": lower,
        "ah_home_net": stats.get("ah_home_net"),
        "ah_away_net": stats.get("ah_away_net"),
        "ah_home_full_win": stats.get("ah_home_full_win"),
        "ah_home_half_win": stats.get("ah_home_half_win"),
        "ah_home_push": stats.get("ah_home_push"),
        "ah_home_half_loss": stats.get("ah_home_half_loss"),
        "ah_home_full_loss": stats.get("ah_home_full_loss"),
        "ah_rate_text": ah_rate_text(stats),
    }


def evaluate_ah_pick(
    pick: str | None,
    *,
    home_score: int,
    away_score: int,
    line: float | None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "pick_ah": pick,
        "pick_ah_cn": None,
        "ah_line_used": line,
        "ah_settlement": None,
        "hit_ah": None,
    }
    if pick not in ("home", "away") or line is None:
        return out

    try:
        line_f = float(line)
    except (TypeError, ValueError):
        return out

    settlement = ah_settle(home_score, away_score, line_f, pick)
    out["ah_settlement"] = settlement
    out["pick_ah_cn"] = format_ah_pick_cn(pick, line_f)
    if settlement > 0:
        out["hit_ah"] = True
    elif settlement < 0:
        out["hit_ah"] = False
    else:
        out["hit_ah"] = None
    return out


def _parse_score(score_text: str | None) -> tuple[int, int] | None:
    if not score_text or "-" not in str(score_text):
        return None
    parts = str(score_text).split("-", 1)
    try:
        return int(parts[0]), int(parts[1])
    except (TypeError, ValueError):
        return None


def _closing_line(record: dict) -> float | None:
    closing = record.get("closing_odds") or {}
    opening = record.get("opening_odds") or {}
    for src in (closing, opening, record):
        line = src.get("ah_line") if isinstance(src, dict) else None
        if line is not None:
            try:
                return float(line)
            except (TypeError, ValueError):
                continue
    line = record.get("closing_ah_line")
    if line is not None:
        try:
            return float(line)
        except (TypeError, ValueError):
            pass
    return None


def enrich_record_with_ah(record: dict) -> dict:
    """Attach empirical line win rates and optional pick backtest fields."""
    rec = dict(record)
    score = _parse_score(rec.get("score_text"))
    line = _closing_line(rec)
    if score and line is not None:
        hs, gs = score
        home_settle = ah_settle(hs, gs, line, "home")
        away_settle = ah_settle(hs, gs, line, "away")
        if line < 0:
            rec["actual_upper_settlement"] = home_settle
            rec["actual_lower_settlement"] = away_settle
        elif line > 0:
            rec["actual_upper_settlement"] = away_settle
            rec["actual_lower_settlement"] = home_settle
        else:
            rec["actual_upper_settlement"] = home_settle
            rec["actual_lower_settlement"] = away_settle
        rec["closing_ah_line"] = line

    pick = rec.get("asian_handicap_pick")
    if pick in ("home", "away") and score and line is not None:
        hs, gs = score
        ah_eval = evaluate_ah_pick(pick, home_score=hs, away_score=gs, line=line)
        rec.update(ah_eval)
        if not rec.get("asian_handicap_cn"):
            rec["asian_handicap_cn"] = format_ah_pick_cn(pick, line)
    return rec


def _rate(hits: int, total: int) -> float | None:
    return round(hits / total * 100, 1) if total else None


def compute_ah_accuracy_report(records: list[dict]) -> dict[str, Any]:
    with_pick = [
        r for r in records
        if r.get("asian_handicap_pick") in ("home", "away")
    ]
    judged = [r for r in with_pick if r.get("hit_ah") is not None]
    wins = sum(1 for r in judged if r.get("hit_ah"))
    pushes = sum(1 for r in with_pick if r.get("hit_ah") is None and r.get("ah_settlement") == 0)
    losses = sum(1 for r in judged if r.get("hit_ah") is False)

    by_side: dict[str, dict] = defaultdict(lambda: {"total": 0, "hit": 0})
    by_conf: dict[str, dict] = defaultdict(lambda: {"total": 0, "hit": 0})
    for r in judged:
        side = r.get("asian_handicap_pick") or "unknown"
        by_side[side]["total"] += 1
        if r.get("hit_ah"):
            by_side[side]["hit"] += 1
        conf = r.get("confidence_cn") or "未知"
        by_conf[conf]["total"] += 1
        if r.get("hit_ah"):
            by_conf[conf]["hit"] += 1

    def _summ(groups: dict) -> dict:
        out = {}
        for k, v in sorted(groups.items(), key=lambda x: -x[1]["total"]):
            out[k] = {**v, "rate_pct": _rate(v["hit"], v["total"])}
        return out

    net_units = sum(r.get("ah_settlement") or 0 for r in with_pick if r.get("ah_settlement") is not None)

    return {
        "total_settled": len(records),
        "with_ah_pick": len(with_pick),
        "judged_ah": len(judged),
        "hit_ah": wins,
        "miss_ah": losses,
        "push_ah": pushes,
        "rate_ah_pct": _rate(wins, len(judged)),
        "net_units": round(net_units, 2) if with_pick else None,
        "by_side": _summ(by_side),
        "by_confidence": _summ(by_conf),
    }


def _line_bucket(line: float) -> str:
    if line == 0:
        return "平手"
    if -0.5 <= line < 0:
        return "主让 0~0.5"
    if -1.0 <= line < -0.5:
        return "主让 0.75~1"
    if line < -1.0:
        return "主让 1+"
    if 0 < line <= 0.5:
        return "主受让 0~0.5"
    return "主受让 0.75+"


def _line_move_label(move: float | None) -> str:
    if move is None:
        return "未知"
    if move > 0:
        return "升盘"
    if move < 0:
        return "降盘"
    return "不动"


def compute_ah_pattern_stats(records: list[dict]) -> dict[str, Any]:
    """Empirical upper/lower win rates grouped by line bucket and line move."""
    bucket: dict[str, dict] = defaultdict(lambda: {"total": 0, "upper_win": 0, "lower_win": 0, "push": 0})
    move_grp: dict[str, dict] = defaultdict(lambda: {"total": 0, "upper_win": 0, "lower_win": 0})
    consistency_grp: dict[str, dict] = defaultdict(lambda: {"total": 0, "upper_win": 0, "lower_win": 0})

    for r in records:
        score = _parse_score(r.get("score_text"))
        line = _closing_line(r)
        if not score or line is None:
            continue
        hs, gs = score
        home_settle = ah_settle(hs, gs, line, "home")
        away_settle = ah_settle(hs, gs, line, "away")
        if line < 0:
            upper_settle, lower_settle = home_settle, away_settle
        elif line > 0:
            upper_settle, lower_settle = away_settle, home_settle
        else:
            upper_settle, lower_settle = home_settle, away_settle

        bk = _line_bucket(line)
        bucket[bk]["total"] += 1
        if upper_settle > 0:
            bucket[bk]["upper_win"] += 1
        if lower_settle > 0:
            bucket[bk]["lower_win"] += 1
        if upper_settle == 0 and lower_settle == 0:
            bucket[bk]["push"] += 1

        mv = _line_move_label(r.get("line_move"))
        move_grp[mv]["total"] += 1
        if upper_settle > 0:
            move_grp[mv]["upper_win"] += 1
        if lower_settle > 0:
            move_grp[mv]["lower_win"] += 1

        cons = r.get("opening_consistency") or "unknown"
        consistency_grp[cons]["total"] += 1
        if upper_settle > 0:
            consistency_grp[cons]["upper_win"] += 1
        if lower_settle > 0:
            consistency_grp[cons]["lower_win"] += 1

    def _fmt(groups: dict) -> list[dict]:
        rows = []
        for label, v in sorted(groups.items(), key=lambda x: -x[1]["total"]):
            t = v["total"]
            rows.append({
                "label": label,
                "count": t,
                "upper_win_pct": _rate(v["upper_win"], t),
                "lower_win_pct": _rate(v["lower_win"], t),
                "push_pct": _rate(v.get("push", 0), t) if "push" in v else None,
            })
        return rows

    total_with_line = sum(v["total"] for v in bucket.values())
    return {
        "sample_count": total_with_line,
        "by_line_bucket": _fmt(bucket),
        "by_line_move": _fmt(move_grp),
        "by_consistency": _fmt(consistency_grp),
    }


def load_ah_records(output_root: str | Path) -> list[dict]:
    from worldcup_analytics import load_tournament_records

    records = load_tournament_records(output_root)
    enriched = [enrich_record_with_ah(r) for r in records]

    # Backfill AH pick from archived predictions when missing
    root = Path(output_root)
    from prediction_archive import load_best_prediction

    for rec in enriched:
        if rec.get("asian_handicap_pick") in ("home", "away"):
            continue
        fid = rec.get("fixture_id")
        if not fid:
            continue
        pred = load_best_prediction(root, str(fid))
        if not pred:
            continue
        pick = pred.get("asian_handicap_pick")
        if pick not in ("home", "away"):
            continue
        rec["asian_handicap_pick"] = pick
        rec["asian_handicap_cn"] = pred.get("asian_handicap_cn")
        rec["asian_handicap_reason"] = pred.get("asian_handicap_reason")
        rec["confidence_cn"] = rec.get("confidence_cn") or pred.get("confidence_cn")
        rec["recommendation_source"] = rec.get("recommendation_source") or pred.get("recommendation_source")
        score = _parse_score(rec.get("score_text"))
        line = _closing_line(rec)
        if score and line is not None:
            hs, gs = score
            rec.update(evaluate_ah_pick(pick, home_score=hs, away_score=gs, line=line))
    return enriched


def build_ah_ledger(output_root: str | Path) -> dict[str, Any]:
    records = load_ah_records(output_root)
    patterns = compute_ah_pattern_stats(records)
    accuracy = compute_ah_accuracy_report(records)
    return {
        "updated_at": now_beijing_str(),
        "accuracy": accuracy,
        "patterns": patterns,
        "records": records,
    }


def save_ah_ledger(output_root: str | Path) -> Path:
    root = Path(output_root)
    out_dir = root / "handicap"
    out_dir.mkdir(parents=True, exist_ok=True)
    ledger = build_ah_ledger(root)
    path = out_dir / "ledger.json"
    path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def refresh_ah_ledger(output_root: str | Path) -> dict[str, Any]:
    path = save_ah_ledger(output_root)
    ledger = build_ah_ledger(output_root)
    log.info("亚盘账本已更新 → %s（%d 场）", path, len(ledger.get("records") or []))
    return ledger


def ah_card_from_prediction(
    prediction: dict | None,
    timeline: list[dict] | None = None,
) -> dict[str, Any] | None:
    """Build match-detail AH analysis card payload."""
    if not prediction:
        return None

    sim = prediction.get("similarity_analysis") or {}
    open_blocks = sim.get("open") or []
    live_blocks = sim.get("live") or []

    def _find_ah_block(blocks: list[dict]) -> dict | None:
        for b in blocks:
            if b.get("source") == "open_ah" or "亚盘" in (b.get("title") or ""):
                return b
        return blocks[0] if blocks else None

    open_ah = _find_ah_block(open_blocks)
    live_ah = _find_ah_block(live_blocks)

    tl = timeline or []
    latest_odds = (tl[-1].get("odds") or {}) if tl else {}
    open_odds = (tl[0].get("odds") or {}) if tl else {}

    open_line = open_odds.get("ah_open_line") or open_odds.get("ah_line")
    live_line = latest_odds.get("ah_line")
    open_hw = open_odds.get("ah_open_home_water") or open_odds.get("ah_home_water")
    open_aw = open_odds.get("ah_open_away_water") or open_odds.get("ah_away_water")
    live_hw = latest_odds.get("ah_home_water")
    live_aw = latest_odds.get("ah_away_water")

    return {
        "pick": prediction.get("asian_handicap_pick") or "skip",
        "pick_cn": prediction.get("asian_handicap_cn") or "观望",
        "reason": prediction.get("asian_handicap_reason") or "",
        "open_line": open_line,
        "live_line": live_line,
        "open_water": f"{open_hw}/{open_aw}" if open_hw is not None or open_aw is not None else None,
        "live_water": f"{live_hw}/{live_aw}" if live_hw is not None or live_aw is not None else None,
        "open_stats": open_ah,
        "live_stats": live_ah,
    }
