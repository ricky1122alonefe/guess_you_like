"""T1: 组装单场五源预测上下文。

数据来源（按优先级回落，有一个就算有）：
  1. european  — timeline.odds.eu_home/draw/away → prediction.odds_snapshot → prediction.cur
  2. asian     — timeline.odds.ah_line/home_water/away_water → prediction.odds_snapshot
  3. betfair   — timeline.odds.betfair → prediction.odds_snapshot.betfair
  4. history_similar — prediction.similarity_analysis → prediction.payload.stats → prediction.sample_count + open_probability_summary
  5. recent_form — team_recent_form（国际队）或 missing

缺源不崩，进 missing；不得因单独 missing recent_form 拖垮预测。
"""
from __future__ import annotations

import json
import logging
import re
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


def _implied_probs(home: float, draw: float, away: float) -> dict[str, float]:
    """去水隐含概率（统一用 analysis.market.devig）。"""
    from analysis.market.devig import devig_1x2
    r = devig_1x2(home, draw, away)
    return {"home": r["p_home"], "draw": r["p_draw"], "away": r["p_away"]}


# ============ odds 合并：timeline + prediction 回落 ============

def _is_valid_tick(tick: dict) -> bool:
    """有效 tick：至少有 eu_home+eu_away 或 ah_line。"""
    odds = tick.get("odds") or tick
    eu_h = _safe_float(odds.get("eu_home"))
    eu_a = _safe_float(odds.get("eu_away"))
    ah = odds.get("ah_line")
    ah_ok = ah is not None and str(ah).strip() not in ("", "None", "null")
    return (eu_h is not None and eu_a is not None) or ah_ok


def _from_tick(timeline: list[dict]) -> dict | None:
    """从 timeline 取最新一个有效 tick 的 odds（跳过无效/空壳 tick）。"""
    for point in reversed(timeline):
        if _is_valid_tick(point):
            odds = point.get("odds") or point
            return odds
    return None


def _merge_odds(timeline_odds: dict | None, prediction: dict | None) -> dict:
    """合并 timeline odds + prediction.odds_snapshot + prediction.cur。

    优先 timeline（DB poll tick），回落 prediction（文件推荐快照）。
    """
    merged: dict[str, Any] = {}
    if timeline_odds:
        merged.update(timeline_odds)

    if prediction:
        # odds_snapshot：文件推荐的盘口快照
        snapshot = prediction.get("odds_snapshot") or {}
        if snapshot:
            for k, v in snapshot.items():
                if merged.get(k) is None and v is not None:
                    merged[k] = v
        # cur：实时快照（部分 pred 结构）
        cur = prediction.get("cur") or {}
        if isinstance(cur, dict):
            for k, v in cur.items():
                if merged.get(k) is None and v is not None:
                    merged[k] = v
        # quant：量化分析里可能有欧赔
        quant = prediction.get("quant") or {}
        if isinstance(quant, dict):
            for k in ("eu_home", "eu_draw", "eu_away", "ah_line", "ah_home_water", "ah_away_water"):
                v = quant.get(k)
                if merged.get(k) is None and v is not None:
                    merged[k] = v

    # 兼容：raw_meta 嵌套的 betfair
    raw_meta = merged.get("raw_meta")
    if isinstance(raw_meta, str):
        try:
            raw_meta = json.loads(raw_meta)
            merged["raw_meta"] = raw_meta
        except json.JSONDecodeError:
            raw_meta = None
    if raw_meta and isinstance(raw_meta, dict):
        bf = raw_meta.get("betfair")
        if bf and not merged.get("betfair"):
            merged["betfair"] = bf
        # eu_books：多庄家欧赔，取第一家
        eu_books = raw_meta.get("eu_books")
        if eu_books and not merged.get("eu_home"):
            for book in (eu_books if isinstance(eu_books, list) else [eu_books]):
                if isinstance(book, dict):
                    h = _safe_float(book.get("home"))
                    d = _safe_float(book.get("draw"))
                    a = _safe_float(book.get("away"))
                    if h and a:
                        merged["eu_home"] = h
                        merged["eu_draw"] = d
                        merged["eu_away"] = a
                        break

    return merged


