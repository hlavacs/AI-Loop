#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: $0 [--timeout seconds] -- <executable> [args...]" >&2
}

timeout_seconds="${AI_LOOP_CRASH_SAFE_TIMEOUT:-60}"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --timeout)
      if [ "$#" -lt 2 ]; then
        usage
        exit 2
      fi
      timeout_seconds="$2"
      shift 2
      ;;
    --)
      shift
      break
      ;;
    -*)
      usage
      exit 2
      ;;
    *)
      break
      ;;
  esac
done

if [ "$#" -lt 1 ]; then
  usage
  exit 2
fi

exe="$1"
shift

if [ ! -x "$exe" ] && ! command -v "$exe" >/dev/null 2>&1; then
  echo "ai_run_crash_safe: executable not found or not executable: $exe" >&2
  exit 127
fi

if command -v ulimit >/dev/null 2>&1; then
  ulimit -c 0 || true
fi

if command -v timeout >/dev/null 2>&1; then
  timeout_cmd=(timeout "$timeout_seconds")
elif command -v gtimeout >/dev/null 2>&1; then
  timeout_cmd=(gtimeout "$timeout_seconds")
else
  timeout_cmd=()
fi

if [ "$(uname -s)" = "Darwin" ] && command -v lldb >/dev/null 2>&1; then
  lldb_cmd=(
    lldb
    --batch
    -o "run"
    -k "thread backtrace all"
    -- "$exe"
  )
  if [ "${#timeout_cmd[@]}" -gt 0 ]; then
    exec "${timeout_cmd[@]}" "${lldb_cmd[@]}" "$@"
  fi
  exec "${lldb_cmd[@]}" "$@"
fi

if [ "${#timeout_cmd[@]}" -gt 0 ]; then
  exec "${timeout_cmd[@]}" "$exe" "$@"
fi

exec "$exe" "$@"
