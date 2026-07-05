#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'USAGE'
usage: ./ai_hibernation.bash status
       ./ai_hibernation.bash disable
       ./ai_hibernation.bash enable

macOS only. Uses pmset to read or change hibernatemode.
disable: sudo pmset -a hibernatemode 0
enable:  sudo pmset -a hibernatemode 25
USAGE
}

if [ "$#" -ne 1 ]; then
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

print_status() {
  local mode
  mode="$(current_mode)"
  if [ "$mode" = "unavailable" ]; then
    echo "hibernatemode: unavailable"
    echo "hibernation: pmset did not report a hibernatemode setting on this system"
    return 0
  fi
  echo "hibernatemode: $mode"
  case "$mode" in
    0)
      echo "hibernation: disabled"
      ;;
    3)
      echo "hibernation: enabled (default portable mode)"
      ;;
    25)
      echo "hibernation: enabled (deep hibernation mode)"
      ;;
    *)
      echo "hibernation: custom mode"
      ;;
  esac
}

set_mode() {
  local mode="$1"
  sudo pmset -a hibernatemode "$mode"
  print_status
}

case "$1" in
  status)
    print_status
    ;;
  disable)
    set_mode 0
    ;;
  enable)
    set_mode 25
    ;;
  -h|--help)
    usage
    ;;
  *)
    usage
    exit 2
    ;;
esac
