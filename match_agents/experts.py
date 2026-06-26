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


def cup_standing_agent(pred: dict, index: dict | None = None, *, output_root=None) -> AgentReport:
    match_name = pred.get("match") or (pred.get("predict_row") or {}).get("比赛") or (index or {}).get("match_name")
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
        if ctx.get("ok") is False:
            warnings.append("未识别到杯赛积分/出线语境")
        else:
            group = ctx.get("group")
            if group:
                evidence.append(f"杯赛小组：{group}")
            for side in ("home", "away"):
                race = ((ctx.get(f"{side}_knockout") or {}).get("race") or {})
                status = race.get("status_cn") or race.get("status")
                note = race.get("note")
                if status:
                    evidence.append(f"{'主队' if side == 'home' else '客队'}出线状态：{status}")
                if note:
                    evidence.append(str(note)[:120])
            picking = ctx.get("picking_level")
            if picking in ("high", "medium"):
                risk = max(risk, 0.7 if picking == "high" else 0.55)
                warnings.append("存在淘汰赛路径选择/挑对手动机，需要降低盘口直觉权重")
            confidence = 0.6
    except Exception as exc:
        raw["error"] = str(exc)
        warnings.append("积分出线上下文暂不可用")
    return AgentReport(
        agent_id="cup_standing",
        name="积分出线 Agent",
        verdict=verdict,
        confidence=confidence,
        risk=risk,
        weight=_weight("cup_standing", output_root),
        evidence=evidence or ["未识别到明确杯赛积分/出线压力"],
        warnings=warnings,
        recommended_action="watch",
        raw=raw,
    )


