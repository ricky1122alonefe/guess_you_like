"""Daily match-day picks: 稳健 / 折中 / 博冷门 — each tier is a 2串1 parlay."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from time_utils import beijing_date, format_beijing, now_beijing, now_beijing_str, to_beijing
from itertools import combinations
from pathlib import Path
from typing import Any

from jingcai_pick import (
    KEY_FROM_SP_CN,
    RQ_CN,
    SP_CN,
    actionable_jingcai_pick,
    infer_rq_pick_from_scores,
    jingcai_market_mode,
    market_label,
)
import config as app_cfg

log = logging.getLogger(__name__)

SKIP_PICKS = frozenset({"观望", "—", "", None})
CONF_W = {"高": 3.0, "中": 2.0, "低": 1.0}
RISK_W = {"常规": 3.0, "升高": 2.0, "显著升高": 0.5}
CTRL_W = {"低": 3.0, "中": 2.0, "高": 0.5}
RESULT_TO_KEY = {"主胜": "home", "平局": "draw", "客胜": "away"}
KEY_TO_CN = {"home": "主胜", "draw": "平局", "away": "客胜"}
PARLAY_SIZE = 2
PARLAY_LABEL = "2串1"
AI_KICKOFF_HOURS = 24.0


def kickoff_within_hours(
    fixture_id: str,
    hours: float,
    kickoff_map: dict[str, datetime],
    *,
    now: datetime | None = None,
    grace_started_minutes: float = 30,
) -> bool:
    """True if kickoff is within `hours` ahead (Beijing), or recently started."""
    ko = kickoff_map.get(str(fixture_id))
    if not isinstance(ko, datetime):
        return False
    ref = now or now_beijing()
    delta_sec = (to_beijing(ko) - to_beijing(ref)).total_seconds()
    return -grace_started_minutes * 60 <= delta_sec <= hours * 3600


@dataclass
class ParlayLeg:
    fixture_id: str
    match: str
    kickoff: str
    pick_cn: str
    scores: str
    asian_handicap_cn: str
    confidence_cn: str
    eu_odds: float | None
    reason: str
    model_note: str
    market_pattern_summary: str = ""


@dataclass
class DailyPick:
    tier: str
    tier_label: str
    parlay_type: str
    legs: list[ParlayLeg]
    combined_odds: float | None
    reason: str
    score: float


def load_kickoff_map(*, within_days: float = 7) -> dict[str, datetime]:
    out: dict[str, datetime] = {}
    try:
        from db.connection import cursor

        with cursor() as cur:
            cur.execute(
                """
                SELECT external_id, kickoff_at
                FROM fixtures
                WHERE kickoff_at IS NOT NULL AND source = '500'
                """
            )
            for row in cur.fetchall():
                ko = row.get("kickoff_at")
                if ko:
                    out[str(row["external_id"])] = ko
    except Exception as exc:
        log.debug("DB kickoff 不可用: %s", exc)

    if not out:
        try:
            from download_500 import fetch_live_fixtures

            for fx in fetch_live_fixtures(within_days=within_days):
                if fx.kickoff:
                    out[str(fx.fixture_id)] = fx.kickoff
        except Exception as exc:
            log.debug("live fixtures kickoff 不可用: %s", exc)
    return out


def _load_prediction_cache(output_root: str | Path) -> dict[str, dict]:
    """Latest predictions; fall back to most recent run if latest.json is empty."""
    from odds_cache import load_latest_predictions

    root = Path(output_root)
    preds = load_latest_predictions(root)
    if preds:
        return preds
    runs_dir = root / "runs"
    if not runs_dir.is_dir():
        return {}
    for run_path in sorted(runs_dir.iterdir(), reverse=True):
        pred_path = run_path / "predictions.json"
        if not pred_path.is_file():
            continue
        try:
            data = json.loads(pred_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        matches = data.get("matches") or []
        if not matches:
            continue
        out: dict[str, dict] = {}
        for m in matches:
            fid = m.get("fixture_id")
            if fid:
                out[str(fid)] = m
        if out:
            log.info("latest.json 为空，回退到 %s（%d 场）", pred_path.parent.name, len(out))
            return out
    return {}


def _stub_dashboard_match(*, fixture_id: str, match_name: str) -> dict:
    return {
        "fixture_id": fixture_id,
        "match": match_name,
        "predict_row": {"比赛": match_name},
        "recommendation_source": "pending",
    }


def _load_db_fixture_stubs(*, within_days: float, now: datetime) -> dict[str, dict]:
    """Future fixtures remembered in DB, used when live.500 only exposes current-day rows."""
    out: dict[str, dict] = {}
    try:
        from db.connection import cursor

        with cursor() as cur:
            cur.execute(
                """
                SELECT external_id, match_name, home_team, away_team, kickoff_at
                FROM fixtures
                WHERE source = '500'
                  AND kickoff_at IS NOT NULL
                  AND kickoff_at >= NOW() - interval '30 minutes'
                  AND kickoff_at <= NOW() + (%s || ' days')::interval
                ORDER BY kickoff_at
                """,
                (str(within_days),),
            )
            rows = cur.fetchall()
    except Exception as exc:
        log.debug("DB future fixtures 不可用: %s", exc)
        return out

    ref = to_beijing(now)
    for row in rows:
        fid = str(row.get("external_id") or "")
        if not fid:
            continue
        ko = row.get("kickoff_at")
        if isinstance(ko, datetime):
            ko_bj = to_beijing(ko)
            if ko_bj < ref - timedelta(minutes=30) or ko_bj > ref + timedelta(days=within_days):
                continue
        name = row.get("match_name") or ""
        if not name:
            home, away = row.get("home_team") or "", row.get("away_team") or ""
            name = f"{home}VS{away}" if home and away else fid
        out[fid] = _stub_dashboard_match(fixture_id=fid, match_name=name)
    return out


def load_dashboard_matches(
    output_root: str | Path,
    *,
    within_days: float | None = None,
) -> list[dict]:
    """Upcoming/live fixtures for dashboard — not limited to latest.json."""
    from download_500 import DEFAULT_LEAGUES, fetch_live_fixtures

    root = Path(output_root)
    days = within_days if within_days is not None else app_cfg.SERVICE_WITHIN_DAYS
    now = now_beijing()
    preds = _load_prediction_cache(root)
    by_id: dict[str, dict] = {}

    try:
        fixtures = fetch_live_fixtures(within_days=days, leagues=DEFAULT_LEAGUES)
    except Exception as exc:
        log.warning("拉取 live 赛程失败: %s", exc)
        fixtures = []

    for fx in fixtures:
        fid = str(fx.fixture_id)
        by_id[fid] = preds.get(fid) or _stub_dashboard_match(
            fixture_id=fid, match_name=fx.base_name,
        )

    # live.500 often exposes only the current match day. Merge DB/cache future rows
    # so upcoming fixtures do not disappear from the dashboard.
    kickoff_map = load_kickoff_map(within_days=days)
    for fid, stub in _load_db_fixture_stubs(within_days=days, now=now).items():
        by_id.setdefault(fid, preds.get(fid) or stub)

    for fid, pred in preds.items():
        ko = kickoff_map.get(fid)
        if ko is None:
            if not by_id:
                by_id[fid] = pred
            continue
        ko_bj = to_beijing(ko)
        ref = to_beijing(now)
        if (ko_bj >= ref - timedelta(minutes=30)) and (
            ko_bj <= ref + timedelta(days=days)
        ):
            by_id.setdefault(fid, pred)

    return list(by_id.values())


def _kickoff_date(m: dict, kickoff_map: dict[str, datetime]) -> str | None:
    fid = str(m.get("fixture_id") or "")
    ko = kickoff_map.get(fid)
    if ko:
        return beijing_date(ko)
    row = m.get("predict_row") or {}
    d = row.get("预测日期")
    return str(d) if d else None


def _kickoff_label(m: dict, kickoff_map: dict[str, datetime]) -> str:
    fid = str(m.get("fixture_id") or "")
    ko = kickoff_map.get(fid)
    if isinstance(ko, datetime):
        return format_beijing(ko, "%m-%d %H:%M")
    return "—"


def _parse_pct(text: str | None) -> float:
    if not text:
        return 0.0
    m = re.search(r"([\d.]+)\s*%", str(text))
    return float(m.group(1)) if m else 0.0


def _eu_odds(m: dict, pick_key: str) -> float | None:
    snap = m.get("odds_snapshot") or {}
    row = m.get("predict_row") or {}
    eu = row.get("临盘欧赔")
    if eu and isinstance(eu, str):
        parts = eu.split("/")
        if len(parts) == 3:
            try:
                h, d, a = map(float, parts)
                return {"home": h, "draw": d, "away": a}.get(pick_key)
            except ValueError:
                pass
    try:
        h, d, a = snap.get("eu_home"), snap.get("eu_draw"), snap.get("eu_away")
        if h and d and a:
            return {"home": float(h), "draw": float(d), "away": float(a)}.get(pick_key)
    except (TypeError, ValueError):
        pass
    return None


def _market_favorite_key(m: dict) -> str | None:
    implied = m.get("implied_probability") or {}
    if not implied:
        snap = m.get("odds_snapshot") or {}
        try:
            h, d, a = float(snap["eu_home"]), float(snap["eu_draw"]), float(snap["eu_away"])
            inv = {"home": 1 / h, "draw": 1 / d, "away": 1 / a}
            return max(inv, key=inv.get)
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            return None
    mapping = {"主胜": "home", "平": "draw", "客胜": "away"}
    best_k, best_v = None, -1.0
    for label, key in mapping.items():
        v = _parse_pct(implied.get(label))
        if v > best_v:
            best_v, best_k = v, key
    return best_k


def _best_actionable_pick(m: dict) -> dict[str, Any] | None:
    """Pick for tier scoring: dual-model consensus > highest conf single."""
    analyses = m.get("ai_analyses") or {}
    candidates: list[dict[str, Any]] = []

    def _one(p: dict, source: str) -> dict[str, Any] | None:
        row = p.get("predict_row") or {}
        jc = actionable_jingcai_pick(p)
        if not jc:
            return None
        pick_cn = jc["pick_cn"]
        pick_key = jc["pick_key"]
        scores = row.get("推荐比分") or "、".join(
            p.get("likely_scores_detail") or p.get("likely_scores") or []
        )
        reasoning = jc.get("reason") or (p.get("actuary_reasoning") or "")[:200]
        return {
            "source": source,
            "pick_cn": pick_cn,
            "pick_key": pick_key,
            "jingcai_market": jc.get("market"),
            "jingcai_market_label": jc.get("market_label"),
            "scores": scores,
            "asian_handicap_cn": row.get("亚盘") or p.get("asian_handicap_cn") or "—",
            "confidence_cn": row.get("置信度") or p.get("confidence_cn") or "低",
            "value_bet": p.get("value_bet"),
            "actuary_reasoning": reasoning,
            "jingcai_sp": jc.get("sp"),
        }

    if analyses:
        for pid, p in analyses.items():
            c = _one(p, p.get("ai_provider_label") or pid)
            if c:
                candidates.append(c)
    else:
        c = _one(m, "综合")
        if c:
            candidates.append(c)

    if not candidates:
        return None

    pick_cns = {c["pick_cn"] for c in candidates}
    if len(pick_cns) == 1 and len(candidates) > 1:
        out = dict(candidates[0])
        out["model_note"] = (
            f"多模型一致·{out['pick_cn']}" if len(candidates) > 2 else f"双模型一致·{out['pick_cn']}"
        )
        out["consensus"] = True
        return out

    best = max(candidates, key=lambda c: CONF_W.get(c["confidence_cn"], 1))
    if len(candidates) > 1:
        others = " / ".join(f"{c['source']}:{c['pick_cn']}" for c in candidates)
        best = dict(best)
        best["model_note"] = f"取高置信·{others}"
        best["consensus"] = False
    else:
        best = dict(best)
        best["model_note"] = best.get("source", "AI")
        best["consensus"] = True
    return best


def _rqsp_extreme_confidence(pick: dict[str, Any]) -> bool:
    """
    仅让球场次进入 2串1 候选池的门槛：极高自信。
    需「高」置信，且多模型一致 / 正 EV / 模型备注含一致。
    """
    if pick.get("jingcai_market") != "rqsp":
        return True
    if pick.get("confidence_cn") != "高":
        return False
    if pick.get("consensus"):
        return True
    if pick.get("value_bet") is True:
        return True
    note = pick.get("model_note") or ""
    return "一致" in note


def _select_daily_candidates(
    all_actionable: list[dict[str, Any]],
    *,
    sp_preferred: bool | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Build parlay pool: SP always; rqsp only when extreme confidence."""
    sp_preferred = (
        app_cfg.DAILY_PICKS_SP_PREFERRED
        if sp_preferred is None
        else sp_preferred
    )
    sp_list = [c for c in all_actionable if c.get("jingcai_market") == "sp"]
    rqsp_all = [c for c in all_actionable if c.get("jingcai_market") == "rqsp"]
    rqsp_eligible = [c for c in rqsp_all if _rqsp_extreme_confidence(c)]

    if not sp_preferred:
        pool = list(all_actionable)
    else:
        pool = sp_list + rqsp_eligible

    stats = {
        "sp_count": len(sp_list),
        "rqsp_total": len(rqsp_all),
        "rqsp_eligible": len(rqsp_eligible),
    }
    return pool, stats


