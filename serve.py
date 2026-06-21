#!/usr/bin/env python3
"""HTTP service: hourly 500.com download + football prediction + match detail pages."""

from __future__ import annotations

import argparse
import html
import json
import logging
import os
import re
import sys
import threading
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import config as app_cfg
from hourly_pipeline import (
    get_history,
    get_state,
    list_runs,
    run_hourly_job,
    run_single_match_ai,
    seconds_until_next_hour,
    set_next_scheduled,
)
from db_timeline import load_match_index_from_db
from match_timeline import load_ai_records, load_deep_analyses, load_match_index, rebuild_from_runs
from timeline_merge import load_latest_poll_meta, merge_match_indexes
from time_utils import now_beijing
from daily_picks import load_daily_picks_from_output, save_daily_picks
from share_card import build_parlay_share_context, build_share_context, html_share_match, html_share_parlay
from web_ui import html_ah_analytics, html_ai_settings, html_daily_picks, html_dashboard, html_eu_ah_divergence, html_group_stage, html_kelly_calculator, html_match_detail, html_quant_analytics, html_recommendation_review, html_worldcup_ledger


def _error_html(body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>提示</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 0 auto; padding: 16px clamp(12px, 3vw, 24px);
       max-width: min(720px, 100%); line-height: 1.6; color: #1a1a1a; background: #f0f2f5; }}
a {{ color: #2563eb; }}
.card {{ background: #fff; border-radius: 10px; padding: 16px; margin-top: 12px; box-shadow: 0 1px 4px rgba(0,0,0,.06); }}
</style></head><body>
<p><a href="/">← 返回首页</a></p>
<div class="card">{body}</div>
</body></html>"""

log = logging.getLogger("serve")
_FID_RE = re.compile(r"^/match/(\d+)$")
_SHARE_RE = re.compile(r"^/share/match/(\d+)$")
_API_FID_RE = re.compile(r"^/api/match/(\d+)/timeline$")
_API_RECOMMEND_RE = re.compile(r"^/api/match/(\d+)/recommend$")
_API_DEEP_RE = re.compile(r"^/api/match/(\d+)/deep-analyze$")
_API_SCORE_RE = re.compile(r"^/api/match/(\d+)/score-recommend$")
_API_SWEET_RE = re.compile(r"^/api/match/(\d+)/sweet-spot$")
_API_CHAT_RE = re.compile(r"^/api/match/(\d+)/chat-stream$")
_daily_ai_lock = threading.Lock()
_daily_ai_running = False


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _load_match_index(output_root: Path, fid: str) -> dict | None:
    db_idx = load_match_index_from_db(fid)
    file_idx = load_match_index(output_root, fid)
    return merge_match_indexes(db_idx, file_idx)


def _load_latest_pred(output_root: Path, fid: str) -> dict | None:
    from analysis.ai.deep import load_richest_prediction

    return load_richest_prediction(output_root, fid)


def _existing_path(path_text: str | None, output_root: Path | None = None) -> Path | None:
    if not path_text:
        return None
    p = Path(path_text)
    candidates = [p]
    if output_root is not None and not p.is_absolute():
        candidates.append(output_root.parent.parent / p)
    for c in candidates:
        if c.is_file():
            return c
    return None


def _ensure_similarity_analysis(pred: dict | None, output_root: Path | None = None) -> None:
    if not pred or pred.get("similarity_analysis"):
        return
    ah = _existing_path(pred.get("xls_asian"), output_root)
    eu = _existing_path(pred.get("xls_european"), output_root)
    if not ah or not eu:
        return
    try:
        from analysis.pipeline import ensure_similarity

        ensure_similarity(pred, ah_path=ah, eu_path=eu, history=get_history())
    except Exception:
        log.exception("相似样本临时重算失败")


def _ensure_quant_analysis(pred: dict | None, idx: dict | None = None) -> None:
    if not pred or pred.get("quant"):
        return
    cur = dict(pred.get("odds_snapshot") or {})
    if idx:
        timeline = idx.get("timeline") or []
        if timeline:
            latest_odds = (timeline[-1].get("odds") or {})
            for k, v in latest_odds.items():
                cur.setdefault(k, v)
    try:
        from analysis.pipeline import ensure_quant

        ensure_quant(pred, cur=cur or None)
    except Exception:
        log.exception("量化分析附加失败")
    try:
        from analysis.score_recommend import attach_score_recommendation

        attach_score_recommendation(pred)
    except Exception:
        log.exception("比分推荐附加失败")


def _ensure_post_recommendation(pred: dict | None) -> None:
    if not pred:
        return
    try:
        from jingcai_pick import ensure_match_jingcai
        from analysis.rules.output import attach_post_recommendation

        ensure_match_jingcai(pred)
        attach_post_recommendation(pred)
    except Exception:
        log.exception("稳胆/甜区分析附加失败")


from jingcai_pick import final_recommendation_cn


def _compact_match_for_chat(m: dict | None) -> dict:
    if not m:
        return {}
    row = m.get("predict_row") or {}
    return {
        "fixture_id": m.get("fixture_id"),
        "match": m.get("match") or row.get("比赛"),
        "final_pick": final_recommendation_cn(m),
        "match_result": m.get("match_result_1x2_cn") or row.get("赛果预测"),
        "scores": row.get("推荐比分") or m.get("likely_scores_detail") or m.get("likely_scores"),
        "asian": row.get("亚盘") or m.get("asian_handicap_cn"),
        "confidence": row.get("置信度") or m.get("confidence_cn"),
        "value_bet": m.get("value_bet"),
        "summary": (m.get("summary") or "")[:700],
        "actuary_reasoning": m.get("actuary_reasoning"),
        "market_pattern_summary": m.get("market_pattern_summary"),
        "market_pattern_names": m.get("market_pattern_names"),
        "risk_level": m.get("risk_level_cn"),
        "control_level": m.get("control_level_cn"),
        "jingcai": m.get("jingcai_pick_info") or {},
    }


def _chat_profile(provider: str, output_root: Path | None = None):
    from ai_profiles import get_profile_by_id

    provider = (provider or "deepseek").strip().lower()
    prof = get_profile_by_id(provider, output_root=output_root)
    if prof:
        return prof
    raise ValueError(f"未配置或不可用的 AI provider: {provider}")


def _parse_chat_answer(text: str) -> str:
    from ai_prompt import _extract_json_text
    try:
        data = json.loads(_extract_json_text(text))
        if isinstance(data, dict):
            return str(data.get("answer") or data.get("summary") or data.get("result") or text)
    except Exception:
        pass
    return text


def _ask_ai_chat(
    *,
    provider: str,
    prompt: str,
    context: dict,
    scope: str,
    output_root: Path | str | None = None,
) -> tuple[str, str]:
    from deepseek_client import chat

    prof = _chat_profile(provider, output_root=Path(output_root or "output/service"))
    api_key = prof.resolve_api_key()
    if not api_key:
        raise RuntimeError(f"未配置 {prof.api_key_env}")

    system = (
        "你是足球盘口人工复核助手。你的任务不是重新给强推荐，而是帮助用户做人工干预。"
        "重点分析：欧亚互转暗线、EV是否足够、诱盘/控盘、平局分流、串关风险。"
        "只能使用输入 context，不得编造新闻、伤病、天气。"
        "输出 JSON：{\"answer\":\"...\"}。answer 用中文，结构清晰，给出人工干预建议。"
    )
    user = {
        "scope": scope,
        "user_question": prompt,
        "context": context,
        "required_style": (
            "先给人工复核结论，再列关键原因，最后给可执行建议。"
            "如果证据不足，要明确说只能观望或小仓位。"
        ),
    }
    text = chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False, default=str)},
        ],
        api_key=api_key,
        model=prof.model,
        base_url=prof.base_url,
        temperature=0.25,
        max_tokens=1800,
        timeout=180,
    )
    return prof.label, _parse_chat_answer(text)


def _sse_write(handler: BaseHTTPRequestHandler, event: str, data: str) -> None:
    handler.wfile.write(f"event: {event}\n".encode("utf-8"))
    for line in str(data).splitlines() or [""]:
        handler.wfile.write(f"data: {line}\n".encode("utf-8"))
    handler.wfile.write(b"\n")
    handler.wfile.flush()


def _send_chat_sse(
    handler: BaseHTTPRequestHandler,
    *,
    provider: str,
    prompt: str,
    context: dict,
    scope: str,
    output_root: Path | str | None = None,
) -> None:
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("Connection", "keep-alive")
    handler.end_headers()
    try:
        label, answer = _ask_ai_chat(
            provider=provider,
            prompt=prompt,
            context=context,
            scope=scope,
            output_root=output_root or getattr(handler, "output_root", None),
        )
        _sse_write(handler, "chunk", f"【{label}】\n")
        step = 80
        for i in range(0, len(answer), step):
            _sse_write(handler, "chunk", answer[i:i + step])
        _sse_write(handler, "done", "ok")
    except Exception as exc:
        log.exception("AI chat SSE failed")
        _sse_write(handler, "chunk", f"错误：{exc}")
        _sse_write(handler, "done", "error")


def _pred_summary(pred: dict) -> dict:
    scores = pred.get("likely_scores_detail") or pred.get("likely_scores") or []
    if isinstance(scores, list):
        scores_txt = "、".join(str(s) for s in scores[:3])
    else:
        scores_txt = str(scores)
    final_pick = final_recommendation_cn(pred)
    out = {
        "ok": True,
        "fixture_id": pred.get("fixture_id"),
        "match": pred.get("match"),
        "result_1x2_cn": final_pick,
        "final_pick_cn": final_pick,
        "match_result_1x2_cn": pred.get("match_result_1x2_cn"),
        "likely_scores": scores_txt,
        "asian_handicap_cn": pred.get("asian_handicap_cn"),
        "over_under_cn": pred.get("over_under_cn"),
        "confidence_cn": pred.get("confidence_cn"),
        "summary": pred.get("summary"),
        "manual_ai": pred.get("manual_ai", True),
        "recommendation_source": pred.get("recommendation_source"),
        "ai_providers": pred.get("ai_providers") or [],
    }
    analyses = pred.get("ai_analyses") or {}
    if analyses:
        out["ai_analyses"] = {
            k: {
                "result_1x2_cn": final_recommendation_cn(v),
                "final_pick_cn": final_recommendation_cn(v),
                "likely_scores": v.get("likely_scores_detail") or v.get("likely_scores"),
                "asian_handicap_cn": v.get("asian_handicap_cn"),
                "confidence_cn": v.get("confidence_cn"),
                "summary": (v.get("summary") or "")[:300],
                "actuary_reasoning": v.get("actuary_reasoning"),
                "ai_provider_label": v.get("ai_provider_label"),
            }
            for k, v in analyses.items()
        }
    return out


class Handler(BaseHTTPRequestHandler):
    output_root: Path = Path("output/service")
    within_days: float = 7
    use_ai: bool = False
    ai_model: str = "deepseek-chat"
    ai_mode: str = "expert"
    ai_base_url: str | None = None
    dual_ai: bool = False
    ai_model_b: str | None = None
    ai_base_url_b: str | None = None
    skip_unchanged: bool = True
    ai_interval_sec: int = app_cfg.AI_INTERVAL_MINUTES * 60
    force_ai: bool = False

    def log_message(self, fmt, *args):
        log.info("%s - %s", self.address_string(), fmt % args)

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, indent=2, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str, status=200):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _trigger_run(self, background: bool = True, *, force_ai: bool | None = None) -> dict:
        force = self.force_ai if force_ai is None else force_ai

        def _job():
            try:
                run_hourly_job(
                    self.output_root,
                    within_days=self.within_days,
                    use_ai=self.use_ai,
                    ai_model=self.ai_model,
                    ai_mode=self.ai_mode,
                    ai_base_url=self.ai_base_url,
                    dual_ai=self.dual_ai,
                    ai_model_b=self.ai_model_b,
                    ai_base_url_b=self.ai_base_url_b,
                    skip_unchanged=self.skip_unchanged,
                    ai_interval_sec=self.ai_interval_sec,
                    force_ai=force,
                )
            except RuntimeError as exc:
                log.warning("%s", exc)

        if get_state().get("running"):
            return {"ok": False, "error": "任务运行中", "state": get_state()}

        if background:
            threading.Thread(target=_job, daemon=True).start()
            return {"ok": True, "message": "任务已启动", "state": get_state()}
        run_hourly_job(
            self.output_root,
            within_days=self.within_days,
            use_ai=self.use_ai,
            ai_model=self.ai_model,
            ai_mode=self.ai_mode,
            ai_base_url=self.ai_base_url,
            dual_ai=self.dual_ai,
            ai_model_b=self.ai_model_b,
            ai_base_url_b=self.ai_base_url_b,
            skip_unchanged=self.skip_unchanged,
            ai_interval_sec=self.ai_interval_sec,
            force_ai=force,
        )
        return {"ok": True, "message": "任务已完成", "state": get_state()}

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        root = self.output_root

        sm = _SHARE_RE.match(path)
        if sm:
            fid = sm.group(1)
            idx = _load_match_index(root, fid)
            if idx is None:
                self._send_html(
                    _error_html(f"<p>暂无该比赛</p>"),
                    404,
                )
                return
            pred = _load_latest_pred(root, fid)
            ctx = build_share_context(
                fid,
                match_name=idx.get("match_name") or "",
                timeline=idx.get("timeline") or [],
                prediction=pred,
            )
            self._send_html(html_share_match(ctx))
            return

        if path == "/share/parlay":
            qs = parse_qs(urlparse(self.path).query)
            raw_ids = qs.get("ids", [""])[0]
            fixture_ids = [x.strip() for x in raw_ids.split(",") if x.strip()]
            if len(fixture_ids) != 2:
                self._send_html(
                    _error_html(
                        "<p>请在 URL 中提供 2 个 fixture_id，"
                        "例如 <code>/share/parlay?ids=123,456</code></p>"
                    ),
                    400,
                )
                return
            try:
                from custom_parlay import analyze_custom_parlay, load_matches_for_parlay
                matches = load_matches_for_parlay(root, fixture_ids)
                analysis = analyze_custom_parlay(matches)
                ctx = build_parlay_share_context(analysis)
                self._send_html(html_share_parlay(ctx))
            except ValueError as exc:
                self._send_html(
                    _error_html(f"<p>{html.escape(str(exc))}</p>"),
                    404,
                )
            except Exception as exc:
                log.exception("2串1 分享图失败")
                self._send_html(
                    _error_html(f"<p>生成失败：{html.escape(str(exc))}</p>"),
                    500,
                )
            return

        m = _FID_RE.match(path)
        if m:
            fid = m.group(1)
            idx = _load_match_index(root, fid)
            if idx is None:
                self._send_html(
                    _error_html(f"<p>暂无该比赛历史（FID {html.escape(fid)}）</p>"),
                    404,
                )
                return
            pred = _load_latest_pred(root, fid)
            _ensure_similarity_analysis(pred, root)
            _ensure_quant_analysis(pred, idx)
            _ensure_post_recommendation(pred)
            ai_records = load_ai_records(root, fid)
            deep_records = load_deep_analyses(root, fid)
            from match_settlement import load_settled_map
            settled = load_settled_map(root).get(fid)
            self._send_html(html_match_detail(
                idx, prediction=pred, ai_records=ai_records,
                deep_records=deep_records, settled=settled,
                output_root=root,
            ))
            return

        am = _API_FID_RE.match(path)
        if am:
            idx = _load_match_index(root, am.group(1))
            if idx is None:
                self._send_json({"error": "not found"}, 404)
            else:
                self._send_json(idx)
            return

        sm = _API_SCORE_RE.match(path)
        if sm:
            fid = sm.group(1)
            pred = _load_latest_pred(root, fid)
            if pred is None:
                self._send_json({"ok": False, "error": "not found"}, 404)
                return
            _ensure_quant_analysis(pred, _load_match_index(root, fid))
            from score_recommend import build_score_recommendation

            self._send_json(build_score_recommendation(pred))
            return

        swm = _API_SWEET_RE.match(path)
        if swm:
            fid = swm.group(1)
            pred = _load_latest_pred(root, fid)
            if pred is None:
                self._send_json({"ok": False, "error": "not found"}, 404)
                return
            _ensure_quant_analysis(pred, _load_match_index(root, fid))
            _ensure_post_recommendation(pred)
            from accuracy_pick import build_sweet_spot_analysis

            self._send_json(build_sweet_spot_analysis(pred))
            return

        cm = _API_CHAT_RE.match(path)
        if cm:
            fid = cm.group(1)
            qs = parse_qs(urlparse(self.path).query)
            prompt = (qs.get("prompt", [""])[0] or "").strip()
            provider = qs.get("provider", ["deepseek"])[0]
            if not prompt:
                self._send_json({"ok": False, "error": "prompt required"}, 400)
                return
            pred = _load_latest_pred(root, fid)
            idx = _load_match_index(root, fid) or {}
            context = {
                "match": _compact_match_for_chat(pred),
                "timeline_summary": {
                    "fixture_id": fid,
                    "match_name": idx.get("match_name"),
                    "updated_at": idx.get("updated_at"),
                    "changes": (idx.get("changes") or [])[-10:],
                    "latest": (idx.get("timeline") or [])[-1:] if isinstance(idx.get("timeline"), list) else [],
                },
            }
            _send_chat_sse(
                self, provider=provider, prompt=prompt, context=context,
                scope="match", output_root=self.output_root,
            )
            return

        if path == "/":
            latest = _read_json(root / "latest.json")
            qs = parse_qs(urlparse(self.path).query)
            match_date = qs.get("date", [None])[0]
            self._send_html(html_dashboard(
                get_state(), latest, output_root=root,
                within_days=self.within_days,
                match_date=match_date,
            ))
            return
        if path == "/api/dashboard/chat-stream":
            qs = parse_qs(urlparse(self.path).query)
            prompt = (qs.get("prompt", [""])[0] or "").strip()
            provider = qs.get("provider", ["deepseek"])[0]
            if not prompt:
                self._send_json({"ok": False, "error": "prompt required"}, 400)
                return
            from daily_picks import load_dashboard_matches, load_kickoff_map
            from match_settlement import classify_matches, load_settled_map

            matches = load_dashboard_matches(root, within_days=self.within_days)
            kickoff_map = load_kickoff_map()
            upcoming, live, finished = classify_matches(
                matches, kickoff_map=kickoff_map, settled_map=load_settled_map(root),
            )
            active = upcoming + live
            latest_payload = _read_json(root / "latest.json") or {}
            context = {
                "state": get_state(),
                "active_count": len(active),
                "finished_count": len(finished),
                "active_matches": [_compact_match_for_chat(m) for m in active[:20]],
                "latest_generated_at": latest_payload.get("generated_at"),
            }
            _send_chat_sse(
                self, provider=provider, prompt=prompt, context=context,
                scope="dashboard", output_root=self.output_root,
            )
            return
        if path == "/daily":
            qs = parse_qs(urlparse(self.path).query)
            match_date = qs.get("date", [None])[0]
            payload = load_daily_picks_from_output(root, match_date=match_date)
            self._send_html(html_daily_picks(payload))
            return
        if path == "/share/daily-safe":
            qs = parse_qs(urlparse(self.path).query)
            match_date = qs.get("date", [None])[0]
            payload = load_daily_picks_from_output(root, match_date=match_date)
            tier = payload.get("fallback_safe")
            if not tier:
                self._send_json({"ok": False, "error": "暂无保底 2串1 候选"}, 404)
                return
            from daily_picks import daily_tier_to_parlay_analysis
            analysis = daily_tier_to_parlay_analysis(
                tier,
                generated_at=payload.get("generated_at") or "",
            )
            self._send_html(html_share_parlay(build_parlay_share_context(analysis)))
            return
        if path == "/worldcup/groups":
            from group_stage_model import build_group_stage_report
            qs = parse_qs(urlparse(self.path).query)
            force = qs.get("refresh", ["0"])[0] in ("1", "true", "yes")
            self._send_html(html_group_stage(build_group_stage_report(force_refresh=force)))
            return
        if path == "/api/worldcup/groups":
            from group_stage_model import build_group_stage_report
            qs = parse_qs(urlparse(self.path).query)
            force = qs.get("refresh", ["0"])[0] in ("1", "true", "yes")
            self._send_json(build_group_stage_report(force_refresh=force))
            return
        if path == "/worldcup":
            from worldcup_analytics import build_tournament_ledger
            ledger = build_tournament_ledger(
                root,
                include_ai_watch=True,
                ai_model=self.ai_model,
                ai_base_url=self.ai_base_url,
            )
            self._send_html(html_worldcup_ledger(ledger))
            return
        if path == "/handicap":
            from ah_analytics import build_ah_ledger
            self._send_html(html_ah_analytics(build_ah_ledger(root)))
            return
        if path == "/quant":
            from quant_analytics import build_quant_backtest_report, refresh_elo_from_settled
            from time_utils import now_beijing_str

            refresh_elo_from_settled(root)
            report = build_quant_backtest_report(root)
            report["updated_at"] = now_beijing_str()
            self._send_html(html_quant_analytics(report))
            return
        if path == "/review":
            from recommendation_review import build_recommendation_review

            self._send_html(html_recommendation_review(build_recommendation_review(root)))
            return
        if path == "/divergence":
            from eu_ah_divergence import build_divergence_report

            qs = parse_qs(urlparse(self.path).query)
            min_score = qs.get("min_score", [None])[0]
            try:
                min_score_int = int(min_score) if min_score else None
            except ValueError:
                min_score_int = None
            report = build_divergence_report(root, min_score=min_score_int)
            self._send_html(html_eu_ah_divergence(report))
            return
        if path == "/settings/ai":
            from ai_config import editable_config_summary

            self._send_html(html_ai_settings(editable_config_summary(root)))
            return
        if path == "/kelly":
            qs = parse_qs(urlparse(self.path).query)
            fid = (qs.get("fixture_id", [None])[0] or "").strip()
            prefill = None
            initial = None
            if fid:
                pred = _load_latest_pred(root, fid)
                _ensure_similarity_analysis(pred, root)
                idx = _load_match_index(root, fid) or {}
                _ensure_quant_analysis(pred, idx)
                from kelly import compute_kelly, kelly_prefill_from_prediction
                prefill = kelly_prefill_from_prediction(pred, fixture_id=fid)
                if prefill.get("probability_pct") is not None and prefill.get("odds_value") is not None:
                    kwargs: dict = {
                        "probability": prefill["probability_pct"] / 100,
                        "fraction": 0.5,
                    }
                    if prefill.get("odds_type") == "water":
                        kwargs["water"] = prefill["odds_value"]
                    else:
                        kwargs["decimal_odds"] = prefill["odds_value"]
                    initial = compute_kelly(**kwargs)
            self._send_html(html_kelly_calculator(prefill, initial_result=initial))
            return
        if path == "/api/handicap/ledger":
            from ah_analytics import build_ah_ledger
            self._send_json(build_ah_ledger(root))
            return
        if path == "/api/quant/report":
            from quant_analytics import build_quant_backtest_report, refresh_elo_from_settled
            from time_utils import now_beijing_str

            refresh_elo_from_settled(root)
            report = build_quant_backtest_report(root)
            report["updated_at"] = now_beijing_str()
            self._send_json(report)
            return
        if path == "/api/review":
            from recommendation_review import build_recommendation_review

            self._send_json(build_recommendation_review(root))
            return
        if path == "/api/divergence/report":
            from eu_ah_divergence import build_divergence_report

            qs = parse_qs(urlparse(self.path).query)
            min_score = qs.get("min_score", [None])[0]
            try:
                min_score_int = int(min_score) if min_score else None
            except ValueError:
                min_score_int = None
            self._send_json(build_divergence_report(root, min_score=min_score_int))
            return
        if path == "/api/worldcup/ledger":
            from worldcup_analytics import build_tournament_ledger
            self._send_json(build_tournament_ledger(
                root,
                include_ai_watch=True,
                ai_model=self.ai_model,
                ai_base_url=self.ai_base_url,
            ))
            return
        if path == "/api/status" or path == "/health":
            from ai_schedule import ai_schedule_info
            from ai_config import public_config_summary

            state = get_state()
            state["ai_schedule"] = ai_schedule_info(self.output_root)
            state["ai_auto_enabled"] = app_cfg.AI_AUTO_ENABLED
            state["ai_interval_minutes"] = app_cfg.AI_INTERVAL_MINUTES
            state["ai_config"] = public_config_summary(self.output_root)
            self._send_json(state)
            return
        if path == "/api/ai/providers":
            from ai_config import list_provider_entries, load_raw_config

            qs = parse_qs(urlparse(self.path).query)
            role = (qs.get("role", [None])[0] or "").strip() or None
            configured_only = qs.get("configured", ["0"])[0] in ("1", "true", "yes")
            cfg = load_raw_config(self.output_root)
            providers = list_provider_entries(
                cfg,
                role=role,
                configured_only=configured_only,
            )
            self._send_json({
                "role": role,
                "primary_id": cfg.get("primary_id"),
                "predict_mode": cfg.get("predict_mode"),
                "providers": providers,
            })
            return
        if path == "/api/ai/config":
            from ai_config import public_config_summary

            self._send_json(public_config_summary(self.output_root))
            return
        if path == "/api/latest":
            data = _read_json(root / "latest.json")
            if data is None:
                self._send_json({"matches": [], "message": "尚无分析结果"}, 404)
            else:
                self._send_json(data)
            return
        if path == "/api/daily-picks":
            qs = parse_qs(urlparse(self.path).query)
            match_date = qs.get("date", [None])[0]
            payload = load_daily_picks_from_output(root, match_date=match_date)
            self._send_json(payload)
            return
        if path == "/api/runs":
            qs = parse_qs(urlparse(self.path).query)
            limit = int(qs.get("limit", ["20"])[0])
            self._send_json({"runs": list_runs(root, limit=limit)})
            return
        if path == "/api/db/status":
            try:
                from db.connection import ping
                from db.repository import db_stats, get_scraper_state
                if not ping():
                    self._send_json({"ok": False, "error": "database unreachable"}, 503)
                    return
                self._send_json({
                    "ok": True,
                    "stats": db_stats(),
                    "last_poll": get_scraper_state("poll_500_last_run"),
                })
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, 500)
            return
        if path == "/api/db/fixtures":
            try:
                from db.repository import list_fixtures
                qs = parse_qs(urlparse(self.path).query)
                limit = int(qs.get("limit", ["50"])[0])
                self._send_json({"fixtures": list_fixtures(limit=limit)})
            except Exception as exc:
                self._send_json({"error": str(exc)}, 500)
            return
        self._send_json({"error": "not found", "path": path}, 404)

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/")
        qs = parse_qs(urlparse(self.path).query)
        if path == "/api/run":
            force_ai = qs.get("force_ai", ["0"])[0] in ("1", "true", "yes")
            self._send_json(self._trigger_run(background=True, force_ai=force_ai))
            return
        if path == "/api/rebuild-timeline":
            n = rebuild_from_runs(self.output_root)
            self._send_json({"ok": True, "records": n})
            return
        if path == "/api/settle":
            from match_settlement import run_settlement
            self._send_json(run_settlement(self.output_root))
            return
        if path == "/api/ai/config":
            try:
                from ai_config import editable_config_summary, save_config, validate_config_patch

                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length else b"{}"
                payload = json.loads(raw.decode("utf-8"))
                errors = validate_config_patch(payload)
                if errors:
                    self._send_json({"ok": False, "errors": errors}, 400)
                    return
                path_saved = save_config(payload, self.output_root)
                self._send_json({
                    "ok": True,
                    "path": str(path_saved),
                    "config": editable_config_summary(self.output_root),
                })
            except json.JSONDecodeError:
                self._send_json({"ok": False, "error": "请求体须为 JSON"}, 400)
            except Exception as exc:
                log.exception("保存 AI 配置失败")
                self._send_json({"ok": False, "error": str(exc)}, 500)
            return
        if path == "/api/ai/test":
            try:
                from ai_config import test_provider_connection

                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length else b"{}"
                payload = json.loads(raw.decode("utf-8"))
                provider_id = str(payload.get("provider_id") or qs.get("provider_id", [""])[0]).strip()
                if not provider_id:
                    self._send_json({"ok": False, "error": "provider_id required"}, 400)
                    return
                result = test_provider_connection(provider_id, output_root=self.output_root)
                self._send_json(result, 200 if result.get("ok") else 502)
            except json.JSONDecodeError:
                self._send_json({"ok": False, "error": "请求体须为 JSON"}, 400)
            except Exception as exc:
                log.exception("AI 连通测试失败")
                self._send_json({"ok": False, "error": str(exc)}, 500)
            return
        if path == "/api/kelly/calc":
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length else b"{}"
                payload = json.loads(raw.decode("utf-8"))
                from kelly import compute_kelly

                prob = payload.get("probability")
                if prob is None and payload.get("probability_pct") is not None:
                    prob = float(payload["probability_pct"]) / 100
                odds_type = payload.get("odds_type") or "decimal"
                odds_val = payload.get("odds_value") or payload.get("odds")
                kwargs = {
                    "probability": float(prob),
                    "fraction": float(payload.get("fraction", 0.5)),
                    "bankroll": payload.get("bankroll"),
                }
                if odds_type == "water":
                    kwargs["water"] = odds_val
                else:
                    kwargs["decimal_odds"] = odds_val
                self._send_json(compute_kelly(**kwargs))
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, 400)
            return
        if path == "/api/worldcup/refresh":
            from worldcup_analytics import refresh_tournament_ledger
            try:
                ledger = refresh_tournament_ledger(
                    self.output_root,
                    include_ai_watch=True,
                    ai_model=self.ai_model,
                    ai_base_url=self.ai_base_url,
                    force_ai_watch=True,
                )
                self._send_json({"ok": True, "ledger": ledger})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, 500)
            return
        if path == "/api/worldcup/match-ai":
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length else b"{}"
                payload = json.loads(raw.decode("utf-8"))
                fid = str(payload.get("fixture_id") or qs.get("fixture_id", [""])[0]).strip()
                if not fid:
                    self._send_json({"ok": False, "error": "fixture_id required"}, 400)
                    return
                force = payload.get("force") is True or qs.get("force", ["0"])[0] in ("1", "true", "yes")
                from worldcup_analytics import build_upcoming_match_ai_watch
                result = build_upcoming_match_ai_watch(
                    self.output_root,
                    fid,
                    ai_model=self.ai_model,
                    ai_base_url=self.ai_base_url,
                    force=force,
                )
                self._send_json(result, 200 if result.get("ok") else 500)
            except json.JSONDecodeError:
                self._send_json({"ok": False, "error": "请求体须为 JSON"}, 400)
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, 400)
            except Exception as exc:
                log.exception("世界杯单场AI分析失败")
                self._send_json({"ok": False, "error": str(exc)}, 500)
            return
        if path == "/api/parlay/analyze":
            use_ai = qs.get("ai", ["0"])[0] in ("1", "true", "yes")
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length else b"{}"
                payload = json.loads(raw.decode("utf-8"))
                fixture_ids = payload.get("fixture_ids") or []
                if len(fixture_ids) != 2:
                    self._send_json({"ok": False, "error": "请勾选恰好 2 场比赛"}, 400)
                    return
                from custom_parlay import (
                    analyze_custom_parlay,
                    load_matches_for_parlay,
                    merge_ai_into_explanation,
                    run_parlay_ai_brief,
                )
                matches = load_matches_for_parlay(self.output_root, fixture_ids)
                result = analyze_custom_parlay(matches)
                if use_ai:
                    try:
                        ai_brief = run_parlay_ai_brief(
                            result,
                            ai_model=self.ai_model,
                            ai_base_url=self.ai_base_url,
                        )
                        result["ai_brief"] = ai_brief
                        merge_ai_into_explanation(result, ai_brief)
                        result["source"] = "local+ai_brief"
                    except Exception as exc:
                        log.warning("2串1 AI 简评失败: %s", exc)
                        result["ai_error"] = str(exc)
                self._send_json(result)
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, 400)
            except json.JSONDecodeError:
                self._send_json({"ok": False, "error": "请求体须为 JSON"}, 400)
            except Exception as exc:
                log.exception("2串1 分析失败")
                self._send_json({"ok": False, "error": str(exc)}, 500)
            return
        if path == "/api/list-parlay/ai":
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length else b"{}"
                payload = json.loads(raw.decode("utf-8"))
                provider = payload.get("provider") or qs.get("provider", ["deepseek"])[0]
                target_date = payload.get("date") or qs.get("date", [None])[0]

                from daily_picks import load_dashboard_matches, load_kickoff_map
                from list_parlay_ai import recommend_list_parlay
                from match_settlement import classify_matches, load_settled_map

                matches = load_dashboard_matches(self.output_root, within_days=self.within_days)
                kickoff_map = load_kickoff_map()
                upcoming, live, _finished = classify_matches(
                    matches,
                    kickoff_map=kickoff_map,
                    settled_map=load_settled_map(self.output_root),
                )
                active = upcoming + live
                result = recommend_list_parlay(
                    active,
                    provider=provider,
                    kickoff_map=kickoff_map,
                    target_date=target_date,
                    output_root=str(self.output_root),
                )
                self._send_json(result)
            except json.JSONDecodeError:
                self._send_json({"ok": False, "error": "请求体须为 JSON"}, 400)
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, 400)
            except Exception as exc:
                log.exception("列表AI 2串1失败")
                self._send_json({"ok": False, "error": str(exc)}, 500)
            return
        if path == "/api/daily/ai":
            global _daily_ai_running
            qs = parse_qs(urlparse(self.path).query)
            match_date = qs.get("date", [None])[0]
            if not match_date:
                from time_utils import now_beijing
                match_date = now_beijing().date().isoformat()
            if _daily_ai_running:
                self._send_json({"ok": False, "error": "当日 AI 分析进行中，请稍候"}, 409)
                return

            def _job():
                global _daily_ai_running
                try:
                    from daily_picks_ai import run_daily_ai_analysis
                    run_daily_ai_analysis(
                        self.output_root,
                        match_date,
                        ai_model=self.ai_model,
                        ai_mode=self.ai_mode,
                        ai_base_url=self.ai_base_url,
                        dual_ai=self.dual_ai,
                        ai_model_b=self.ai_model_b,
                        ai_base_url_b=self.ai_base_url_b,
                        within_days=self.within_days,
                    )
                except Exception as exc:
                    log.exception("当日 AI 分析失败")
                finally:
                    with _daily_ai_lock:
                        _daily_ai_running = False

            with _daily_ai_lock:
                _daily_ai_running = True
            threading.Thread(target=_job, daemon=True).start()
            self._send_json({
                "ok": True,
                "message": f"已启动 {match_date} AI 分析（逐场 + 三档 2串1），约 2–5 分钟",
                "date": match_date,
            })
            return
        rm = _API_RECOMMEND_RE.match(path)
        if rm:
            fid = rm.group(1)
            try:
                pred = run_single_match_ai(
                    self.output_root,
                    fid,
                    ai_model=self.ai_model,
                    ai_mode=self.ai_mode,
                    ai_base_url=self.ai_base_url,
                    dual_ai=self.dual_ai,
                    ai_model_b=self.ai_model_b,
                    ai_base_url_b=self.ai_base_url_b,
                )
                self._send_json(_pred_summary(pred))
            except RuntimeError as exc:
                self._send_json({"ok": False, "error": str(exc)}, 409)
            except Exception as exc:
                log.exception("手动 AI 失败 fid=%s", fid)
                self._send_json({"ok": False, "error": str(exc)}, 500)
            return
        dm = _API_DEEP_RE.match(path)
        if dm:
            fid = dm.group(1)
            try:
                from ai_deep_analysis import has_prior_ai_analysis, run_deep_match_analysis
                pred = _load_latest_pred(self.output_root, fid)
                idx = _load_match_index(self.output_root, fid)
                ai_records = load_ai_records(self.output_root, fid)
                had_prior = has_prior_ai_analysis(
                    pred, ai_records,
                    output_root=self.output_root, fixture_id=fid,
                    index=idx,
                )
                if not had_prior:
                    log.info("深度分析前自动跑首轮 AI fid=%s", fid)
                    pred = run_single_match_ai(
                        self.output_root,
                        fid,
                        ai_model=self.ai_model,
                        ai_mode=self.ai_mode,
                        ai_base_url=self.ai_base_url,
                        dual_ai=self.dual_ai,
                        ai_model_b=self.ai_model_b,
                        ai_base_url_b=self.ai_base_url_b,
                    )
                    ai_records = load_ai_records(self.output_root, fid)
                record = run_deep_match_analysis(
                    self.output_root,
                    fid,
                    ai_model=self.ai_model,
                    ai_base_url=self.ai_base_url,
                    prediction=pred,
                    index=idx,
                    ai_records=ai_records,
                )
                self._send_json({
                    "ok": True,
                    "headline": (record.get("analysis") or {}).get("headline"),
                    "final_pick": (record.get("analysis") or {}).get("final_pick"),
                    "ts": record.get("ts"),
                    "auto_first_pass": not had_prior,
                })
            except RuntimeError as exc:
                self._send_json({"ok": False, "error": str(exc)}, 409)
            except Exception as exc:
                log.exception("深度 AI 失败 fid=%s", fid)
                self._send_json({"ok": False, "error": str(exc)}, 500)
            return
        self._send_json({"error": "not found"}, 404)


def scheduler_loop(
    output_root: Path,
    *,
    within_days: float,
    use_ai: bool,
    ai_model: str,
    ai_mode: str,
    ai_base_url: str | None,
    dual_ai: bool = False,
    ai_model_b: str | None = None,
    ai_base_url_b: str | None = None,
    run_on_start: bool,
    skip_unchanged: bool = True,
    ai_interval_sec: int = app_cfg.AI_INTERVAL_MINUTES * 60,
):
    job_kw = dict(
        within_days=within_days,
        use_ai=use_ai,
        ai_model=ai_model,
        ai_mode=ai_mode,
        ai_base_url=ai_base_url,
        dual_ai=dual_ai,
        ai_model_b=ai_model_b,
        ai_base_url_b=ai_base_url_b,
        skip_unchanged=skip_unchanged,
        ai_interval_sec=ai_interval_sec,
        force_ai=False,
    )
    if run_on_start:
        log.info("启动时立即执行一次（AI 仍受 %ds 节流）", ai_interval_sec)
        try:
            run_hourly_job(output_root, **job_kw)
        except RuntimeError:
            pass

    while True:
        wait = seconds_until_next_hour()
        nxt = now_beijing() + timedelta(seconds=wait)
        set_next_scheduled(nxt)
        log.info("下次整点任务: %s 北京时间（%.0f 秒后）", nxt.strftime("%H:%M:%S"), wait)
        time.sleep(wait)
        try:
            run_hourly_job(output_root, **job_kw)
        except RuntimeError:
            log.warning("整点任务跳过（已有任务在运行）")


def main(argv: list[str] | None = None) -> int:
    from __version__ import __version__

    parser = argparse.ArgumentParser(
        description="HTTP 服务：每整点拉取赔率、分析，并提供比赛趋势二级页",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("-o", "--output", default="output/service", help="结果输出目录")
    parser.add_argument("--days", type=float, default=7, help="只处理 N 天内比赛")
    parser.add_argument("--with-ai", action="store_true", help="启用 AI 专家分析")
    parser.add_argument("--ai-model", default="deepseek-chat")
    parser.add_argument("--ai-mode", default="expert", choices=["expert", "locked"])
    parser.add_argument("--ai-base-url", default=None)
    parser.add_argument(
        "--dual-ai", action="store_true",
        help="多模型：DeepSeek + 已配置的豆包各分析一次",
    )
    parser.add_argument(
        "--ai-model-b", default=None,
        help="第二模型 ID（豆包 Model ID 如 doubao-seed-2-0-lite-260428，或 ep- 接入点）",
    )
    parser.add_argument(
        "--ai-base-url-b", default="https://ark.cn-beijing.volces.com/api/v3",
        help="第二模型 API 地址（默认火山方舟）",
    )
    parser.add_argument("--run-on-start", action="store_true", help="启动后立即跑一轮")
    parser.add_argument("--no-scheduler", action="store_true", help="仅 HTTP，不自动整点")
    parser.add_argument(
        "--ai-interval-minutes", type=int, default=app_cfg.AI_INTERVAL_MINUTES,
        help=f"AI 最短调用间隔（分钟），默认 {app_cfg.AI_INTERVAL_MINUTES}（约 2～3 小时）；0=不限制",
    )
    parser.add_argument(
        "--force-analyze", action="store_true",
        help="即使赔率 xls 未变动也重新分析（含 AI）",
    )
    parser.add_argument(
        "--rebuild-timeline", action="store_true",
        help="启动时从 runs/ 重建 hourly 时间线文件",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    if args.rebuild_timeline or not (out / "matches").is_dir():
        rebuild_from_runs(out)

    Handler.output_root = out
    Handler.within_days = args.days
    Handler.use_ai = args.with_ai
    Handler.ai_model = args.ai_model
    Handler.ai_mode = args.ai_mode
    Handler.ai_base_url = args.ai_base_url
    Handler.dual_ai = args.dual_ai
    Handler.ai_model_b = args.ai_model_b or os.environ.get("DOUBAO_ENDPOINT") or os.environ.get("DOUBAO_MODEL")
    Handler.ai_base_url_b = args.ai_base_url_b
    Handler.skip_unchanged = not args.force_analyze
    Handler.ai_interval_sec = max(0, args.ai_interval_minutes * 60)

    if not args.no_scheduler:
        threading.Thread(
            target=scheduler_loop,
            kwargs={
                "output_root": out,
                "within_days": args.days,
                "use_ai": args.with_ai,
                "ai_model": args.ai_model,
                "ai_mode": args.ai_mode,
                "ai_base_url": args.ai_base_url,
                "dual_ai": args.dual_ai,
                "ai_model_b": Handler.ai_model_b,
                "ai_base_url_b": args.ai_base_url_b,
                "run_on_start": args.run_on_start,
                "skip_unchanged": not args.force_analyze,
                "ai_interval_sec": Handler.ai_interval_sec,
            },
            daemon=True,
        ).start()
    elif args.run_on_start:
        threading.Thread(
            target=lambda: run_hourly_job(
                out, within_days=args.days, use_ai=args.with_ai,
                ai_model=args.ai_model, ai_mode=args.ai_mode,
                ai_base_url=args.ai_base_url,
                dual_ai=args.dual_ai,
                ai_model_b=Handler.ai_model_b,
                ai_base_url_b=args.ai_base_url_b,
                skip_unchanged=not args.force_analyze,
                ai_interval_sec=Handler.ai_interval_sec,
            ),
            daemon=True,
        ).start()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    log.info("服务已启动 http://%s:%s/", args.host, args.port)
    log.info("比赛详情页 http://%s:%s/match/{{fid}}", args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("已停止")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