# ============ 五源提取 ============

def _extract_european(odds: dict) -> dict | None:
    """提取欧洲赔率信号。"""
    home = _safe_float(odds.get("eu_home"))
    draw = _safe_float(odds.get("eu_draw"))
    away = _safe_float(odds.get("eu_away"))
    if not home or not away:
        return None
    implied = _implied_probs(home, draw or 3.0, away)
    open_home = _safe_float(odds.get("eu_open_home"))
    open_away = _safe_float(odds.get("eu_open_away"))
    move = ""
    if open_home and open_away and open_home > 1.0 and open_away > 1.0:
        if home < open_home - 0.05:
            move = "主胜降水"
        elif away < open_away - 0.05:
            move = "客胜降水"
        elif home > open_home + 0.05:
            move = "主胜升水"
        elif away > open_away + 0.05:
            move = "客胜升水"
    best = max(implied, key=implied.get)
    return {
        "odds": {"home": home, "draw": draw, "away": away},
        "implied": implied,
        "best": best,
        "move": move,
    }


def _extract_asian(odds: dict) -> dict | None:
    """提取亚洲盘口信号。"""
    line = odds.get("ah_line")
    home_water = _safe_float(odds.get("ah_home_water"))
    away_water = _safe_float(odds.get("ah_away_water"))
    if line is None:
        return None
    try:
        line_f = float(line)
    except (TypeError, ValueError):
        return None
    open_line = odds.get("ah_open_line")
    try:
        open_line_f = float(open_line) if open_line is not None else None
    except (TypeError, ValueError):
        open_line_f = None
    # 方向映射：line > 0 主队受让（客队强），line < 0 主队让球（主队强）
    if line_f > 0:
        favored = "away"
    elif line_f < 0:
        favored = "home"
    else:
        favored = "even"
    # 水位变化
    water_move = ""
    open_home_w = _safe_float(odds.get("ah_open_home_water"))
    if home_water and open_home_w:
        if home_water < open_home_w - 0.02:
            water_move = "上盘降水"
        elif home_water > open_home_w + 0.02:
            water_move = "上盘升水"
    return {
        "line": line_f,
        "home_water": home_water,
        "away_water": away_water,
        "open_line": open_line_f,
        "favored": favored,
        "water_move": water_move,
    }


def _extract_betfair(odds: dict) -> dict | None:
    """提取必发信号。volume_total≈0 时不输出热门标签。"""
    bf = odds.get("betfair") or {}
    if not bf.get("has_data") and not bf.get("volume_total"):
        return None
    vol_total = bf.get("volume_total", 0) or 0
    if vol_total < 100:
        return None  # 成交量过低（<100），不输出热门标签
    vol_pct = bf.get("volume_pct") or {}
    vh = _safe_float(vol_pct.get("home")) or 0
    vd = _safe_float(vol_pct.get("draw")) or 0
    va = _safe_float(vol_pct.get("away")) or 0
    # 兼容：仅有 volume_home/draw/away 时合成
    if vh == 0 and vd == 0 and va == 0:
        vh = _safe_float(bf.get("volume_home")) or 0
        vd = _safe_float(bf.get("volume_draw")) or 0
        va = _safe_float(bf.get("volume_away")) or 0
    if vh > 1:
        vh, vd, va = vh / 100, vd / 100, va / 100
    total = vh + vd + va
    if total <= 0:
        return None
    p = {"home": vh / total, "draw": vd / total, "away": va / total}
    trade_price = bf.get("trade_price") or {}
    return {
        "volume_total": bf.get("volume_total", 0),
        "volume_pct": p,
        "trade_price": trade_price,
        "hot": max(p, key=p.get),
    }


