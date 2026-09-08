#!/usr/bin/env bash
# One-shot acceptance run on macOS: Homebrew LLVM (installed if missing), build the sample, start ICODA on it.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
if ! command -v brew >/dev/null 2>&1; then
  echo "mac_check: Homebrew is required (https://brew.sh)" >&2
  exit 1
fi
llvm_prefix="$(brew --prefix llvm)"
if [ ! -x "$llvm_prefix/bin/clang++" ]; then
  echo "mac_check: installing LLVM with Homebrew (a few minutes) ..." >&2
  brew install llvm
fi
for tool in cmake ninja; do
  command -v "$tool" >/dev/null 2>&1 || brew install "$tool"
done
echo "mac_check: building the sample project with $llvm_prefix/bin/clang++" >&2
(cd tests/sample_project && ./build.sh) 2>&1 | tee tests/sample_project/.icoda-build.log | tail -5
echo "mac_check: starting ICODA on the sample project" >&2
exec ./icoda.bash tests/sample_project
