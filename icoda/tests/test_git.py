"""git helpers on a throwaway repository: status, worktrees, promotion with rollback, commits, revert."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from icoda_core import git

AUTHOR = ("Test", "test@example.org")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    git.run_git(["init", "-q", "-b", "main"], path)
    (path / "keep.txt").write_text("keep\n")
    (path / "src").mkdir()
    (path / "src" / "a.cpp").write_text("int a() { return 1; }\n")
    git.commit_all(path, "initial", *AUTHOR)
    return path


def test_status_and_clean(repo: Path) -> None:
    assert git.is_repository(repo) and git.is_clean(repo) and git.is_own_repository(repo)
    nested = repo / "nested"
    nested.mkdir()
    assert git.is_repository(nested) and not git.is_own_repository(nested)
    assert git.repository_root(nested) == repo.resolve()
    (repo / "new.txt").write_text("x")
    (repo / "keep.txt").write_text("changed")
    (repo / "src" / "a.cpp").unlink()
    statuses = {c.path: c.status for c in git.status_changes(repo)}
    assert statuses == {"new.txt": "A", "keep.txt": "M", "src/a.cpp": "D"}
    assert not git.is_clean(repo)
    assert git.is_clean(repo, ignore_prefixes=("new.txt", "keep.txt", "src/"))


def test_worktree_promotion_copies_adds_and_deletes(repo: Path, tmp_path: Path) -> None:
    tree = git.create_worktree(repo, tmp_path / "wt", "icoda/step-1")
    (tree / "src" / "a.cpp").write_text("int a() { return 2; }\n")
    (tree / "src" / "b.cpp").write_text("int b();\n")
    (tree / "keep.txt").unlink()
    promoted = git.promote_worktree(repo, tree)
    assert sorted(promoted) == ["keep.txt", "src/a.cpp", "src/b.cpp"]
    assert (repo / "src" / "a.cpp").read_text().strip() == "int a() { return 2; }"
    assert (repo / "src" / "b.cpp").exists() and not (repo / "keep.txt").exists()
    git.remove_worktree(repo, tree, "icoda/step-1")
    assert not tree.exists()


def test_promotion_rolls_back_on_mid_copy_failure(repo: Path, tmp_path: Path) -> None:
    tree = git.create_worktree(repo, tmp_path / "wt", "icoda/step-2")
    (tree / "keep.txt").write_text("modified\n")          # applied first (alphabetical)
    (tree / "src" / "a.cpp").write_text("int a() { return 3; }\n")
    shutil.rmtree(repo / "src")
    (repo / "src").write_text("a file where a directory is needed\n")   # second copy fails
    with pytest.raises(git.PromotionError) as info:
        git.promote_worktree(repo, tree)
    assert "rolled back 1 of 1" in str(info.value)
    assert (repo / "keep.txt").read_text() == "keep\n"


def test_commit_and_revert(repo: Path) -> None:
    before = git.head_commit(repo)
    (repo / "keep.txt").write_text("v2\n")
    after = git.commit_all(repo, "step", *AUTHOR)
    assert after != before and git.is_clean(repo)
    git.revert_last_commit(repo, *AUTHOR)
    assert (repo / "keep.txt").read_text() == "keep\n"
    assert git.run_git(["rev-list", "--count", "HEAD"], repo).stdout.strip() == "3"
