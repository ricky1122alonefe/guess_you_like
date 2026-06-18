#!/usr/bin/env bash
# 本地 Python 跑 poll + web（同一终端看两边日志）
#
#   bash scripts/run_local.sh ai-dual   # poll + web + 多模型 AI（DeepSeek + 豆包）
#   豆包：ARK_API_KEY + 可选 DOUBAO_MODEL（默认 doubao-seed-2-0-lite-260428）
#   Kimi（默认关闭）：AI_ENABLE_KIMI=1 + MOONSHOT_API_KEY
#   bash scripts/run_local.sh ai        # poll + web + 整点AI（1小时节流）
#   bash scripts/run_local.sh           # 同上但不调 AI（省钱）
#   bash scripts/run_local.sh kill      # 停掉旧进程
#   bash scripts/run_local.sh once      # 只抓一轮赔率
set -euo pipefail
cd "$(dirname "$0")/.."

export DATABASE_URL="${DATABASE_URL:-postgresql://odds:odds@127.0.0.1:5432/odds}"
export PYTHONUNBUFFERED=1
PY="${PY:-.venv/bin/python3}"
PORT="${PORT:-8765}"
LOG_DIR="${LOG_DIR:-logs}"

kill_port() {
  local pids
  pids=$(lsof -ti :"$PORT" 2>/dev/null || true)
  if [[ -n "$pids" ]]; then
    echo "停止占用 :$PORT 的进程: $pids"
    kill $pids 2>/dev/null || true
    sleep 0.5
  fi
}

prefix_lines() {
  local tag=$1
  while IFS= read -r line || [[ -n "$line" ]]; do
    printf '[%s] %s\n' "$tag" "$line"
  done
}

stop_all() {
  echo ""
  echo "[dev] 正在停止…"
  pkill -f "poll_service.py" 2>/dev/null || true
  pkill -f "serve.py --host" 2>/dev/null || true
  kill_port
}

run_dev() {
  local with_ai="${1:-0}"
  local dual_ai="${2:-0}"
  if [[ "$with_ai" == "1" && "$dual_ai" == "1" && ! -d node_modules/@cursor/sdk ]]; then
    echo "[dev] 未找到 node_modules，正在 npm install（Cursor 桥接需要）…"
    npm install
  fi
  kill_port
  pkill -f "poll_service.py" 2>/dev/null || true

  "$PY" poll_service.py --init-db
  echo "DATABASE_URL=$DATABASE_URL"
  if [[ "$with_ai" == "1" ]]; then
    if [[ "$dual_ai" == "1" ]]; then
      echo "模式: poll 5分钟 | 多模型 AI（DeepSeek+豆包）1小时一次 → http://127.0.0.1:$PORT"
    else
      echo "模式: 爬赔率 5分钟一次 | AI 分析 1小时一次 → http://127.0.0.1:$PORT"
    fi
  else
    echo "模式: 爬赔率 5分钟一次 | 无 AI → http://127.0.0.1:$PORT"
  fi
  echo "poll 日志: $LOG_DIR/poll.log  |  Ctrl+C 全部停止"
  echo "----------------------------------------"

  trap stop_all INT TERM EXIT

  : > "$LOG_DIR/poll.log"
  "$PY" poll_service.py --interval 300 --days 7 2>&1 \
    | tee -a "$LOG_DIR/poll.log" \
    | prefix_lines poll &

  SERVE_ARGS=(serve.py --host 127.0.0.1 --port "$PORT")
  if [[ "$with_ai" == "1" ]]; then
    SERVE_ARGS+=(--with-ai --ai-interval-minutes 60 --run-on-start)
    if [[ "$dual_ai" == "1" ]]; then
      SERVE_ARGS+=(--dual-ai)
      if [[ -n "${DOUBAO_ENDPOINT:-}" ]]; then
        SERVE_ARGS+=(--ai-model-b "$DOUBAO_ENDPOINT")
      elif [[ -n "${DOUBAO_MODEL:-}" ]]; then
        SERVE_ARGS+=(--ai-model-b "$DOUBAO_MODEL")
      fi
    fi
  else
    SERVE_ARGS+=(--no-scheduler --run-on-start)
  fi

  "$PY" "${SERVE_ARGS[@]}" 2>&1 | prefix_lines web &

  sleep 2
  if curl -sf "http://127.0.0.1:$PORT/api/status" >/dev/null 2>&1; then
    echo "[dev] Web 已就绪 http://127.0.0.1:$PORT"
    command -v open >/dev/null && open "http://127.0.0.1:$PORT" || true
  else
    echo "[dev] Web 启动中… 请稍后打开 http://127.0.0.1:$PORT"
  fi

  wait
}

if [[ ! -x "$PY" ]]; then
  echo "请先: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

cmd="${1:-all}"
mkdir -p "$LOG_DIR"

case "$cmd" in
  kill)
    kill_port
    pkill -f "poll_service.py" 2>/dev/null && echo "已停 poll_service" || echo "无 poll_service 进程"
    pkill -f "serve.py --host" 2>/dev/null && echo "已停 serve.py" || true
    ;;
  once)
    "$PY" poll_service.py --init-db
    echo "DATABASE_URL=$DATABASE_URL"
    echo "=== 抓取一轮 ==="
    "$PY" poll_service.py --once --days 7
    ;;
  web)
    kill_port
    exec "$PY" serve.py --host 127.0.0.1 --port "$PORT" --no-scheduler
    ;;
  poll)
    "$PY" poll_service.py --init-db
    exec "$PY" poll_service.py --interval 300 --days 2
    ;;
  ai)
    run_dev 1 0
    ;;
  ai-dual|dual)
    run_dev 1 1
    ;;
  all|dev)
    run_dev 0
    ;;
  *)
    echo "用法: bash scripts/run_local.sh [ai|ai-dual|all|kill|once|web|poll]"
    exit 1
    ;;
esac
