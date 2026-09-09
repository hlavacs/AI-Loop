"""LLM providers: providers.json, invocation templates, rate-limit handling.

Prompt assembly and response validation follow in M2.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from icoda_core.process import ProcessResult, run_bounded

PROVIDERS_FILE = Path(__file__).with_name("providers.json")


@dataclass(frozen=True)
class Model:
    id: str
    label: str


@dataclass(frozen=True)
class Provider:
    """One command-line agent: how to call it and which two models to offer."""

    id: str
    label: str
    command: str
    invocation: tuple[str, ...]
    prompt_mode: str
    models: tuple[Model, ...]
    enabled: bool
    verified: bool
    login_hint: str

    @property
    def default_model(self) -> str:
        return self.models[0].id


@dataclass(frozen=True)
class ProviderCheck:
    """Local evidence that an installed CLI accepts every option in its invocation template."""

    provider_id: str
    configured_enabled: bool
    configured_verified: bool
    installed: bool
    compatible: bool
    path: str = ""
    version: str = ""
    help_command: tuple[str, ...] = ()
    required_flags: tuple[str, ...] = ()
    missing_flags: tuple[str, ...] = ()
    detail: str = ""


def load_providers(path: Path = PROVIDERS_FILE) -> list[Provider]:
    """Read providers.json; the list order is the order shown in the Binary field."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    providers = []
    for item in raw["providers"]:
        models = tuple(Model(m["id"], m["label"]) for m in item["models"])
        providers.append(Provider(item["id"], item["label"], item["command"], tuple(item["invocation"]),
                                  item["prompt_mode"], models, bool(item["enabled"]), bool(item["verified"]),
                                  item.get("login_hint", "")))
    return providers


def providers_checked_on(path: Path = PROVIDERS_FILE) -> str:
    return str(json.loads(path.read_text(encoding="utf-8")).get("checked", ""))


def find_provider(providers: Sequence[Provider], provider_id: str) -> Provider:
    for provider in providers:
        if provider.id == provider_id:
            return provider
    raise KeyError(provider_id)


def build_command(provider: Provider, model: str, prompt: str, cwd: Path | str,
                  binary: str | None = None) -> tuple[list[str], str | None]:
    """Fill the provider's invocation template; return argv and the stdin text (None when the prompt is an argument)."""
    values = {"binary": binary or provider.command, "model": model, "cwd": str(cwd)}
    stdin_text = prompt if provider.prompt_mode == "stdin" else None
    argv = []
    for token in provider.invocation:
        if token == "{prompt}":
            argv.append(prompt)
        else:
            argv.append(token.format(**values))
    return argv, stdin_text


def binary_available(provider: Provider, binary: str | None = None) -> bool:
    candidate = binary or provider.command
    return Path(candidate).is_file() or shutil.which(candidate) is not None


def check_provider(
    provider: Provider,
    cwd: Path | str,
    *,
    finder: Callable[[str], str | None] = shutil.which,
    runner: Callable[..., ProcessResult] = run_bounded,
) -> ProviderCheck:
    """Inspect one local CLI's help and version without making a model request."""
    path = _binary_path(provider.command, finder)
    flags = tuple(token for token in provider.invocation if token.startswith("-") and token != "-")
    if not path:
        return ProviderCheck(provider.id, provider.enabled, provider.verified, False, False,
                             required_flags=flags, detail="not installed")
    help_command = _help_command(provider, path)
    help_result = runner(help_command, cwd=cwd, timeout=20.0)
    help_text = help_result.stdout + help_result.stderr
    missing = tuple(flag for flag in flags if flag not in help_text)
    version_result = runner([path, "--version"], cwd=cwd, timeout=20.0)
    version = (version_result.stdout.strip() or version_result.stderr.strip()).splitlines()[:1]
    compatible = help_result.ok and not missing
    detail = "invocation options present" if compatible else _check_failure(help_result, missing)
    return ProviderCheck(provider.id, provider.enabled, provider.verified, True, compatible, path,
                         version[0] if version else "", tuple(help_command), flags, missing, detail)


def check_providers(
    providers: Sequence[Provider],
    cwd: Path | str,
    *,
    finder: Callable[[str], str | None] = shutil.which,
    runner: Callable[..., ProcessResult] = run_bounded,
) -> list[ProviderCheck]:
    return [check_provider(provider, cwd, finder=finder, runner=runner) for provider in providers]


def _binary_path(command: str, finder: Callable[[str], str | None]) -> str:
    candidate = Path(command).expanduser()
    if candidate.is_file():
        return str(candidate.resolve())
    found = finder(command)
    return str(Path(found).resolve()) if found else ""


def _help_command(provider: Provider, binary: str) -> list[str]:
    command = [binary]
    for token in provider.invocation[1:]:
        if token.startswith(("-", "{")):
            break
        command.append(token)
    return [*command, "--help"]


def _check_failure(result: ProcessResult, missing: tuple[str, ...]) -> str:
    if not result.ok:
        return f"help command failed with exit code {result.returncode}"
    return "missing from help: " + ", ".join(missing)


_RATE_LIMIT_PATTERNS = (
    r"rate limit", r"usage limit", r"quota", r"\b429\b", r"too many requests", r"resets? at", r"try again in",
    r"overloaded", r"capacity",
)


def is_rate_limited(text: str) -> bool:
    lowered = text.lower()
    return any(re.search(pattern, lowered) for pattern in _RATE_LIMIT_PATTERNS)


def retry_after_seconds(text: str, now: datetime | None = None, default: int = 300) -> int:
    """Seconds to wait as the provider's message suggests; ``default`` when it names no time."""
    lowered = text.lower()
    if match := re.search(r"(?:try again|retry|wait) (?:in|after) (\d+)\s*(second|sec|minute|min|hour|h)", lowered):
        amount, unit = int(match.group(1)), match.group(2)
        factor = 1 if unit.startswith("s") else 60 if unit.startswith("m") else 3600
        return max(amount * factor, 1)
    if match := re.search(r"resets? at (\d{1,2}):(\d{2})\s*(am|pm)?", lowered):
        return _seconds_until(int(match.group(1)), int(match.group(2)), match.group(3), now or datetime.now(timezone.utc).astimezone())
    return default


def _seconds_until(hour: int, minute: int, meridiem: str | None, now: datetime) -> int:
    if meridiem == "pm" and hour < 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0
    target = now.replace(hour=hour % 24, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return max(int((target - now).total_seconds()), 1)


def run_provider(provider: Provider, model: str, prompt: str, cwd: Path | str, *, binary: str | None = None,
                 timeout: float = 1800.0, attempts: int = 3, sleep: Callable[[float], None] = time.sleep,
                 runner: Callable[..., ProcessResult] = run_bounded) -> ProcessResult:
    """Invoke the provider; on a rate-limit reply wait as it suggests and try again, up to ``attempts`` times."""
    argv, stdin_text = build_command(provider, model, prompt, cwd, binary)
    result = runner(argv, cwd=cwd, timeout=timeout, input_text=stdin_text)
    for _ in range(attempts - 1):
        if result.ok or not is_rate_limited(result.stdout + result.stderr):
            break
        sleep(retry_after_seconds(result.stdout + result.stderr))
        result = runner(argv, cwd=cwd, timeout=timeout, input_text=stdin_text)
    return result
