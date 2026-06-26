"""Hourly download + predict pipeline for the HTTP service."""

from __future__ import annotations

import json
import logging
import threading
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ai_profiles import AiProfile, load_profiles, merge_multi_ai_predictions
from download_500 import Download500Error, download_match_pair, download_upcoming
from ai_schedule import record_ai_run, should_run_ai
from history import load_all_history
from odds_cache import (
    bootstrap_fingerprints,
    can_reuse_prediction,
    fingerprint_equal,
    load_fingerprints,
    load_latest_predictions,
    match_fingerprint,
    reuse_prediction,
    save_fingerprints,
)
from parser import parse_match_pair
from predict import build_payload
from jingcai_pick import final_recommendation_cn
from analysis.pipeline import enrich_prediction
from analysis.registry import enrichment_steps
from core.context import EnrichmentContext
from time_utils import format_beijing, now_beijing, now_beijing_str
from predict_sheet import rec_to_row, save_csv
from recommend import build_recommendation, recommendation_from_dict, recommendation_to_baseline
from daily_picks import (
    AI_KICKOFF_HOURS,
    kickoff_within_hours,
    load_kickoff_map,
    save_daily_picks,
)
from daily_picks_ai import build_daily_picks_auto
from match_settlement import run_settlement
from timeline_merge import load_latest_poll_meta
from match_timeline import append_ai_record, append_hourly_snapshot

log = logging.getLogger(__name__)

_history_cache: Any = None
_history_lock = threading.Lock()
_run_lock = threading.Lock()
_single_ai_locks: dict[str, threading.Lock] = {}
_single_ai_locks_guard = threading.Lock()


def _lock_for_fixture(fixture_id: str) -> threading.Lock:
    with _single_ai_locks_guard:
        if fixture_id not in _single_ai_locks:
            _single_ai_locks[fixture_id] = threading.Lock()
        return _single_ai_locks[fixture_id]


def _merge_prediction_into_latest(output_root: Path, pred: dict) -> None:
    root = Path(output_root)
    path = root / "latest.json"
    data: dict = {"matches": [], "summary": {}}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    fid = str(pred.get("fixture_id", ""))
    matches = data.get("matches") or []
    replaced = False
    for i, m in enumerate(matches):
        if str(m.get("fixture_id")) == fid:
            matches[i] = pred
            replaced = True
            break
    if not replaced:
        matches.append(pred)
    data["matches"] = matches
    data["generated_at"] = now_beijing_str()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


@dataclass
class RunSummary:
    run_id: str
    started_at: str
    finished_at: str = ""
    status: str = "running"  # running | ok | error
    within_days: float = 7
    use_ai: bool = False
    match_count: int = 0
    download_ok: int = 0
    predict_ok: int = 0
    predict_skipped: int = 0
    ai_called: int = 0
    ai_skipped_far: int = 0
    settled_count: int = 0
    ai_throttled: bool = False
    daily_picks_ai: bool = False
    errors: list[str] = field(default_factory=list)
    output_dir: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ServiceState:
    last_run: RunSummary | None = None
    last_success_at: str = ""
    next_scheduled_at: str = ""
    running: bool = False
    total_runs: int = 0

    def to_dict(self) -> dict:
        d = {
            "running": self.running,
            "last_success_at": self.last_success_at,
            "next_scheduled_at": self.next_scheduled_at,
            "total_runs": self.total_runs,
            "last_run": self.last_run.to_dict() if self.last_run else None,
        }
        return d


_state = ServiceState()
_state_lock = threading.Lock()


def get_state() -> dict:
    with _state_lock:
        return _state.to_dict()


def get_history():
    global _history_cache
    with _history_lock:
        if _history_cache is None:
            log.info("加载历史库…")
            _history_cache = load_all_history()
        return _history_cache


def reload_history():
    global _history_cache
    with _history_lock:
        _history_cache = load_all_history()
        return _history_cache