def _score_match(m: dict, pick: dict[str, Any], kickoff_map: dict[str, datetime]) -> dict[str, float]:
    conf = CONF_W.get(pick["confidence_cn"], 1.0)
    risk = RISK_W.get(m.get("risk_level_cn") or "升高", 1.5)
    ctrl = CTRL_W.get(m.get("control_level_cn") or "中", 1.5)
    open_cn = m.get("open_result_1x2_cn") or ""
    aligns_open = pick["pick_cn"] == open_cn
    value_bet = m.get("value_bet") is True or pick.get("value_bet") is True
    eu = _eu_odds(m, pick["pick_key"])
    fav = _market_favorite_key(m)
    is_fav = pick["pick_key"] == fav
    is_dog = fav and pick["pick_key"] != fav and pick["pick_key"] in ("home", "away")
    consensus = pick.get("consensus") is True

    safe = 0.0
    safe += conf * 4
    safe += risk * 2
    safe += ctrl * 2
    if aligns_open:
        safe += 5
    if value_bet:
        safe += 4
    if consensus:
        safe += 4
    if is_fav:
        safe += 3
    if eu and eu < 1.7:
        safe += 2
    elif eu and eu < 2.2:
        safe += 3
    if m.get("insufficient_data"):
        safe -= 8
    if pick.get("jingcai_market") == "rqsp":
        safe -= getattr(app_cfg, "DAILY_PICKS_RQSP_SCORE_PENALTY", 5)
    elif pick["asian_handicap_cn"] != "观望":
        safe += 1

    balanced = 0.0
    balanced += conf * 3
    balanced += 2 if pick["pick_cn"] not in SKIP_PICKS else -10
    if value_bet:
        balanced += 3
    if eu and 1.6 <= eu <= 3.5:
        balanced += 4
    if aligns_open:
        balanced += 2
    balanced += risk * 1.5
    if consensus:
        balanced += 2
    if m.get("eu_implied_anomaly"):
        safe -= app_cfg.EU_IMPLIED_SCORE_PENALTY
        balanced -= app_cfg.EU_IMPLIED_SCORE_PENALTY * 0.5
    if pick.get("jingcai_market") == "rqsp":
        pen = getattr(app_cfg, "DAILY_PICKS_RQSP_SCORE_PENALTY", 5)
        balanced -= pen * 0.6

    upset = 0.0
    upset += 2 if pick["pick_cn"] not in SKIP_PICKS else -10
    if is_dog:
        upset += 6
    if eu and eu >= 3.0:
        upset += min(8.0, (eu - 2.0) * 2)
    if value_bet:
        upset += 5
    if not aligns_open and open_cn:
        upset += 4
    implied = m.get("implied_probability") or {}
    adj = m.get("adjusted_probability") or {}
    if implied and adj:
        pk_cn = KEY_TO_CN.get(pick["pick_key"], pick["pick_cn"])
        imp = _parse_pct(implied.get(pk_cn.replace("平局", "平")))
        adp = _parse_pct(adj.get(pk_cn.replace("平局", "平")))
        if adp > imp + 5:
            upset += 4
    upset += conf * 0.5
    if m.get("risk_level_cn") == "显著升高":
        upset += 1

    try:
        from style_clash import VARIANCE_HIGH, VARIANCE_MEDIUM, style_clash_for_match
        clash = style_clash_for_match(m)
        if clash.get("available"):
            adj = clash.get("score_adjustment") or {}
            lvl = clash.get("variance_level")
            if lvl in (VARIANCE_MEDIUM, VARIANCE_HIGH):
                upset += adj.get("upset_boost", 0)
            dog_side = clash.get("favors_underdog_side")
            if is_fav and dog_side and fav and fav != dog_side:
                safe -= adj.get("safe_penalty", 0)
    except Exception:
        pass

    return {"safe": safe, "balanced": balanced, "upset": upset}


