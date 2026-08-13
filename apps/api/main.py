"""FastAPI application factory."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from __version__ import __version__


def create_app(output_root: Path, *, within_days: float = 7):
    from fastapi import FastAPI, HTTPException

    from analysis.registry import public_config_summary
    from apps.api.services import list_fixtures, load_prediction, prediction_summary

    app = FastAPI(
        title="guess-you-like API",
        version=__version__,
        description="Read-only API for fixtures, predictions, and analysis reports.",
    )
    root = Path(output_root)

    @app.get("/health")
    def health():
        return {"ok": True, "version": __version__}

    @app.get("/v1/analysis/config")
    def analysis_config():
        return public_config_summary(root)

    @app.get("/v1/fixtures")
    def fixtures():
        return {"ok": True, "fixtures": list_fixtures(root, within_days=within_days)}

    @app.get("/v1/fixtures/{fixture_id}")
    def fixture_detail(fixture_id: str):
        pred = load_prediction(root, fixture_id)
        body = prediction_summary(pred)
        if not body.get("ok"):
            raise HTTPException(status_code=404, detail="fixture not found")
        return body

    @app.get("/v1/divergence")
    def divergence(min_score: Optional[int] = None):
        from analysis.signals.eu_ah_divergence import build_divergence_report

        report = build_divergence_report(root, min_score=min_score, within_days=within_days)
        return {"ok": True, **report}

    @app.get("/api/focus-watch")
    @app.get("/v1/focus-watch")
    def get_focus_watch():
        from focus_watch import load_focus_watch

        return {"ok": True, **load_focus_watch(root)}

    @app.post("/api/focus-watch")
    @app.post("/v1/focus-watch")
    def post_focus_watch(payload: dict):
        from fastapi import HTTPException

        from focus_watch import (
            add_focus_fid,
            clear_focus,
            load_focus_watch,
            remove_focus_fid,
            set_focus_fids,
            update_note,
        )

        action = str(payload.get("action") or "").strip().lower()
        fids_in = [str(x).strip() for x in payload.get("fids", []) if str(x).strip()]
        note = payload.get("note")
        if action == "add":
            ok, msg = True, ""
            for fid in fids_in:
                ok, msg = add_focus_fid(fid, note=note, output_root=root)
                if not ok:
                    break
            return {"ok": ok, "message": msg, "focus_watch": load_focus_watch(root)}
        if action == "remove":
            for fid in fids_in:
                remove_focus_fid(fid, output_root=root)
            return {"ok": True, "focus_watch": load_focus_watch(root)}
        if action == "set":
            notes = payload.get("notes") or {}
            ok, msg = set_focus_fids(
                fids_in,
                notes=notes if isinstance(notes, dict) else None,
                output_root=root,
            )
            if not ok:
                raise HTTPException(status_code=400, detail=msg)
            return {"ok": True, "focus_watch": load_focus_watch(root)}
        if action == "clear":
            clear_focus(output_root=root)
            return {"ok": True, "focus_watch": load_focus_watch(root)}
        if action == "note":
            fid = (fids_in[0] if fids_in else str(payload.get("fid") or "")).strip()
            if not fid:
                raise HTTPException(status_code=400, detail="fid required")
            ok = update_note(fid, note=str(note or ""), output_root=root)
            return {"ok": ok, "focus_watch": load_focus_watch(root)}
        raise HTTPException(status_code=400, detail=f"unknown action: {action}")

    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="guess-you-like read-only JSON API (FastAPI)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("-o", "--output", default="output/service", help="Pipeline output directory")
    parser.add_argument("--days", type=float, default=7, help="Fixture window in days")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit(
            "缺少 API 依赖：pip install -e '.[api]'  （需要 fastapi + uvicorn）"
        ) from exc

    app = create_app(Path(args.output), within_days=args.days)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
