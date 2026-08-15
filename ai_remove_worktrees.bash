#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir"

source ./ai_loop_python.bash

usage() {
  cat <<'USAGE'
Usage: ai_remove_worktrees.bash [--yes] [--dry-run] [--force]

Removes AI job worktrees registered by target repos and leftover folders
under the AI runs directory.

  --yes      Actually delete. Without it, nothing is removed.
  --dry-run  Show what would be removed, then exit.
  --force    Pass --force to `git worktree remove`, discarding uncommitted
             changes in the worktrees. Default is off: worktrees with
             uncommitted (un-promoted) work are reported and kept.
             AI_LOOP_FORCE_REMOVE_WORKTREES=1 also enables this.
USAGE
}

confirmed=0
dry_run=0
force="${AI_LOOP_FORCE_REMOVE_WORKTREES:-0}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes) confirmed=1 ;;
    --dry-run) dry_run=1 ;;
    --force) force=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if [[ "$dry_run" == "0" && "$confirmed" == "0" ]]; then
  echo "Refusing to delete without --yes. Use --dry-run to preview." >&2
  usage >&2
  exit 2
fi

python_bin="$(choose_ai_loop_python)"
runs_dir_raw="${AI_LOOP_RUNS_DIR:-$(cd "$script_dir/.." && pwd)/ai-runs}"
db_path="${AI_LOOP_DB:-./ai_loop.sqlite3}"

# Canonicalize the runs directory so the deletion guard below compares real
# paths, not whatever string AI_LOOP_RUNS_DIR happened to contain.
if [[ -d "$runs_dir_raw" ]]; then
  runs_dir="$(cd -- "$runs_dir_raw" && pwd -P)"
else
  runs_dir="$runs_dir_raw"
fi

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
if [[ "$dry_run" == "1" ]]; then
  echo "  - mode: dry run (nothing will be deleted)"
fi

removed_worktrees=0
kept_worktrees=0
registered_worktrees=()
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
      if [[ "$dry_run" == "0" ]]; then
        git -C "$repo" worktree prune
      fi
      continue
    fi

    remove_args=(worktree remove)
    if [[ "$force" != "0" && "$force" != "false" && "$force" != "no" ]]; then
      remove_args+=(--force)
    fi

    for worktree in "${worktrees[@]}"; do
      if [[ "$dry_run" == "1" ]]; then
        echo "  - would remove: $worktree"
        registered_worktrees+=("$worktree")
        continue
      fi
      if git -C "$repo" "${remove_args[@]}" "$worktree"; then
        echo "  - removed: $worktree"
        removed_worktrees=$((removed_worktrees + 1))
      else
        echo "  - kept: $worktree (uncommitted changes; rerun with --force to discard them)"
        kept_worktrees=$((kept_worktrees + 1))
      fi
    done

    if [[ "$dry_run" == "0" ]]; then
      echo "  - pruning: stale git worktree metadata"
      git -C "$repo" worktree prune
    fi
  done
fi

if [[ "${#repos[@]}" -eq 0 ]]; then
  echo "  - status: no target repos found in AI_LOOP_TARGET_REPO or $db_path"
  echo "  - skipping leftover-folder sweep: cannot tell which folders are still live worktrees"
  echo "  - done: removed 0 registered AI worktree(s); leftover folders untouched"
  exit 0
fi

leftover_count=0
if [[ "$kept_worktrees" -gt 0 ]]; then
  echo "  - skipping leftover-folder sweep: $kept_worktrees worktree(s) with uncommitted work were kept"
elif [[ -d "$runs_dir" ]]; then
  while IFS= read -r leftover; do
    leftover_real="$(cd -- "$leftover" && pwd -P)"
    for registered in ${registered_worktrees[@]+"${registered_worktrees[@]}"}; do
      if [[ "$leftover_real" == "$registered" ]]; then
        continue 2
      fi
    done
    case "$leftover_real" in
      "$runs_dir"/*)
        if [[ "$dry_run" == "1" ]]; then
          echo "  - would delete leftover folder: $leftover_real"
        else
          echo "  - deleting leftover folder: $leftover_real"
          rm -rf -- "$leftover_real"
        fi
        leftover_count=$((leftover_count + 1))
        ;;
      *)
        echo "refusing to delete path outside AI runs directory: $leftover_real" >&2
        exit 1
        ;;
    esac
  done < <(find "$runs_dir" -mindepth 1 -maxdepth 1 -type d -print | sort)
else
  echo "  - status: AI runs directory does not exist"
fi

if [[ "$dry_run" == "1" ]]; then
  echo "  - done (dry run): would remove ${#repos[@]} repo(s)' registered AI worktree(s) and $leftover_count leftover folder(s)"
else
  echo "  - done: removed $removed_worktrees registered AI worktree(s) and $leftover_count leftover folder(s)"
fi
