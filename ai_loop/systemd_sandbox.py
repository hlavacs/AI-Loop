"""Systemd-based confinement for AI provider CLIs when bubblewrap is unavailable."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Sequence


SYSTEMD_SANDBOX_ENV = "AI_LOOP_CODEX_SYSTEMD_SANDBOX"

# These properties are supported by unprivileged user services. Do not add
# PrivateDevices or ProtectKernelModules: on affected Linux hosts they make
# the user manager fail before exec with status 218/CAPABILITIES.

_SYSTEMD_PROPERTIES = (
    "ProtectSystem=strict",
    "ProtectHome=read-only",
    "PrivateTmp=yes",
    "NoNewPrivileges=yes",
    "ProtectKernelTunables=yes",
    "ProtectControlGroups=yes",
    "RestrictSUIDSGID=yes",
    "LockPersonality=yes",
    "RestrictRealtime=yes",
)


def systemd_sandbox_enabled(value: str | None = None) -> bool:
    """Return whether the explicit external provider sandbox is enabled."""

    raw = os.getenv(SYSTEMD_SANDBOX_ENV, "") if value is None else value
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def wrap_with_systemd_sandbox(
    command: Sequence[str],
    *,
    writable_paths: Sequence[str | Path],
) -> list[str]:
    """Confine a command to read-only host access plus explicit write roots.

    This wrapper is intended for a provider command that uses its documented
    sandbox-bypass flag because bubblewrap cannot start on the host. The
    systemd unit restores the important write boundary without requiring a
    global user-namespace or AppArmor relaxation.
    """

    systemd_run = shutil.which("systemd-run")
    if systemd_run is None:
        raise RuntimeError(f"{SYSTEMD_SANDBOX_ENV}=1 requires systemd-run on PATH")
    roots: list[str] = []
    for value in writable_paths:
        resolved = Path(value).expanduser().resolve()
        if not resolved.is_dir():
            raise ValueError(
                f"systemd sandbox write root is not a directory: {resolved}"
            )
        text = str(resolved)
        if text not in roots:
            roots.append(text)
    if not roots:
        raise ValueError("systemd sandbox requires at least one writable path")

    wrapped = [
        systemd_run,
        "--user",
        "--wait",
        "--pipe",
        "--collect",
    ]
    for property_value in _SYSTEMD_PROPERTIES:
        wrapped.extend(["--property", property_value])
    for root in roots:
        wrapped.extend(["--property", f"ReadWritePaths={root}"])
    wrapped.extend(["--", *command])
    return wrapped
