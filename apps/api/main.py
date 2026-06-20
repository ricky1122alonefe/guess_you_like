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
