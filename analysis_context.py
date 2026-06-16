"""Pre-compute rich analysis context for DeepSeek prompts."""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path

import config as app_cfg
import logging

log = logging.getLogger(__name__)

from eu_implied_metrics import compute_eu_implied
from market_control import LEVEL_CN, analyze_control
from odds_signals import build_market_signals
from trap_signals import analyze_traps
from recommend import MIN_SAMPLES_FOR_PICK, build_recommendation, recommendation_to_baseline


RESULT_CN = {"home": "主胜", "draw": "平", "away": "客胜"}


def _implied_probs(h, d, a) -> dict | None:
    m = compute_eu_implied(h, d, a)
    if not m:
        return None
    return {
        "home": m.fair_home_pct / 100.0,
        "draw": m.fair_draw_pct / 100.0,
        "away": m.fair_away_pct / 100.0,
    }


def _pct(v) -> str:
    if v is None:
        return "n/a"
    return f"{round(v * 100, 1)}%"


def _score_line(row: dict) -> str:
    return f"{row.get('home')} {row.get('score_h')}-{row.get('score_a')} {row.get('away')}"


def _analyze_samples(samples: list[dict], limit: int = 5, *, pool: dict | None = None) -> dict:
    if not samples and not pool:
        return {"highlights": [], "result_counts": {}, "score_top": [], "avg_goals": None}

    highlights = []
    for s in samples[:limit]:
        highlights.append({
            "date": s.get("date"),
            "match": _score_line(s),
            "result": RESULT_CN.get(s.get("result_1x2"), s.get("result_1x2")),
            "ah_line": s.get("ah_line"),
            "eu_home": s.get("eu_home"),
            "source": s.get("source"),
            "ah_home_result": s.get("ah_home_result"),
            "similarity_dist": s.get("similarity_dist"),
        })

    out = {
        "highlights": highlights,
        "display_count": len(highlights),
        "full_pool_count": (pool or {}).get("count", len(samples)),
    }
    if pool and pool.get("count"):
        out["score_top"] = pool.get("score_top") or []
        out["score_top_by_result"] = pool.get("score_top_by_result") or {}
        out["result_counts"] = {
            "主胜": round((pool.get("home_win_rate") or 0) * pool["count"]),
            "平": round((pool.get("draw_rate") or 0) * pool["count"]),
            "客胜": round((pool.get("away_win_rate") or 0) * pool["count"]),
        }
        out["avg_goals"] = pool.get("avg_total_goals")
    else:
        results = Counter(s.get("result_1x2") for s in samples)
        scores = Counter(f"{s.get('score_h')}-{s.get('score_a')}" for s in samples)
        total_goals = [(s.get("score_h") or 0) + (s.get("score_a") or 0) for s in samples]
        out["result_counts"] = {RESULT_CN.get(k, k): v for k, v in results.items()}
        out["score_top"] = [{"score": sc, "count": cnt} for sc, cnt in scores.most_common(8)]
        out["avg_goals"] = sum(total_goals) / len(total_goals) if total_goals else None
    return out


