#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo="${AI_LOOP_TARGET_REPO:-/Users/hlavacs/GitHub/ViennaVulkanEngine}"
runs_dir="${AI_LOOP_RUNS_DIR:-/Users/hlavacs/GitHub/ai-runs}"
force="${AI_LOOP_FORCE_REMOVE_WORKTREES:-1}"

if [[ ! -d "$repo/.git" && ! -f "$repo/.git" ]]; then
  echo "target repo is not a git checkout: $repo" >&2
  exit 1
fi

if [[ ! -d "$runs_dir" ]]; then
  echo "AI runs directory does not exist: $runs_dir"
  exit 0
fi

worktrees=()
while IFS= read -r worktree; do
  worktrees+=("$worktree")
done < <(
  git -C "$repo" worktree list --porcelain |
    awk '/^worktree / {print substr($0, 10)}' |
    grep -E "^${runs_dir%/}/" || true
)

echo "AI worktree cleanup"
echo "  - repo: $repo"
echo "  - runs: $runs_dir"
echo "  - force: $force"

if [[ "${#worktrees[@]}" -eq 0 ]]; then
  echo "  - status: no registered AI worktrees found"
  git -C "$repo" worktree prune
else
  remove_args=(worktree remove)
  if [[ "$force" != "0" && "$force" != "false" && "$force" != "no" ]]; then
    remove_args+=(--force)
  fi

  for worktree in "${worktrees[@]}"; do
    echo "  - removing: $worktree"
    git -C "$repo" "${remove_args[@]}" "$worktree"
  done

  echo "  - pruning: stale git worktree metadata"
  git -C "$repo" worktree prune
fi

leftover_count=0
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

echo "  - done: removed ${#worktrees[@]} registered AI worktree(s) and $leftover_count leftover folder(s)"
