"""Open a provider's ordinary interactive CLI with explicit project context and normal approvals."""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from icoda_core import agent


def interactive_command(provider: agent.Provider, binary: str, model: str, cwd: Path,
                        context: str) -> list[str]:
    if not provider.enabled or provider.id not in {"codex", "claude"}:
        raise ValueError("Choose an enabled Codex or Claude CLI for an interactive session.")
    if provider.id == "codex":
        return [binary, "--cd", str(cwd), "-m", model, "--sandbox", "workspace-write",
                "--ask-for-approval", "on-request", context]
    return [binary, "--model", model, context]


def open_cli(command: list[str], cwd: Path) -> None:
    """Quote arguments once at the macOS shell boundary; other platforms launch argument vectors."""
    if sys.platform == "darwin":
        shell_command = "cd " + shlex.quote(str(cwd)) + " && " + shlex.join(command)
        script = 'tell application "Terminal"\nactivate\ndo script ' + json.dumps(shell_command, ensure_ascii=False) + "\nend tell"
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True,
                                timeout=20, check=False)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "Could not open Terminal.")
    elif sys.platform == "win32":
        subprocess.Popen(command, cwd=cwd, creationflags=subprocess.CREATE_NEW_CONSOLE)
    else:
        emulator = shutil.which("x-terminal-emulator") or shutil.which("xterm")
        if emulator is None:
            raise RuntimeError("No terminal emulator found. Install x-terminal-emulator or run the CLI manually.")
        subprocess.Popen([emulator, "-e", *command], cwd=cwd, start_new_session=True)
