"""Lightweight tactical style proxy + clash variance (low weight, precaution only)."""

from __future__ import annotations

from typing import Any

import config as app_cfg

STYLE_ATTACK = "attack"
STYLE_BALANCED = "balanced"
STYLE_DEFENSIVE = "defensive"
STYLE_UNKNOWN = "unknown"

STYLE_CN = {
    STYLE_ATTACK: "进攻型",
    STYLE_BALANCED: "均衡型",
    STYLE_DEFENSIVE: "防守型",
    STYLE_UNKNOWN: "数据不足",
}

VARIANCE_LOW = "low"
VARIANCE_MEDIUM = "medium"
VARIANCE_HIGH = "high"

VARIANCE_CN = {
    VARIANCE_LOW: "低",
    VARIANCE_MEDIUM: "中",
    VARIANCE_HIGH: "偏高",
}


def _min_matches() -> int:
    return getattr(app_cfg, "STYLE_CLASH_MIN_MATCHES", 3)


def _style_metrics(matches: list[dict]) -> dict[str, Any]:
    n = len(matches)
    if not n:
        return {"n": 0}
    gf = sum(m.get("goals_for") or 0 for m in matches)
    ga = sum(m.get("goals_against") or 0 for m in matches)
    totals = [(m.get("goals_for") or 0) + (m.get("goals_against") or 0) for m in matches]
    low_score = sum(1 for t in totals if t <= 2)
    high_attack = sum(1 for m in matches if (m.get("goals_for") or 0) >= 2)
    clean_sheet = sum(1 for m in matches if (m.get("goals_against") or 0) == 0)
    return {
        "n": n,
        "avg_gf": round(gf / n, 2),
        "avg_ga": round(ga / n, 2),
        "avg_total": round(sum(totals) / n, 2),
        "low_score_rate": round(low_score / n, 2),
        "high_attack_rate": round(high_attack / n, 2),
        "clean_sheet_rate": round(clean_sheet / n, 2),
    }


def infer_team_style(team_block: dict[str, Any]) -> dict[str, Any]:
    """Proxy style from recent int'l results (not true tactical tracking)."""
    matches = team_block.get("recent_matches") or []
    team = team_block.get("team") or "—"
    metrics = _style_metrics(matches)
    n = metrics.get("n", 0)
    if n < _min_matches():
        return {
            "team": team,
            "style": STYLE_UNKNOWN,
            "style_cn": STYLE_CN[STYLE_UNKNOWN],
            "confidence": "低",
            "metrics": metrics,
            "reason": f"近场仅{n}场，样本不足",
        }

    avg_gf = metrics["avg_gf"]
    avg_ga = metrics["avg_ga"]
    avg_total = metrics["avg_total"]
    low_rate = metrics["low_score_rate"]
    attack_rate = metrics["high_attack_rate"]

    if avg_gf >= 1.55 and avg_total >= 2.6 and avg_ga <= 1.35:
        style = STYLE_ATTACK
        reason = f"场均进{avg_gf}球、总{avg_total}球，进攻输出偏高"
    elif avg_ga <= 0.95 and (low_rate >= 0.45 or avg_gf <= 1.35):
        style = STYLE_DEFENSIVE
        reason = f"场均失{avg_ga}球，小比分占比{int(low_rate * 100)}%，偏低位防守"
    elif attack_rate >= 0.45 and avg_gf >= 1.35:
        style = STYLE_ATTACK
        reason = f"多场进球≥2，场均进{avg_gf}球，偏主动进攻"
    else:
        style = STYLE_BALANCED
        reason = f"进失球居中（进{avg_gf}/失{avg_ga}），风格较均衡"

    return {
        "team": team,
        "style": style,
        "style_cn": STYLE_CN[style],
        "confidence": "中",
        "metrics": metrics,
        "reason": reason,
    }


