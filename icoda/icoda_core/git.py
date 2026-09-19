"""git helpers: worktrees, status, promotion with rollback, commits."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from difflib import unified_diff
from pathlib import Path


class GitError(RuntimeError):
    """A git command failed."""


class PromotionError(GitError):
    """Copying a worktree's changes onto the working tree failed; the message says what was rolled back."""


@dataclass(frozen=True)
class Change:
    """One changed path relative to a repository root: ``status`` is ``M``, ``A`` or ``D``."""

    status: str
    path: str


def run_git(args: Sequence[str], cwd: Path | str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run ``git`` with ``args`` in ``cwd``; raise :class:`GitError` on failure when ``check`` is set."""
    result = subprocess.run(["git", "--no-optional-locks", *args], cwd=str(cwd), capture_output=True,
                            text=True, check=False)
    if check and result.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed in {cwd}: {result.stderr.strip() or result.stdout.strip()}")
    return result


def is_repository(path: Path | str) -> bool:
    return run_git(["rev-parse", "--is-inside-work-tree"], path, check=False).stdout.strip() == "true"


def repository_root(path: Path | str) -> Path | None:
    """The top level of the repository containing ``path`` (a parent repository counts), or None."""
    output = run_git(["rev-parse", "--show-toplevel"], path, check=False).stdout.strip()
    return Path(output).resolve() if output else None


def is_own_repository(path: Path | str) -> bool:
    """True when ``path`` itself is the top level of a repository, not merely inside a parent's."""
    return repository_root(path) == Path(path).resolve()


def head_commit(repo: Path | str) -> str:
    return run_git(["rev-parse", "HEAD"], repo).stdout.strip()


def status_changes(repo: Path | str) -> list[Change]:
    """Uncommitted changes, including untracked files, as :class:`Change` records."""
    output = run_git(["status", "--porcelain", "--untracked-files=all"], repo).stdout
    changes: list[Change] = []
    for line in output.splitlines():
        if len(line) < 4:
            continue
        code, path = line[:2], line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        changes.append(Change(_normalize_status(code), path))
    return changes


def _normalize_status(code: str) -> str:
    if "D" in code:
        return "D"
    if code.strip() in ("??", "A", "AM") or code[0] == "A":
        return "A"
    return "M"


def is_clean(repo: Path | str, ignore_prefixes: Sequence[str] = ()) -> bool:
    """True when nothing is changed except paths under ``ignore_prefixes``."""
    return all(change.path.startswith(tuple(ignore_prefixes)) for change in status_changes(repo)
               if ignore_prefixes) if ignore_prefixes else not status_changes(repo)


def working_tree_diff(repo: Path | str) -> str:
    """Return a no-colour source diff against HEAD, including untracked text files."""
    root = Path(repo)
    tracked = run_git(["diff", "--no-ext-diff", "--no-color", "HEAD", "--"], root).stdout.rstrip()
    additions = [_untracked_diff(root, change.path) for change in status_changes(root)
                 if change.status == "A" and run_git(["cat-file", "-e", f"HEAD:{change.path}"], root,
                                                      check=False).returncode != 0]
    return "\n".join(part for part in (tracked, *additions) if part).rstrip()


def _untracked_diff(repo: Path, path: str) -> str:
    """Represent one untracked text file without staging or otherwise changing the worktree."""
    content = (repo / path).read_text(encoding="utf-8", errors="replace")
    body = "".join(unified_diff([], content.splitlines(keepends=True), fromfile="/dev/null", tofile=f"b/{path}"))
    header = f"diff --git a/{path} b/{path}\nnew file mode 100644"
    return header + ("\n" + body.rstrip() if body else "")


def create_worktree(repo: Path | str, path: Path | str, branch: str) -> Path:
    """Add a worktree at ``path`` on a new ``branch`` starting from HEAD."""
    run_git(["worktree", "add", "-b", branch, str(path), "HEAD"], repo)
    return Path(path)


def remove_worktree(repo: Path | str, path: Path | str, branch: str | None = None) -> None:
    run_git(["worktree", "remove", "--force", str(path)], repo, check=False)
    if Path(path).exists():
        shutil.rmtree(path, ignore_errors=True)
    run_git(["worktree", "prune"], repo, check=False)
    if branch:
        run_git(["branch", "-D", branch], repo, check=False)


def promote_worktree(repo: Path | str, worktree: Path | str) -> list[str]:
    """Copy the worktree's uncommitted changes onto the repository; roll everything back on failure."""
    repo_path, tree_path = Path(repo), Path(worktree)
    changes = status_changes(tree_path)
    applied: list[Change] = []
    try:
        for change in changes:
            _apply_change(repo_path, tree_path, change)
            applied.append(change)
    except OSError as exc:
        restored = _rollback(repo_path, applied)
        raise PromotionError(f"promotion of {applied[-1].path if applied else '?'} failed ({exc}); "
                             f"rolled back {restored} of {len(applied)} applied paths") from exc
    return [change.path for change in changes]


def rollback_promotion(repo: Path | str, paths: Sequence[str]) -> int:
    """Restore successfully promoted paths from HEAD; return the number restored."""
    return _rollback(Path(repo), [Change("", path) for path in paths])


def _apply_change(repo: Path, worktree: Path, change: Change) -> None:
    target = repo / change.path
    if change.status == "D":
        if target.exists():
            target.unlink()
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(worktree / change.path, target)


def _rollback(repo: Path, applied: Sequence[Change]) -> int:
    """Restore each applied path from HEAD, or delete it when HEAD does not have it."""
    restored = 0
    for change in reversed(applied):
        tracked = run_git(["cat-file", "-e", f"HEAD:{change.path}"], repo, check=False).returncode == 0
        if tracked:
            ok = run_git(["checkout", "--", change.path], repo, check=False).returncode == 0
        else:
            target = repo / change.path
            ok = True
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            elif target.exists():
                target.unlink()
        restored += int(ok)
    return restored


def commit_all(repo: Path | str, message: str, author_name: str, author_email: str) -> str:
    """Stage everything and commit; return the new commit hash."""
    run_git(["add", "-A"], repo)
    run_git(["-c", f"user.name={author_name}", "-c", f"user.email={author_email}", "commit", "-q", "-m", message],
            repo)
    return head_commit(repo)


def revert_last_commit(repo: Path | str, author_name: str, author_email: str) -> str:
    """Create a commit that undoes HEAD; return its hash."""
    run_git(["-c", f"user.name={author_name}", "-c", f"user.email={author_email}", "revert", "--no-edit", "HEAD"],
            repo)
    return head_commit(repo)