def _build_candidate(
    m: dict,
    kickoff_map: dict[str, datetime],
) -> dict[str, Any] | None:
    pick = _best_actionable_pick(m)
    if not pick:
        return None
    market = pick.get("jingcai_market") or "sp"
    scores = _score_match(m, pick, kickoff_map)
    fid = str(m.get("fixture_id") or "")
    reason = pick.get("actuary_reasoning") or m.get("confidence_reason") or ""
    if not reason:
        reason = (m.get("open_probability_summary") or "")[:120]
    eu = pick.get("jingcai_sp") or _eu_odds(m, pick["pick_key"])
    sp = pick.get("jingcai_sp") or _jc_sp(m.get("jingcai_snapshot"), market, pick["pick_key"])
    return {
        "fixture_id": fid,
        "match": m.get("match") or (m.get("predict_row") or {}).get("比赛") or fid,
        "kickoff": _kickoff_label(m, kickoff_map),
        "match_date": _kickoff_date(m, kickoff_map),
        "pick_cn": pick["pick_cn"],
        "jingcai_market": market,
        "jingcai_market_label": pick.get("jingcai_market_label") or "胜平负",
        "scores": pick["scores"],
        "asian_handicap_cn": pick["asian_handicap_cn"],
        "confidence_cn": pick["confidence_cn"],
        "jingcai_sp": round(sp, 2) if sp else None,
        "odds_used": round(sp, 2) if sp else None,
        "eu_odds": round(eu, 2) if eu else None,
        "reason": reason,
        "model_note": pick.get("model_note") or "",
        "market_pattern_summary": m.get("market_pattern_summary") or "",
        "consensus": pick.get("consensus") is True,
        "value_bet": pick.get("value_bet") is True or m.get("value_bet") is True,
        "safe_score": scores["safe"],
        "balanced_score": scores["balanced"],
        "upset_score": scores["upset"],
    }