def _clash_pair(home_style: str, away_style: str) -> dict[str, Any]:
    """Lookup clash narrative; symmetric for reversed attack/defensive."""
    key = (home_style, away_style)
    rev = (away_style, home_style)

    rules: dict[tuple[str, str], dict] = {
        (STYLE_ATTACK, STYLE_DEFENSIVE): {
            "variance_level": VARIANCE_HIGH,
            "headline": "高压进攻 × 低位防反，热门破局难、冷门变数偏高",
            "detail": "进攻方需持续压制并破门，防守方可收缩打反击；热门若久攻不下易被偷反击。",
            "watch": "防反冷门、小比分客胜/平局",
            "favors_underdog_side": "away",
        },
        (STYLE_DEFENSIVE, STYLE_ATTACK): {
            "variance_level": VARIANCE_HIGH,
            "headline": "低位防守 × 对手高压，主队防反存在偷分空间",
            "detail": "主队收缩时，客队压上留身后空档；若热门是客队，需防被反击。",
            "watch": "主胜/平局冷门",
            "favors_underdog_side": "home",
        },
        (STYLE_ATTACK, STYLE_ATTACK): {
            "variance_level": VARIANCE_MEDIUM,
            "headline": "对攻局，进球波动大但方向仍可能清晰",
            "detail": "双方均偏进攻，场面开放；热门仍占优，但比分分布更散。",
            "watch": "大比分或逆转",
            "favors_underdog_side": None,
        },
        (STYLE_DEFENSIVE, STYLE_DEFENSIVE): {
            "variance_level": VARIANCE_MEDIUM,
            "headline": "双防守型，破局难，平局与小冷门需防",
            "detail": "双方均偏保守，节奏慢、进球少；低赔热门小胜或平局概率上升。",
            "watch": "平局、1-0/0-1",
            "favors_underdog_side": None,
        },
        (STYLE_ATTACK, STYLE_BALANCED): {
            "variance_level": VARIANCE_LOW,
            "headline": "进攻方对均衡队，风格冲突有限",
            "detail": "一方偏攻一方居中，变数一般，仍看实力与盘口。",
            "watch": "—",
            "favors_underdog_side": None,
        },
        (STYLE_BALANCED, STYLE_ATTACK): {
            "variance_level": VARIANCE_LOW,
            "headline": "均衡队遇进攻型，变数一般",
            "detail": "风格冲突不明显，以盘口与样本为主。",
            "watch": "—",
            "favors_underdog_side": None,
        },
        (STYLE_DEFENSIVE, STYLE_BALANCED): {
            "variance_level": VARIANCE_MEDIUM,
            "headline": "防守型遇均衡队，节奏偏慢、小比分概率升",
            "detail": "防守方可能拖慢节奏；热门需耐心破密集。",
            "watch": "小比分、平局",
            "favors_underdog_side": None,
        },
        (STYLE_BALANCED, STYLE_DEFENSIVE): {
            "variance_level": VARIANCE_MEDIUM,
            "headline": "均衡队遇低位防守，热门需防久攻不下",
            "detail": "对手收缩时，热门控球多但转化率是关键。",
            "watch": "平局、防反",
            "favors_underdog_side": "away",
        },
        (STYLE_BALANCED, STYLE_BALANCED): {
            "variance_level": VARIANCE_LOW,
            "headline": "双方风格均衡，战术变数低",
            "detail": "无显著球风相克，参考盘口与历史样本即可。",
            "watch": "—",
            "favors_underdog_side": None,
        },
    }

    if key in rules:
        return rules[key]
    if rev in rules:
        r = dict(rules[rev])
        fav = r.get("favors_underdog_side")
        if fav == "home":
            r["favors_underdog_side"] = "away"
        elif fav == "away":
            r["favors_underdog_side"] = "home"
        return r

    return {
        "variance_level": VARIANCE_LOW,
        "headline": "风格样本不足或无明显相克",
        "detail": "战术变数权重低，不作主要依据。",
        "watch": "—",
        "favors_underdog_side": None,
    }


