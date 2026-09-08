#!/usr/bin/env bash
# ICODA launcher for macOS and Linux: checks the tools, keeps .icoda-venv current, starts icoda.py.
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir"
# shellcheck source=icoda_python.bash
source ./icoda_python.bash

venv_dir="$script_dir/.icoda-venv"
venv_python="$venv_dir/bin/python"
stamp="$venv_dir/.installed-from"

pkg_install() {
  # Install a package by the name the local package manager knows; print the manual command on failure.
  local brew_pkg="$1" apt_pkg="$2" dnf_pkg="$3"
  if [ "$(uname -s)" = "Darwin" ] && command -v brew >/dev/null 2>&1; then
    brew install "$brew_pkg" && return 0
    echo "icoda: manual fix: brew install $brew_pkg" >&2
  elif command -v apt-get >/dev/null 2>&1; then
    sudo apt-get install -y "$apt_pkg" && return 0
    echo "icoda: manual fix: sudo apt-get install -y $apt_pkg" >&2
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y "$dnf_pkg" && return 0
    echo "icoda: manual fix: sudo dnf install -y $dnf_pkg" >&2
  else
    echo "icoda: install $brew_pkg with your package manager" >&2
  fi
  return 1
}

need_tool() {
  # need_tool <command> <brew> <apt> <dnf> [fatal]
  local cmd="$1" fatal="${5:-no}"
  command -v "$cmd" >/dev/null 2>&1 && return 0
  echo "icoda: $cmd is missing; attempting installation..." >&2
  pkg_install "$2" "$3" "$4" && return 0
  if [ "$fatal" = "fatal" ]; then
    echo "icoda: $cmd is required" >&2
    exit 1
  fi
  echo "icoda: continuing without $cmd (building projects will not work until it is installed)" >&2
}

check_clang() {
  if [ "$(uname -s)" = "Darwin" ]; then
    xcrun --find clang >/dev/null 2>&1 && return 0
    echo "icoda: no clang toolchain; install the Xcode Command Line Tools (xcode-select --install) or 'brew install llvm'" >&2
    return 0
  fi
  for c in clang clang-20 clang-19 clang-18 clang-17 clang-16; do
    command -v "$c" >/dev/null 2>&1 && return 0
  done
  echo "icoda: no clang found; install it with your package manager (e.g. sudo apt-get install -y clang)" >&2
}

check_vcpkg() {
  if [ -n "${VCPKG_ROOT:-}" ] && [ -x "$VCPKG_ROOT/vcpkg" ]; then return 0; fi
  command -v vcpkg >/dev/null 2>&1 && return 0
  echo "icoda: vcpkg not found (set VCPKG_ROOT); library installation will be unavailable" >&2
}

ensure_venv() {
  local base_python="$1"
  if [ ! -x "$venv_python" ]; then
    echo "icoda: creating virtual environment .icoda-venv" >&2
    "$base_python" -m venv "$venv_dir"
  fi
  if [ ! -f "$stamp" ] || [ pyproject.toml -nt "$stamp" ]; then
    echo "icoda: installing Python dependencies" >&2
    "$venv_python" -m pip install --quiet --upgrade pip
    # The libclang wheel and LLVM's clang bindings both own the clang/ package; only one may be installed.
    "$venv_python" -m pip uninstall --quiet --yes libclang >/dev/null 2>&1 || true
    "$venv_python" -m pip install --quiet -e .
    date > "$stamp"
  fi
}

python_bin="$(choose_icoda_python)" || exit 1
if ! icoda_python_has_tk "$python_bin"; then
  version="$("$python_bin" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  echo "icoda: Tkinter is missing for $python_bin; attempting installation..." >&2
  pkg_install "python-tk@$version" "python3-tk" "python3-tkinter" || exit 1
  icoda_python_has_tk "$python_bin" || { echo "icoda: Tkinter still unavailable for $python_bin" >&2; exit 1; }
fi
need_tool git git git git fatal
need_tool cmake cmake cmake cmake
need_tool ninja ninja ninja-build ninja-build
check_clang
check_vcpkg
ensure_venv "$python_bin"
exec "$venv_python" icoda.py "$@"