def _pick_best(candidates: list[dict], score_key: str, exclude_fids: set[str]) -> dict | None:
    pool = [c for c in candidates if c["fixture_id"] not in exclude_fids]
    if not pool:
        pool = candidates
    if not pool:
        return None
    return max(pool, key=lambda c: c[score_key])


def _combined_odds(legs: list[dict]) -> float | None:
    """Multiply leg odds — prefers 竞彩 SP (odds_used / jingcai_sp)."""
    odds: list[float | None] = []
    for leg in legs:
        val = leg.get("odds_used")
        if val is None:
            val = leg.get("jingcai_sp")
        if val is None:
            odds.append(None)
            continue
        try:
            odds.append(float(val))
        except (TypeError, ValueError):
            odds.append(None)
    if not all(odds):
        return None
    combined = 1.0
    for o in odds:
        combined *= o  # type: ignore[operator]
    return round(combined, 2)


def _jc_sp(jc: dict | None, market: str, pick_key: str) -> float | None:
    if not jc or pick_key in ("", "skip"):
        return None
    if market == "sp":
        mapping = {"home": "sp_home", "draw": "sp_draw", "away": "sp_away"}
    else:
        mapping = {"home": "rqsp_home", "draw": "rqsp_draw", "away": "rqsp_away"}
    try:
        val = jc.get(mapping[pick_key])
        return round(float(val), 2) if val is not None else None
    except (KeyError, TypeError, ValueError):
        return None