def _score_adjustment(variance_level: str) -> dict[str, float]:
    """Small nudges for daily_picks — intentionally light."""
    if variance_level == VARIANCE_HIGH:
        return {
            "upset_boost": getattr(app_cfg, "STYLE_CLASH_UPSET_BOOST", 2.0),
            "safe_penalty": getattr(app_cfg, "STYLE_CLASH_SAFE_PENALTY", 1.0),
        }
    if variance_level == VARIANCE_MEDIUM:
        base_u = getattr(app_cfg, "STYLE_CLASH_UPSET_BOOST", 2.0)
        base_s = getattr(app_cfg, "STYLE_CLASH_SAFE_PENALTY", 1.0)
        return {"upset_boost": base_u * 0.5, "safe_penalty": base_s * 0.5}
    return {"upset_boost": 0.0, "safe_penalty": 0.0}


def analyze_style_clash(
    home_style: dict[str, Any],
    away_style: dict[str, Any],
    *,
    market_favorite: str | None = None,
) -> dict[str, Any]:
    """Combine two team style profiles into a precautionary clash note."""
    hs = home_style.get("style") or STYLE_UNKNOWN
    aws = away_style.get("style") or STYLE_UNKNOWN
    if hs == STYLE_UNKNOWN or aws == STYLE_UNKNOWN:
        return {
            "available": False,
            "variance_level": VARIANCE_LOW,
            "variance_cn": VARIANCE_CN[VARIANCE_LOW],
            "headline": "战术风格样本不足，不作相克判断",
            "detail": f"需至少各队近{_min_matches()}场国际赛记录。",
            "home_style": home_style,
            "away_style": away_style,
            "note": "代理指标：进失球/小比分率，非真实压迫/防线数据",
        }

    pair = _clash_pair(hs, aws)
    level = pair["variance_level"]
    score_adj = _score_adjustment(level)

    return {
        "available": True,
        "variance_level": level,
        "variance_cn": VARIANCE_CN[level],
        "headline": pair["headline"],
        "detail": pair["detail"],
        "watch": pair.get("watch") or "—",
        "favors_underdog_side": pair.get("favors_underdog_side"),
        "market_favorite": market_favorite,
        "home_style": home_style,
        "away_style": away_style,
        "score_adjustment": score_adj,
        "summary": (
            f"{home_style.get('team')}（{home_style.get('style_cn')}）vs "
            f"{away_style.get('team')}（{away_style.get('style_cn')}）· "
            f"变数{VARIANCE_CN[level]}：{pair['headline']}"
        ),
        "note": "轻量代理（进失球/小比分），权重低，仅防一手；非 Opta 战术数据",
    }


def build_style_clash_from_form(
    form: dict[str, Any],
    *,
    market_favorite: str | None = None,
) -> dict[str, Any]:
    home = infer_team_style(form.get("home") or {})
    away = infer_team_style(form.get("away") or {})
    return analyze_style_clash(home, away, market_favorite=market_favorite)


def build_style_clash_from_match(
    match_name: str,
    *,
    market_favorite: str | None = None,
) -> dict[str, Any]:
    from team_recent_form import build_team_recent_form_from_match

    form = build_team_recent_form_from_match(match_name or "")
    return build_style_clash_from_form(form, market_favorite=market_favorite)


def style_clash_for_match(m: dict) -> dict[str, Any]:
    """Cached-style helper for scoring pipelines."""
    cached = m.get("style_clash")
    if cached:
        return cached
    name = m.get("match") or (m.get("predict_row") or {}).get("比赛") or ""
    fav = None
    eu_h = m.get("eu_home") or (m.get("predict_row") or {}).get("欧赔主")
    eu_a = m.get("eu_away") or (m.get("predict_row") or {}).get("欧赔客")
    try:
        if eu_h and eu_a and float(eu_h) < float(eu_a):
            fav = "home"
        elif eu_h and eu_a and float(eu_a) < float(eu_h):
            fav = "away"
    except (TypeError, ValueError):
        pass
    clash = build_style_clash_from_match(name, market_favorite=fav)
    m["style_clash"] = clash
    return clash


def clash_headline(clash: dict[str, Any]) -> str:
    if not clash.get("available"):
        return clash.get("headline") or ""
    return clash.get("summary") or clash.get("headline") or ""
