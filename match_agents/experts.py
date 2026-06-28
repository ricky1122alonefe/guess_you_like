"""Deterministic expert agents that prepare evidence for the AI chief agent."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .factor_fetch import enrich_match_factors, kickoff_value, parse_match_teams
from .config import agent_weight, load_match_agent_config
from .types import AgentReport

OUTCOME_TO_VERDICT = {"home": "lean_home", "draw": "lean_draw", "away": "lean_away"}


def _safe_float(v) -> float | None:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _pct(v) -> str:
    if v is None:
        return "n/a"
    try:
        return f"{float(v) * 100:.1f}%"
    except (TypeError, ValueError):
        return str(v)


def _odds(pred: dict, index: dict | None = None) -> dict[str, Any]:
    out = dict(pred.get("odds_snapshot") or {})
    timeline = (index or {}).get("timeline") or []
    if timeline:
        for k, v in ((timeline[-1].get("odds") or {}).items()):
            out.setdefault(k, v)
    return out


def _weight(agent_id: str, output_root=None) -> float:
    return agent_weight(agent_id, output_root)


def _match_name(pred: dict, index: dict | None = None) -> str:
    return (
        pred.get("match")
        or (pred.get("predict_row") or {}).get("比赛")
        or (index or {}).get("match_name")
        or ""
    )


def intel_agent(pred: dict, index: dict | None = None, *, output_root=None) -> AgentReport:
    factors = enrich_match_factors(pred, index, output_root=output_root)
    news = factors.get("news") or {}
    fetch_log = factors.get("fetch_log") or []
    evidence: list[str] = []
    warnings: list[str] = []
    raw: dict[str, Any] = {"factors": factors, "fetch_log": fetch_log}

    snippets = news.get("snippets") or []
    if snippets:
        evidence.append(f"情报检索：{news.get('summary') or snippets[0][:80]}")
        for line in snippets[:4]:
            evidence.append(str(line)[:160])
        raw["status"] = "partial"
    elif news.get("summary"):
        evidence.append(f"情报：{news.get('summary')}")
        raw["status"] = "partial"
    else:
        evidence.append("已尝试 500 情报页 + 网页搜索伤停/首发，暂无可靠结构化伤停")
        warnings.append("AI 总 Agent 不得编造未提供的球员、天气、新闻信息")
        raw["status"] = "insufficient_data"

    for line in fetch_log:
        if any(k in line for k in ("500.com", "网页搜索", "情报")):
            evidence.append(f"查询：{line}")

    return AgentReport(
        agent_id="intel",
        name="情报 Agent",
        verdict="neutral",
        confidence=0.45 if news else 0.15,
        risk=0.35 if news else 0.45,
        weight=_weight("intel", output_root),
        evidence=evidence,
        warnings=warnings,
        recommended_action="watch",
        raw=raw,
    )


def _read_factor_source(source: str | None, pred: dict, index: dict | None) -> dict[str, Any] | None:
    if not source:
        return None
    try:
        import json
        from pathlib import Path
        path = Path(source).expanduser()
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[1] / source
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    fid = str(pred.get("fixture_id") or (index or {}).get("fixture_id") or "")
    name = _match_name(pred, index)
    if isinstance(data, dict):
        matches = data.get("matches") if isinstance(data.get("matches"), dict) else data
        if fid and isinstance(matches, dict) and fid in matches:
            return matches[fid]
        if name and isinstance(matches, dict) and name in matches:
            return matches[name]
    return None


def external_context_agent(pred: dict, index: dict | None = None, *, output_root=None) -> AgentReport:
    cfg = load_match_agent_config(output_root)
    ext_cfg = cfg.get("external_factors") or {}
    sources = ext_cfg.get("sources") or {}
    factors = enrich_match_factors(pred, index, output_root=output_root, cfg=cfg)
    fetch_log = factors.get("fetch_log") or []
    evidence: list[str] = []
    warnings: list[str] = []
    raw: dict[str, Any] = {"sources": sources, "fetch_log": fetch_log}
    found: dict[str, Any] = {}

    if ext_cfg.get("enabled", True):
        for key, label in (("news", "新闻/伤停"), ("weather", "天气"), ("venue", "场地/海拔")):
            item = factors.get(key) or {}
            if not item and sources.get(key):
                item = _read_factor_source(sources.get(key), pred, index) or {}
            if item:
                found[key] = item
                if key == "news":
                    summary = item.get("summary") or "已接入伤停/新闻"
                elif key == "weather":
                    summary = item.get("summary") or item.get("condition") or "已接入天气"
                    temp = item.get("temperature_c")
                    if temp is not None:
                        summary = f"{summary} · {temp}°C"
                elif key == "venue":
                    name = item.get("stadium") or item.get("venue") or item.get("name") or "球场"
                    city = item.get("city") or ""
                    alt = item.get("altitude_m")
                    summary = name + (f" · {city}" if city else "")
                    if alt is not None:
                        summary += f" · 海拔{alt}m"
                else:
                    summary = item.get("summary") if isinstance(item, dict) else str(item)
                src = item.get("source") or "unknown"
                evidence.append(f"{label}（{src}）：{summary or '已接入数据'}")

    for line in fetch_log[:6]:
        evidence.append(f"数据查询：{line}")

    if not found:
        evidence.append("外部因素仍不完整；已执行 catalog / API 自动查询")
        warnings.append("总 Agent 不得臆测伤停、天气、海拔或场地条件")
        raw["status"] = factors.get("status") or "insufficient_data"
    else:
        raw["status"] = "available" if factors.get("status") == "available" else "partial"
        raw["factors"] = found
    return AgentReport(
        agent_id="external_context",
        name="外部因素 Agent",
        verdict="neutral",
        confidence=0.6 if len(found) >= 2 else (0.5 if found else 0.15),
        risk=0.3 if len(found) >= 2 else (0.4 if found else 0.45),
        weight=_weight("external_context", output_root),
        evidence=evidence,
        warnings=warnings,
        recommended_action="watch",
        raw=raw,
    )


def _kickoff_value(pred: dict, index: dict | None = None) -> str:
    return kickoff_value(pred, index)


def schedule_venue_agent(pred: dict, index: dict | None = None, *, output_root=None) -> AgentReport:
    cfg = load_match_agent_config(output_root)
    factors = enrich_match_factors(pred, index, output_root=output_root, cfg=cfg)
    schedule = factors.get("schedule") or {}
    venue = factors.get("venue") or {}
    weather = factors.get("weather") or {}
    fetch_log = factors.get("fetch_log") or []
    kickoff = schedule.get("kickoff_at") or _kickoff_value(pred, index)
    evidence: list[str] = []
    warnings: list[str] = []
    raw = {"schedule": schedule, "venue": venue, "weather": weather, "fetch_log": fetch_log}
    risk = 0.35
    confidence = 0.25

    if kickoff:
        evidence.append(f"开球时间：{kickoff}")
        confidence = max(confidence, 0.45)
    else:
        warnings.append("缺少开球时间，无法判断赛前窗口、当地气候和旅途影响")
        risk = max(risk, 0.7)

    if isinstance(venue, dict) and venue:
        name = venue.get("stadium") or venue.get("venue") or venue.get("name") or "未知球场"
        city = venue.get("city") or venue.get("location") or ""
        altitude = venue.get("altitude_m")
        grass = venue.get("surface")
        parts = [str(name)]
        if city:
            parts.append(str(city))
        if altitude is not None:
            parts.append(f"海拔{altitude}m")
            try:
                if float(altitude) >= 1200:
                    risk = max(risk, 0.65)
                    warnings.append("高海拔可能影响体能、压迫强度和后程节奏")
            except (TypeError, ValueError):
                pass
        if grass:
            parts.append(f"场地{grass}")
        evidence.append("球馆/地点：" + " · ".join(parts))
        confidence = max(confidence, 0.6)
    else:
        warnings.append("缺少球馆/城市/海拔/场地数据，不能推断场地适应性")

    if isinstance(weather, dict) and weather:
        summary = weather.get("summary") or weather.get("condition") or ""
        temp = weather.get("temperature_c")
        wind = weather.get("wind_kph")
        humidity = weather.get("humidity_pct")
        bits = [str(summary)] if summary else []
        if temp is not None:
            bits.append(f"{temp}°C")
            try:
                if float(temp) >= 30 or float(temp) <= 5:
                    risk = max(risk, 0.6)
                    warnings.append("极端温度可能影响比赛节奏和体能分配")
            except (TypeError, ValueError):
                pass
        if wind is not None:
            bits.append(f"风{wind}km/h")
            try:
                if float(wind) >= 25:
                    risk = max(risk, 0.58)
                    warnings.append("较大风速可能影响长传、定位球和射门质量")
            except (TypeError, ValueError):
                pass
        if humidity is not None:
            bits.append(f"湿度{humidity}%")
        evidence.append("天气：" + " · ".join(bits or ["已接入天气数据"]))
        confidence = max(confidence, 0.65)
    else:
        warnings.append("缺少天气数据，不能推断高温、雨战、风速等球风影响")

    for line in fetch_log[:5]:
        evidence.append(f"数据查询：{line}")

    if not evidence:
        evidence.append("赛程/球馆数据不足")

    return AgentReport(
        agent_id="schedule_venue",
        name="赛程球馆 Agent",
        verdict="neutral",
        confidence=confidence,
        risk=risk,
        weight=_weight("schedule_venue", output_root),
        evidence=evidence,
        warnings=warnings,
        recommended_action="watch",
        raw=raw,
    )


def history_agent(pred: dict, index: dict | None = None, *, output_root=None) -> AgentReport:
    sim = pred.get("similarity_analysis") or {}
    candidates: list[dict] = []
    for layer in ("open", "live"):
        for block in sim.get(layer) or []:
            if isinstance(block, dict):
                candidates.append(block)
    best = max(candidates, key=lambda x: int(x.get("count") or 0), default={})
    cnt = int(best.get("count") or 0)
    evidence = []
    warnings = []
    verdict = "neutral"
    confidence = 0.25
    if cnt:
        rates = {
            "home": best.get("home_win_rate"),
            "draw": best.get("draw_rate"),
            "away": best.get("away_win_rate"),
        }
        best_key = max(rates, key=lambda k: rates.get(k) or 0)
        verdict = OUTCOME_TO_VERDICT.get(best_key, "neutral")
        confidence = min(0.75, 0.25 + cnt / 100)
        evidence.append(
            f"相似样本 {cnt} 场：主胜{_pct(rates.get('home'))} / 平{_pct(rates.get('draw'))} / 客胜{_pct(rates.get('away'))}"
        )
        if cnt < 20:
            warnings.append("相似样本偏少，历史 Agent 只能低权重参考")
    else:
        evidence.append("未找到可用相似样本统计")
        warnings.append("历史维度缺证据，不能用传统强弱印象替代")
    return AgentReport(
        agent_id="history",
        name="历史战绩 Agent",
        verdict=verdict,
        confidence=confidence,
        risk=0.35 if cnt >= 20 else 0.65,
        weight=_weight("history", output_root),
        evidence=evidence,
        warnings=warnings,
        recommended_action="watch",
        raw={"best_sample": best},
    )


def asian_handicap_agent(pred: dict, index: dict | None = None, *, output_root=None) -> AgentReport:
    odds = _odds(pred, index)
    line = _safe_float(odds.get("ah_line"))
    open_line = _safe_float(odds.get("ah_open_line"))
    evidence: list[str] = []
    warnings: list[str] = []
    verdict = "neutral"
    risk = 0.35
    confidence = 0.35
    try:
        from analysis.signals.odds import build_market_signals
        sig = build_market_signals(odds)
        if sig.line_summary:
            evidence.append(sig.line_summary)
        if sig.water_summary:
            evidence.append(sig.water_summary)
        if sig.ah_side_bias > 0.04:
            verdict = "lean_home"
            confidence += min(0.25, abs(sig.ah_side_bias))
        elif sig.ah_side_bias < -0.04:
            verdict = "lean_away"
            confidence += min(0.25, abs(sig.ah_side_bias))
        raw = {
            "market_signals": {
                "line_summary": sig.line_summary,
                "water_summary": sig.water_summary,
                "ah_side_bias": sig.ah_side_bias,
                "notes": sig.notes,
            }
        }
    except Exception as exc:
        raw = {"error": str(exc)}
        warnings.append("亚盘信号解析失败")

    if line is not None:
        evidence.append(f"当前亚盘主视角 {line:+g}")
        if abs(line) >= 2:
            risk = max(risk, 0.85)
            warnings.append("大让球盘，净胜球弹性大，不能作为稳健串关依据")
    if line is not None and open_line is not None:
        delta = line - open_line
        if abs(delta) >= 0.5:
            risk = max(risk, 0.75)
            warnings.append(f"初盘到临盘移动 {delta:+g}，需开球前复核")
    action = "skip" if risk >= 0.85 else "watch"
    return AgentReport(
        agent_id="asian_handicap",
        name="亚洲盘口 Agent",
        verdict=verdict,
        confidence=min(confidence, 0.8),
        risk=risk,
        weight=_weight("asian_handicap", output_root),
        evidence=evidence or ["亚盘数据不足"],
        warnings=warnings,
        recommended_action=action,
        raw={**raw, "odds": odds},
    )


def european_odds_agent(pred: dict, index: dict | None = None, *, output_root=None) -> AgentReport:
    odds = _odds(pred, index)
    evidence: list[str] = []
    warnings: list[str] = []
    verdict = "neutral"
    confidence = 0.3
    risk = 0.35
    raw: dict[str, Any] = {}
    try:
        from eu_implied_metrics import compute_eu_implied
        live = compute_eu_implied(odds.get("eu_home"), odds.get("eu_draw"), odds.get("eu_away"))
        open_ = compute_eu_implied(odds.get("eu_open_home"), odds.get("eu_open_draw"), odds.get("eu_open_away"))
        if live:
            raw["live"] = live.to_dict()
            fair = {
                "home": live.fair_home_pct,
                "draw": live.fair_draw_pct,
                "away": live.fair_away_pct,
            }
            best = max(fair, key=fair.get)
            verdict = OUTCOME_TO_VERDICT.get(best, "neutral")
            confidence = min(0.8, 0.25 + fair[best] / 100)
            evidence.append(
                f"临盘欧赔去水：主{live.fair_home_pct:.1f}% / 平{live.fair_draw_pct:.1f}% / 客{live.fair_away_pct:.1f}%"
            )
            if live.is_anomaly:
                risk = max(risk, 0.7)
                warnings.append(live.reason)
        if open_ and live:
            raw["open"] = open_.to_dict()
            moves = []
            for label, k, a, b in (
                ("主胜", "home", open_.fair_home_pct, live.fair_home_pct),
                ("平局", "draw", open_.fair_draw_pct, live.fair_draw_pct),
                ("客胜", "away", open_.fair_away_pct, live.fair_away_pct),
            ):
                delta = b - a
                if abs(delta) >= 2:
                    moves.append(f"{label}{delta:+.1f}pp")
            if moves:
                evidence.append("欧赔概率移动：" + " / ".join(moves))
                risk = max(risk, 0.55)
    except Exception as exc:
        raw["error"] = str(exc)
        warnings.append("欧赔隐含概率解析失败")

    return AgentReport(
        agent_id="european_odds",
        name="欧洲盘口 Agent",
        verdict=verdict,
        confidence=confidence,
        risk=risk,
        weight=_weight("european_odds", output_root),
        evidence=evidence or ["欧赔数据不足"],
        warnings=warnings,
        recommended_action="watch",
        raw=raw,
    )


def jingcai_agent(pred: dict, index: dict | None = None, *, output_root=None) -> AgentReport:
    jc = pred.get("jingcai_snapshot") or (pred.get("jingcai_pick_info") or {}).get("snapshot") or {}
    pick_info = pred.get("jingcai_pick_info") or {}
    evidence: list[str] = []
    warnings: list[str] = []
    verdict = "neutral"
    action = "watch"
    risk = 0.35
    confidence = 0.35
    try:
        from jingcai_pick import jingcai_market_mode, market_label, RQSP_LARGE_HANDICAP_ABS
        mode = pick_info.get("jingcai_market") or jingcai_market_mode(jc)
        label = pick_info.get("jingcai_market_label") or market_label(jc, mode)
        pick = pick_info.get("jingcai_pick_display") or pick_info.get("jingcai_pick_cn") or "—"
        evidence.append(f"竞彩可售玩法：{label}；当前推荐：{pick}")
        if mode == "rqsp":
            risk = max(risk, 0.7)
            warnings.append("仅让球胜平负售卖，竞彩判断依赖净胜球而非自然赛果")
            h = jc.get("handicap")
            if h is not None and abs(int(h)) >= RQSP_LARGE_HANDICAP_ABS:
                risk = max(risk, 0.9)
                action = "skip"
                warnings.append(f"让球({int(h):+d})属于大让球，默认不进串关")
        elif mode == "sp":
            confidence = 0.55
        else:
            risk = max(risk, 0.8)
            action = "skip"
            warnings.append("暂无竞彩可售数据")
        key = pick_info.get("jingcai_pick")
        verdict = OUTCOME_TO_VERDICT.get(key, "neutral")
    except Exception as exc:
        warnings.append("竞彩字段解析失败")
        return AgentReport(
            agent_id="jingcai",
            name="竞彩 Agent",
            verdict="risk",
            confidence=0.2,
            risk=0.8,
            weight=_weight("jingcai", output_root),
            evidence=evidence or ["竞彩数据不足"],
            warnings=warnings,
            recommended_action="watch",
            raw={"error": str(exc), "jingcai": jc, "pick_info": pick_info},
        )
    return AgentReport(
        agent_id="jingcai",
        name="竞彩 Agent",
        verdict=verdict,
        confidence=confidence,
        risk=risk,
        weight=_weight("jingcai", output_root),
        evidence=evidence,
        warnings=warnings,
        recommended_action=action,
        raw={"jingcai": jc, "pick_info": pick_info},
    )


def knockout_path_agent(pred: dict, index: dict | None = None, *, output_root=None) -> AgentReport:
    """Knockout bracket deep analysis: half strength, potential opponent chain, path difficulty."""
    match_name = _match_name(pred, index)
    evidence: list[str] = []
    warnings: list[str] = []
    raw: dict[str, Any] = {}
    risk = 0.35
    confidence = 0.35

    try:
        from analysis.tournament.knockout import (
            build_match_knockout_context,
            _load_bracket,
            _bracket_half,
            path_for_rank,
        )
        ctx = build_match_knockout_context(match_name)
        raw["knockout_context"] = ctx
        if ctx and ctx.get("group"):
            group = ctx["group"]
            evidence.append(f"所属小组：{group}")

            bracket = _load_bracket()
            half = _bracket_half(group, bracket)
            half_cn = {"upper": "上半区", "lower": "下半区"}.get(half, "未知半区")
            evidence.append(f"所在半区：{half_cn}")
            raw["bracket_half"] = half

            for side in ("home", "away"):
                ko = ctx.get(f"{side}_knockout") or {}
                team_label = "主队" if side == "home" else "客队"
                paths = ko.get("paths") or {}
                easiest_rank = ko.get("easiest_path_rank")
                preferred = ko.get("preferred_path_cn") or ""
                if preferred:
                    evidence.append(f"{team_label}最优路径：{preferred}")
                race = ko.get("race") or {}
                status = race.get("status_cn") or race.get("status")
                if status:
                    evidence.append(f"{team_label}状态：{status}")
                notes = ko.get("notes") or []
                for n in notes[:2]:
                    evidence.append(f"{team_label}：{str(n)[:140]}")

            picking = ctx.get("picking_level")
            if picking in ("high", "medium"):
                risk = max(risk, 0.7 if picking == "high" else 0.55)
                warnings.append("存在淘汰赛路径选择/挑对手动机，需要降低盘口直觉权重")

            scenarios = ctx.get("scenarios") or []
            for sc in scenarios[:3]:
                note = sc.get("note")
                if note:
                    evidence.append(f"情景：{sc.get('label')} → {str(note)[:100]}")

            confidence = 0.65
        else:
            warnings.append("未识别到淘汰赛对阵语境")
    except Exception as exc:
        raw["error"] = str(exc)
        warnings.append("淘汰赛路径分析暂不可用")

    return AgentReport(
        agent_id="knockout_path",
        name="淘汰赛路径 Agent",
        verdict="neutral",
        confidence=confidence,
        risk=risk,
        weight=_weight("knockout_path", output_root),
        evidence=evidence or ["未识别到明确淘汰赛对阵路径"],
        warnings=warnings,
        recommended_action="watch",
        raw=raw,
    )


def extra_time_penalty_agent(pred: dict, index: dict | None = None, *, output_root=None) -> AgentReport:
    """Analyze extra time and penalty shootout probability for knockout matches."""
    match_name = _match_name(pred, index)
    evidence: list[str] = []
    warnings: list[str] = []
    raw: dict[str, Any] = {}
    risk = 0.35
    confidence = 0.35

    odds = _odds(pred, index)
    eu_draw = _safe_float(odds.get("eu_draw"))
    draw_pct = None
    if eu_draw and eu_draw > 1:
        try:
            from eu_implied_metrics import compute_eu_implied
            live = compute_eu_implied(odds.get("eu_home"), eu_draw, odds.get("eu_away"))
            if live:
                draw_pct = live.fair_draw_pct
                evidence.append(f"欧赔隐含平局概率：{draw_pct:.1f}%")
        except Exception:
            pass

    if draw_pct is not None and draw_pct >= 28:
        risk = max(risk, 0.65)
        evidence.append("平局概率偏高，加时赛可能性较大")
        warnings.append("高平局概率场景，竞彩90分钟结果与最终结果可能不一致")
    elif draw_pct is not None and draw_pct >= 24:
        risk = max(risk, 0.5)
        evidence.append("平局概率中等，存在加时赛可能")

    sim = pred.get("similarity_analysis") or {}
    for pool_name, pool in (("亚盘样本", sim.get("asian")), ("欧赔样本", sim.get("european"))):
        if not pool:
            continue
        cnt = int(pool.get("count") or 0)
        rates = pool.get("result_rates") or {}
        draw_rate = _safe_float(rates.get("draw"))
        if cnt >= 10 and draw_rate is not None and draw_rate >= 0.28:
            evidence.append(f"{pool_name} {cnt} 场历史平局率 {draw_rate*100:.1f}%，加时赛参考")
            raw[f"{pool_name}_draw_rate"] = draw_rate

    raw["extra_time_data"] = {
        "draw_pct": draw_pct,
        "high_draw": draw_pct is not None and draw_pct >= 28,
    }

    if draw_pct is not None and draw_pct >= 30:
        warnings.append("平局概率超过30%，需重点考虑加时赛/点球对竞彩结算的影响")
        risk = max(risk, 0.75)

    if not evidence:
        evidence.append("暂无明确加时/点球高概率信号")

    return AgentReport(
        agent_id="extra_time_penalty",
        name="加时点球 Agent",
        verdict="lean_draw" if (draw_pct is not None and draw_pct >= 30) else "neutral",
        confidence=0.6 if risk >= 0.5 else 0.4,
        risk=risk,
        weight=_weight("extra_time_penalty", output_root),
        evidence=evidence[:5],
        warnings=warnings[:4],
        recommended_action="watch",
        raw=raw,
    )


def knockout_motivation_agent(pred: dict, index: dict | None = None, *, output_root=None) -> AgentReport:
    """Knockout stage motivation: conservative vs aggressive strategy, first-leg caution."""
    match_name = _match_name(pred, index)
    evidence: list[str] = []
    warnings: list[str] = []
    raw: dict[str, Any] = {}
    verdict = "neutral"
    risk = 0.4
    confidence = 0.35

    try:
        from analysis.tournament.knockout import build_match_knockout_context
        ctx = build_match_knockout_context(match_name)
        raw["knockout_context"] = ctx
        if ctx:
            motivation = ctx.get("motivation") or {}
            raw["motivation"] = motivation

            picking = ctx.get("picking_level")
            picking_cn = ctx.get("picking_level_cn") or "低"
            evidence.append(f"挑对手/控分级别：{picking_cn}")

            if picking in ("medium", "high"):
                risk = max(risk, 0.65 if picking == "medium" else 0.75)
                warnings.append("淘汰赛存在控分/保守策略动机，可能影响比赛节奏和进球数")
                verdict = "lean_draw"

            for side in ("home", "away"):
                ko = ctx.get(f"{side}_knockout") or {}
                team_label = "主队" if side == "home" else "客队"
                easiest = ko.get("easiest_path_rank")
                preferred = ko.get("preferred_path_cn") or ""
                if easiest and preferred:
                    evidence.append(f"{team_label}最优排名策略：{preferred}")

            scenarios = ctx.get("scenarios") or []
            for sc in scenarios[:3]:
                label = sc.get("label")
                note = sc.get("note")
                if note:
                    evidence.append(f"{label}：{str(note)[:120]}")

            prediction_hint = ctx.get("prediction_hint") or {}
            if prediction_hint.get("picking_note"):
                evidence.append(f"预测提示：{prediction_hint['picking_note']}")
            if prediction_hint.get("draw_bias") and float(prediction_hint.get("draw_bias") or 0) > 0.05:
                verdict = "lean_draw"
                warnings.append("淘汰赛路径分析提示平局概率上升")

            confidence = 0.6
        else:
            warnings.append("未识别到淘汰赛战意语境")
    except Exception as exc:
        raw["error"] = str(exc)
        warnings.append("淘汰赛战意分析暂不可用")

    return AgentReport(
        agent_id="knockout_motivation",
        name="淘汰赛战意 Agent",
        verdict=verdict,
        confidence=confidence,
        risk=risk,
        weight=_weight("knockout_motivation", output_root),
        evidence=evidence or ["暂无明确淘汰赛战意信号"],
        warnings=warnings,
        recommended_action="watch" if risk < 0.75 else "skip",
        raw=raw,
    )


def opening_structure_agent(pred: dict, index: dict | None = None, *, output_root=None) -> AgentReport:
    evidence: list[str] = []
    warnings: list[str] = []
    raw: dict[str, Any] = {}
    risk = 0.35
    confidence = 0.3
    try:
        import json
        from pathlib import Path
        root = Path(output_root or "output/service")
        ledger_path = root / "worldcup" / "ledger.json"
        if ledger_path.is_file():
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            opening = ledger.get("opening_patterns") or {}
        else:
            from worldcup_analytics import compute_opening_characteristics, load_tournament_records
            opening = compute_opening_characteristics(load_tournament_records(root))
        raw["opening_patterns"] = opening
        sample_size = int(opening.get("sample_size") or 0)
        if sample_size <= 0:
            evidence.append("本届杯赛暂无完场开盘样本，开盘结构权重暂低")
            warnings.append("样本不足，不能用本届开盘套路做强结论")
            risk = 0.5
        else:
            confidence = min(0.75, 0.25 + sample_size / 40)
            evidence.append(f"本届杯赛开盘结构样本：{sample_size} 场")
            if opening.get("summary"):
                evidence.append(str(opening.get("summary"))[:180])
            traits = opening.get("traits") or []
            evidence.extend(str(x)[:160] for x in traits[:4])
            stats = opening.get("stats") or {}
            if stats.get("upset_count"):
                risk = max(risk, 0.55)
            if stats.get("draw_rate_pct") is not None and stats.get("avg_implied_draw_pct") is not None:
                gap = float(stats.get("draw_rate_pct") or 0) - float(stats.get("avg_implied_draw_pct") or 0)
                if abs(gap) >= 5:
                    risk = max(risk, 0.6)
                    warnings.append("本届实际平局率与初盘隐含平局率偏离明显，需重视杯赛节奏差异")
    except Exception as exc:
        raw["error"] = str(exc)
        evidence.append("本届杯赛开盘结构读取失败")
        warnings.append("缺少本届开盘结构证据，总 Agent 需降低该维度权重")
        risk = 0.55
    return AgentReport(
        agent_id="opening_structure",
        name="本届开盘结构 Agent",
        verdict="neutral",
        confidence=confidence,
        risk=risk,
        weight=_weight("opening_structure", output_root),
        evidence=evidence,
        warnings=warnings,
        recommended_action="watch",
        raw=raw,
    )


def _extract_handicap(pred: dict) -> int | None:
    jc = pred.get("jingcai_snapshot") or {}
    if jc.get("handicap") is not None:
        try:
            return int(jc.get("handicap"))
        except (TypeError, ValueError):
            pass
    info = pred.get("jingcai_pick_info") or {}
    h = info.get("handicap") or info.get("jingcai_handicap")
    if h is not None:
        try:
            return int(h)
        except (TypeError, ValueError):
            pass
    row = pred.get("predict_row") or {}
    text = str(row.get("竞彩玩法") or row.get("竞彩推荐") or "")
    import re
    m = re.search(r"让球\(([+\-]?\d+)\)", text)
    if m:
        return int(m.group(1))
    return None


def _recommended_score_margins(pred: dict) -> list[int]:
    raw = pred.get("likely_scores_detail") or pred.get("likely_scores") or (pred.get("predict_row") or {}).get("推荐比分")
    if not raw:
        return []
    if isinstance(raw, str):
        import re
        parts = re.split(r"[、,，/ ]+", raw)
    else:
        parts = [str(x) for x in raw]
    margins: list[int] = []
    import re
    for p in parts:
        m = re.search(r"(\d+)\s*[-:：]\s*(\d+)", p)
        if not m:
            continue
        margins.append(int(m.group(1)) - int(m.group(2)))
    return margins[:6]


def goal_swing_agent(pred: dict, index: dict | None = None, *, output_root=None) -> AgentReport:
    """Detect one-goal leverage in handicap markets for knockout matches."""
    evidence: list[str] = []
    warnings: list[str] = []
    raw: dict[str, Any] = {}
    risk = 0.3
    confidence = 0.35

    hcap = _extract_handicap(pred)
    if hcap is not None:
        evidence.append(f"竞彩让球线 {hcap:+d}，一球差可能改变让胜/让平/让负")
        risk = max(risk, 0.65)
        if abs(hcap) >= 2:
            risk = max(risk, 0.9)
            warnings.append("大让球场景，一球差经常直接改变竞彩让球结果，禁止稳健串关")
        margins = _recommended_score_margins(pred)
        raw["score_margins"] = margins
        if margins:
            near = [m for m in margins if abs((m + hcap)) <= 1]
            if near:
                risk = max(risk, 0.85)
                warnings.append("推荐比分净胜球贴近让球线，少/多 1 球就可能改变结算")

    try:
        match_name = _match_name(pred, index)
        from analysis.tournament.knockout import build_match_knockout_context
        ctx = build_match_knockout_context(match_name)
        raw["knockout_context"] = ctx
        if ctx:
            scenarios = ctx.get("scenarios") or []
            for sc in scenarios[:3]:
                note = sc.get("note")
                if note and ("控节奏" in str(note) or "抢分" in str(note) or "告急" in str(note)):
                    risk = max(risk, 0.65)
                    evidence.append(f"淘汰赛情景：{sc.get('label')} → {str(note)[:100]}")
            picking = ctx.get("picking_level")
            if picking in ("medium", "high"):
                risk = max(risk, 0.7)
                evidence.append("淘汰赛路径差异可能诱发控分，一球差改变后续对阵")
    except Exception as exc:
        raw["knockout_error"] = str(exc)

    if not evidence:
        evidence.append("未识别到明显一球杠杆场景")
    action = "skip" if risk >= 0.88 else "watch"
    return AgentReport(
        agent_id="goal_swing",
        name="一球杠杆 Agent",
        verdict="risk" if risk >= 0.75 else "neutral",
        confidence=confidence if risk < 0.75 else 0.65,
        risk=risk,
        weight=_weight("goal_swing", output_root),
        evidence=evidence[:6],
        warnings=warnings[:5],
        recommended_action=action,
        raw=raw,
    )


def cross_group_path_agent(pred: dict, index: dict | None = None, *, output_root=None) -> AgentReport:
    """Legacy cross-group path agent — now disabled in knockout phase."""
    return AgentReport(
        agent_id="cross_group_path",
        name="跨组出线路径 Agent（已停用）",
        verdict="neutral",
        confidence=0.0,
        risk=0.0,
        weight=0.0,
        evidence=["小组赛已结束，此 Agent 在淘汰赛阶段停用"],
        warnings=[],
        recommended_action="watch",
        raw={"disabled": True, "reason": "knockout_phase"},
    )


def league_pressure_agent(pred: dict, index: dict | None = None, *, output_root=None) -> AgentReport:
    """League-oriented role: schedule congestion, rotation, multi-front pressure."""
    evidence: list[str] = []
    warnings: list[str] = []
    raw: dict[str, Any] = {}
    row = pred.get("predict_row") or {}
    league = pred.get("league") or pred.get("competition") or row.get("赛事") or row.get("联赛")
    if league:
        evidence.append(f"联赛/赛事：{league}")
    kickoff = _kickoff_value(pred, index)
    if kickoff:
        evidence.append(f"开球时间：{kickoff}")
    raw["available_fields"] = {
        "league": league,
        "kickoff": kickoff,
        "team_recent_form": pred.get("team_recent_form"),
        "style_clash": pred.get("style_clash"),
    }
    if pred.get("team_recent_form"):
        evidence.append("已接入近期战绩/状态，可辅助判断联赛持续性表现")
    else:
        warnings.append("缺少近期赛程密度、欧战/杯赛、轮换和伤停数据，多线压力只能占位提示")
    if pred.get("style_clash"):
        evidence.append("已接入风格克制信息，可辅助判断联赛对位")
    risk = 0.45 if warnings else 0.35
    return AgentReport(
        agent_id="league_pressure",
        name="联赛压力 Agent",
        verdict="neutral",
        confidence=0.35 if warnings else 0.55,
        risk=risk,
        weight=_weight("league_pressure", output_root),
        evidence=evidence or ["联赛压力数据尚未接入"],
        warnings=warnings,
        recommended_action="watch",
        raw=raw,
    )


def late_confirmation_agent(pred: dict, index: dict | None = None, *, output_root=None) -> AgentReport:
    """Pre-kickoff checklist: lineups, closing odds, weather and data freshness."""
    evidence: list[str] = []
    warnings: list[str] = []
    raw: dict[str, Any] = {}
    kickoff = _kickoff_value(pred, index)
    run_id = str(pred.get("run_id") or "")
    risk = 0.45
    confidence = 0.35

    if kickoff:
        evidence.append(f"已识别开球时间：{kickoff}")
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                ko = datetime.strptime(kickoff[: len(fmt)], fmt)
                if run_id and len(run_id) >= 16:
                    ts = datetime.strptime(run_id[:16], "%Y-%m-%d_%H%M")
                    hours = round((ko - ts).total_seconds() / 3600, 1)
                    raw["lead_hours"] = hours
                    evidence.append(f"当前预测距开球约 {hours:g} 小时")
                    if hours > 3:
                        risk = max(risk, 0.72)
                        warnings.append("预测快照距离开球超过 3 小时，必须临场复核终盘/首发/天气")
                    elif 0 <= hours <= 3:
                        confidence = max(confidence, 0.55)
                        evidence.append("处于临场窗口，可用于终盘确认")
                break
            except ValueError:
                continue
    else:
        risk = max(risk, 0.75)
        warnings.append("缺少开球时间，无法判断是否需要临场复核")

    odds = _odds(pred, index)
    raw["odds_keys"] = sorted(k for k, v in odds.items() if v is not None)
    if odds.get("ah_line") is not None and odds.get("eu_home") is not None:
        evidence.append("已有当前亚盘/欧赔快照")
    else:
        risk = max(risk, 0.7)
        warnings.append("缺少当前亚盘或欧赔快照，不能当作临场版结论")
    if not pred.get("lineup") and not pred.get("lineups"):
        warnings.append("未接入首发阵容；开球前必须复核主力轮换、门将和中轴线")
    if not pred.get("injury_report") and not pred.get("injuries"):
        warnings.append("未接入可靠伤停；总 Agent 只能标注缺失，不能补故事")

    return AgentReport(
        agent_id="late_confirmation",
        name="临场确认 Agent",
        verdict="risk" if risk >= 0.7 else "neutral",
        confidence=confidence,
        risk=risk,
        weight=_weight("late_confirmation", output_root),
        evidence=evidence or ["临场确认数据不足"],
        warnings=warnings[:6],
        recommended_action="watch" if risk < 0.75 else "skip",
        raw=raw,
    )


def scenario_simulator_agent(pred: dict, index: dict | None = None, *, output_root=None) -> AgentReport:
    """Legacy group-stage scenario simulator — now disabled in knockout phase."""
    return AgentReport(
        agent_id="scenario_simulator",
        name="杯赛场景模拟 Agent（已停用）",
        verdict="neutral",
        confidence=0.0,
        risk=0.0,
        weight=0.0,
        evidence=["小组赛已结束，此 Agent 在淘汰赛阶段停用"],
        warnings=[],
        recommended_action="watch",
        raw={"disabled": True, "reason": "knockout_phase"},
    )


def market_consistency_agent(pred: dict, index: dict | None = None, *, output_root=None) -> AgentReport:
    """Judge whether European odds and Asian handicap express the same attitude."""
    odds = _odds(pred, index)
    evidence: list[str] = []
    warnings: list[str] = []
    raw: dict[str, Any] = {"odds": odds}
    risk = 0.35
    confidence = 0.35
    verdict = "neutral"
    try:
        from eu_implied_metrics import compute_eu_implied
        live = compute_eu_implied(odds.get("eu_home"), odds.get("eu_draw"), odds.get("eu_away"))
        if live:
            raw["eu_live"] = live.to_dict()
            probs = {"home": live.fair_home_pct, "draw": live.fair_draw_pct, "away": live.fair_away_pct}
            eu_side = max(probs, key=probs.get)
            verdict = OUTCOME_TO_VERDICT.get(eu_side, "neutral")
            evidence.append(f"欧赔态度：{eu_side} 概率最高 {probs[eu_side]:.1f}%")
            line = _safe_float(odds.get("ah_line"))
            if line is not None:
                ah_side = "home" if line < 0 else ("away" if line > 0 else "balanced")
                raw["ah_side"] = ah_side
                evidence.append(f"亚盘态度：主视角盘口 {line:+g}，倾向 {ah_side}")
                if ah_side != "balanced" and eu_side in ("home", "away") and ah_side != eu_side:
                    risk = max(risk, 0.82)
                    warnings.append("欧赔主方向与亚盘让球方向不一致，存在诱盘/分歧风险")
                elif ah_side != "balanced" and eu_side == ah_side:
                    confidence = max(confidence, 0.62)
                    evidence.append("欧赔与亚盘主方向一致")
                if abs(line) >= 2 and probs.get(ah_side if ah_side != "balanced" else eu_side, 0) < 68:
                    risk = max(risk, 0.78)
                    warnings.append("亚盘大让球但欧赔优势没有明显拉开，净胜球风险偏高")
    except Exception as exc:
        raw["error"] = str(exc)
        warnings.append("欧亚一致性解析失败")
    if not evidence:
        evidence.append("欧赔/亚盘数据不足，无法判断欧亚态度是否一致")
        risk = max(risk, 0.6)
    return AgentReport(
        agent_id="market_consistency",
        name="欧亚一致性 Agent",
        verdict="risk" if risk >= 0.75 else verdict,
        confidence=confidence,
        risk=risk,
        weight=_weight("market_consistency", output_root),
        evidence=evidence,
        warnings=warnings,
        recommended_action="watch" if risk < 0.8 else "skip",
        raw=raw,
    )


def contrarian_agent(pred: dict, index: dict | None = None, *, output_root=None) -> AgentReport:
    """Always argue against buying; useful for suppressing overconfident stories."""
    evidence: list[str] = []
    warnings: list[str] = []
    risk = 0.35
    row = pred.get("predict_row") or {}
    pick = row.get("竞彩推荐") or pred.get("pick_jingcai_cn") or ""
    if pick:
        evidence.append(f"当前推荐：{pick}")
    hcap = _extract_handicap(pred)
    if hcap is not None and abs(hcap) >= 2:
        risk = max(risk, 0.88)
        warnings.append("反方观点：大让球需要净胜球兑现，强队赢球不等于赢盘/让胜")
    conf = pred.get("confidence_cn") or row.get("置信度")
    if conf and conf != "高":
        risk = max(risk, 0.65)
        warnings.append(f"反方观点：置信度为 {conf}，不适合当稳胆")
    risk_cn = pred.get("risk_level_cn")
    if risk_cn in ("升高", "显著升高", "高"):
        risk = max(risk, 0.75)
        warnings.append(f"反方观点：系统风险等级 {risk_cn}，应先解释不买理由")
    if not pred.get("lineup") and not pred.get("injury_report"):
        warnings.append("反方观点：缺少首发/伤停，热门方向容易被赛前信息反转")
        risk = max(risk, 0.62)
    odds = _odds(pred, index)
    line = _safe_float(odds.get("ah_line"))
    open_line = _safe_float(odds.get("ah_open_line"))
    if line is not None and open_line is not None and abs(line - open_line) >= 0.5:
        risk = max(risk, 0.72)
        warnings.append("反方观点：盘口移动较大，可能已透支或诱导热门")
    if not warnings:
        evidence.append("未找到强反方风险，但仍需避免无条件升为 A 档")
    return AgentReport(
        agent_id="contrarian",
        name="反方辩手 Agent",
        verdict="risk" if risk >= 0.65 else "neutral",
        confidence=0.65 if risk >= 0.65 else 0.35,
        risk=risk,
        weight=_weight("contrarian", output_root),
        evidence=evidence,
        warnings=warnings[:6],
        recommended_action="watch" if risk < 0.82 else "skip",
        raw={"pick": pick, "handicap": hcap},
    )


def memory_agent(pred: dict, index: dict | None = None, *, output_root=None) -> AgentReport:
    """Search prior GrowthAgent reports for reusable error patterns."""
    evidence: list[str] = []
    warnings: list[str] = []
    raw: dict[str, Any] = {}
    risk = 0.35
    confidence = 0.25
    if output_root:
        root = Path(output_root)
        records = []
        for p in (root / "matches").glob("*/growth_report.jsonl") if (root / "matches").is_dir() else []:
            try:
                for line in p.read_text(encoding="utf-8").splitlines()[-3:]:
                    if not line.strip():
                        continue
                    import json
                    records.append(json.loads(line))
            except Exception:
                continue
        raw["growth_count"] = len(records)
        miss_records = [r for r in records if r.get("status") == "learned_miss"]
        hcap = _extract_handicap(pred)
        matched = []
        for r in miss_records:
            diag = r.get("diagnosis") or {}
            tags = diag.get("tags") or []
            if hcap is not None and abs(hcap) >= 2 and "大让球" in tags:
                matched.append(r)
            elif "RQSP" in tags and "让球" in str((pred.get("predict_row") or {}).get("竞彩推荐") or ""):
                matched.append(r)
        raw["matched_count"] = len(matched)
        if matched:
            risk = max(risk, 0.78)
            confidence = 0.65
            evidence.append(f"历史成长库命中 {len(matched)} 个相似错误模式")
            for r in matched[:3]:
                evidence.append(f"{r.get('match_name')}：{(r.get('diagnosis') or {}).get('tags')}")
            warnings.append("当前场景接近历史翻车样本，Chief 必须解释为何本场不一样，否则降级")
        elif records:
            evidence.append(f"已读取成长记忆 {len(records)} 条，未命中强相似错误模式")
            confidence = 0.45
        else:
            evidence.append("暂无历史成长记忆，先累计完赛复盘样本")
            warnings.append("记忆库为空，不能声称已吸收历史错误模式")
    else:
        evidence.append("未提供 output_root，无法读取成长记忆库")
        warnings.append("Growth 历史记忆未参与本场判断")
        risk = 0.55
    return AgentReport(
        agent_id="memory",
        name="成长记忆库 Agent",
        verdict="risk" if risk >= 0.7 else "neutral",
        confidence=confidence,
        risk=risk,
        weight=_weight("memory", output_root),
        evidence=evidence[:6],
        warnings=warnings[:4],
        recommended_action="watch" if risk < 0.8 else "skip",
        raw=raw,
    )


_OUTCOME_CN = {"home": "主胜", "draw": "平局", "away": "客胜"}
_CN_TO_OUTCOME = {"主胜": "home", "平局": "draw", "客胜": "away", "平": "draw"}


def result_1x2_agent(pred: dict, index: dict | None = None, *, output_root=None) -> AgentReport:
    """Synthesize 1X2 pick from engine, model, samples and market hints."""
    votes: dict[str, float] = {"home": 0.0, "draw": 0.0, "away": 0.0}
    sources: list[str] = []
    evidence: list[str] = []
    warnings: list[str] = []
    row = pred.get("predict_row") or {}

    ref_key = pred.get("result_1x2") or pred.get("reference_result_1x2")
    ref_cn = pred.get("result_1x2_cn") or pred.get("reference_result_1x2_cn") or row.get("赛果预测")
    if ref_key in votes:
        votes[str(ref_key)] += 1.25
        sources.append("规则引擎")
        evidence.append(f"规则引擎赛果：{_OUTCOME_CN.get(str(ref_key), ref_cn or ref_key)}")
    elif ref_cn in _CN_TO_OUTCOME:
        votes[_CN_TO_OUTCOME[ref_cn]] += 1.25
        sources.append("规则引擎")
        evidence.append(f"规则引擎赛果：{ref_cn}")

    sm = (pred.get("quant") or {}).get("score_model") or {}
    p1 = sm.get("prob_1x2_pct") or {}
    if isinstance(p1, dict) and p1:
        for k in ("home", "draw", "away"):
            v = _safe_float(p1.get(k))
            if v is not None:
                votes[k] += (v / 100.0) * 0.9
        sources.append("Poisson")
        evidence.append(
            "模型 1X2："
            + " / ".join(f"{_OUTCOME_CN[k]}{float(p1.get(k) or 0):.1f}%" for k in ("home", "draw", "away") if p1.get(k) is not None)
        )

    sim = pred.get("similarity_analysis") or {}
    for pool_name, pool in (("亚盘样本", sim.get("asian")), ("欧赔样本", sim.get("european"))):
        rates = (pool or {}).get("result_rates") or {}
        cnt = int((pool or {}).get("count") or 0)
        if cnt >= 8 and rates:
            for k in ("home", "draw", "away"):
                v = _safe_float(rates.get(k))
                if v is not None:
                    votes[k] += v * 0.55
            sources.append(pool_name)
            evidence.append(
                f"{pool_name} {cnt} 场："
                + " / ".join(f"{_OUTCOME_CN[k]}{_pct(rates.get(k))}" for k in ("home", "draw", "away"))
            )

    odds = _odds(pred, index)
    try:
        from analysis.signals.odds import build_market_signals

        sig = build_market_signals(odds)
        if sig.ah_side_bias > 0.05:
            votes["home"] += 0.35
            evidence.append("亚盘倾向主队")
        elif sig.ah_side_bias < -0.05:
            votes["away"] += 0.35
            evidence.append("亚盘倾向客队")
    except Exception:
        pass

    pick_info = pred.get("jingcai_pick_info") or {}
    jc_key = pick_info.get("jingcai_pick")
    if jc_key in votes:
        votes[jc_key] += 0.45
        sources.append("竞彩")
        evidence.append(f"竞彩方向：{_OUTCOME_CN.get(jc_key, jc_key)}")

    total = sum(votes.values()) or 1.0
    best = max(votes, key=lambda k: votes[k])
    share = votes[best] / total
    pick_cn = _OUTCOME_CN[best]
    confidence = min(0.82, 0.32 + share * 0.55)
    risk = 0.35 if share >= 0.42 else 0.58
    if not sources:
        warnings.append("胜负信号来源不足，只能低置信参考")
        risk = max(risk, 0.62)

    return AgentReport(
        agent_id="result_1x2",
        name="胜负研判 Agent",
        verdict=OUTCOME_TO_VERDICT.get(best, "neutral"),
        confidence=confidence,
        risk=risk,
        weight=_weight("result_1x2", output_root),
        evidence=evidence[:6] or [f"综合研判：{pick_cn}"],
        warnings=warnings[:4],
        recommended_action="watch" if share >= 0.38 else "skip",
        raw={
            "pick_1x2": best,
            "pick_1x2_cn": pick_cn,
            "vote_share": round(share, 3),
            "votes": {k: round(v, 3) for k, v in votes.items()},
            "sources": sources,
        },
    )


def scoreline_agent(pred: dict, index: dict | None = None, *, output_root=None) -> AgentReport:
    """Top scorelines from historical + Poisson tracks."""
    evidence: list[str] = []
    warnings: list[str] = []
    raw: dict[str, Any] = {}
    primary: list[dict[str, Any]] = []
    try:
        from analysis.score_recommend import build_score_recommendation

        sr = build_score_recommendation(pred)
        raw["score_recommendation"] = sr
        primary = list(sr.get("primary") or [])[:2]
        top_scores = [str(p.get("score") or "") for p in primary if p.get("score")]
        raw["top_scores"] = top_scores
        if sr.get("pick_1x2_cn"):
            raw["pick_1x2_cn"] = sr["pick_1x2_cn"]
        if sr.get("disabled"):
            warnings.append(str(sr.get("headline") or "比分预测已关闭"))
        elif not primary:
            warnings.append(str(sr.get("reason") or "暂无比分推荐"))
        else:
            detail = " / ".join(
                f"{p['score']}" + (f"({p['prob_pct']}%)" if p.get("prob_pct") is not None else "")
                for p in primary
            )
            evidence.append(f"Top{len(primary)} 比分：{detail}")
            if sr.get("summary"):
                evidence.append(str(sr["summary"])[:160])
            tracks = sr.get("track_summary") or {}
            if tracks.get("historical") and tracks.get("historical") != "—":
                evidence.append(f"历史轨：{tracks['historical']}")
            if tracks.get("model") and tracks.get("model") != "—":
                evidence.append(f"模型轨：{tracks['model']}")
    except Exception as exc:
        raw["error"] = str(exc)
        warnings.append(f"比分研判失败：{exc}")
        top_scores = []
        primary = []

    margins = _recommended_score_margins(pred)
    if margins and raw.get("top_scores"):
        hcap = _extract_handicap(pred)
        if hcap is not None:
            near = [s for s in raw["top_scores"] if any(abs(m + hcap) <= 1 for m in margins)]
            if near:
                warnings.append("Top 比分贴近让球线，一球差可能改变竞彩结算")

    confidence = 0.62 if primary else 0.3
    risk = 0.4 if primary else 0.65
    return AgentReport(
        agent_id="scoreline",
        name="比分研判 Agent",
        verdict="neutral",
        confidence=confidence,
        risk=risk,
        weight=_weight("scoreline", output_root),
        evidence=evidence[:6] or ["比分数据不足"],
        warnings=warnings[:4],
        recommended_action="watch" if primary else "skip",
        raw=raw,
    )


DEFAULT_EXPERTS = (
    intel_agent,
    external_context_agent,
    schedule_venue_agent,
    late_confirmation_agent,
    opening_structure_agent,
    knockout_path_agent,
    goal_swing_agent,
    extra_time_penalty_agent,
    knockout_motivation_agent,
    market_consistency_agent,
    contrarian_agent,
    memory_agent,
    history_agent,
    asian_handicap_agent,
    european_odds_agent,
    jingcai_agent,
)