def _score_text(m: dict) -> str:
    row = m.get("predict_row") or {}
    scores = row.get("推荐比分") or m.get("likely_scores_detail") or m.get("likely_scores") or []
    if isinstance(scores, list):
        return "、".join(str(s) for s in scores[:3])
    return str(scores or "")


def _fallback_pick_key(m: dict, market: str, jc: dict | None) -> tuple[str, str, str]:
    """Best buyable direction when strict actionable pick is empty."""
    row = m.get("predict_row") or {}
    if market == "sp":
        for raw in (
            row.get("赛果预测"),
            m.get("match_result_1x2_cn"),
            m.get("result_1x2_cn"),
            row.get("胜平负"),
        ):
            key = KEY_FROM_SP_CN.get(str(raw or ""))
            if key and key != "skip":
                return key, SP_CN[key], "按赛果分析方向落到竞彩胜平负"
        key = m.get("result_1x2")
        if key in SP_CN and key != "skip":
            return key, SP_CN[key], "按模型赛果方向落到竞彩胜平负"
        return "skip", "观望", "无可用赛果方向"

    if market == "rqsp" and jc:
        hcap = jc.get("handicap")
        if hcap is None:
            return "skip", "观望", "缺少让球数"
        pick_key, reason = infer_rq_pick_from_scores(_score_text(m).split("、"), int(hcap))
        if pick_key == "skip":
            return pick_key, "观望", reason
        label = market_label(jc, market)
        return pick_key, f"{label} {RQ_CN[pick_key]}", reason

    return "skip", "观望", "暂无可售玩法"


def _build_floor_candidate(m: dict, kickoff_map: dict[str, datetime]) -> dict[str, Any] | None:
    """Most conservative buyable fallback candidate, even when strict EV says observe."""
    strict = _build_candidate(m, kickoff_map)
    if strict:
        c = dict(strict)
        c["floor_source"] = "strict"
        return c

    jc = m.get("jingcai_snapshot") or {}
    info = m.get("jingcai_pick_info") or {}
    market = info.get("jingcai_market") or jingcai_market_mode(jc)
    if market == "none":
        return None

    pick_key, pick_cn, reason = _fallback_pick_key(m, market, jc)
    if pick_key == "skip":
        return None

    fid = str(m.get("fixture_id") or "")
    row = m.get("predict_row") or {}
    sp = info.get("jingcai_sp") or _jc_sp(jc, market, pick_key)
    eu = sp or _eu_odds(m, pick_key)
    conf = row.get("置信度") or m.get("confidence_cn") or "低"
    return {
        "fixture_id": fid,
        "match": m.get("match") or row.get("比赛") or fid,
        "kickoff": _kickoff_label(m, kickoff_map),
        "match_date": _kickoff_date(m, kickoff_map),
        "pick_cn": pick_cn,
        "pick_key": pick_key,
        "jingcai_market": market,
        "jingcai_market_label": info.get("jingcai_market_label") or market_label(jc, market),
        "scores": _score_text(m),
        "asian_handicap_cn": row.get("亚盘") or m.get("asian_handicap_cn") or "观望",
        "confidence_cn": conf,
        "eu_odds": round(float(eu), 2) if eu else None,
        "reason": f"{reason}；原模型偏保守，作为保底候选需小仓位",
        "model_note": "保底候选·非强推荐",
        "market_pattern_summary": m.get("market_pattern_summary") or "",
        "consensus": False,
        "value_bet": m.get("value_bet") is True,
        "safe_score": 0.0,
        "balanced_score": 0.0,
        "upset_score": 0.0,
        "floor_source": "fallback",
        "insufficient_data": bool(m.get("insufficient_data")),
        "risk_level_cn": m.get("risk_level_cn"),
        "control_level_cn": m.get("control_level_cn"),
    }