def _stats_from_sim_list(sim_list: list) -> dict | None:
    """从 similarity_analysis.open/live 列表中提取最佳 1X2 分布。

    sim_list 是 dict 列表，每个含 count/home_win_rate/draw_rate/away_win_rate。
    优先 open（初盘），取 count 最大的。
    """
    best = None
    best_count = 0
    for item in sim_list:
        if not isinstance(item, dict):
            continue
        count = item.get("count") or 0
        hr = item.get("home_win_rate")
        dr = item.get("draw_rate")
        ar = item.get("away_win_rate")
        if hr is None and ar is None:
            continue
        if count > best_count:
            best_count = count
            best = item
    if not best:
        return None
    hr = float(best.get("home_win_rate") or 0)
    dr = float(best.get("draw_rate") or 0)
    ar = float(best.get("away_win_rate") or 0)
    total = hr + dr + ar
    if total <= 0:
        return None
    return {
        "count": best.get("count", 0),
        "p": {"home": hr / total, "draw": dr / total, "away": ar / total},
        "source": best.get("source", "unknown"),
    }


def _parse_probability_summary(text: str) -> dict | None:
    """从 open_probability_summary 文本中解析 1X2 概率。

    例: "初盘亚盘+欧赔融合相似 240/407 场：主胜 73.9%、平 16.1%、客胜 10.1%"
    """
    if not text:
        return None
    m_h = re.search(r"主胜\s*([\d.]+)%", text)
    m_d = re.search(r"平\s*([\d.]+)%", text)
    m_a = re.search(r"客胜\s*([\d.]+)%", text)
    m_count = re.search(r"(\d+)\s*/\s*(\d+)\s*场", text)
    if not (m_h or m_a):
        return None
    hr = float(m_h.group(1)) / 100 if m_h else 0
    dr = float(m_d.group(1)) / 100 if m_d else 0
    ar = float(m_a.group(1)) / 100 if m_a else 0
    total = hr + dr + ar
    if total <= 0:
        return None
    count = int(m_count.group(2)) if m_count else 0
    return {
        "count": count,
        "p": {"home": hr / total, "draw": dr / total, "away": ar / total},
        "source": "probability_summary",
    }


def _extract_history(prediction: dict | None) -> dict | None:
    """从 prediction 提取历史相似 1X2 分布（多源回落）。"""
    if not prediction:
        return None

    # 1. payload.stats / eu_stats / open_stats（DB prediction 结构）
    payload = prediction.get("payload") or prediction
    stats = payload.get("stats") or {}
    eu_stats = payload.get("eu_stats") or {}
    open_stats = payload.get("open_stats") or {}
    ah_count = stats.get("count") or 0
    eu_count = eu_stats.get("count") or 0
    open_count = open_stats.get("count") or 0
    if ah_count or eu_count or open_count:
        best_stats = open_stats if open_count >= max(ah_count, eu_count) else (stats if ah_count >= eu_count else eu_stats)
        hr = _safe_float(best_stats.get("home_win_rate"))
        dr = _safe_float(best_stats.get("draw_rate"))
        ar = _safe_float(best_stats.get("away_win_rate"))
        if hr is not None or ar is not None:
            hr, dr, ar = float(hr or 0), float(dr or 0), float(ar or 0)
            total = hr + dr + ar
            if total > 0:
                return {
                    "count": best_stats.get("count", 0),
                    "p": {"home": hr / total, "draw": dr / total, "away": ar / total},
                    "source": "open" if best_stats is open_stats else ("eu" if best_stats is eu_stats else "close"),
                }

    # 2. similarity_analysis.open/live（文件 prediction 结构）
    sim = prediction.get("similarity_analysis") or {}
    if isinstance(sim, dict):
        for sub_key in ("open", "live"):
            sub = sim.get(sub_key)
            if isinstance(sub, list) and sub:
                result = _stats_from_sim_list(sub)
                if result:
                    return result
            elif isinstance(sub, dict):
                # 单 dict 形式
                hr = _safe_float(sub.get("home_win_rate"))
                dr = _safe_float(sub.get("draw_rate"))
                ar = _safe_float(sub.get("away_win_rate"))
                if hr is not None or ar is not None:
                    hr, dr, ar = float(hr or 0), float(dr or 0), float(ar or 0)
                    total = hr + dr + ar
                    if total > 0:
                        return {
                            "count": sub.get("count", 0),
                            "p": {"home": hr / total, "draw": dr / total, "away": ar / total},
                            "source": sub.get("source", sub_key),
                        }

    # 3. open_probability_summary 文本解析
    summary = prediction.get("open_probability_summary") or ""
    if summary:
        result = _parse_probability_summary(summary)
        if result:
            return result

    # 4. predict_row 兼容字段
    pr = prediction.get("predict_row") or {}
    if isinstance(pr, dict):
        for rate_key in ("home_win_rate", "胜率", "主胜率"):
            v = _safe_float(pr.get(rate_key))
            if v is not None:
                # 无法确定平/客，跳过
                break

    # 5. sample_count + result_1x2_cn 兜底（只有倾向无分布）
    sc = prediction.get("sample_count") or prediction.get("open_sample_count") or 0
    if sc and sc > 0:
        r1x2 = prediction.get("result_1x2_cn") or prediction.get("open_result_1x2_cn") or ""
        if r1x2:
            p = {"home": 0.33, "draw": 0.34, "away": 0.33}
            if "主" in r1x2:
                p["home"] = 0.50
            elif "客" in r1x2:
                p["away"] = 0.50
            elif "平" in r1x2:
                p["draw"] = 0.45
            total = sum(p.values())
            p = {k: v / total for k, v in p.items()}
            return {"count": sc, "p": p, "source": "fallback_result_cn"}

    return None


