#!/usr/bin/env bash

ai_loop_python_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

python_can_run() {
  local candidate="$1"
  local resolved
  [ -x "$candidate" ] || command -v "$candidate" >/dev/null 2>&1 || return 1
  resolved="$(command -v "$candidate" 2>/dev/null || printf '%s' "$candidate")"
  if [ "$(uname -s)" = "Darwin" ] &&
    [ "$resolved" = "/usr/bin/python3" ] &&
    ! xcode-select -p >/dev/null 2>&1; then
    return 1
  fi
  "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

python_has_redis() {
  local candidate="$1"
  "$candidate" -c 'import redis' >/dev/null 2>&1
}

choose_ai_loop_python() {
  local candidate

  if [ "${AI_LOOP_PYTHON:-}" != "" ]; then
    python_can_run "$AI_LOOP_PYTHON" || {
      echo "AI_LOOP_PYTHON does not run: $AI_LOOP_PYTHON" >&2
      return 1
    }
    printf '%s\n' "$AI_LOOP_PYTHON"
    return 0
  fi

  for candidate in "$ai_loop_python_dir/.venv/bin/python" "$ai_loop_python_dir/.gui-venv/bin/python" "$ai_loop_python_dir/.venv/bin/python3.14" "$ai_loop_python_dir/.venv/bin/python3.12" "$ai_loop_python_dir/.venv/bin/python3.11" "$ai_loop_python_dir/.venv/bin/python3.10" python3.14 python3.12 python3.11 python3.10 python3; do
    if python_can_run "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  echo "could not find a runnable Python interpreter" >&2
  return 1
}

resolve_ai_loop_python() {
  local candidate="$1"
  local dir
  local base

  if [[ "$candidate" == */* ]]; then
    dir="$(dirname "$candidate")"
    base="$(basename "$candidate")"
    (cd "$dir" && printf '%s/%s\n' "$PWD" "$base")
    return
  fi

  command -v "$candidate"
}

quote_ai_loop_shell_word() {
  printf '%q' "$1"
}

ensure_ai_loop_python_redis() {
  local python_bin="$1"
  local site_packages
  local absolute_site_packages

  if python_has_redis "$python_bin"; then
    return 0
  fi

  for site_packages in "$ai_loop_python_dir"/.venv/lib/python*/site-packages; do
    if [ -d "$site_packages/redis" ]; then
      absolute_site_packages="$(cd "$site_packages" && pwd)"
      export PYTHONPATH="$absolute_site_packages${PYTHONPATH:+:$PYTHONPATH}"
      break
    fi
  done

  if python_has_redis "$python_bin"; then
    return 0
  fi

  echo "selected Python cannot import redis: $python_bin" >&2
  echo "install it with: $python_bin -m pip install redis" >&2
  return 1
}
