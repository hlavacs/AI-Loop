from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import worker
from ai_loop.report_artifacts import (
    is_worker_report_path,
    relocate_worker_reports,
    worker_report_directory,
)


class WorkerReportArtifactTests(unittest.TestCase):
    def test_reserved_report_names_are_narrow(self) -> None:
        self.assertTrue(is_worker_report_path(".ai-loop-worker-report.md"))
        self.assertTrue(
            is_worker_report_path("nested/.ai-loop-worker-report-iteration-62.md")
        )
        self.assertFalse(is_worker_report_path("docs/worker-report.md"))
        self.assertFalse(is_worker_report_path(".ai-loop-worker-report.txt"))

    def test_relocates_reports_but_not_project_docs_or_git_internals(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            worktree = root / "worktree"
            temp_root = root / "temp"
            (worktree / "nested").mkdir(parents=True)
            (worktree / ".git").mkdir()
            root_report = worktree / ".ai-loop-worker-report-iteration-1.md"
            nested_report = worktree / "nested" / ".ai-loop-worker-report.md"
            project_doc = worktree / "nested" / "worker-report.md"
            git_internal = worktree / ".git" / ".ai-loop-worker-report-hidden.md"
            root_report.write_text("root", encoding="utf-8")
            nested_report.write_text("nested", encoding="utf-8")
            project_doc.write_text("project", encoding="utf-8")
            git_internal.write_text("git", encoding="utf-8")

            result = relocate_worker_reports(
                worktree, "J/report unsafe", temp_root=temp_root
            )

            destination = worker_report_directory(
                "J/report unsafe", temp_root=temp_root
            )
            self.assertEqual(Path(str(result["directory"])), destination)
            self.assertEqual(len(result["moved"]), 2)
            self.assertEqual(result["failures"], [])
            self.assertFalse(root_report.exists())
            self.assertFalse(nested_report.exists())
            self.assertEqual(project_doc.read_text(encoding="utf-8"), "project")
            self.assertEqual(git_internal.read_text(encoding="utf-8"), "git")
            self.assertEqual(
                sorted(
                    path.read_text(encoding="utf-8")
                    for path in destination.iterdir()
                ),
                ["nested", "root"],
            )

    def test_existing_temp_report_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            worktree = root / "worktree"
            worktree.mkdir()
            destination = worker_report_directory(
                "J-collision", temp_root=root / "temp"
            )
            destination.mkdir(parents=True)
            name = ".ai-loop-worker-report-iteration-1.md"
            (destination / name).write_text("older", encoding="utf-8")
            (worktree / name).write_text("newer", encoding="utf-8")

            result = relocate_worker_reports(
                worktree, "J-collision", temp_root=root / "temp"
            )

            self.assertEqual(result["failures"], [])
            self.assertEqual(
                sorted(
                    path.read_text(encoding="utf-8")
                    for path in destination.iterdir()
                ),
                ["newer", "older"],
            )

    def test_worker_prompt_forbids_repository_reports_and_names_temp_location(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            job = {
                "id": "J-prompt",
                "worktree_path": directory,
                "goal": "Implement the task",
                "granularity": "normal",
            }
            task = {
                "iteration": 1,
                "goal": "Make a focused change",
                "constraints": [],
                "acceptance": [],
            }

            prompt = worker.codex_prompt(job, task)

            self.assertIn(
                "Do not create progress, summary, or worker-report files", prompt
            )
            self.assertIn(str(worker_report_directory("J-prompt")), prompt)
            self.assertIn("never create `.ai-loop-worker-report*.md`", prompt)


if __name__ == "__main__":
    unittest.main()