def build_analysis_context(payload: dict, *, baseline: dict | None = None) -> dict:
    cur = payload["current"]
    stats = payload["stats"]
    eu = payload["eu_stats"]
    open_stats = payload.get("open_stats") or stats
    open_eu = payload.get("open_eu_stats") or eu
    control = analyze_control(cur)
    trap = analyze_traps(cur, intensity=control.intensity, level=control.level)
    mp = trap.market_patterns
    baseline_ref = baseline or recommendation_to_baseline(build_recommendation(payload))

    market = _implied_probs(cur.get("eu_home"), cur.get("eu_draw"), cur.get("eu_away"))
    market_open = _implied_probs(
        cur.get("eu_open_home"), cur.get("eu_open_draw"), cur.get("eu_open_away")
    )
    eu_imp_live = compute_eu_implied(cur.get("eu_home"), cur.get("eu_draw"), cur.get("eu_away"))
    eu_imp_open = compute_eu_implied(
        cur.get("eu_open_home"), cur.get("eu_open_draw"), cur.get("eu_open_away"),
    )

    def _hist_block(s, label):
        return {
            "label": label,
            "sample_count": s.get("count", 0),
            "home_win_rate": s.get("home_win_rate"),
            "draw_rate": s.get("draw_rate"),
            "away_win_rate": s.get("away_win_rate"),
            "ah_upper_win_rate": None if s.get("ah_home_net") is None else (s["ah_home_net"] + 1) / 2,
            "ah_lower_win_rate": None if s.get("ah_away_net") is None else (s["ah_away_net"] + 1) / 2,
            "avg_total_goals": s.get("avg_total_goals"),
        }

    hist_open_ah = _hist_block(open_stats, "初盘亚盘相似（赛事本身，优先）")
    hist_open_eu = _hist_block(open_eu, "初盘欧赔扩展")
    hist_live_ah = _hist_block(stats, "临盘亚盘相似（含控盘后）")
    hist_live_eu = _hist_block(eu, "临盘欧赔扩展")

    market_vs_history = {}
    if (open_stats.get("count") or 0) >= MIN_SAMPLES_FOR_PICK and (open_eu.get("count") or 0) >= MIN_SAMPLES_FOR_PICK:
        ah_w = math.sqrt(open_stats.get("count") or 0)
        eu_w = min(
            math.sqrt(open_eu.get("count") or 0),
            ah_w * app_cfg.HIST_EU_BLEND_MAX_WEIGHT_RATIO,
        )
        total_w = ah_w + eu_w
        ref_hist = {
            **hist_open_ah,
            "label": "初盘亚盘+欧赔融合",
            "sample_count": f"{open_stats.get('count')}/{open_eu.get('count')}",
            "home_win_rate": (
                (hist_open_ah.get("home_win_rate") or 0) * ah_w
                + (hist_open_eu.get("home_win_rate") or 0) * eu_w
            ) / total_w,
            "draw_rate": (
                (hist_open_ah.get("draw_rate") or 0) * ah_w
                + (hist_open_eu.get("draw_rate") or 0) * eu_w
            ) / total_w,
            "away_win_rate": (
                (hist_open_ah.get("away_win_rate") or 0) * ah_w
                + (hist_open_eu.get("away_win_rate") or 0) * eu_w
            ) / total_w,
        }
    else:
        ref_hist = hist_open_ah if (open_stats.get("count") or 0) >= MIN_SAMPLES_FOR_PICK else hist_open_eu
    ref_market = market_open or market
    if ref_market and ref_hist.get("home_win_rate") is not None:
        mapping = [("主胜", "home", "home_win_rate"), ("平局", "draw", "draw_rate"), ("客胜", "away", "away_win_rate")]
        for label, mkey, hkey in mapping:
            m = ref_market[mkey]
            h = ref_hist.get(hkey)
            if h is not None:
                gap = h - m
                if gap > 0.03:
                    interp = "初盘历史高于市场，该结果被低估"
                elif gap < -0.03:
                    interp = "初盘历史低于市场，该结果被高估"
                else:
                    interp = "初盘历史与市场接近"
                market_vs_history[label] = {
                    "market_implied": round(m, 4),
                    "historical_rate": round(h, 4),
                    "gap": round(gap, 4),
                    "interpretation": interp,
                }

    baseline_ev = {}
    baseline_pick_cn = baseline_ref.get("result_1x2_cn")
    gap_key = {"主胜": "主胜", "平局": "平局", "客胜": "客胜"}.get(baseline_pick_cn or "")
    if gap_key and gap_key in market_vs_history:
        g = market_vs_history[gap_key]
        edge = g.get("gap")
        baseline_ev = {
            "pick": baseline_pick_cn,
            "market_implied_probability": g.get("market_implied"),
            "historical_adjusted_probability": g.get("historical_rate"),
            "edge": edge,
            "edge_pp": round((edge or 0) * 100, 1),
            "value_hint": "positive" if (edge or 0) > 0.03 else (
                "negative" if (edge or 0) < -0.03 else "thin"
            ),
            "note": g.get("interpretation"),
        }

    line_move = {}
    if cur.get("ah_open_line") is not None and cur.get("ah_line") is not None:
        delta = cur["ah_line"] - cur["ah_open_line"]
        if delta < 0:
            direction = "升盘（主队让球加深）"
        elif delta > 0:
            direction = "降盘（主队让球变浅）"
        else:
            direction = "盘口未变"
        line_move = {
            "open_line": cur.get("ah_open_line"),
            "live_line": cur.get("ah_line"),
            "direction": direction,
            "open_water": [cur.get("ah_open_home_water"), cur.get("ah_open_away_water")],
            "live_water": [cur.get("ah_home_water"), cur.get("ah_away_water")],
        }

    eu_move = {}
    if cur.get("eu_open_home") and cur.get("eu_home"):
        eu_move = {
            "home": f"{cur['eu_open_home']} -> {cur['eu_home']}",
            "draw": f"{cur.get('eu_open_draw')} -> {cur.get('eu_draw')}",
            "away": f"{cur.get('eu_open_away')} -> {cur.get('eu_away')}",
        }

    sig = build_market_signals(cur)

    ctx = {
        "match_name": cur.get("match_name"),
        "baseline_recommendation": baseline_ref,
        "control_analysis": {
            "level": control.level,
            "level_cn": LEVEL_CN[control.level],
            "pattern_weight": control.pattern_weight,
            "trajectory": control.trajectory_tag,
            "payout_pressure_note": control.payout_pressure_note,
            "notes": control.notes,
        },
        "trap_analysis": {
            "penalties": trap.penalties,
            "flagged_direction": trap.flagged_direction,
            "draw_steam": trap.draw_steam,
            "notes": trap.notes,
        },
        "market_patterns": {
            "eu_to_ah_line": getattr(mp, "eu_to_ah_line", None) if mp else None,
            "ah_to_eu_sketch": getattr(mp, "ah_to_eu_sketch", None) if mp else None,
            "ah_line_live": getattr(mp, "ah_line_live", None) if mp else None,
            "line_gap": getattr(mp, "line_gap", None) if mp else None,
            "consistency": getattr(mp, "consistency", None) if mp else None,
            "conversion_summary": getattr(mp, "conversion_summary", "") if mp else "",
            "patterns": getattr(mp, "patterns", []) if mp else [],
            "routine_notes": getattr(mp, "routine_notes", []) if mp else [],
        },
        "market_signals": {
            "line_summary": sig.line_summary,
            "water_summary": sig.water_summary,
            "eu_summary": sig.eu_summary,
            "bias_1x2": sig.bias_1x2,
            "ah_side_bias": sig.ah_side_bias,
            "notes": sig.notes,
        },
        "current_odds": {
            "asian_handicap_open": {
                "line": cur.get("ah_open_line"),
                "home_water": cur.get("ah_open_home_water"),
                "away_water": cur.get("ah_open_away_water"),
            },
            "asian_handicap_live": {
                "line": cur.get("ah_line"),
                "home_water": cur.get("ah_home_water"),
                "away_water": cur.get("ah_away_water"),
            },
            "european_open": {
                "home": cur.get("eu_open_home"),
                "draw": cur.get("eu_open_draw"),
                "away": cur.get("eu_open_away"),
            },
            "european_live": {
                "home": cur.get("eu_home"),
                "draw": cur.get("eu_draw"),
                "away": cur.get("eu_away"),
            },
            "bookmaker": cur.get("bookmaker"),
        },
        "odds_movement": {"asian": line_move, "european": eu_move},
        "market_implied_probability": market,
        "market_open_implied_probability": market_open,
        "eu_implied_live": eu_imp_live.to_dict() if eu_imp_live else None,
        "eu_implied_open": eu_imp_open.to_dict() if eu_imp_open else None,
        "precomputed_ev": {
            "probability_source": "code_precomputed_from_eu_fair_probability_and_open_history",
            "threshold_positive_edge": 0.03,
            "baseline": baseline_ev,
            "all_outcomes": market_vs_history,
        },
        "historical_open_asian": hist_open_ah,
        "historical_open_eu": hist_open_eu,
        "historical_live_asian": hist_live_ah,
        "historical_live_eu": hist_live_eu,
        "market_vs_history_gap": market_vs_history,
        "open_asian_sample_analysis": _analyze_samples(open_stats.get("samples") or [], 5, pool=open_stats),
        "open_eu_sample_analysis": _analyze_samples(open_eu.get("samples") or [], 5, pool=open_eu),
        "live_asian_sample_analysis": _analyze_samples(stats.get("samples") or [], 5, pool=stats),
        "live_eu_sample_analysis": _analyze_samples(eu.get("samples") or [], 5, pool=eu),
        "history_total_in_db": payload.get("history_total"),
        "analysis_notes": [
            f"推荐门槛：初盘/临盘相似样本至少 {MIN_SAMPLES_FOR_PICK} 场",
            "第一层：historical_open_* = 初盘相似样本，代表赛事本身概率（主依据）",
            "第二层：market_patterns = 欧转亚/亚转欧对照 + 盘赔套路识别",
            "第三层：trap_analysis + control_analysis = 诱盘惩罚与控盘解读",
            "第四层：baseline_recommendation = 综合结论，AI 必须原样采用",
            "highlights 仅展示最相似几条；score_top 来自全量样本",
        ],
    }
    return attach_team_recent_form(ctx, ctx.get("match_name"))