def _extract_recent_form(match_name: str, home_team: str | None = None, away_team: str | None = None) -> dict | None:
    """尝试获取近期战绩：优先 team_recent_form（国际队），回落 club_form（联赛队）。"""
    # 1. team_recent_form（世界杯/国际队）
    try:
        from team_recent_form import build_team_form_context
        ctx = build_team_form_context(match_name)
        if ctx:
            home = ctx.get("home") or {}
            away = ctx.get("away") or {}
            if home or away:
                return {
                    "home": {
                        "label": home.get("label", ""),
                        "form_str": home.get("form_str", ""),
                        "win_rate": home.get("win_rate"),
                        "goals_for": home.get("goals_for"),
                        "goals_against": home.get("goals_against"),
                    },
                    "away": {
                        "label": away.get("label", ""),
                        "form_str": away.get("form_str", ""),
                        "win_rate": away.get("win_rate"),
                        "goals_for": away.get("goals_for"),
                        "goals_against": away.get("goals_against"),
                    },
                    "source": "team_recent_form",
                }
    except Exception as exc:
        log.debug("team_recent_form failed: %s", exc)

    # 2. club_form（联赛队，从 PG match_results）
    try:
        from analysis.team_form.club_form import build_club_form
        # 优先使用外部传入的队名
        if home_team and away_team:
            home_team = home_team.strip()
            away_team = away_team.strip()
        else:
            # 兼容 "A vs B" / "AVS B" / "A VS B" / "A对B"
            normalized = match_name
            for sep in (" VS ", " Vs ", " vs ", "VS", "Vs", "vs", "对"):
                if sep in normalized:
                    normalized = normalized.replace(sep, "\x00")
                    break
            parts = normalized.split("\x00")
            if len(parts) != 2:
                return None
            home_team, away_team = parts[0].strip(), parts[1].strip()
        cf = build_club_form(home_team, away_team)
        if not isinstance(cf, dict):
            return None
        overall = cf.get("overall") or {}
        split = cf.get("split") or {}
        h = overall.get("home_team")
        a = overall.get("away_team")
        # 有任一侧 played>0 才算有数据
        if (h and h.get("played")) or (a and a.get("played")):
            h_home = split.get("home_at_home_last_20") or {}
            a_away = split.get("away_at_away_last_20") or {}
            return {
                "home": {
                    "label": h.get("team", home_team) if h else home_team,
                    "form_str": h.get("form_str", "") if h else "",
                    "win_rate": h.get("win_rate") if h else None,
                    "goals_for": h.get("goals_for") if h else None,
                    "goals_against": h.get("goals_against") if h else None,
                    "home_at_home": h_home.get("summary_cn", "") if h_home else "",
                } if h else {"label": home_team},
                "away": {
                    "label": a.get("team", away_team) if a else away_team,
                    "form_str": a.get("form_str", "") if a else "",
                    "win_rate": a.get("win_rate") if a else None,
                    "goals_for": a.get("goals_for") if a else None,
                    "goals_against": a.get("goals_against") if a else None,
                    "away_at_away": a_away.get("summary_cn", "") if a_away else "",
                } if a else {"label": away_team},
                "source": "club_form",
            }
        elif cf and cf.get("missing"):
            log.debug("club_form missing: %s", cf.get("missing"))
    except Exception as exc:
        import traceback
        log.debug("club_form failed: %s\n%s", exc, traceback.format_exc())

    return None


