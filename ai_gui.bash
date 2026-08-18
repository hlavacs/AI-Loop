#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
parent_launcher="$script_dir/../start-ai-loop-with-email.bash"

# The private parent launcher calls this script again after exporting its
# settings. Delegate only on the initial entry so that callback continues
# with the local Python GUI instead of recursing indefinitely.
if [[ "${AI_LOOP_PARENT_LAUNCHER_ACTIVE:-0}" != "1" && -f "$parent_launcher" ]]; then
  export AI_LOOP_PARENT_LAUNCHER_ACTIVE=1
  exec bash "$parent_launcher" "$@"
fi

cd "$script_dir"
source ./ai_loop_python.bash

manual_command=""

run_privileged() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    echo "automatic installation needs root privileges, but sudo is not available" >&2
    return 1
  fi
}

install_component() {
  local component="$1"
  local python_version="${2:-3.14}"

  echo "ai-loop GUI: $component is missing; attempting automatic installation..." >&2
  if [ "$(uname -s)" = "Darwin" ]; then
    case "$component" in
      Python)
        manual_command="brew install python@3.14 python-tk@3.14"
        command -v brew >/dev/null 2>&1 && brew install python@3.14 python-tk@3.14
        ;;
      Tkinter)
        manual_command="brew install python-tk@$python_version"
        command -v brew >/dev/null 2>&1 && brew install "python-tk@$python_version"
        ;;
      Git)
        manual_command="brew install git"
        command -v brew >/dev/null 2>&1 && brew install git
        ;;
      Redis)
        manual_command="brew install redis"
        command -v brew >/dev/null 2>&1 && brew install redis
        ;;
    esac
  elif command -v apt-get >/dev/null 2>&1; then
    case "$component" in
      Python)
        manual_command="sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-tk"
        run_privileged apt-get update &&
          run_privileged apt-get install -y python3 python3-venv python3-tk
        ;;
      Tkinter)
        manual_command="sudo apt-get install -y python3-tk"
        run_privileged apt-get install -y python3-tk
        ;;
      Git)
        manual_command="sudo apt-get install -y git"
        run_privileged apt-get install -y git
        ;;
      Redis)
        manual_command="sudo apt-get install -y redis-server"
        run_privileged apt-get install -y redis-server
        ;;
    esac
  elif command -v dnf >/dev/null 2>&1; then
    case "$component" in
      Python)
        manual_command="sudo dnf install -y python3 python3-tkinter"
        run_privileged dnf install -y python3 python3-tkinter
        ;;
      Tkinter)
        manual_command="sudo dnf install -y python3-tkinter"
        run_privileged dnf install -y python3-tkinter
        ;;
      Git)
        manual_command="sudo dnf install -y git"
        run_privileged dnf install -y git
        ;;
      Redis)
        manual_command="sudo dnf install -y redis"
        run_privileged dnf install -y redis
        ;;
    esac
  elif command -v pacman >/dev/null 2>&1; then
    case "$component" in
      Python)
        manual_command="sudo pacman -S --needed python tk"
        run_privileged pacman -S --needed --noconfirm python tk
        ;;
      Tkinter)
        manual_command="sudo pacman -S --needed tk"
        run_privileged pacman -S --needed --noconfirm tk
        ;;
      Git)
        manual_command="sudo pacman -S --needed git"
        run_privileged pacman -S --needed --noconfirm git
        ;;
      Redis)
        manual_command="sudo pacman -S --needed redis"
        run_privileged pacman -S --needed --noconfirm redis
        ;;
    esac
  else
    manual_command="Install $component with your operating system's package manager."
    return 1
  fi
}

installation_failed() {
  local component="$1"
  local detail="$2"
  echo "ai-loop GUI could not install $component: $detail" >&2
  echo "Usual manual fix: $manual_command" >&2
  exit 1
}

if ! python_bin="$(choose_ai_loop_python 2>/dev/null)"; then
  install_component Python || installation_failed Python "no supported package manager succeeded"
  python_bin="$(choose_ai_loop_python 2>/dev/null)" ||
    installation_failed Python "the installer completed, but Python 3.10+ is still not runnable"
fi

python_version="$("$python_bin" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if ! "$python_bin" -c 'import tkinter' >/dev/null 2>&1; then
  install_component Tkinter "$python_version" ||
    installation_failed Tkinter "the package-manager command failed"
  "$python_bin" -c 'import tkinter' >/dev/null 2>&1 ||
    installation_failed Tkinter "it is still unavailable to $python_bin after installation"
fi

if ! command -v git >/dev/null 2>&1; then
  install_component Git || installation_failed Git "the package-manager command failed"
  command -v git >/dev/null 2>&1 ||
    installation_failed Git "the installer completed, but git is still not on PATH"
fi

if ! command -v redis-server >/dev/null 2>&1; then
  install_component Redis || installation_failed Redis "the package-manager command failed"
  command -v redis-server >/dev/null 2>&1 ||
    installation_failed Redis "the installer completed, but redis-server is still not on PATH"
fi

exec "$python_bin" ai_loop_gui.py "$@"
