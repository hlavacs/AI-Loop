"""Windows virtual environments find Tcl/Tk in their base Python installation."""

import os
import unittest
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import icoda


class TkRuntimeTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.context = ExitStack()
        self.addCleanup(self.context.close)
        self.context.enter_context(patch.object(icoda.sys, "platform", "win32"))
        self.context.enter_context(patch.object(icoda.sys, "base_prefix", str(self.base)))
        self.context.enter_context(patch.object(icoda.tk, "TclVersion", 8.6, create=True))
        self.context.enter_context(patch.object(icoda.tk, "TkVersion", 8.6, create=True))
        self.context.enter_context(patch.dict(os.environ))
        for variable in ("TCL_LIBRARY", "TK_LIBRARY"):
            os.environ.pop(variable, None)

    def install_scripts(self):
        for directory, script in (("tcl8.6", "init.tcl"), ("tk8.6", "tk.tcl")):
            library = self.base / "tcl" / directory
            library.mkdir(parents=True)
            (library / script).touch()

    def test_discovers_base_installation(self):
        self.install_scripts()
        icoda.configure_tk_libraries()
        self.assertEqual(os.environ["TCL_LIBRARY"], str(self.base / "tcl" / "tcl8.6"))
        self.assertEqual(os.environ["TK_LIBRARY"], str(self.base / "tcl" / "tk8.6"))

    def test_preserves_explicit_paths(self):
        self.install_scripts()
        os.environ.update(TCL_LIBRARY="custom-tcl", TK_LIBRARY="custom-tk")
        icoda.configure_tk_libraries()
        self.assertEqual(os.environ["TCL_LIBRARY"], "custom-tcl")
        self.assertEqual(os.environ["TK_LIBRARY"], "custom-tk")

    def test_ignores_missing_scripts(self):
        icoda.configure_tk_libraries()
        self.assertNotIn("TCL_LIBRARY", os.environ)
        self.assertNotIn("TK_LIBRARY", os.environ)

    def test_leaves_other_platforms_unchanged(self):
        self.install_scripts()
        with patch.object(icoda.sys, "platform", "linux"):
            icoda.configure_tk_libraries()
        self.assertNotIn("TCL_LIBRARY", os.environ)
        self.assertNotIn("TK_LIBRARY", os.environ)
