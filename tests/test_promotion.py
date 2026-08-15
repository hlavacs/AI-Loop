from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

import controller
from controller import PromotionError, promote_successful_worktree, repo_has_local_change, status_paths


def run_git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def make_repo_with_worktree(base: Path, files: dict[str, str]) -> tuple[Path, Path]:
    """Build a target repo with an initial commit plus a linked worktree.

    Mirrors start_job.create_worktree semantics:
    git worktree add -b ai/<job-id> <dir> HEAD, run from the target repo.
    """
    repo = base / "repo"
    repo.mkdir()
    run_git(["init", "-q"], repo)
    run_git(["config", "user.email", "ai-loop-test@example.invalid"], repo)
    run_git(["config", "user.name", "AI Loop Test"], repo)
    for relative, content in files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    run_git(["add", "-A"], repo)
    run_git(["commit", "-q", "-m", "initial"], repo)
    runs_dir = base / "runs"
    runs_dir.mkdir()
    worktree = runs_dir / "J-promo"
    run_git(["worktree", "add", "-q", "-b", "ai/J-promo", str(worktree), "HEAD"], repo)
    return repo, worktree


def job_dict(repo: Path, worktree: Path, use_worktree: bool = True) -> dict:
    # promote_successful_worktree reads exactly these three keys.
    return {
        "repo_path": str(repo),
        "worktree_path": str(worktree),
        "use_worktree": use_worktree,
    }