def _floor_score(c: dict) -> float:
    conf = CONF_W.get(c.get("confidence_cn"), 1.0)
    risk = RISK_W.get(c.get("risk_level_cn") or "升高", 1.5)
    ctrl = CTRL_W.get(c.get("control_level_cn") or "中", 1.5)
    score = conf * 4 + risk * 2 + ctrl * 2
    if c.get("floor_source") == "strict":
        score += 5
    if c.get("value_bet"):
        score += 3
    if c.get("jingcai_market") == "sp":
        score += 3
    else:
        score -= 2
    odds = c.get("eu_odds")
    if odds:
        if 1.45 <= odds <= 2.25:
            score += 4
        elif odds < 1.45:
            score += 1
        elif odds > 3.5:
            score -= 3
    if c.get("insufficient_data"):
        score -= 5
    return score


def _build_floor_safe_parlay(candidates: list[dict], *, target: str) -> dict[str, Any] | None:
    if len(candidates) < PARLAY_SIZE:
        return None
    best: tuple[list[dict], float] | None = None
    for a, b in combinations(candidates, PARLAY_SIZE):
        combined = _combined_odds([a, b])
        score = (_floor_score(a) + _floor_score(b)) / 2
        if combined:
            if 2.2 <= combined <= 5.5:
                score += 4
            elif combined > 7:
                score -= 5
        if best is None or score > best[1]:
            best = ([a, b], score)
    if best is None:
        return None

    leg_dicts, score = best
    legs = _legs_from_candidates(leg_dicts)
    combined = _combined_odds(leg_dicts)
    reason = _parlay_summary(legs, combined)
    reason += (
        "\n保底逻辑：同日可购买场次中，优先选胜平负、低赔区间、低风险/低控盘、"
        "或已有明确方向的组合。若原模型为观望，本组合只代表最不差候选，不代表强烈下注。"
    )
    return asdict(DailyPick(
        tier="fallback_safe",
        tier_label="保底候选",
        parlay_type=PARLAY_LABEL,
        legs=[asdict(leg) for leg in legs],
        combined_odds=combined,
        reason=reason,
        score=round(score, 1),
    ))


def _score_parlay_pair(a: dict, b: dict, score_key: str, tier_id: str) -> float:
    """Score a 2-leg parlay for the given tier."""
    sa, sb = a[score_key], b[score_key]
    base = (sa + sb) / 2

    for leg in (a, b):
        note = leg.get("model_note") or ""
        if "一致" in note:
            base += 2

    combined = _combined_odds([a, b])
    if tier_id == "safe":
        if combined and combined < 3.5:
            base += 4
        elif combined and combined < 5.0:
            base += 2
        elif combined and combined > 7.0:
            base -= 5
        for leg in (a, b):
            if leg.get("confidence_cn") == "高":
                base += 1.5
    elif tier_id == "balanced":
        if combined and 2.5 <= combined <= 8.0:
            base += 3
        elif combined and combined > 12.0:
            base -= 2
    elif tier_id == "upset":
        if combined and combined >= 5.0:
            base += min(6.0, (combined - 3.0) * 0.8)
        if combined and combined >= 8.0:
            base += 2

    return base


def _pick_best_parlay(
    candidates: list[dict],
    score_key: str,
    tier_id: str,
    exclude_fids: set[str],
    *,
    min_score: float,
) -> tuple[list[dict], float] | None:
    pool = [c for c in candidates if c["fixture_id"] not in exclude_fids]
    if len(pool) < PARLAY_SIZE:
        pool = candidates
    if len(pool) < PARLAY_SIZE:
        return None

    best_legs: list[dict] | None = None
    best_score = -1.0
    for a, b in combinations(pool, PARLAY_SIZE):
        s = _score_parlay_pair(a, b, score_key, tier_id)
        if s > best_score and s >= min_score:
            best_score = s
            best_legs = [a, b]

    if not best_legs:
        return None
    return best_legs, best_score


def _legs_from_candidates(items: list[dict]) -> list[ParlayLeg]:
    return [
        ParlayLeg(
            fixture_id=c["fixture_id"],
            match=c["match"],
            kickoff=c["kickoff"],
            pick_cn=c["pick_cn"],
            scores=c["scores"],
            asian_handicap_cn=c["asian_handicap_cn"],
            confidence_cn=c["confidence_cn"],
            eu_odds=c.get("eu_odds"),
            reason=c.get("reason") or "",
            model_note=c.get("model_note") or "",
            market_pattern_summary=c.get("market_pattern_summary") or "",
        )
        for c in items
    ]


