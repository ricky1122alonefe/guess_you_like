#!/usr/bin/env python3
"""Unified CLI for guess-you-like."""

from __future__ import annotations

import sys

from __version__ import __version__

EPILOG = """
Examples:
  guess-you-like serve --host 127.0.0.1 --port 8765
  guess-you-like poll --interval 300 --days 7
  guess-you-like settle --resettle
  bash scripts/run_local.sh          # local dev (poll + web)
""".strip()


def _print_help() -> None:
    print(f"""guess-you-like {__version__} — 世界杯 / 竞彩赔率分析本地服务

Usage:
  guess-you-like serve [args...]   Start web UI + hourly pipeline
  guess-you-like poll [args...]    Poll odds into PostgreSQL
  guess-you-like settle [args...]  Settle finished match results
  guess-you-like version           Print version
  guess-you-like --help            Show this help

Subcommands forward arguments to the underlying module (serve.py, etc.).

{EPILOG}
""")


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])

    if not args or args[0] in ("-h", "--help", "help"):
        _print_help()
        return 0

    cmd = args[0]
    rest = args[1:]

    if cmd in ("version", "-V", "--version"):
        print(__version__)
        return 0

    if cmd == "serve":
        from serve import main as serve_main

        return serve_main(rest) or 0

    if cmd == "poll":
        from poll_service import main as poll_main

        return poll_main(rest) or 0

    if cmd == "settle":
        from scripts.settle_results import main as settle_main

        return settle_main(rest)

    print(f"Unknown command: {cmd}\n", file=sys.stderr)
    _print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