class StatusPathsTests(unittest.TestCase):
    def test_modified_untracked_and_deleted_codes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _repo, worktree = make_repo_with_worktree(Path(directory), {"a.txt": "one\n", "b.txt": "two\n"})
            (worktree / "a.txt").write_text("changed\n", encoding="utf-8")
            (worktree / "new.txt").write_text("new\n", encoding="utf-8")
            (worktree / "b.txt").unlink()
            entries = dict((path, code) for code, path in status_paths(worktree))
            self.assertEqual(entries["a.txt"], " M")
            self.assertEqual(entries["new.txt"], "??")
            self.assertEqual(entries["b.txt"], " D")

    def test_untracked_files_inside_new_directory_are_listed_individually(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _repo, worktree = make_repo_with_worktree(Path(directory), {"a.txt": "one\n"})
            (worktree / "newdir").mkdir()
            (worktree / "newdir" / "inner.txt").write_text("inner\n", encoding="utf-8")
            paths = [path for _code, path in status_paths(worktree)]
            # --untracked-files=all lists the file, not a collapsed "newdir/".
            self.assertIn("newdir/inner.txt", paths)
            self.assertNotIn("newdir/", paths)

    def test_rename_returns_new_path_plus_synthetic_deletion(self) -> None:
        # git status --porcelain=v1 -z emits rename entries as "R  NEW\0ORIG\0"
        # (new path first). status_paths returns the NEW path for the rename
        # entry and appends a synthetic (" D", ORIG) entry so promotion both
        # copies the renamed file and removes the original from the target.
        with tempfile.TemporaryDirectory() as directory:
            _repo, worktree = make_repo_with_worktree(Path(directory), {"a.txt": "one\n"})
            run_git(["mv", "a.txt", "b.txt"], worktree)
            entries = status_paths(worktree)
            self.assertEqual(len(entries), 2)
            code, path = entries[0]
            self.assertEqual(code[0], "R")
            self.assertEqual(path, "b.txt")
            self.assertEqual(entries[1], (" D", "a.txt"))


class RepoHasLocalChangeTests(unittest.TestCase):
    def test_detects_dirty_path_and_ignores_clean_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, _worktree = make_repo_with_worktree(Path(directory), {"a.txt": "one\n", "b.txt": "two\n"})
            (repo / "a.txt").write_text("locally edited\n", encoding="utf-8")
            self.assertTrue(repo_has_local_change(repo, "a.txt"))
            self.assertFalse(repo_has_local_change(repo, "b.txt"))


class PromotionTests(unittest.TestCase):
    def test_promotes_modified_and_new_files_including_new_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, worktree = make_repo_with_worktree(Path(directory), {"a.txt": "one\n"})
            (worktree / "a.txt").write_text("modified\n", encoding="utf-8")
            (worktree / "new.txt").write_text("brand new\n", encoding="utf-8")
            (worktree / "newdir").mkdir()
            (worktree / "newdir" / "inner.txt").write_text("inner\n", encoding="utf-8")

            result = promote_successful_worktree(job_dict(repo, worktree))

            self.assertTrue(result["promoted"])
            self.assertEqual(result["files"], ["a.txt", "new.txt", "newdir/inner.txt"])
            self.assertEqual(result["removed"], [])
            self.assertEqual((repo / "a.txt").read_text(encoding="utf-8"), "modified\n")
            self.assertEqual((repo / "new.txt").read_text(encoding="utf-8"), "brand new\n")
            self.assertEqual((repo / "newdir" / "inner.txt").read_text(encoding="utf-8"), "inner\n")

    def test_no_changes_means_not_promoted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, worktree = make_repo_with_worktree(Path(directory), {"a.txt": "one\n"})
            result = promote_successful_worktree(job_dict(repo, worktree))
            self.assertFalse(result["promoted"])
            self.assertEqual(result["files"], [])
            self.assertIn("no changed files", result["reason"])

    def test_conflicting_local_change_raises_and_target_is_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, worktree = make_repo_with_worktree(Path(directory), {"shared.txt": "base\n"})
            (worktree / "shared.txt").write_text("worktree version\n", encoding="utf-8")
            (repo / "shared.txt").write_text("local uncommitted edit\n", encoding="utf-8")

            with self.assertRaises(PromotionError) as ctx:
                promote_successful_worktree(job_dict(repo, worktree))

            self.assertIn("shared.txt", str(ctx.exception))
            self.assertEqual(
                (repo / "shared.txt").read_text(encoding="utf-8"),
                "local uncommitted edit\n",
            )

    def test_gitignored_file_in_target_survives_promotion_of_new_directory(self) -> None:
        # H4 fix: because status lists newdir/a.txt (a file) instead of a
        # collapsed newdir/ entry, promotion copies the single file and never
        # rmtree's the target's newdir, so the ignored file survives.
        with tempfile.TemporaryDirectory() as directory:
            repo, worktree = make_repo_with_worktree(
                Path(directory),
                {".gitignore": "newdir/ignored.bin\n", "keep.txt": "keep\n"},
            )
            (repo / "newdir").mkdir()
            (repo / "newdir" / "ignored.bin").write_bytes(b"precious local build output")
            (worktree / "newdir").mkdir()
            (worktree / "newdir" / "a.txt").write_text("promoted\n", encoding="utf-8")

            result = promote_successful_worktree(job_dict(repo, worktree))

            self.assertTrue(result["promoted"])
            self.assertEqual(result["files"], ["newdir/a.txt"])
            self.assertEqual((repo / "newdir" / "a.txt").read_text(encoding="utf-8"), "promoted\n")
            self.assertEqual(
                (repo / "newdir" / "ignored.bin").read_bytes(),
                b"precious local build output",
            )

    def test_deletion_in_worktree_is_propagated_to_target(self) -> None:
        # status_paths reports an unstaged delete as ' D'; promote sees "D" in
        # the code with a missing source and removes the file from the target.
        with tempfile.TemporaryDirectory() as directory:
            repo, worktree = make_repo_with_worktree(
                Path(directory), {"a.txt": "one\n", "doomed.txt": "delete me\n"}
            )
            (worktree / "doomed.txt").unlink()

            result = promote_successful_worktree(job_dict(repo, worktree))

            self.assertTrue(result["promoted"])
            self.assertEqual(result["removed"], ["doomed.txt"])
            self.assertEqual(result["files"], ["doomed.txt"])
            self.assertFalse((repo / "doomed.txt").exists())
            self.assertTrue((repo / "a.txt").exists())

    def test_rename_in_worktree_is_fully_propagated(self) -> None:
        # A rename must land in the target as: new file present with the
        # renamed content, original file removed.
        with tempfile.TemporaryDirectory() as directory:
            repo, worktree = make_repo_with_worktree(Path(directory), {"a.txt": "one\n"})
            run_git(["mv", "a.txt", "b.txt"], worktree)

            result = promote_successful_worktree(job_dict(repo, worktree))

            self.assertTrue(result["promoted"])
            self.assertTrue((repo / "b.txt").exists())
            self.assertEqual((repo / "b.txt").read_text(encoding="utf-8"), "one\n")
            self.assertFalse((repo / "a.txt").exists())

    def test_use_worktree_false_short_circuits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, worktree = make_repo_with_worktree(Path(directory), {"a.txt": "one\n"})
            (worktree / "new.txt").write_text("new\n", encoding="utf-8")
            result = promote_successful_worktree(job_dict(repo, worktree, use_worktree=False))
            self.assertFalse(result["promoted"])
            self.assertIn("already ran in the target repository", result["reason"])
            self.assertFalse((repo / "new.txt").exists())

    def test_same_path_short_circuits_even_with_use_worktree_true(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, _worktree = make_repo_with_worktree(Path(directory), {"a.txt": "one\n"})
            result = promote_successful_worktree(job_dict(repo, repo, use_worktree=True))
            self.assertFalse(result["promoted"])
            self.assertEqual(result["files"], [])

    def test_promotion_error_is_a_runtime_error(self) -> None:
        self.assertTrue(issubclass(controller.PromotionError, RuntimeError))

    def test_on_before_copy_receives_changed_paths_before_any_file_lands(self) -> None:
        # Crash-atomicity mitigation: the callback (which finish_done_job uses
        # to durably record a promotion_started event) must fire with the full
        # changed-path list BEFORE the copy loop touches the target repo.
        with tempfile.TemporaryDirectory() as directory:
            repo, worktree = make_repo_with_worktree(Path(directory), {"a.txt": "one\n"})
            (worktree / "a.txt").write_text("modified\n", encoding="utf-8")
            (worktree / "new.txt").write_text("brand new\n", encoding="utf-8")
            observed: dict = {}

            def on_before_copy(changed_paths: list[str]) -> None:
                observed["paths"] = list(changed_paths)
                # Marker of the target state at callback time: nothing has
                # landed yet.
                observed["a_at_callback"] = (repo / "a.txt").read_text(encoding="utf-8")
                observed["new_exists_at_callback"] = (repo / "new.txt").exists()

            result = promote_successful_worktree(
                job_dict(repo, worktree), on_before_copy=on_before_copy
            )

            self.assertTrue(result["promoted"])
            self.assertEqual(observed["paths"], ["a.txt", "new.txt"])
            self.assertEqual(observed["a_at_callback"], "one\n")
            self.assertFalse(observed["new_exists_at_callback"])
            # After promotion the target repo is updated.
            self.assertEqual((repo / "a.txt").read_text(encoding="utf-8"), "modified\n")
            self.assertEqual((repo / "new.txt").read_text(encoding="utf-8"), "brand new\n")


if __name__ == "__main__":
    unittest.main()