# ============ 主入口 ============

def build_result_forecast_context(
    fixture_id: str,
    *,
    index: dict | None = None,
    prediction: dict | None = None,
) -> dict[str, Any]:
    """组装单场五源预测上下文。

    Args:
        fixture_id: 500.com fixture ID
        index: 预加载的 match index（含 timeline）；不传则从 DB 加载
        prediction: 预加载的 prediction dict；不传则不回落

    Returns:
        含 european/asian/betfair/history_similar/recent_form + missing 的 dict
    """
    # 加载 index
    if index is None:
        try:
            from db_timeline import load_match_index_from_db
            index = load_match_index_from_db(fixture_id)
        except Exception as exc:
            log.warning("load_match_index failed: %s", exc)
            index = None

    # 若 index 的 timeline 无有效 tick：强制合并 DB timeline
    if index:
        file_tl = index.get("timeline") or []
        has_valid = any(_is_valid_tick(t) for t in file_tl)
        if not has_valid:
            try:
                from db_timeline import load_match_index_from_db
                db_idx = load_match_index_from_db(fixture_id)
                if db_idx and db_idx.get("timeline"):
                    db_tl = db_idx["timeline"]
                    if any(_is_valid_tick(t) for t in db_tl):
                        index["timeline"] = db_tl
            except Exception:
                pass

    if not index:
        # 尝试从 DB fixtures 拿队名（无 timeline 也能继续算 club_form）
        fixture = None
        try:
            from db.connection import cursor
            with cursor() as cur:
                cur.execute(
                    "SELECT external_id, match_name, home_team, away_team, source FROM fixtures WHERE external_id = %s",
                    (fixture_id,),
                )
                fixture = cur.fetchone()
        except Exception:
            fixture = None
        if fixture and (fixture.get("home_team") or fixture.get("match_name")):
            index = {
                "fixture_id": fixture_id,
                "match_name": fixture.get("match_name", ""),
                "home_team": fixture.get("home_team", ""),
                "away_team": fixture.get("away_team", ""),
                "timeline": [],
            }
        elif prediction:
            index = {"fixture_id": fixture_id, "match_name": prediction.get("match_name", ""), "timeline": []}
        else:
            return {
                "fixture_id": fixture_id,
                "match_name": "",
                "european": None, "asian": None, "betfair": None,
                "history_similar": None, "recent_form": None,
                "score_range": {"missing": ["no_index"], "bands": [], "top_bands": []},
                "missing": ["european", "asian", "betfair", "history_similar", "recent_form"],
            }

    timeline = index.get("timeline") or []
    # 优先用 home_team/away_team 拼 match_name（DB match_name 可能是联赛名）
    home_team = index.get("home_team") or ""
    away_team = index.get("away_team") or ""
    if home_team and away_team:
        match_name = f"{home_team}VS{away_team}"
    else:
        match_name = index.get("match_name") or (prediction.get("match_name", "") if prediction else "") or fixture_id

    # 合并 odds：timeline tick + prediction.odds_snapshot/cur/quant
    tick_odds = _from_tick(timeline)
    odds = _merge_odds(tick_odds, prediction)

    missing: list[str] = []
    european = _extract_european(odds) if odds else None
    if not european:
        missing.append("european")
    asian = _extract_asian(odds) if odds else None
    if not asian:
        missing.append("asian")
    betfair = _extract_betfair(odds) if odds else None
    if not betfair:
        missing.append("betfair")

    history = _extract_history(prediction)
    if not history:
        try:
            from analysis.result_forecast.history_similar import build_history_similar
            history = build_history_similar(fixture_id, phase="open", use_ah=False)
        except Exception as exc:
            logger.warning("build_history_similar 失败 %s: %s", fixture_id, exc)
            history = None
    if not history:
        missing.append("history_similar")

    recent = _extract_recent_form(match_name, home_team=home_team, away_team=away_team)
    if not recent:
        missing.append("recent_form")

    # 同时保留 club_form 原结构供 viz summary 使用
    club_form = None
    try:
        from analysis.team_form.club_form import build_club_form

        parts = match_name.replace(" VS ", " vs ").replace(" Vs ", " vs ").split(" vs ")
        if len(parts) == 2:
            h, a = parts[0].strip(), parts[1].strip()
            club_form = build_club_form(h, a)
    except Exception:
        pass

    # 盘口 lifecycle（开盘 vs 临盘）
    market_open_close = None
    try:
        from analysis.market.odds_lifecycle import get_match_odds_lifecycle

        market_open_close = get_match_odds_lifecycle(str(fixture_id))
        if market_open_close and market_open_close.get("error"):
            market_open_close = None
    except Exception as exc:
        log.debug("market_open_close failed for %s: %s", fixture_id, exc)
        market_open_close = None

    # 尝试获取 missing_reason 供 UI 展示
    recent_missing_reason = ""
    if not recent:
        try:
            from analysis.team_form.club_form import build_club_form
            parts = match_name.replace(" VS ", " vs ").replace(" Vs ", " vs ").split(" vs ")
            if len(parts) == 2:
                home_team, away_team = parts[0].strip(), parts[1].strip()
                cf = build_club_form(home_team, away_team)
                if cf and cf.get("missing"):
                    recent_missing_reason = f"库无历史：{home_team}/{away_team} 未映射或无赛果"
        except Exception:
            pass

    ctx = {
        "fixture_id": fixture_id,
        "match_name": match_name,
        "home_team": home_team,
        "away_team": away_team,
        "european": european,
        "asian": asian,
        "betfair": betfair,
        "market_open_close": market_open_close,
        "history_similar": history,
        "recent_form": recent,
        "recent_missing_reason": recent_missing_reason,
        "club_form": club_form,
        "missing": missing,
    }

    # 欧亚分歧（DB 主链）
    try:
        from analysis.market.eu_ah_divergence_ctx import build_eu_ah_divergence

        ctx["divergence"] = build_eu_ah_divergence(str(fixture_id))
    except Exception as exc:
        log.debug("divergence 接入 context 失败 %s: %s", fixture_id, exc)
        ctx["divergence"] = {"missing": ["context_build_error"], "fixture_id": str(fixture_id)}

    # 市场态度（赔率变动）
    try:
        from analysis.market import market_attitude

        ma_features = market_attitude.build_move_features(str(fixture_id))
        if "missing" not in ma_features:
            ctx["market_attitude"] = {
                "features": ma_features,
                "attitude": market_attitude.classify_attitude(ma_features),
            }
        else:
            ctx["market_attitude"] = {"missing": ma_features["missing"], "external_id": str(fixture_id)}
    except Exception as exc:
        log.debug("market_attitude 接入 context 失败 %s: %s", fixture_id, exc)
        ctx["market_attitude"] = {"missing": ["context_build_error"], "fixture_id": str(fixture_id)}

    # 比分区间预测（接入主链，但不压过主结论）
    try:
        from analysis.market.score_range import build_score_range_forecast

        ctx["score_range"] = build_score_range_forecast(fixture_id, context=ctx)
    except Exception as exc:
        log.debug("score_range 接入 context 失败 %s: %s", fixture_id, exc)
        ctx["score_range"] = {"missing": ["context_build_error"], "bands": [], "top_bands": []}

    return ctx
