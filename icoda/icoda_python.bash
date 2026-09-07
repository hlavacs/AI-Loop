#!/usr/bin/env bash
# Sourced by icoda.bash: pick a Python 3.10+ interpreter for ICODA.

icoda_python_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

icoda_python_can_run() {
  local candidate="$1"
  [ -x "$candidate" ] || command -v "$candidate" >/dev/null 2>&1 || return 1
  "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

icoda_python_has_tk() {
  "$1" -c 'import tkinter' >/dev/null 2>&1
}

choose_icoda_python() {
  local candidate
  if [ "${ICODA_PYTHON:-}" != "" ]; then
    icoda_python_can_run "$ICODA_PYTHON" || { echo "ICODA_PYTHON does not run: $ICODA_PYTHON" >&2; return 1; }
    printf '%s\n' "$ICODA_PYTHON"
    return 0
  fi
  for candidate in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
    if icoda_python_can_run "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  echo "could not find a Python 3.10+ interpreter" >&2
  return 1
}
