#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
source .venv/bin/activate

export CODEX_BYPASS_SANDBOX="${CODEX_BYPASS_SANDBOX:-1}"
exec python codex_worker.py
