#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'USAGE'
usage: ./ai_hibernation.bash status
       ./ai_hibernation.bash disable
       ./ai_hibernation.bash enable
       ./ai_hibernation.bash set <0|3|25>

macOS only. Uses pmset to read or change hibernatemode.
Works on macOS only.

Modes:
  0: disabled
  3: enabled (default portable mode)
 25: enabled (deep hibernation mode)
USAGE
}

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
  usage
  exit 2
fi

if [ "$(uname -s)" != "Darwin" ]; then
  echo "pmset hibernation control is only available on macOS" >&2
  exit 1
fi

if ! command -v pmset >/dev/null 2>&1; then
  echo "pmset not found" >&2
  exit 1
fi

current_mode() {
  pmset -g | awk '$1 == "hibernatemode" { print $2; found=1 } END { if (!found) print "unavailable" }'
}

mode_description() {
  case "$1" in
    0)
      echo "disabled"
      ;;
    3)
      echo "enabled (default portable mode)"
      ;;
    25)
      echo "enabled (deep hibernation mode)"
      ;;
    *)
      echo "custom mode"
      ;;
  esac
}

print_status() {
  local mode
  mode="$(current_mode)"
  if [ "$mode" = "unavailable" ]; then
    echo "hibernatemode: unavailable"
    echo "hibernation: pmset did not report a hibernatemode setting on this system"
    return 0
  fi
  echo "hibernatemode: $mode"
  echo "hibernation: $(mode_description "$mode")"
}

set_mode() {
  local mode="$1"
  case "$mode" in
    0|3|25)
      ;;
    *)
      echo "invalid hibernatemode: $mode (expected 0, 3, or 25)" >&2
      exit 2
      ;;
  esac
  echo "setting hibernatemode $mode: $(mode_description "$mode")"
  sudo pmset -a hibernatemode "$mode"
  print_status
}

case "$1" in
  status)
    if [ "$#" -ne 1 ]; then
      usage
      exit 2
    fi
    print_status
    ;;
  disable)
    if [ "$#" -ne 1 ]; then
      usage
      exit 2
    fi
    set_mode 0
    ;;
  enable)
    if [ "$#" -ne 1 ]; then
      usage
      exit 2
    fi
    set_mode 3
    ;;
  set)
    if [ "$#" -ne 2 ]; then
      usage
      exit 2
    fi
    set_mode "$2"
    ;;
  -h|--help)
    usage
    ;;
  *)
    usage
    exit 2
    ;;
esac
