"""Read-only, bounded CLI questions about the AI-Loop repository."""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai_loop.config import sanitized_child_env
from ai_loop.process_runner import (
    DEFAULT_MAX_OUTPUT_BYTES,
    read_bounded_text_tail,
    run_bounded_process,
)
from ai_loop.systemd_sandbox import systemd_sandbox_enabled, wrap_with_systemd_sandbox

SUPPORTED_QA_PROVIDERS = frozenset({"codex", "claude", "gemini"})


class ProjectQuestionError(RuntimeError):
    """A repository question could not be answered by the selected CLI."""


@dataclass(frozen=True)
class AvailableLlm:
    """One installed provider CLI and configured model combination."""

    provider: str
    binary: str
    model: str = ""

    @property
    def label(self) -> str:
        model = self.model or "default model"
        return f"{self.provider.title()} — {model}"


def discover_available_llms(
    configurations: Iterable[tuple[str, str, str]],
) -> tuple[AvailableLlm, ...]:
    """Return unique configured LLMs whose provider executable is installed."""

    discovered: list[AvailableLlm] = []
    seen: set[tuple[str, str, str]] = set()
    for raw_provider, raw_binary, raw_model in configurations:
        provider = raw_provider.strip().lower()
        binary = raw_binary.strip()
        model = raw_model.strip()
        key = (provider, binary, model)
        if (
            provider not in SUPPORTED_QA_PROVIDERS
            or not binary
            or key in seen
            or shutil.which(binary) is None
        ):
            continue
        seen.add(key)
        discovered.append(AvailableLlm(provider, binary, model))
    return tuple(discovered)


def build_project_question_prompt(
    question: str,
    history: Sequence[tuple[str, str]] = (),
) -> str:
    """Build a bounded repository-grounded prompt with recent conversation context."""

    clean_question = question.strip()
    if not clean_question:
        raise ValueError("question must not be empty")
    transcript_parts: list[str] = []
    for earlier_question, earlier_answer in history[-8:]:
        transcript_parts.append(
            f"User: {earlier_question.strip()}\nAssistant: {earlier_answer.strip()}"
        )
    transcript = "\n\n".join(transcript_parts)
    if len(transcript) > 20_000:
        transcript = transcript[-20_000:]
    context = (
        "\n\nRecent conversation:\n" + transcript if transcript else ""
    )
    return (
        "You answer questions about the AI-Loop project in the current repository. "
        "Inspect the repository's source code, tests, and documentation as needed. "
        "Base the answer on the current files, distinguish confirmed facts from inference, "
        "and say when the repository does not establish an answer. Do not modify files, run "
        "destructive commands, or start jobs. Give a direct, readable answer."
        f"{context}\n\nCurrent question:\n{clean_question}"
    )


def _unwrap_text_output(output: str) -> str:
    stripped = output.strip()
    if not stripped:
        return ""
    try:
        parsed: Any = json.loads(stripped)
    except json.JSONDecodeError:
        return stripped
    if isinstance(parsed, str):
        return parsed.strip()
    if isinstance(parsed, dict):
        for key in ("result", "response", "text", "content", "output", "message"):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return stripped


def ask_project_question(
    repository_path: str | Path,
    llm: AvailableLlm,
    question: str,
    *,
    history: Sequence[tuple[str, str]] = (),
    timeout: float = 900,
) -> str:
    """Ask one installed CLI a read-only question grounded in *repository_path*."""

    provider = llm.provider.strip().lower()
    if provider not in SUPPORTED_QA_PROVIDERS:
        raise ProjectQuestionError(f"unsupported Q&A provider: {provider!r}")
    repository = Path(repository_path).expanduser().resolve()
    if not repository.is_dir():
        raise ProjectQuestionError(f"AI-Loop repository is not a directory: {repository}")
    if shutil.which(llm.binary) is None:
        raise ProjectQuestionError(
            f"configured {provider} executable was not found: {llm.binary}"
        )

    prompt = build_project_question_prompt(question, history)
    temporary_paths: list[Path] = []
    input_text: str | None = None
    if provider == "codex":
        with tempfile.NamedTemporaryFile(
            "w", suffix="-ai-loop-answer.txt", encoding="utf-8", delete=False
        ) as result_handle:
            result_path = Path(result_handle.name)
        temporary_paths.append(result_path)
        command = [llm.binary, "exec", "--cd", str(repository)]
        if systemd_sandbox_enabled():
            command.append("--dangerously-bypass-approvals-and-sandbox")
        else:
            command.extend(["--sandbox", "read-only"])
        command.extend(["--output-last-message", str(result_path)])
        if llm.model:
            command.extend(["-m", llm.model])
        command.append("-")
        input_text = prompt
        if systemd_sandbox_enabled():
            command = wrap_with_systemd_sandbox(
                command, writable_paths=[result_path.parent]
            )
    elif provider == "claude":
        command = [
            llm.binary,
            "-p",
            "--output-format",
            "json",
            "--permission-mode",
            "plan",
            "--allowedTools",
            "Read,Glob,Grep",
        ]
        if llm.model:
            command.extend(["--model", llm.model])
        command.append(prompt)
    else:
        command = [llm.binary]
        if llm.model:
            command.extend(["-m", llm.model])
        command.extend(["--sandbox", "-p", prompt, "--output-format", "json"])

    try:
        process = run_bounded_process(
            command,
            cwd=repository,
            input_text=input_text,
            timeout=timeout,
            env=sanitized_child_env(),
            max_output_bytes=DEFAULT_MAX_OUTPUT_BYTES,
        )
        combined = (process.stdout + "\n" + process.stderr).strip()
        if process.timed_out:
            raise ProjectQuestionError(
                f"{provider} did not answer within {timeout:g} seconds"
            )
        if process.returncode != 0:
            raise ProjectQuestionError(
                f"{provider} question failed with rc={process.returncode}: "
                f"{combined[-4000:] or '<no output>'}"
            )
        output = process.stdout
        if provider == "codex":
            try:
                file_output, _truncated = read_bounded_text_tail(
                    result_path, max_bytes=DEFAULT_MAX_OUTPUT_BYTES
                )
                output = file_output.strip() or output
            except OSError:
                pass
        answer = _unwrap_text_output(output)
        if not answer:
            raise ProjectQuestionError(f"{provider} returned an empty answer")
        return answer
    finally:
        for path in temporary_paths:
            path.unlink(missing_ok=True)


__all__ = [
    "AvailableLlm",
    "ProjectQuestionError",
    "ask_project_question",
    "build_project_question_prompt",
    "discover_available_llms",
]
