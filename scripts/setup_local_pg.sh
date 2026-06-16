#!/usr/bin/env bash
# 不用 Docker，Homebrew 安装本地 PostgreSQL
set -euo pipefail

if ! command -v brew >/dev/null 2>&1; then
  echo "需要 Homebrew: https://brew.sh"
  exit 1
fi

brew install postgresql@16
brew services start postgresql@16

PG_BIN="$(brew --prefix postgresql@16)/bin"
export PATH="$PG_BIN:$PATH"

# 创建用户和库
psql postgres -tc "SELECT 1 FROM pg_roles WHERE rolname='odds'" | grep -q 1 \
  || psql postgres -c "CREATE USER odds WITH PASSWORD 'odds' SUPERUSER;"
psql postgres -tc "SELECT 1 FROM pg_database WHERE datname='odds'" | grep -q 1 \
  || psql postgres -c "CREATE DATABASE odds OWNER odds;"

cd "$(dirname "$0")/.."
export DATABASE_URL=postgresql://odds:odds@127.0.0.1:5432/odds
.venv/bin/python3 poll_service.py --init-db 2>/dev/null || true

echo ""
echo "本地 Postgres 已就绪"
echo "  DATABASE_URL=$DATABASE_URL"
echo "  下一步: bash scripts/run_local.sh"
