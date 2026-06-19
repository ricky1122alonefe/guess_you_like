"""Backward-compatible shim — use analysis.ai.predict."""

from analysis.ai.predict import main, run_one_match

__all__ = ["run_one_match", "main"]

if __name__ == "__main__":
    raise SystemExit(main())
