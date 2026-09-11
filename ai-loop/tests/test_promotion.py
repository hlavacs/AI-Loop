from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import controller
from ai_loop import db
from controller import (
    PromotionError,
    finish_done_job,
    promote_successful_worktree,
    promotion_recovery_decision,
    repo_has_local_change,
    rollback_promoted_checkout,
    status_paths,
    validate_promoted_checkout,
)


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
    def test_transient_worker_reports_are_never_promoted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, worktree = make_repo_with_worktree(
                Path(directory), {"tracked.txt": "base\n"}
            )
            report = worktree / ".ai-loop-worker-report-iteration-1.md"
            report.write_text("transient", encoding="utf-8")
            (worktree / "tracked.txt").write_text("changed\n", encoding="utf-8")

            result = promote_successful_worktree(job_dict(repo, worktree))

            self.assertEqual(result["files"], ["tracked.txt"])
            self.assertFalse((repo / report.name).exists())

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

    def test_subdirectory_selected_job_promotes_relative_to_git_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, worktree = make_repo_with_worktree(
                Path(directory), {"project/a.txt": "base\n"}
            )
            (worktree / "project" / "a.txt").write_text(
                "promoted\n", encoding="utf-8"
            )

            result = promote_successful_worktree(
                job_dict(repo / "project", worktree)
            )

            self.assertTrue(result["promoted"])
            self.assertEqual(result["files"], ["project/a.txt"])
            self.assertEqual(
                (repo / "project" / "a.txt").read_text(encoding="utf-8"),
                "promoted\n",
            )
            self.assertFalse((repo / "project" / "project").exists())

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

    def test_identical_local_change_is_already_promoted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, worktree = make_repo_with_worktree(
                Path(directory), {"shared.txt": "base\n"}
            )
            (worktree / "shared.txt").write_text("same result\n", encoding="utf-8")
            (repo / "shared.txt").write_text("same result\n", encoding="utf-8")

            result = promote_successful_worktree(job_dict(repo, worktree))

            self.assertTrue(result["promoted"])
            self.assertEqual(result["files"], ["shared.txt"])
            self.assertEqual(result["already_present"], ["shared.txt"])
            self.assertEqual(result["copied"], [])
            self.assertEqual(
                (repo / "shared.txt").read_text(encoding="utf-8"),
                "same result\n",
            )

    def test_validation_rollback_reverts_only_paths_copied_by_ai_loop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, worktree = make_repo_with_worktree(
                Path(directory),
                {
                    "changed.txt": "base\n",
                    "deleted.txt": "keep until promotion\n",
                    "preserved.txt": "base\n",
                },
            )
            (worktree / "changed.txt").write_text("candidate\n", encoding="utf-8")
            (worktree / "deleted.txt").unlink()
            (worktree / "new.txt").write_text("candidate new\n", encoding="utf-8")
            (worktree / "preserved.txt").write_text("same local result\n", encoding="utf-8")
            (repo / "preserved.txt").write_text("same local result\n", encoding="utf-8")

            promotion = promote_successful_worktree(job_dict(repo, worktree))
            rollback = rollback_promoted_checkout(job_dict(repo, worktree), promotion)

            self.assertTrue(rollback["passed"])
            self.assertEqual(
                (repo / "changed.txt").read_text(encoding="utf-8"), "base\n"
            )
            self.assertEqual(
                (repo / "deleted.txt").read_text(encoding="utf-8"),
                "keep until promotion\n",
            )
            self.assertFalse((repo / "new.txt").exists())
            self.assertEqual(
                (repo / "preserved.txt").read_text(encoding="utf-8"),
                "same local result\n",
            )
            self.assertEqual(rollback["preserved_already_present"], ["preserved.txt"])

    def test_validation_rollback_preserves_a_concurrent_target_edit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, worktree = make_repo_with_worktree(
                Path(directory), {"changed.txt": "base\n"}
            )
            (worktree / "changed.txt").write_text("candidate\n", encoding="utf-8")
            promotion = promote_successful_worktree(job_dict(repo, worktree))
            (repo / "changed.txt").write_text("concurrent user edit\n", encoding="utf-8")

            rollback = rollback_promoted_checkout(job_dict(repo, worktree), promotion)

            self.assertFalse(rollback["passed"])
            self.assertEqual(rollback["failures"], ["changed.txt"])
            self.assertEqual(
                (repo / "changed.txt").read_text(encoding="utf-8"),
                "concurrent user edit\n",
            )

    def test_identical_untracked_file_and_deletion_are_already_promoted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, worktree = make_repo_with_worktree(
                Path(directory), {"doomed.txt": "remove\n"}
            )
            (worktree / "new.txt").write_text("same new file\n", encoding="utf-8")
            (repo / "new.txt").write_text("same new file\n", encoding="utf-8")
            (worktree / "doomed.txt").unlink()
            (repo / "doomed.txt").unlink()

            result = promote_successful_worktree(job_dict(repo, worktree))

            self.assertEqual(result["files"], ["doomed.txt", "new.txt"])
            self.assertEqual(
                result["already_present"], ["doomed.txt", "new.txt"]
            )
            self.assertEqual(result["copied"], [])
            self.assertEqual(result["removed"], [])

    def test_already_present_change_survives_later_copy_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, worktree = make_repo_with_worktree(
                Path(directory), {"a_same.txt": "base\n"}
            )
            (worktree / "a_same.txt").write_text("reconciled\n", encoding="utf-8")
            (repo / "a_same.txt").write_text("reconciled\n", encoding="utf-8")
            (worktree / "bdir").mkdir()
            (worktree / "bdir" / "blocked.txt").write_text(
                "blocked\n", encoding="utf-8"
            )
            (repo / "bdir").write_text("not a directory\n", encoding="utf-8")

            with self.assertRaises(PromotionError):
                promote_successful_worktree(job_dict(repo, worktree))

            self.assertEqual(
                (repo / "a_same.txt").read_text(encoding="utf-8"),
                "reconciled\n",
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


class PromotionValidationTests(unittest.TestCase):
    def test_promoted_checkout_validation_runs_from_target_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, worktree = make_repo_with_worktree(
                Path(directory), {"a.txt": "one\n"}
            )
            (worktree / "promoted.txt").write_text("ready\n", encoding="utf-8")
            job = {
                **job_dict(repo, worktree),
                "test_cmd": "test -f promoted.txt",
            }
            promotion = promote_successful_worktree(job)

            validation = validate_promoted_checkout(job, promotion)

            self.assertTrue(validation["performed"])
            self.assertTrue(validation["passed"])
            self.assertEqual(validation["cwd"], str(repo.resolve()))

    def test_subdirectory_selected_job_validates_from_matching_git_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, worktree = make_repo_with_worktree(
                Path(directory), {"project/a.txt": "one\n"}
            )
            (worktree / "project" / "promoted.txt").write_text(
                "ready\n", encoding="utf-8"
            )
            job = {
                **job_dict(repo / "project", worktree),
                "test_cmd": (
                    "test -f project/promoted.txt "
                    "&& test ! -e project/project/promoted.txt"
                ),
            }
            promotion = promote_successful_worktree(job)

            validation = validate_promoted_checkout(job, promotion)

            self.assertTrue(validation["performed"])
            self.assertTrue(validation["passed"])
            self.assertEqual(validation["cwd"], str(repo.resolve()))

    def test_promoted_checkout_validation_reports_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, worktree = make_repo_with_worktree(
                Path(directory), {"a.txt": "one\n"}
            )
            (worktree / "promoted.txt").write_text("ready\n", encoding="utf-8")
            job = {
                **job_dict(repo, worktree),
                "test_cmd": "test -f missing.txt",
            }
            promotion = promote_successful_worktree(job)

            validation = validate_promoted_checkout(job, promotion)

            self.assertTrue(validation["performed"])
            self.assertFalse(validation["passed"])
            self.assertNotEqual(validation["returncode"], 0)

    def test_failed_target_validation_requests_llm_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "loop.sqlite3"
            db.init_db(database)
            with db.transaction(database) as conn:
                db.create_job(
                    conn,
                    job_id="J-promotion-validation",
                    repo_path=str(root / "repo"),
                    worktree_path=str(root / "worktree"),
                    branch="ai/J-promotion-validation",
                    base_ref="HEAD",
                    goal="Promote safely",
                    constraints=[],
                    acceptance=[],
                    test_cmd="false",
                    max_iterations=2,
                    use_worktree=True,
                    worker="codex",
                    controller="claude",
                )
                job = db.get_job(conn, "J-promotion-validation")
            settings = SimpleNamespace(db_path=database)
            promotion = {"promoted": True, "files": ["a.txt"]}
            validation = {
                "performed": True,
                "passed": False,
                "reason": "promoted-checkout validation failed",
                "returncode": 1,
            }

            with patch.object(
                controller,
                "promote_successful_worktree",
                return_value=promotion,
            ), patch.object(
                controller,
                "validate_promoted_checkout",
                return_value=validation,
            ), patch.object(
                controller,
                "rollback_promoted_checkout",
                return_value={
                    "performed": True,
                    "passed": True,
                    "reason": "rolled back",
                    "restored": ["a.txt"],
                    "removed": [],
                    "failures": [],
                },
            ), patch.object(controller, "notify_terminal"), patch.object(
                controller, "xadd_json"
            ) as publish:
                finish_done_job(
                    settings,
                    object(),
                    job,
                    {
                        "action": "DONE",
                        "reason": "worker validation passed",
                        "history_summary": "complete in worktree",
                    },
                )

            with db.transaction(database) as conn:
                stored = db.get_job(conn, "J-promotion-validation")
                kinds = [
                    row["kind"]
                    for row in conn.execute(
                        "SELECT kind FROM events WHERE job_id = ? ORDER BY id",
                        ("J-promotion-validation",),
                    ).fetchall()
                ]
            self.assertEqual(stored["status"], "planning")
            self.assertIn("promotion_validation_failed", kinds)
            self.assertIn("promotion_rollback_completed", kinds)
            self.assertIn("promotion_recovery_requested", kinds)
            self.assertNotIn("human_needed", kinds)
            self.assertNotIn("done", kinds)
            request = publish.call_args.args[3]
            self.assertEqual(request["type"], "PROMOTION_RECOVERY")
            self.assertEqual(request["failure"]["stage"], "target_validation")

    def test_copy_failure_requests_llm_recovery_instead_of_human(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "loop.sqlite3"
            db.init_db(database)
            with db.transaction(database) as conn:
                db.create_job(
                    conn,
                    job_id="J-promotion-copy",
                    repo_path=str(root / "repo"),
                    worktree_path=str(root / "worktree"),
                    branch="ai/J-promotion-copy",
                    base_ref="HEAD",
                    goal="Promote safely",
                    constraints=[],
                    acceptance=[],
                    test_cmd="true",
                    max_iterations=2,
                    use_worktree=True,
                    worker="codex",
                    controller="claude",
                )
                job = db.get_job(conn, "J-promotion-copy")
            settings = SimpleNamespace(db_path=database)

            with patch.object(
                controller,
                "promote_successful_worktree",
                side_effect=PromotionError("path mapping failed"),
            ), patch.object(controller, "xadd_json") as publish:
                finish_done_job(
                    settings,
                    object(),
                    job,
                    {
                        "action": "DONE",
                        "reason": "worktree passed",
                        "history_summary": "implementation complete",
                    },
                )

            with db.transaction(database) as conn:
                stored = db.get_job(conn, "J-promotion-copy")
                kinds = [
                    row["kind"]
                    for row in conn.execute(
                        "SELECT kind FROM events WHERE job_id = ? ORDER BY id",
                        ("J-promotion-copy",),
                    ).fetchall()
                ]
            self.assertEqual(stored["status"], "planning")
            self.assertIn("promotion_failed", kinds)
            self.assertIn("promotion_recovery_requested", kinds)
            self.assertNotIn("human_needed", kinds)
            request = publish.call_args.args[3]
            self.assertEqual(request["type"], "PROMOTION_RECOVERY")
            self.assertEqual(request["failure"]["stage"], "promotion")


class PromotionRecoveryDecisionTests(unittest.TestCase):
    def test_tries_other_available_llms_until_one_offers_repair(self) -> None:
        settings = SimpleNamespace(
            controller_default="claude",
            claude_bin="claude",
            codex_bin="codex",
            gemini_bin="gemini",
        )
        job = {"controller": "claude", "worktree_path": "/tmp/worktree"}
        declined = {
            "action": "HUMAN_NEEDED",
            "reason": "I cannot solve this",
            "history_summary": "blocked",
        }
        repair = {
            "action": "CONTINUE",
            "reason": "Codex found a safe repair",
            "history_summary": "repair queued",
            "progress": {
                "completed_work_units": 1,
                "remaining_work_units": 1,
                "remaining_minutes": 5,
            },
            "next_task": {
                "goal": "Repair promotion path mapping",
                "constraints": ["Preserve local target changes"],
                "acceptance": ["Promotion succeeds without a conflict"],
                "test_cmd": "pytest -q tests/test_promotion.py",
            },
        }

        with patch.object(controller.shutil, "which", return_value="/usr/bin/fake"), patch.object(
            controller, "controller_decision", side_effect=[declined, repair]
        ) as decide:
            result = promotion_recovery_decision(settings, job, "diagnostics")

        self.assertEqual(result["action"], "REPAIR")
        self.assertEqual(result["recovery_provider"], "codex")
        self.assertEqual(decide.call_count, 2)
        self.assertEqual(decide.call_args_list[0].args[1]["controller"], "claude")
        self.assertEqual(decide.call_args_list[1].args[1]["controller"], "codex")
        self.assertFalse(decide.call_args_list[0].kwargs["wait_for_tokens"])
        self.assertFalse(decide.call_args_list[1].kwargs["wait_for_tokens"])

    def test_recovery_request_creates_a_normal_repair_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "loop.sqlite3"
            db.init_db(database)
            with db.transaction(database) as conn:
                db.create_job(
                    conn,
                    job_id="J-recovery-route",
                    repo_path=str(root / "repo"),
                    worktree_path=str(root / "worktree"),
                    branch="ai/J-recovery-route",
                    base_ref="HEAD",
                    goal="Recover promotion",
                    constraints=[],
                    acceptance=[],
                    test_cmd="true",
                    max_iterations=0,
                    use_worktree=True,
                    worker="codex",
                    controller="claude",
                )
            decision = {
                "action": "REPAIR",
                "reason": "repair is safe",
                "history_summary": "recovering promotion",
                "progress": {
                    "completed_work_units": 1,
                    "remaining_work_units": 1,
                    "remaining_minutes": 5,
                },
                "next_task": {
                    "goal": "Repair target-relative promotion paths",
                    "constraints": ["Preserve unrelated local edits"],
                    "acceptance": ["The job test command passes: true"],
                    "test_cmd": "true",
                },
                "recovery_provider": "codex",
            }

            with patch.object(
                controller, "promotion_recovery_decision", return_value=decision
            ), patch.object(controller, "publish_worker_task") as publish, patch.object(
                controller, "timestamp_id", return_value="T-recovery-route"
            ):
                controller.handle_request(
                    SimpleNamespace(db_path=database),
                    object(),
                    {
                        "type": "PROMOTION_RECOVERY",
                        "job_id": "J-recovery-route",
                        "scope": "job",
                        "failure": {"stage": "promotion", "error": "wrong path"},
                    },
                )

            with db.transaction(database) as conn:
                job = db.get_job(conn, "J-recovery-route")
                task = db.get_task(conn, "T-recovery-route")
            self.assertEqual(job["status"], "queued")
            self.assertEqual(task["created_by"], "codex:promotion_recovery")
            self.assertEqual(task["goal"], "Repair target-relative promotion paths")
            publish.assert_called_once()

    def test_recovery_task_allowance_has_a_hard_cap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "loop.sqlite3"
            db.init_db(database)
            with db.transaction(database) as conn:
                db.create_job(
                    conn,
                    job_id="J-recovery-cap",
                    repo_path=str(root / "repo"),
                    worktree_path=str(root / "worktree"),
                    branch="ai/J-recovery-cap",
                    base_ref="HEAD",
                    goal="Recover promotion",
                    constraints=[],
                    acceptance=[],
                    test_cmd="true",
                    max_iterations=100,
                    use_worktree=True,
                    worker="codex",
                    controller="claude",
                )
                for iteration in range(controller.PROMOTION_RECOVERY_MAX_TASKS):
                    db.create_task(
                        conn,
                        task_id=f"T-recovery-cap-{iteration}",
                        job_id="J-recovery-cap",
                        iteration=iteration,
                        goal="Previous promotion repair",
                        constraints=[],
                        acceptance=[],
                        test_cmd="true",
                        created_by="codex:promotion_recovery",
                    )
            decision = {
                "action": "REPAIR",
                "reason": "another possible repair",
                "history_summary": "still recovering",
                "progress": {
                    "completed_work_units": 1,
                    "remaining_work_units": 1,
                    "remaining_minutes": 5,
                },
                "next_task": {
                    "goal": "Try another repair",
                    "constraints": [],
                    "acceptance": [],
                    "test_cmd": "true",
                },
                "recovery_provider": "codex",
            }

            with patch.object(
                controller, "promotion_recovery_decision", return_value=decision
            ), patch.object(controller, "finish_job") as finish, patch.object(
                controller, "publish_worker_task"
            ) as publish:
                controller.handle_request(
                    SimpleNamespace(db_path=database),
                    object(),
                    {
                        "type": "PROMOTION_RECOVERY",
                        "job_id": "J-recovery-cap",
                        "scope": "job",
                        "failure": {"stage": "promotion", "error": "still failing"},
                    },
                )

            self.assertEqual(finish.call_args.args[4], "human_needed")
            self.assertEqual(
                finish.call_args.args[5]["reason"],
                "promotion recovery task limit reached",
            )
            publish.assert_not_called()


class PromotionRollbackTests(unittest.TestCase):
    """Mid-copy failures must roll the target repo back (monkeypatch-free).

    The failure is triggered deterministically: the copy loop walks the
    sorted status paths, so "a_*" lands first, then "bdir/blocked.txt" fails
    because the target repo contains a plain FILE named "bdir" and
    target.parent.mkdir(parents=True, exist_ok=True) raises FileExistsError
    on a non-directory. The blocking file "bdir" is untracked in the target
    but never matches the conflict check's pathspec "bdir/blocked.txt", so
    the failure happens inside the copy loop, after earlier paths applied.
    """

    def test_mid_copy_failure_rolls_back_modified_tracked_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, worktree = make_repo_with_worktree(Path(directory), {"a_first.txt": "one\n"})
            (worktree / "a_first.txt").write_text("modified\n", encoding="utf-8")
            (worktree / "bdir").mkdir()
            (worktree / "bdir" / "blocked.txt").write_text("blocked\n", encoding="utf-8")
            (repo / "bdir").write_text("i am a file, not a directory\n", encoding="utf-8")

            with self.assertRaises(PromotionError) as ctx:
                promote_successful_worktree(job_dict(repo, worktree))

            message = str(ctx.exception)
            self.assertIn("rolled back 1 of 1", message)
            # a_first.txt had already been copied; the rollback's
            # `git checkout -- a_first.txt` restored the original content.
            self.assertEqual((repo / "a_first.txt").read_text(encoding="utf-8"), "one\n")
            # The blocking file is untouched and the blocked path never landed.
            self.assertEqual(
                (repo / "bdir").read_text(encoding="utf-8"),
                "i am a file, not a directory\n",
            )

    def test_mid_copy_failure_removes_already_copied_new_file(self) -> None:
        # An untracked-new path cannot be restored by `git checkout` (it
        # returns nonzero); rollback must delete the copied file instead.
        with tempfile.TemporaryDirectory() as directory:
            repo, worktree = make_repo_with_worktree(Path(directory), {"base.txt": "base\n"})
            (worktree / "a_new.txt").write_text("fresh\n", encoding="utf-8")
            (worktree / "bdir").mkdir()
            (worktree / "bdir" / "blocked.txt").write_text("blocked\n", encoding="utf-8")
            (repo / "bdir").write_text("blocking file\n", encoding="utf-8")

            with self.assertRaises(PromotionError) as ctx:
                promote_successful_worktree(job_dict(repo, worktree))

            self.assertIn("rolled back 1 of 1", str(ctx.exception))
            self.assertFalse((repo / "a_new.txt").exists())
            self.assertEqual((repo / "base.txt").read_text(encoding="utf-8"), "base\n")

    def test_mid_copy_failure_restores_propagated_deletion(self) -> None:
        # A deletion applied to the target before the failure must come back:
        # checkout restores tracked files including deleted ones.
        with tempfile.TemporaryDirectory() as directory:
            repo, worktree = make_repo_with_worktree(Path(directory), {"a_doomed.txt": "keep me\n"})
            (worktree / "a_doomed.txt").unlink()
            (worktree / "bdir").mkdir()
            (worktree / "bdir" / "blocked.txt").write_text("blocked\n", encoding="utf-8")
            (repo / "bdir").write_text("blocking file\n", encoding="utf-8")

            with self.assertRaises(PromotionError) as ctx:
                promote_successful_worktree(job_dict(repo, worktree))

            self.assertIn("rolled back 1 of 1", str(ctx.exception))
            self.assertEqual((repo / "a_doomed.txt").read_text(encoding="utf-8"), "keep me\n")


if __name__ == "__main__":
    unittest.main()