def set_next_scheduled(when: datetime) -> None:
    with _state_lock:
        _state.next_scheduled_at = format_beijing(when)


def _enrich_prediction(
    pred: dict,
    *,
    ah_path: Path | None = None,
    eu_path: Path | None = None,
    payload: dict | None = None,
    poll_meta: dict | None = None,
    cur=None,
    steps: tuple[str, ...] | None = None,
    output_root: Path | None = None,
) -> dict:
    cur_dict = cur
    if cur is not None and not isinstance(cur, dict):
        cur_dict = vars(cur)
    return enrich_prediction(
        EnrichmentContext(
            pred=pred,
            ah_path=ah_path,
            eu_path=eu_path,
            payload=payload,
            poll_meta=poll_meta,
            cur=cur_dict,
        ),
        steps=steps,
        output_root=output_root,
    )


def _predict_one(
    ah_path: Path,
    eu_path: Path,
    *,
    history,
    use_ai: bool,
    ai_model: str,
    ai_mode: str,
    ai_base_url: str | None,
    ai_profile: AiProfile | None = None,
    fixture_id: str | None = None,
):
    cur = parse_match_pair(str(ah_path), str(eu_path))
    predict_date = now_beijing_str("%Y-%m-%d")
    poll_meta = load_latest_poll_meta(fixture_id) if fixture_id else {}

    if use_ai:
        from analysis.ai.predict import run_one_match
        from recommend import recommendation_from_dict

        prof = ai_profile
        if prof is None:
            prof = AiProfile(
                "deepseek", "DeepSeek 精算师", ai_model,
                ai_base_url or "https://api.deepseek.com",
                "DEEPSEEK_API_KEY",
            )
        _payload, result, _artifact = run_one_match(
            str(ah_path), str(eu_path),
            history=history,
            sample_limit=10,
            relaxed=False,
            model=prof.model,
            mode=ai_mode,
            base_url=prof.base_url,
            api_key=prof.resolve_api_key(),
            provider_id=prof.provider_id,
            provider_label=prof.label,
            poll_meta=poll_meta or None,
            verbose=False,
        )
        rec = recommendation_from_dict(result)
        result["predict_row"] = rec_to_row(rec, cur=cur, predict_date=predict_date)
        _enrich_prediction(
            result,
            ah_path=ah_path,
            eu_path=eu_path,
            payload=_payload,
            poll_meta=poll_meta,
            cur=cur,
        )
        return result

    payload = build_payload(str(ah_path), str(eu_path), history=history, sample_limit=10)
    if fixture_id:
        payload["fixture_id"] = str(fixture_id)
    jc = (poll_meta or {}).get("jingcai")
    if jc:
        payload["jingcai"] = jc
    rec = build_recommendation(payload)
    base = recommendation_to_baseline(rec)
    base["match"] = rec.match
    if jc:
        from jingcai_pick import attach_jingcai_recommendation

        attach_jingcai_recommendation(base, jc)
    row = rec_to_row(rec, cur=cur, predict_date=predict_date)
    if base.get("predict_row"):
        row.update({k: v for k, v in base["predict_row"].items() if v not in (None, "")})
    base["predict_row"] = row
    from analysis.rules.output import attach_post_recommendation

    attach_post_recommendation(base)
    base["analysis_basis"] = base.get("analysis_basis") or []
    base["recommendation_source"] = "rule_engine"
    _enrich_prediction(
        base,
        ah_path=ah_path,
        eu_path=eu_path,
        payload=payload,
        poll_meta=poll_meta,
        cur=cur,
    )
    return base


