#!/usr/bin/env bash
set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]:-${0}}"
SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_PATH}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
LOG_DIR="$PROJECT_ROOT/logs"
PID_FILE="$LOG_DIR/challenge-server.pid"
ENV_FILE="$PROJECT_ROOT/.env"
PYTHON_SCRIPT="$PROJECT_ROOT/challenge-server.py"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
STDOUT_LOG="$LOG_DIR/challenge-server-$TIMESTAMP.log"

COLOR_RESET='\033[0m'
COLOR_INFO='\033[32m'
COLOR_ERROR='\033[31m'

info() {
  printf '%b[INFO]%b %s\n' "$COLOR_INFO" "$COLOR_RESET" "$1"
}

error() {
  printf '%b[ERROR]%b %s\n' "$COLOR_ERROR" "$COLOR_RESET" "$1" >&2
  exit 1
}

show_help() {
  cat <<EOF
Usage: ./challenge-server-start.sh [options]

Options:
  --host <host>             Host address to bind (default: 0.0.0.0)
  --port <port>             TCP port to listen on (default: 8004)
  --challenge-dir <path>    Directory for challenge files (default: ./challenges)
  --api-base-path <path>    Base path for API endpoints (default: /acps-atr-v1)
  --python-bin <path>       Python interpreter to use (default: python3)
  --help                    Show this help message

Environment variables override the same options prior to CLI parsing.
EOF
}

load_env_file() {
  if [[ -f "$ENV_FILE" ]]; then
    info "Loading environment variables from $ENV_FILE"
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
  fi
}

ensure_requirements() {
  if [[ ! -f "$PYTHON_SCRIPT" ]]; then
    error "Challenge server script not found at $PYTHON_SCRIPT"
  fi

  if ! command -v "${PYTHON_BIN:-python3}" >/dev/null 2>&1; then
    error "Required command '${PYTHON_BIN:-python3}' is not available."
  fi

  if ! command -v lsof >/dev/null 2>&1; then
    error "Required command 'lsof' is not available."
  fi
}

parse_cli() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --host)
        [[ $# -ge 2 ]] || error "Missing value for --host"
        HOST="$2"
        shift 2
        ;;
      --port)
        [[ $# -ge 2 ]] || error "Missing value for --port"
        PORT="$2"
        shift 2
        ;;
      --challenge-dir)
        [[ $# -ge 2 ]] || error "Missing value for --challenge-dir"
        CHALLENGE_DIR="$2"
        shift 2
        ;;
      --api-base-path)
        [[ $# -ge 2 ]] || error "Missing value for --api-base-path"
        API_BASE_PATH="$2"
        shift 2
        ;;
      --python-bin)
        [[ $# -ge 2 ]] || error "Missing value for --python-bin"
        PYTHON_BIN="$2"
        shift 2
        ;;
      --help)
        show_help
        exit 0
        ;;
      *)
        error "Unknown option: $1"
        ;;
    esac
  done
}

load_env_file

PYTHON_BIN="${PYTHON_BIN:-python3}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8004}"
CHALLENGE_DIR="${CHALLENGE_DIR:-$PROJECT_ROOT/challenges}"
API_BASE_PATH="${API_BASE_PATH:-/acps-atr-v1}"

parse_cli "$@"

ensure_requirements

cd "$PROJECT_ROOT"

mkdir -p "$LOG_DIR" "$CHALLENGE_DIR"

if [[ -f "$PID_FILE" ]]; then
  PID_CONTENT="$(cat "$PID_FILE")"
  if [[ -n "$PID_CONTENT" ]] && kill -0 "$PID_CONTENT" 2>/dev/null; then
    error "Challenge server already running with PID $PID_CONTENT. Use ./challenge-server-stop.sh first."
  fi
  error "Stale PID file detected at $PID_FILE. Remove it or run ./challenge-server-stop.sh."
fi

if ! [[ "$PORT" =~ ^[0-9]+$ ]] || (( PORT < 1 || PORT > 65535 )); then
  error "Invalid port specified: $PORT"
fi

if lsof -ti tcp:"$PORT" >/dev/null 2>&1; then
  error "Port $PORT is already in use."
fi

info "Starting challenge server on $HOST:$PORT"
CMD=("$PYTHON_BIN" "$PYTHON_SCRIPT" "--host" "$HOST" "--port" "$PORT" "--challenge-dir" "$CHALLENGE_DIR" "--api-base-path" "$API_BASE_PATH")

nohup "${CMD[@]}" >>"$STDOUT_LOG" 2>&1 &
SERVICE_PID=$!

if [[ -z "$SERVICE_PID" ]]; then
  error "Failed to obtain service PID."
fi

echo "$SERVICE_PID" >"$PID_FILE"

sleep 3

if ! kill -0 "$SERVICE_PID" 2>/dev/null; then
  rm -f "$PID_FILE"
  error "Challenge server failed to start. Check log at $STDOUT_LOG"
fi

info "Challenge server started successfully (PID: $SERVICE_PID)."
info "Logs available at $STDOUT_LOG"
info "To stop the server, run ./challenge-server-stop.sh"