def motivation_agent(pred: dict, index: dict | None = None, *, output_root=None) -> AgentReport:
    match_name = pred.get("match") or (pred.get("predict_row") or {}).get("比赛") or (index or {}).get("match_name")
    evidence: list[str] = []
    warnings: list[str] = []
    raw: dict[str, Any] = {}
    verdict = "neutral"
    risk = 0.4
    confidence = 0.35
    try:
        from group_stage_model import analyze_match_from_name
        ma = analyze_match_from_name(match_name)
        raw["motivation"] = ma
        if ma:
            mt = ma.get("match_type_cn") or ma.get("match_type")
            if mt:
                evidence.append(f"战意类型：{mt}")
            evidence.extend(str(x)[:140] for x in (ma.get("reasoning") or [])[:4])
            hint = ma.get("model_pick_hint")
            verdict = OUTCOME_TO_VERDICT.get(hint, "neutral")
            if ma.get("draw_bias"):
                verdict = "lean_draw"
                warnings.append("战意模型提示平局友好/默契球观察")
            if ma.get("match_type") in ("collusion_watch", "draw_friendly", "dead_rubber"):
                risk = max(risk, 0.75)
            confidence = 0.6
        else:
            warnings.append("战意模型未匹配该场比赛")
    except Exception as exc:
        raw["error"] = str(exc)
        warnings.append("战意分析暂不可用")
    return AgentReport(
        agent_id="motivation",
        name="战意 Agent",
        verdict=verdict,
        confidence=confidence,
        risk=risk,
        weight=_weight("motivation", output_root),
        evidence=evidence or ["暂无明确战意信号"],
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
    """Detect one-goal leverage in qualification and handicap markets."""
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
        from group_stage_model import analyze_match_from_name
        ma = analyze_match_from_name(match_name)
        raw["motivation"] = ma
        if ma:
            mt = ma.get("match_type")
            mt_cn = ma.get("match_type_cn") or mt
            reasoning = "；".join(str(x) for x in (ma.get("reasoning") or [])[:4])
            if mt in ("gd_race", "must_win", "open_race", "collusion_watch", "draw_friendly"):
                risk = max(risk, 0.75)
                evidence.append(f"杯赛战意类型 {mt_cn}，净胜球/平局价值敏感")
            if "净胜球" in reasoning or "最佳" in reasoning or "第三" in reasoning:
                risk = max(risk, 0.82)
                warnings.append("出线条件涉及净胜球/最佳第三，1球可能改变晋级排序或战术选择")
                evidence.append(reasoning[:180])
    except Exception as exc:
        raw["motivation_error"] = str(exc)

    try:
        from analysis.tournament.group_knockout_outlook import outlook_for_match
        om = outlook_for_match(_match_name(pred, index))
        raw["outlook"] = om
        best = om.get("best_third_live") or {}
        rows = best.get("rows") or []
        if rows:
            cutoff = f"{best.get('cutoff_points')}分 净{best.get('cutoff_gd'):+d}" if best.get("cutoff_gd") is not None else ""
            evidence.append(f"最佳第三实时线：{cutoff or '有排名数据'}")
            near_rows = [
                r for r in rows
                if r.get("third_rank") in (7, 8, 9, 10)
                or (best.get("cutoff_points") is not None and r.get("points") == best.get("cutoff_points"))
            ][:4]
            if near_rows:
                risk = max(risk, 0.78)
                warnings.append("最佳第三边界附近，净胜球/进球数的一球变化可能改变跨组排名")
                raw["best_third_boundary"] = near_rows
    except Exception as exc:
        raw["outlook_error"] = str(exc)

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
    """Read dynamic best-third ranking and knockout path incentives."""
    match_name = _match_name(pred, index)
    evidence: list[str] = []
    warnings: list[str] = []
    raw: dict[str, Any] = {}
    risk = 0.35
    confidence = 0.35

    try:
        from analysis.tournament.group_knockout_outlook import outlook_for_match
        om = outlook_for_match(match_name)
        raw["outlook_for_match"] = om
        if om.get("ok"):
            group = om.get("group")
            if group:
                evidence.append(f"当前比赛属于 {group} 组，需同时参考 12 个小组第三横向排名")
            best = om.get("best_third_live") or {}
            rows = best.get("rows") or []
            if best:
                cutoff = []
                if best.get("cutoff_points") is not None:
                    cutoff.append(f"{best.get('cutoff_points')}分")
                if best.get("cutoff_gd") is not None:
                    cutoff.append(f"净{best.get('cutoff_gd'):+d}")
                evidence.append("最佳第三实时切线：" + (" / ".join(cutoff) if cutoff else "已有动态排名"))
            boundary = [
                r for r in rows
                if r.get("third_rank") in (7, 8, 9, 10)
                or (best.get("cutoff_points") is not None and r.get("points") == best.get("cutoff_points"))
            ][:6]
            if boundary:
                risk = max(risk, 0.72)
                raw["best_third_boundary"] = boundary
                txt = "；".join(
                    f"{r.get('group')}组{r.get('team')} 第{r.get('third_rank')} "
                    f"{r.get('points')}分 净{r.get('gd'):+d}"
                    for r in boundary if r.get("gd") is not None
                )
                evidence.append("最佳第三边界：" + txt[:220])
                warnings.append("最佳第三边界附近，一球净胜球/进球数可能改变跨组出线")

            grp = om.get("group_outlook") or {}
            team_bits = []
            for t in grp.get("teams") or []:
                scenarios = t.get("rank_scenarios") or []
                if not scenarios:
                    continue
                sc_txt = " / ".join(
                    f"第{s.get('rank')}→{s.get('r32_summary')}"
                    for s in scenarios[:3]
                )
                team_bits.append(f"{t.get('team')}：{sc_txt}")
            if team_bits:
                evidence.extend(x[:180] for x in team_bits[:4])
    except Exception as exc:
        raw["outlook_error"] = str(exc)
        warnings.append("跨组最佳第三/出线路径读取失败")

    try:
        from analysis.tournament.knockout import build_match_knockout_context
        ctx = build_match_knockout_context(match_name)
        raw["knockout_context"] = ctx
        picking = ctx.get("picking_level")
        if picking in ("medium", "high", "watch"):
            risk = max(risk, 0.8 if picking == "high" else 0.68)
            warnings.append("出线路径差异可能诱发控分、保平或默契球观察")
        for side in ("home", "away"):
            team = "主队" if side == "home" else "客队"
            ko = ctx.get(f"{side}_knockout") or {}
            race = ko.get("race") or {}
            likely = race.get("likely_r32") or ko.get("likely_r32") or {}
            status = race.get("status_cn") or race.get("status")
            if status:
                evidence.append(f"{team}出线状态：{status}")
            if isinstance(likely, dict) and likely.get("summary"):
                evidence.append(f"{team}32强路径：{likely.get('summary')}"[:180])
        notes = ctx.get("opponent_picking_notes") or []
        if isinstance(notes, list) and notes:
            evidence.extend(str(x)[:180] for x in notes[:3])
    except Exception as exc:
        raw["knockout_error"] = str(exc)

    if not evidence:
        evidence.append("未读取到跨组最佳第三或32强路径数据")
        warnings.append("缺少另一侧动态排名/路径证据，不能判断默契球或挑对手动机")
        risk = max(risk, 0.6)

    return AgentReport(
        agent_id="cross_group_path",
        name="跨组出线路径 Agent",
        verdict="risk" if risk >= 0.7 else "neutral",
        confidence=0.65 if evidence and risk >= 0.7 else confidence,
        risk=risk,
        weight=_weight("cross_group_path", output_root),
        evidence=evidence[:8],
        warnings=warnings[:5],
        recommended_action="watch" if risk < 0.8 else "skip",
        raw=raw,
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
    """Cup scenario simulator for group/cross-group knock-on effects."""
    match_name = _match_name(pred, index)
    evidence: list[str] = []
    warnings: list[str] = []
    raw: dict[str, Any] = {}
    risk = 0.35
    confidence = 0.35
    try:
        from analysis.tournament.group_knockout_outlook import outlook_for_match
        outlook = outlook_for_match(match_name)
        raw["outlook"] = outlook
        if outlook.get("ok"):
            group = outlook.get("group")
            if group:
                evidence.append(f"{group}组场景：需联动同组另一场与跨组第三排名")
            best = outlook.get("best_third_live") or {}
            rows = best.get("rows") or []
            boundary = [r for r in rows if r.get("third_rank") in (7, 8, 9, 10)][:5]
            if boundary:
                risk = max(risk, 0.75)
                warnings.append("最佳第三边界队伍接近，胜/平/净胜球变化会影响多队决策")
                evidence.append("边界第三：" + "；".join(
                    f"{r.get('group')}组{r.get('team')}第{r.get('third_rank')}"
                    for r in boundary
                ))
            grp = outlook.get("group_outlook") or {}
            team_lines = []
            for team in grp.get("teams") or []:
                scenarios = team.get("rank_scenarios") or []
                if scenarios:
                    risk = max(risk, 0.68)
                    team_lines.append(
                        f"{team.get('team')}：" + " / ".join(
                            f"第{s.get('rank')}→{s.get('r32_summary')}" for s in scenarios[:3]
                        )
                    )
            if team_lines:
                evidence.extend(x[:180] for x in team_lines[:4])
                confidence = max(confidence, 0.62)
    except Exception as exc:
        raw["outlook_error"] = str(exc)
        warnings.append("场景模拟读取出线/签位数据失败")

    try:
        from group_stage_model import analyze_match_from_name
        ma = analyze_match_from_name(match_name)
        raw["motivation"] = ma
        if ma and ma.get("match_type") in ("must_win", "gd_race", "draw_friendly", "collusion_watch"):
            risk = max(risk, 0.78)
            evidence.append("战意场景：" + "；".join(str(x) for x in (ma.get("reasoning") or [])[:3])[:180])
            warnings.append("不同比分场景下战术目标可能改变，不能只用单一赛果预测")
    except Exception as exc:
        raw["motivation_error"] = str(exc)

    if not evidence:
        evidence.append("未读取到可模拟的杯赛联动场景")
        warnings.append("缺少同组/跨组场景数据，出线压力只能低置信参考")
        risk = max(risk, 0.55)
    return AgentReport(
        agent_id="scenario_simulator",
        name="杯赛场景模拟 Agent",
        verdict="risk" if risk >= 0.7 else "neutral",
        confidence=confidence,
        risk=risk,
        weight=_weight("scenario_simulator", output_root),
        evidence=evidence[:8],
        warnings=warnings[:5],
        recommended_action="watch" if risk < 0.8 else "skip",
        raw=raw,
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


DEFAULT_EXPERTS = (
    intel_agent,
    external_context_agent,
    schedule_venue_agent,
    late_confirmation_agent,
    opening_structure_agent,
    scenario_simulator_agent,
    goal_swing_agent,
    cross_group_path_agent,
    market_consistency_agent,
    contrarian_agent,
    memory_agent,
    history_agent,
    asian_handicap_agent,
    european_odds_agent,
    jingcai_agent,
    cup_standing_agent,
    motivation_agent,
)
