"""Provider authentication failure detection and guided recovery."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any, Callable


AUTH_FAILURE_PATTERNS = (
    "failed to authenticate",
    "authentication failed",
    "authentication required",
    "oauth session expired",
    "oauth token expired",
    "not logged in",
    "not authenticated",
    "please log in",
    "please login",
    "run `claude auth login`",
    "run 'claude auth login'",
    "run `codex login`",
    "run 'codex login'",
    "invalid api key",
    "invalid_api_key",
    "unauthorized",
)


@dataclass(frozen=True)
class AuthRequirement:
    provider: str
    role: str
    reason: str


@dataclass(frozen=True)
class AuthRecoveryResult:
    provider: str
    already_authenticated: bool
    detail: str


def provider_for_role(role: str) -> str:
    normalized = role.strip().lower()
    if normalized in {"claude", "fable", "opus"}:
        return "claude"
    if normalized in {"codex", "gemini"}:
        return normalized
    return ""


def provider_display_name(provider: str) -> str:
    return {"claude": "Claude", "codex": "Codex", "gemini": "Gemini"}.get(
        provider,
        provider.title(),
    )


def is_auth_failure(output: str) -> bool:
    lowered = output.lower()
    return any(pattern in lowered for pattern in AUTH_FAILURE_PATTERNS)


def auth_failure_decision(provider: str, reason: str) -> dict[str, Any]:
    display = provider_display_name(provider)
    return {
        "action": "HUMAN_NEEDED",
        "reason": reason,
        "history_summary": (
            f"{display} authentication is required. Sign in through the GUI, "
            "then ai-loop can resume this job."
        ),
        "error_code": "provider_auth_required",
        "provider": provider,
    }


def _decision_payload(decision: dict[str, Any]) -> dict[str, Any]:
    try:
        payload = json.loads(str(decision.get("decision_json") or "{}"))
    except (TypeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def find_auth_requirement(details: dict[str, Any]) -> AuthRequirement | None:
    job = details.get("job") or {}
    if str(job.get("status")) != "human_needed":
        return None

    decisions = details.get("decisions") or []
    if decisions:
        decision = decisions[0]
        payload = _decision_payload(decision)
        reason = str(decision.get("reason") or payload.get("reason") or "")
        provider = str(payload.get("provider") or "")
        structured = payload.get("error_code") == "provider_auth_required"
        if not provider:
            provider = provider_for_role(str(job.get("controller") or ""))
        if provider and (structured or is_auth_failure(reason)):
            return AuthRequirement(provider=provider, role="controller", reason=reason)

    runs = details.get("runs") or []
    if runs:
        run = runs[0]
        reason = "\n".join(
            str(value or "")
            for value in (run.get("error"), run.get("codex_output"))
            if value
        )
        provider = provider_for_role(str(job.get("worker") or ""))
        if provider and is_auth_failure(reason):
            return AuthRequirement(provider=provider, role="worker", reason=reason)

    events = details.get("events") or []
    for event in events:
        try:
            payload = json.loads(str(event.get("payload_json") or "{}"))
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        reason = str(payload.get("reason") or payload.get("error") or "")
        if not is_auth_failure(reason):
            continue
        role = str(payload.get("role") or "controller")
        selected_role = job.get("worker") if role == "worker" else job.get("controller")
        provider = str(payload.get("provider") or provider_for_role(str(selected_role or "")))
        if provider:
            return AuthRequirement(provider=provider, role=role, reason=reason)

    return None


def authentication_commands(provider: str, binary: str) -> tuple[list[str], list[str]]:
    if provider == "claude":
        return [binary, "auth", "status"], [binary, "auth", "login"]
    if provider == "codex":
        return [binary, "login", "status"], [binary, "login"]
    raise RuntimeError(
        f"Automatic sign-in is not supported for {provider_display_name(provider)}. "
        "Authenticate that CLI manually, then use Resume."
    )


def _command_output(result: subprocess.CompletedProcess[str]) -> str:
    output = "\n".join(
        part.strip()
        for part in (result.stdout, result.stderr)
        if part and part.strip()
    )
    return output[-4000:]


def authenticate_provider(
    provider: str,
    binary: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    timeout: int = 900,
) -> AuthRecoveryResult:
    run = runner or subprocess.run
    status_command, login_command = authentication_commands(provider, binary)
    display = provider_display_name(provider)

    try:
        initial = run(
            status_command,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        if initial.returncode == 0:
            return AuthRecoveryResult(
                provider=provider,
                already_authenticated=True,
                detail=f"{display} was already authenticated.",
            )

        login = run(
            login_command,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"{display} sign-in did not finish within {exc.timeout:g} seconds. "
            f"Run {' '.join(login_command)} in a terminal, then try Sign In + Resume again."
        ) from exc
    except OSError as exc:
        raise RuntimeError(f"Could not start {display} authentication: {exc}") from exc

    if login.returncode != 0:
        detail = _command_output(login) or f"command exited with status {login.returncode}"
        raise RuntimeError(f"{display} sign-in failed: {detail}")

    try:
        verified = run(
            status_command,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Could not verify {display} authentication: {exc}") from exc
    if verified.returncode != 0:
        detail = _command_output(verified) or "the CLI still reports that it is logged out"
        raise RuntimeError(f"{display} sign-in could not be verified: {detail}")

    return AuthRecoveryResult(
        provider=provider,
        already_authenticated=False,
        detail=f"{display} authentication succeeded.",
    )