def _parlay_summary(legs: list[ParlayLeg], combined: float | None) -> str:
    picks = " × ".join(f"{leg.match} {leg.pick_cn}" for leg in legs)
    if combined:
        return f"{PARLAY_LABEL}：{picks} · 组合赔率约 {combined:.2f}"
    return f"{PARLAY_LABEL}：{picks}"


def build_daily_picks(
    matches: list[dict],
    *,
    match_date: str | None = None,
    kickoff_map: dict[str, datetime] | None = None,
) -> dict[str, Any]:
    """Build 稳健/折中/博冷门 for one calendar match day."""
    today = now_beijing().date().isoformat()
    kickoff_map = kickoff_map or load_kickoff_map()

    available_dates = sorted({
        d for m in matches
        if (d := _kickoff_date(m, kickoff_map))
    })

    target = match_date or today
    if match_date is None and target not in available_dates and available_dates:
        future = [d for d in available_dates if d >= today]
        target = future[0] if future else available_dates[-1]

    day_matches = [
        m for m in matches
        if _kickoff_date(m, kickoff_map) == target
    ]
    all_actionable = [
        c for m in day_matches
        if (c := _build_candidate(m, kickoff_map))
    ]
    floor_candidates = [
        c for m in day_matches
        if (c := _build_floor_candidate(m, kickoff_map))
    ]
    candidates, mkt = _select_daily_candidates(all_actionable)
    sp_count = mkt["sp_count"]
    rqsp_count = mkt["rqsp_total"]
    rqsp_eligible = mkt["rqsp_eligible"]

    result: dict[str, Any] = {
        "date": target,
        "generated_at": now_beijing_str(),
        "match_count": len(day_matches),
        "actionable_count": len(candidates),
        "sp_actionable_count": sp_count,
        "rqsp_actionable_count": rqsp_count,
        "rqsp_eligible_count": rqsp_eligible,
        "pick_policy": "胜平负优先，极高置信让球可入选",
        "available_dates": available_dates,
        "tiers": {},
        "fallback_safe": _build_floor_safe_parlay(floor_candidates, target=target),
        "source": "rules",
    }
    if result["fallback_safe"]:
        result["fallback_safe_note"] = "保底候选仅用于当正常推荐偏少/观望较多时参考，建议小仓位。"
    if rqsp_count and rqsp_eligible == 0:
        result["pick_policy_note"] = (
            f"优先胜平负（{sp_count} 场）；"
            f"{rqsp_count} 场仅让球未达「高置信+一致/正EV」门槛，未纳入"
        )
    elif rqsp_eligible:
        result["pick_policy_note"] = (
            f"胜平负 {sp_count} 场 + 极高置信让球 {rqsp_eligible} 场"
            f"（另有 {rqsp_count - rqsp_eligible} 场让球未入选）"
        )

    if not candidates:
        if sp_count == 0 and rqsp_count and rqsp_eligible == 0:
            result["message"] = (
                f"{target} 无胜平负推荐，"
                f"{rqsp_count} 场让球均未达极高置信门槛"
            )
        else:
            result["message"] = f"{target} 暂无可用竞彩推荐（未开售或均为观望）"
        return result

    if len(candidates) < PARLAY_SIZE:
        if sp_count < PARLAY_SIZE and rqsp_eligible == 0 and rqsp_count:
            result["message"] = (
                f"{target} 胜平负可推荐 {sp_count} 场，"
                f"{rqsp_count} 场让球未达极高置信，暂无法组成 {PARLAY_LABEL}"
            )
        else:
            result["message"] = (
                f"{target} 可推荐场次不足 {PARLAY_SIZE} 场，暂无法组成 {PARLAY_LABEL}"
            )
        return result

    tiers_spec = (
        ("safe", "稳健", "safe_score", 7.0),
        ("balanced", "折中", "balanced_score", 5.0),
        ("upset", "博冷门", "upset_score", 4.0),
    )
    used: set[str] = set()
    for tier_id, tier_label, score_key, min_score in tiers_spec:
        picked = _pick_best_parlay(
            candidates, score_key, tier_id, used, min_score=min_score,
        )
        if not picked:
            result["tiers"][tier_id] = None
            continue
        leg_dicts, pair_score = picked
        legs = _legs_from_candidates(leg_dicts)
        combined = _combined_odds(leg_dicts)
        for leg in leg_dicts:
            used.add(leg["fixture_id"])
        result["tiers"][tier_id] = asdict(DailyPick(
            tier=tier_id,
            tier_label=tier_label,
            parlay_type=PARLAY_LABEL,
            legs=[asdict(leg) for leg in legs],
            combined_odds=combined,
            reason=_parlay_summary(legs, combined),
            score=round(pair_score, 1),
        ))

    return result