def attach_team_recent_form(ctx: dict, match_name: str | None = None) -> dict:
    """Attach last-year int'l/qualifier results + odds for both teams."""
    name = match_name or ctx.get("match_name") or ""
    if not name:
        return ctx
    try:
        from team_recent_form import build_team_recent_form_from_match, form_headline
        form = build_team_recent_form_from_match(name)
        ctx["team_recent_form"] = form
        ctx["team_recent_form_headline"] = form_headline(form)
        from style_clash import build_style_clash_from_form, clash_headline
        fav = None
        cur_odds = ctx.get("current_odds") or {}
        eu = cur_odds.get("european_live") or {}
        try:
            eh, ea = eu.get("home"), eu.get("away")
            if eh and ea:
                if float(eh) < float(ea):
                    fav = "home"
                elif float(ea) < float(eh):
                    fav = "away"
        except (TypeError, ValueError):
            pass
        clash = build_style_clash_from_form(form, market_favorite=fav)
        ctx["style_clash"] = clash
        ctx["style_clash_headline"] = clash_headline(clash)
    except Exception as exc:
        log.debug("team_recent_form 跳过: %s", exc)
    return ctx


def attach_tournament_context(ctx: dict, output_root: str | Path) -> dict:
    """Inject current WC opening-characteristics summary for AI / UI."""
    try:
        root = Path(output_root)
        ledger_path = root / "worldcup" / "ledger.json"
        if ledger_path.is_file():
            data = json.loads(ledger_path.read_text(encoding="utf-8"))
            chars = data.get("opening_patterns") or {}
        else:
            from worldcup_analytics import compute_opening_characteristics, load_tournament_records
            chars = compute_opening_characteristics(load_tournament_records(output_root))

        conc = chars.get("conclusions") or {}
        ctx["tournament_opening"] = {
            "sample_size": chars.get("sample_size"),
            "summary": conc.get("headline") or chars.get("summary"),
            "traits": conc.get("actionable") or chars.get("traits") or [],
            "stats": chars.get("stats") or {},
            "cards": conc.get("cards") or [],
        }
    except Exception:
        ctx.setdefault("tournament_opening", {"sample_size": 0, "traits": []})
    return ctx
