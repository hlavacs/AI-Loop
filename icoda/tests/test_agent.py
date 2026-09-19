"""providers.json, invocation templates, rate-limit parsing and the retry loop."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from icoda_core import agent, persistence, provider_check
from icoda_core.process import ProcessResult

EXPECTED_IDS = ["claude", "codex", "gemini", "opencode", "aider", "copilot", "qwen"]


def test_providers_file_lists_seven_binaries_with_two_models_each() -> None:
    providers = agent.load_providers()
    assert [p.id for p in providers] == EXPECTED_IDS
    for provider in providers:
        assert len(provider.models) == 2, provider.id
        assert "{model}" in provider.invocation and "{binary}" in provider.invocation, provider.id
        assert ("{prompt}" in provider.invocation) == (provider.prompt_mode == "arg"), provider.id
    assert agent.providers_checked_on() == "2026-09-09"
    assert {p.id for p in providers if p.enabled} == {"claude", "codex"}


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


def test_provider_check_uses_subcommand_help_and_reports_missing_flags(tmp_path: Path) -> None:
    codex = agent.find_provider(agent.load_providers(), "codex")

    def compatible(command, **_kwargs):
        output = "codex-cli 0.152.1" if "--version" in command else "-m --model --cd --sandbox"
        return ProcessResult(command, 0, output, "")

    check = agent.check_provider(codex, tmp_path, finder=lambda _command: "/opt/bin/codex", runner=compatible)
    assert check.installed and check.compatible and check.version == "codex-cli 0.152.1"
    assert check.help_command == ("/opt/bin/codex", "exec", "--help") and not check.missing_flags

    def incompatible(command, **_kwargs):
        return ProcessResult(command, 0, "codex help without configured options", "")

    failed = agent.check_provider(codex, tmp_path, finder=lambda _command: "/opt/bin/codex", runner=incompatible)
    assert failed.installed and not failed.compatible and set(failed.missing_flags) == {"--cd", "-m", "--sandbox"}


def test_provider_check_does_not_run_an_unavailable_binary(tmp_path: Path) -> None:
    gemini = agent.find_provider(agent.load_providers(), "gemini")

    def should_not_run(*_args, **_kwargs):
        raise AssertionError("runner called")

    check = agent.check_provider(gemini, tmp_path, finder=lambda _command: None, runner=should_not_run)
    assert not check.installed and not check.compatible and check.detail == "not installed"


def test_provider_check_cli_writes_qualification_report(tmp_path: Path, monkeypatch) -> None:
    checks = [agent.ProviderCheck("codex", True, True, True, True, "/opt/bin/codex", "codex 1",
                                  ("/opt/bin/codex", "exec", "--help"), ("-m",), (), "options present")]
    monkeypatch.setattr(provider_check.agent, "load_providers", list)
    monkeypatch.setattr(provider_check.agent, "check_providers", lambda _providers, _cwd: checks)
    monkeypatch.setattr(provider_check.agent, "providers_checked_on", lambda: "2026-09-09")
    output = tmp_path / "qualification.json"
    assert provider_check.main(["--output", str(output), "--cwd", str(tmp_path)]) == 0
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["configured_on"] == "2026-09-09"
    assert data["providers"][0]["path"] == "/opt/bin/codex"


def test_provider_check_output_uses_atomic_write_and_cleans_up_after_mid_write_failure(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "qualification.json"
    output.write_bytes(b"previous qualification bytes\n")
    previous_bytes = output.read_bytes()
    calls: list[Path] = []
    atomic_write = persistence._atomic_write_text

    def observed_atomic_write(target: Path, text: str) -> None:
        calls.append(target)
        atomic_write(target, text)

    def fail_fsync(_descriptor: int) -> None:
        raise OSError("injected mid-write failure")

    monkeypatch.setattr(provider_check.agent, "load_providers", list)
    monkeypatch.setattr(provider_check.agent, "check_providers", lambda _providers, _cwd: [])
    monkeypatch.setattr(persistence, "_atomic_write_text", observed_atomic_write)
    monkeypatch.setattr(persistence.os, "fsync", fail_fsync)

    with pytest.raises(OSError, match="injected mid-write failure"):
        provider_check.main(["--output", str(output), "--cwd", str(tmp_path)])

    assert calls == [output]
    assert output.read_bytes() == previous_bytes
    assert sorted(item.name for item in tmp_path.iterdir()) == ["qualification.json"]


def test_provider_check_cli_fails_for_an_enabled_incompatible_binary(tmp_path: Path, monkeypatch) -> None:
    checks = [agent.ProviderCheck("codex", True, True, True, False, missing_flags=("--sandbox",),
                                  detail="missing from help: --sandbox")]
    monkeypatch.setattr(provider_check.agent, "load_providers", list)
    monkeypatch.setattr(provider_check.agent, "check_providers", lambda _providers, _cwd: checks)
    assert provider_check.main(["--cwd", str(tmp_path)]) == 1


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
