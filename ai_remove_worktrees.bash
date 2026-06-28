#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir"

source ./ai_loop_python.bash

python_bin="$(choose_ai_loop_python)"
runs_dir="${AI_LOOP_RUNS_DIR:-$(cd "$script_dir/.." && pwd)/ai-runs}"
db_path="${AI_LOOP_DB:-./ai_loop.sqlite3}"
force="${AI_LOOP_FORCE_REMOVE_WORKTREES:-1}"

repos=()
if [[ "${AI_LOOP_TARGET_REPO:-}" != "" ]]; then
  repos+=("$(cd "$AI_LOOP_TARGET_REPO" && pwd)")
elif [[ -f "$db_path" ]]; then
  while IFS= read -r repo; do
    [[ "$repo" == "" ]] && continue
    repos+=("$repo")
  done < <("$python_bin" - "$db_path" <<'PY'
import sqlite3
import sys

conn = sqlite3.connect(sys.argv[1])
rows = conn.execute(
    """
    SELECT DISTINCT repo_path
    FROM jobs
    WHERE repo_path IS NOT NULL AND repo_path != ''
    ORDER BY repo_path
    """
).fetchall()
for (repo_path,) in rows:
    print(repo_path)
PY
)
fi

echo "AI worktree cleanup"
echo "  - runs: $runs_dir"
echo "  - force: $force"

removed_worktrees=0
if [[ "${#repos[@]}" -gt 0 ]]; then
  for repo in "${repos[@]}"; do
    if [[ ! -d "$repo/.git" && ! -f "$repo/.git" ]]; then
      echo "  - skipping repo: $repo is not a git checkout"
      continue
    fi

    echo "  - repo: $repo"
    worktrees=()
    while IFS= read -r worktree; do
      case "$worktree" in
        "$runs_dir"/*) worktrees+=("$worktree") ;;
      esac
    done < <(git -C "$repo" worktree list --porcelain | awk '/^worktree / {print substr($0, 10)}')

    if [[ "${#worktrees[@]}" -eq 0 ]]; then
      echo "  - status: no registered AI worktrees found for this repo"
      git -C "$repo" worktree prune
      continue
    fi

    remove_args=(worktree remove)
    if [[ "$force" != "0" && "$force" != "false" && "$force" != "no" ]]; then
      remove_args+=(--force)
    fi

    for worktree in "${worktrees[@]}"; do
      echo "  - removing: $worktree"
      git -C "$repo" "${remove_args[@]}" "$worktree"
      removed_worktrees=$((removed_worktrees + 1))
    done

    echo "  - pruning: stale git worktree metadata"
    git -C "$repo" worktree prune
  done
fi

if [[ "${#repos[@]}" -eq 0 ]]; then
  echo "  - status: no target repos found in AI_LOOP_TARGET_REPO or $db_path"
fi

leftover_count=0
if [[ -d "$runs_dir" ]]; then
  while IFS= read -r leftover; do
    case "$leftover" in
      "$runs_dir"/*)
        echo "  - deleting leftover folder: $leftover"
        rm -rf -- "$leftover"
        leftover_count=$((leftover_count + 1))
        ;;
      *)
        echo "refusing to delete path outside AI runs directory: $leftover" >&2
        exit 1
        ;;
    esac
  done < <(find "$runs_dir" -mindepth 1 -maxdepth 1 -type d -print | sort)
else
  echo "  - status: AI runs directory does not exist"
fi

echo "  - done: removed $removed_worktrees registered AI worktree(s) and $leftover_count leftover folder(s)"
