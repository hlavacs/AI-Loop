"""providers.json, invocation templates, rate-limit parsing and the retry loop."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from icoda_core import agent
from icoda_core.process import ProcessResult

EXPECTED_IDS = ["claude", "codex", "gemini", "opencode", "aider", "copilot", "qwen"]


def test_providers_file_lists_seven_binaries_with_two_models_each() -> None:
    providers = agent.load_providers()
    assert [p.id for p in providers] == EXPECTED_IDS
    for provider in providers:
        assert len(provider.models) == 2, provider.id
        assert "{model}" in provider.invocation and "{binary}" in provider.invocation, provider.id
        assert ("{prompt}" in provider.invocation) == (provider.prompt_mode == "arg"), provider.id
    assert agent.providers_checked_on() == "2026-09-07"
    assert {p.id for p in providers if p.enabled} == {"claude", "codex", "gemini"}


def test_claude_command_reads_the_prompt_from_stdin_and_disables_editing_tools(tmp_path: Path) -> None:
    """``--disallowedTools`` takes a list, so a prompt argument after it would be swallowed: stdin it is."""
    claude = agent.find_provider(agent.load_providers(), "claude")
    argv, stdin_text = agent.build_command(claude, "claude-opus-5", "hello world", tmp_path)
    assert argv[:2] == ["claude", "-p"] and "--model" in argv and "claude-opus-5" in argv
    assert "--disallowedTools" in argv and "hello world" not in argv and stdin_text == "hello world"


def test_codex_command_reads_prompt_from_stdin_with_read_only_sandbox(tmp_path: Path) -> None:
    codex = agent.find_provider(agent.load_providers(), "codex")
    argv, stdin_text = agent.build_command(codex, "gpt-6-astra", "do it", tmp_path, binary="/opt/bin/codex")
    assert argv == ["/opt/bin/codex", "exec", "--cd", str(tmp_path), "-m", "gpt-6-astra", "--sandbox", "read-only", "-"]
    assert stdin_text == "do it"


def test_gemini_command(tmp_path: Path) -> None:
    gemini = agent.find_provider(agent.load_providers(), "gemini")
    argv, _ = agent.build_command(gemini, "gemini-3.8-flash", "p", tmp_path)
    assert argv == ["gemini", "-m", "gemini-3.8-flash", "-p", "p"]


def test_rate_limit_detection_and_wait_times() -> None:
    assert agent.is_rate_limited("Error: rate limit exceeded, try again in 2 minutes")
    assert not agent.is_rate_limited("compiled successfully")
    assert agent.retry_after_seconds("try again in 2 minutes") == 120
    assert agent.retry_after_seconds("retry after 45 seconds") == 45
    now = datetime(2026, 9, 7, 14, 0, tzinfo=timezone.utc)
    assert agent.retry_after_seconds("usage limit reached, resets at 2:30 pm", now=now) == 1800
    assert agent.retry_after_seconds("usage limit reached, resets at 1:00pm", now=now) == 23 * 3600
    assert agent.retry_after_seconds("quota exceeded") == 300


def test_run_provider_retries_after_rate_limit(tmp_path: Path) -> None:
    claude = agent.find_provider(agent.load_providers(), "claude")
    replies = [ProcessResult(["x"], 1, "", "rate limit, try again in 1 minute"),
               ProcessResult(["x"], 0, '{"ok": true}', "")]
    slept: list[float] = []
    result = agent.run_provider(claude, "claude-opus-5", "p", tmp_path, sleep=slept.append,
                                runner=lambda *a, **k: replies.pop(0))
    assert result.ok and slept == [60]
