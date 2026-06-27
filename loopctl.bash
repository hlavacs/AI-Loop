#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

runtime_dir="${AI_LOOP_RUNTIME_DIR:-./run}"
mkdir -p "$runtime_dir"

usage() {
  echo "usage: $0 start|stop|restart|status" >&2
}

pid_file() {
  echo "$runtime_dir/$1.pid"
}

find_pids() {
  local script="$1"
  pgrep -f "python[0-9.]* ${script}" || true
}

is_running() {
  local pid="$1"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

read_pid() {
  local file
  file="$(pid_file "$1")"
  if [ -f "$file" ]; then
    cat "$file"
  fi
}

start_one() {
  local name="$1"
  local wrapper="$2"
  local process_script="$3"
  local pid
  pid="$(read_pid "$name")"

  if is_running "$pid"; then
    echo "$name already running pid=$pid"
    return
  fi

  pid="$(find_pids "$process_script" | head -n 1)"
  if is_running "$pid"; then
    echo "$pid" > "$(pid_file "$name")"
    echo "$name already running pid=$pid"
    return
  fi

  setsid "$wrapper" >/dev/null 2>&1 &
  pid="$!"
  echo "$pid" > "$(pid_file "$name")"
  echo "started $name pid=$pid"
}

stop_one() {
  local name="$1"
  local process_script="$2"
  local pid
  local pids
  pid="$(read_pid "$name")"

  if is_running "$pid"; then
    pids="$pid"
  else
    pids="$(find_pids "$process_script")"
  fi

  if [ -z "$pids" ]; then
    echo "$name not running"
    rm -f "$(pid_file "$name")"
    return
  fi

  kill $pids
  for _ in $(seq 1 20); do
    local still_running=""
    for pid in $pids; do
      if is_running "$pid"; then
        still_running=1
      fi
    done
    if [ -z "$still_running" ]; then
      rm -f "$(pid_file "$name")"
      echo "stopped $name pid=$pids"
      return
    fi
    sleep 0.25
  done

  kill -KILL $pids
  rm -f "$(pid_file "$name")"
  echo "killed $name pid=$pids"
}

status_one() {
  local name="$1"
  local process_script="$2"
  local pid
  pid="$(read_pid "$name")"

  if is_running "$pid"; then
    echo "$name running pid=$pid"
    return
  fi

  pid="$(find_pids "$process_script" | head -n 1)"
  if is_running "$pid"; then
    echo "$name running pid=$pid"
  else
    echo "$name stopped"
  fi
}

start_all() {
  start_one claude_controller ./run_claude.bash claude_controller.py
  start_one codex_worker ./run_codex.bash codex_worker.py
  start_one watcher ./run_watcher.bash watcher.py
}

stop_all() {
  stop_one watcher watcher.py
  stop_one codex_worker codex_worker.py
  stop_one claude_controller claude_controller.py
}

status_all() {
  status_one claude_controller claude_controller.py
  status_one codex_worker codex_worker.py
  status_one watcher watcher.py
}

case "${1:-}" in
  start)
    start_all
    ;;
  stop)
    stop_all
    ;;
  restart)
    stop_all
    start_all
    ;;
  status)
    status_all
    ;;
  *)
    usage
    exit 2
    ;;
esac
