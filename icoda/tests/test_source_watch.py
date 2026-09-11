"""Pure external-source snapshot detection."""

from __future__ import annotations

from pathlib import Path

from icoda_core import source_watch


def test_changed_files_reports_only_the_edited_analysed_source(tmp_path: Path) -> None:
    edited = tmp_path / "edited.py"
    untouched = tmp_path / "untouched.py"
    edited.write_text("value = 1\n", encoding="utf-8")
    untouched.write_text("other = 2\n", encoding="utf-8")
    before = source_watch.snapshot_files(tmp_path, ("edited.py", "untouched.py"))

    edited.write_text("value = 1000\n", encoding="utf-8")
    after = source_watch.snapshot_files(tmp_path, ("edited.py", "untouched.py"))

    assert source_watch.changed_files(before, after) == frozenset({"edited.py"})
    assert "untouched.py" not in source_watch.changed_files(before, after)
    assert "tkinter" not in Path(source_watch.__file__).read_text(encoding="utf-8")
