#!/usr/bin/env bash
# Run ICODA's complete verification gate and retain its evidence.
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir"

python="${ICODA_VERIFY_PYTHON:-$script_dir/.icoda-venv/bin/python}"
if [ ! -x "$python" ] && ! command -v "$python" >/dev/null 2>&1; then
  echo "verify: run ./icoda.bash once to create .icoda-venv" >&2
  exit 1
fi
if ! "$python" -c 'import coverage, PIL, pytest' >/dev/null 2>&1; then
  echo "verify: install development tools with .icoda-venv/bin/python -m pip install -e '\''.[dev]'\''" >&2
  exit 1
fi

exec "$python" tests/verify.py "$@"