def _predict_multi_ai(
    ah_path: Path,
    eu_path: Path,
    *,
    history,
    ai_mode: str,
    profiles: list[AiProfile],
    fixture_id: str | None = None,
) -> dict:
    analyses: dict[str, dict] = {}
    errors: list[str] = []
    for prof in profiles:
        try:
            pred = _predict_one(
                ah_path, eu_path,
                history=history,
                use_ai=True,
                ai_model=prof.model,
                ai_mode=ai_mode,
                ai_base_url=prof.base_url,
                ai_profile=prof,
                fixture_id=fixture_id,
            )
            analyses[prof.provider_id] = pred
            log.info("AI %s → %s", prof.label, final_recommendation_cn(pred))
        except Exception as exc:
            msg = f"{prof.label}: {exc}"
            errors.append(msg)
            log.warning("AI 失败 %s", msg)
    if not analyses:
        raise RuntimeError("全部模型失败：" + "；".join(errors))
    merged = merge_multi_ai_predictions(analyses)
    if errors:
        merged["ai_errors"] = errors
    return merged


def run_single_match_ai(
    output_root: str | Path,
    fixture_id: str,
    *,
    ai_model: str = "deepseek-chat",
    ai_mode: str = "expert",
    ai_base_url: str | None = None,
    dual_ai: bool = False,
    ai_model_b: str | None = None,
    ai_base_url_b: str | None = None,
) -> dict:
    """On-demand AI analysis for one fixture (manual button; bypasses hourly throttle)."""
    fid = str(fixture_id)
    lock = _lock_for_fixture(fid)
    if not lock.acquire(blocking=False):
        raise RuntimeError(f"比赛 {fid} 的 AI 分析正在进行中，请稍候")

    root = Path(output_root)
    run_id = now_beijing_str("%Y-%m-%d_%H%M") + f"_ai_{fid}"
    run_dir = root / "runs" / run_id
    xls_dir = run_dir / "xls"
    try:
        log.info("手动 AI 推荐 fid=%s", fid)
        dl = download_match_pair(fid, xls_dir)
        if not dl.asian or not dl.european:
            raise Download500Error(f"{dl.match_name}: 下载不完整")

        history = get_history()
        profiles = load_profiles(
            dual=dual_ai,
            primary_model=ai_model,
            primary_base_url=ai_base_url,
            secondary_model=ai_model_b,
            secondary_base_url=ai_base_url_b,
            output_root=root,
        )
        if not profiles:
            raise RuntimeError(
                "未配置可用 AI：请设置 DEEPSEEK_API_KEY；"
                "多模型可选 ARK_API_KEY（豆包）；Kimi 需 AI_ENABLE_KIMI=1"
            )

        if len(profiles) == 1:
            pred = _predict_one(
                dl.asian, dl.european,
                history=history,
                use_ai=True,
                ai_model=profiles[0].model,
                ai_mode=ai_mode,
                ai_base_url=profiles[0].base_url,
                ai_profile=profiles[0],
                fixture_id=fid,
            )
        else:
            pred = _predict_multi_ai(
                dl.asian, dl.european,
                history=history,
                ai_mode=ai_mode,
                profiles=profiles,
                fixture_id=fid,
            )
        pred["fixture_id"] = fid
        pred["run_id"] = run_id
        pred["match"] = pred.get("match") or dl.match_name
        pred["manual_ai"] = True
        pred["xls_asian"] = str(dl.asian)
        pred["xls_european"] = str(dl.european)

        fp = match_fingerprint(dl.asian, dl.european)
        fps = load_fingerprints(root)
        fps[fid] = fp
        save_fingerprints(root, fps)

        run_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "summary": {
                "run_id": run_id,
                "started_at": now_beijing_str(),
                "status": "ok",
                "manual_ai": True,
                "fixture_id": fid,
            },
            "generated_at": now_beijing_str(),
            "matches": [pred],
        }
        (run_dir / "predictions.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        _merge_prediction_into_latest(root, pred)
        append_hourly_snapshot(
            root, fid, pred,
            run_id=run_id,
            ts=payload["generated_at"],
            match_name=dl.match_name,
        )
        append_ai_record(
            root, fid, pred,
            run_id=run_id,
            ts=payload["generated_at"],
        )
        try:
            from match_agents import build_and_archive_agent_board

            build_and_archive_agent_board(root, fid, pred, run_id=run_id)
        except Exception as exc:
            log.warning("手动 AI 多 Agent 证据板归档失败 %s: %s", dl.match_name, exc)
        record_ai_run(root, ai_called=len(profiles), run_id=run_id)
        log.info(
            "手动 AI 完成 %s → %s（%d 模型）",
            dl.match_name, pred.get("result_1x2_cn"), len(profiles),
        )
        return pred
    finally:
        lock.release()


def run_hourly_job(
    output_root: str | Path,
    *,
    within_days: float = 7,
    use_ai: bool = False,
    ai_model: str = "deepseek-chat",
    ai_mode: str = "expert",
    ai_base_url: str | None = None,
    dual_ai: bool = False,
    ai_model_b: str | None = None,
    ai_base_url_b: str | None = None,
    skip_unchanged: bool = True,
    ai_interval_sec: int | None = None,
    force_ai: bool = False,
) -> RunSummary:
    """Download upcoming fixtures from 500.com, then predict each match."""
    import config as app_cfg

    if ai_interval_sec is None:
        ai_interval_sec = app_cfg.AI_INTERVAL_MINUTES * 60
    if not _run_lock.acquire(blocking=False):
        raise RuntimeError("已有任务在运行，请稍后再试")

    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    run_id = now_beijing_str("%Y-%m-%d_%H%M")
    run_dir = root / "runs" / run_id
    xls_dir = run_dir / "xls"
    summary = RunSummary(
        run_id=run_id,
        started_at=now_beijing_str(),
        within_days=within_days,
        use_ai=use_ai,
        output_dir=str(run_dir),
    )

    use_ai_effective = use_ai
    import config as app_cfg

    if ai_interval_sec is None:
        ai_interval_sec = app_cfg.AI_INTERVAL_MINUTES * 60
    if use_ai and not app_cfg.AI_AUTO_ENABLED:
        use_ai_effective = False
        log.info("定时 AI 已关闭（config.AI_AUTO_ENABLED=False），本轮仅抓数 + 规则引擎")
    elif use_ai and not should_run_ai(root, interval_sec=ai_interval_sec, force=force_ai):
        use_ai_effective = False
        summary.ai_throttled = True

    with _state_lock:
        _state.running = True
        _state.last_run = summary
        _state.total_runs += 1

    results: list[dict] = []
    try:
        log.info("开始整点任务 %s（%s 天内比赛）", run_id, within_days)
        downloads = download_upcoming(xls_dir, within_days=within_days)
        summary.match_count = len(downloads)
        summary.download_ok = sum(
            1 for d in downloads if d.asian and d.european
        )

        if not downloads:
            summary.status = "ok"
            summary.errors.append("无符合时间窗口的比赛")
            log.info("无比赛可分析")
        else:
            history = get_history()
            prev_preds = load_latest_predictions(root) if skip_unchanged else {}
            prev_fps = load_fingerprints(root) if skip_unchanged else {}
            if skip_unchanged and not prev_fps:
                prev_fps = bootstrap_fingerprints(root)
            fp_store = dict(prev_fps)
            kickoff_map = load_kickoff_map()

            for dl in downloads:
                if not dl.asian or not dl.european:
                    summary.errors.append(f"{dl.match_name}: 下载不完整")
                    continue
                fid = str(dl.fixture_id)
                fp = match_fingerprint(dl.asian, dl.european)
                fp_match = fingerprint_equal(fp, prev_fps.get(fid))
                cached = prev_preds.get(fid)
                ai_for_match = use_ai_effective and kickoff_within_hours(
                    fid, AI_KICKOFF_HOURS, kickoff_map,
                )
                if use_ai_effective and not ai_for_match:
                    summary.ai_skipped_far += 1
                    log.info(
                        "规则引擎 %s：开球超过 %.0f 小时，跳过 AI",
                        dl.match_name, AI_KICKOFF_HOURS,
                    )

                if skip_unchanged and can_reuse_prediction(
                    cached, use_ai=ai_for_match, fp_match=fp_match,
                ):
                    pred = reuse_prediction(
                        cached,
                        run_id=run_id,
                        fixture_id=fid,
                        ah_path=dl.asian,
                        eu_path=dl.european,
                        match_name=dl.match_name,
                    )
                    poll_meta = load_latest_poll_meta(fid)
                    _enrich_prediction(
                        pred,
                        poll_meta=poll_meta,
                        cur=pred.get("odds_snapshot") or {},
                        steps=enrichment_steps("reuse", root),
                        output_root=root,
                    )
                    results.append(pred)
                    summary.predict_ok += 1
                    summary.predict_skipped += 1
                    fp_store[fid] = fp
                    try:
                        from match_agents import build_and_archive_agent_board

                        build_and_archive_agent_board(root, fid, pred, run_id=run_id)
                    except Exception as exc:
                        log.warning("多 Agent 证据板归档失败 %s: %s", dl.match_name, exc)
                    log.info("跳过 %s：赔率文件未变动，复用上次结果", dl.match_name)
                    continue

                try:
                    profiles = load_profiles(
                        dual=dual_ai,
                        primary_model=ai_model,
                        primary_base_url=ai_base_url,
                        secondary_model=ai_model_b,
                        secondary_base_url=ai_base_url_b,
                        output_root=root,
                    ) if ai_for_match else []

                    if ai_for_match and len(profiles) > 1:
                        pred = _predict_multi_ai(
                            dl.asian, dl.european,
                            history=history,
                            ai_mode=ai_mode,
                            profiles=profiles,
                            fixture_id=fid,
                        )
                        summary.ai_called += len(profiles)
                    else:
                        pred = _predict_one(
                            dl.asian, dl.european,
                            history=history,
                            use_ai=ai_for_match,
                            ai_model=ai_model,
                            ai_mode=ai_mode,
                            ai_base_url=ai_base_url,
                            ai_profile=profiles[0] if profiles else None,
                            fixture_id=fid,
                        )
                        if ai_for_match:
                            summary.ai_called += 1
                    pred["fixture_id"] = dl.fixture_id
                    pred["run_id"] = run_id
                    pred["xls_asian"] = str(dl.asian)
                    pred["xls_european"] = str(dl.european)
                    results.append(pred)
                    summary.predict_ok += 1
                    fp_store[fid] = fp
                    append_hourly_snapshot(
                        root, dl.fixture_id, pred,
                        run_id=run_id,
                        ts=summary.started_at,
                        match_name=dl.match_name,
                    )
                    try:
                        from match_agents import build_and_archive_agent_board, run_chief_match_agent
                        from match_agents.board import board_is_cup_context

                        board = build_and_archive_agent_board(root, fid, pred, run_id=run_id)
                        if ai_for_match and board_is_cup_context(board):
                            run_chief_match_agent(
                                root,
                                fid,
                                pred,
                                board=board,
                                model=ai_model,
                                base_url=ai_base_url,
                                run_id=run_id,
                            )
                            summary.ai_called += 1
                    except Exception as exc:
                        log.warning("多 Agent 分析归档失败 %s: %s", dl.match_name, exc)
                    if ai_for_match:
                        append_ai_record(
                            root, dl.fixture_id, pred,
                            run_id=run_id,
                            ts=summary.started_at,
                        )
                except Exception as exc:
                    msg = f"{dl.match_name}: {exc}"
                    summary.errors.append(msg)
                    log.exception("预测失败 %s", dl.match_name)

            if skip_unchanged:
                save_fingerprints(root, fp_store)

            if summary.predict_skipped and summary.predict_skipped == summary.download_ok:
                summary.status = "ok"
                log.info(
                    "全部 %d 场赔率文件未变动，未调用 AI/规则引擎",
                    summary.predict_skipped,
                )
            else:
                summary.status = "ok" if summary.predict_ok else "error"

            if results:
                overview = build_daily_picks_auto(
                    results, kickoff_map=kickoff_map, use_ai=use_ai_effective,
                )
                save_daily_picks(root, overview)
                for d in overview.get("available_dates") or []:
                    if d == overview.get("date"):
                        continue
                    day_payload = build_daily_picks_auto(
                        results, match_date=d, kickoff_map=kickoff_map, use_ai=use_ai_effective,
                    )
                    save_daily_picks(root, day_payload)
                if use_ai_effective:
                    summary.daily_picks_ai = overview.get("source") == "ai"
                    if summary.daily_picks_ai:
                        summary.ai_called += 1

            record_ai_run(root, ai_called=summary.ai_called, run_id=run_id)

        run_dir.mkdir(parents=True, exist_ok=True)
        prev_preds = load_latest_predictions(root) if skip_unchanged else {}
        merged_preds = dict(prev_preds)
        for r in results:
            fid = str(r.get("fixture_id", ""))
            if fid:
                merged_preds[fid] = r
        payload = {
            "summary": summary.to_dict(),
            "generated_at": now_beijing_str(),
            "matches": list(merged_preds.values()),
        }
        (run_dir / "predictions.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        (root / "latest.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        (root / "state.json").write_text(
            json.dumps(get_state(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        try:
            settle = run_settlement(root)
            summary.settled_count = int(settle.get("settled") or 0)
        except Exception as exc:
            log.warning("赛果结算失败: %s", exc)

            try:
                from worldcup_analytics import save_tournament_ledger
                save_tournament_ledger(
                    root,
                    include_ai_watch=use_ai_effective,
                    ai_model=ai_model,
                    ai_base_url=ai_base_url,
                )
            except Exception as exc:
                log.warning("世界杯开盘套路刷新失败: %s", exc)

        rows = [r.get("predict_row") or {} for r in results if r.get("predict_row")]
        if rows:
            save_csv(rows, run_dir / "predictions.csv")
            save_csv(rows, root / "latest.csv")

        log.info(
            "任务完成 %s: 下载 %d 预测 %d 跳过 %d AI调用 %d AI远场跳过 %d 赛果结算 %d 三档AI %s 节流 %s 错误 %d",
            run_id, summary.download_ok, summary.predict_ok,
            summary.predict_skipped, summary.ai_called, summary.ai_skipped_far,
            summary.settled_count,
            summary.daily_picks_ai, summary.ai_throttled, len(summary.errors),
        )
    except (Download500Error, Exception) as exc:
        summary.status = "error"
        summary.errors.append(str(exc))
        summary.errors.append(traceback.format_exc())
        log.exception("整点任务失败")
    finally:
        summary.finished_at = now_beijing_str()
        with _state_lock:
            _state.running = False
            _state.last_run = summary
            if summary.status == "ok" and summary.predict_ok:
                _state.last_success_at = summary.finished_at
            state_payload = _state.to_dict()
        try:
            (root / "state.json").write_text(
                json.dumps(state_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            log.exception("写入最终 state.json 失败")
        _run_lock.release()

    return summary


def seconds_until_next_hour(now: datetime | None = None) -> float:
    now = now or now_beijing()
    nxt = (now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
    return max(0.0, (nxt - now).total_seconds())


def list_runs(output_root: str | Path, limit: int = 20) -> list[dict]:
    runs_dir = Path(output_root) / "runs"
    if not runs_dir.is_dir():
        return []
    out = []
    for p in sorted(runs_dir.iterdir(), reverse=True)[:limit]:
        if not p.is_dir():
            continue
        meta = p / "predictions.json"
        if meta.is_file():
            try:
                data = json.loads(meta.read_text(encoding="utf-8"))
                out.append(data.get("summary") or {"run_id": p.name})
            except json.JSONDecodeError:
                out.append({"run_id": p.name, "status": "unknown"})
        else:
            out.append({"run_id": p.name, "status": "incomplete"})
    return out