def daily_tier_to_parlay_analysis(tier: dict, *, generated_at: str = "") -> dict[str, Any]:
    """Adapt a daily pick tier to the existing parlay share-card schema."""
    legs = []
    for leg in tier.get("legs") or []:
        item = dict(leg)
        if item.get("odds_used") is None:
            item["odds_used"] = item.get("eu_odds")
        item.setdefault("jingcai_market", "sp")
        legs.append(item)

    combined = tier.get("combined_odds")
    warnings = ["保底候选不是强推荐，建议小仓位"] if tier.get("tier") == "fallback_safe" else []
    if any((leg.get("confidence_cn") == "低") for leg in legs):
        warnings.append("含低置信场次")
    if any((leg.get("jingcai_market") == "rqsp") for leg in legs):
        warnings.append("含让球玩法，净胜球敏感")

    verdict = "可小串" if tier.get("tier") == "fallback_safe" else (tier.get("tier_label") or "可串")
    verdict_detail = (
        "同日可购买场次中的最保守候选，适合小仓位参考"
        if tier.get("tier") == "fallback_safe"
        else tier.get("reason") or ""
    )
    explanation = {
        "headline": verdict_detail,
        "reasons": [
            "优先同日比赛，避免跨日信息差",
            "优先胜平负与低赔率区间，降低串关波动",
            "若模型原本观望，仅代表保底候选而非强推",
        ],
        "leg_reasons": [
            {
                "match": leg.get("match"),
                "pick_cn": leg.get("pick_cn"),
                "text": "；".join(
                    x for x in [
                        f"推荐 {leg.get('pick_cn')}",
                        f"置信 {leg.get('confidence_cn')}",
                        f"参考比分 {leg.get('scores')}" if leg.get("scores") else "",
                        f"欧亚转换：{leg.get('market_pattern_summary')}" if leg.get("market_pattern_summary") else "",
                        leg.get("reason") or leg.get("model_note") or "",
                    ] if x
                ),
            }
            for leg in legs
        ],
        "stake_advice": "保底候选也有串关风险，建议小仓位，不追注。",
        "paragraph": tier.get("reason") or verdict_detail,
    }
    return {
        "ok": True,
        "generated_at": generated_at or now_beijing_str(),
        "parlay_type": tier.get("parlay_type") or PARLAY_LABEL,
        "legs": legs,
        "combined_odds": combined,
        "implied_win_pct": round(100 / combined, 1) if combined and combined > 1 else None,
        "payout_per_100": round(combined * 100, 0) if combined else None,
        "verdict": verdict,
        "verdict_detail": verdict_detail,
        "warnings": warnings,
        "blockers": [],
        "summary": tier.get("reason") or _parlay_summary(_legs_from_candidates(legs), combined),
        "explanation": explanation,
        "source": "daily_fallback",
    }


def load_daily_picks_from_output(output_root: str | Path, match_date: str | None = None) -> dict[str, Any]:
    root = Path(output_root)
    today = now_beijing().date().isoformat()

    matches: list[dict] = []
    latest_path = root / "latest.json"
    if latest_path.is_file():
        try:
            data = json.loads(latest_path.read_text(encoding="utf-8"))
            matches = data.get("matches") or []
        except json.JSONDecodeError:
            pass

    kickoff_map = load_kickoff_map()
    available_dates = sorted({
        d for m in matches if (d := _kickoff_date(m, kickoff_map))
    })
    target = match_date or today
    if match_date is None and target not in available_dates and available_dates:
        future = [d for d in available_dates if d >= today]
        target = future[0] if future else available_dates[-1]

    saved = root / "daily_picks" / f"{target}.json"
    if saved.is_file():
        try:
            payload = json.loads(saved.read_text(encoding="utf-8"))
            if payload.get("date") == target and (
                payload.get("tiers") is not None
                or payload.get("message")
                or payload.get("ai_run_at")
            ):
                if not payload.get("fallback_safe") and matches:
                    fresh = build_daily_picks(matches, match_date=target, kickoff_map=kickoff_map)
                    payload["fallback_safe"] = fresh.get("fallback_safe")
                    if fresh.get("fallback_safe_note"):
                        payload["fallback_safe_note"] = fresh["fallback_safe_note"]
                return payload
        except json.JSONDecodeError:
            pass

    return build_daily_picks(matches, match_date=match_date, kickoff_map=kickoff_map)


def save_daily_picks(output_root: str | Path, payload: dict) -> Path:
    root = Path(output_root)
    out_dir = root / "daily_picks"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{payload['date']}.json"

    if path.is_file() and payload.get("source") != "ai":
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            if old.get("source") == "ai":
                log.debug("保留 AI 三档推荐，跳过规则引擎覆盖 %s", path.name)
                return path
        except json.JSONDecodeError:
            pass

    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
