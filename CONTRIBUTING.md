# Contributing

Thanks for your interest in this project. This is a personal research tool shared as open source — contributions are welcome.

## Before you start

- Read the [README](README.md) disclaimer: **not betting advice**; respect local laws and data-source terms of use.
- Do not commit secrets (`.env`, `local_secrets.py`, API keys).
- Keep changes focused; avoid drive-by refactors unrelated to your PR.

## Development setup

```bash
git clone https://github.com/ricky1122alonefe/guess_you_like.git
cd guess_you_like
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
cp local_secrets.example.py local_secrets.py   # optional, for AI

docker compose up -d db
bash scripts/run_local.sh
```

## Running checks

```bash
python -m compileall -q .
pytest -q
ruff check .
```

## Commit messages

Use clear, imperative subjects (English or 中文均可), e.g.:

- `fix: use full-time scores from 500 API for settlement`
- `feat: add EU-AH divergence scan page`

## Pull requests

1. Describe **what** and **why** (not only how).
2. Note how you tested (commands, screenshots if UI).
3. Update [CHANGELOG.md](CHANGELOG.md) under `[Unreleased]` for user-visible changes.

## Reporting issues

Include: OS, Python version, command run, relevant log lines, and whether PostgreSQL / AI keys are configured.
