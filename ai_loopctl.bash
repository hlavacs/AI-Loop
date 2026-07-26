#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

runtime_dir="${AI_LOOP_RUNTIME_DIR:-./run}"
mkdir -p "$runtime_dir"

usage() {
  echo "usage: $0 stop|status" >&2
}

pid_file() {
  echo "$runtime_dir/$1.pid"
}

job_runtime_root() {
  echo "$runtime_dir/jobs"
}

find_pids() {
  local script="$1"
  pgrep -f "python[0-9.]* ${script}" 2>/dev/null || true
}

is_running() {
  local pid="$1"
  if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
    return 1
  fi
  if [ -r "/proc/$pid/stat" ]; then
    local state
    state="$(awk '{print $3}' "/proc/$pid/stat" 2>/dev/null || true)"
    [ "$state" != "Z" ]
    return
  fi
  return 0
}
read_pid() {
  local file
  file="$(pid_file "$1")"
  if [ -f "$file" ]; then
    cat "$file"
  fi
}

stop_pid_file() {
  local file="$1"
  local label="$2"
  local pid
  pid="$(cat "$file" 2>/dev/null || true)"

  if ! is_running "$pid"; then
    echo "$label not running"
    rm -f "$file"
    return
  fi

  kill "$pid"
  for _ in $(seq 1 20); do
    if ! is_running "$pid"; then
      rm -f "$file"
      echo "stopped $label pid=$pid"
      return
    fi
    sleep 0.25
  done

  kill -KILL "$pid"
  rm -f "$file"
  echo "killed $label pid=$pid"
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

stop_job_processes() {
  local root
  root="$(job_runtime_root)"
  if [ ! -d "$root" ]; then
    echo "no per-job processes"
    return
  fi

  local found=0
  local job_dir job_id name file
  for job_dir in "$root"/*; do
    [ -d "$job_dir" ] || continue
    job_id="$(basename "$job_dir")"
    for name in watcher worker controller codex_worker claude_controller; do
      file="$job_dir/$name.pid"
      [ -f "$file" ] || continue
      found=1
      stop_pid_file "$file" "job $job_id $name"
    done
  done
  if [ "$found" -eq 0 ]; then
    echo "no per-job processes"
  fi
}

status_job_processes() {
  local root
  root="$(job_runtime_root)"
  if [ ! -d "$root" ]; then
    echo "per-job processes: none"
    return
  fi

  local found=0
  local job_dir job_id name file pid
  for job_dir in "$root"/*; do
    [ -d "$job_dir" ] || continue
    job_id="$(basename "$job_dir")"
    for name in controller worker watcher claude_controller codex_worker; do
      file="$job_dir/$name.pid"
      [ -f "$file" ] || continue
      found=1
      pid="$(cat "$file" 2>/dev/null || true)"
      if is_running "$pid"; then
        echo "job $job_id $name running pid=$pid"
      else
        echo "job $job_id $name stopped stale_pid=$pid"
      fi
    done
  done
  if [ "$found" -eq 0 ]; then
    echo "per-job processes: none"
  fi
}

stop_all() {
  stop_job_processes
  stop_one watcher watcher.py
  stop_one worker worker.py
  stop_one controller controller.py
}

status_all() {
  status_one controller controller.py
  status_one worker worker.py
  status_one watcher watcher.py
  status_job_processes
}

case "${1:-}" in
  stop)
    stop_all
    ;;
  status)
    status_all
    ;;
  *)
    usage
    exit 2
    ;;
esac
