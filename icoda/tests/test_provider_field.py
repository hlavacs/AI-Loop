"""The Binary/Model field against the Tk stub: options follow the binary, models are remembered per binary."""

from __future__ import annotations

import tkinter as tk

from icoda_core.agent import Model, Provider
from icoda_gui import provider_field


def providers() -> list[Provider]:
    def make(pid: str, command: str, models: tuple[str, str], enabled: bool = True) -> Provider:
        return Provider(pid, f"{pid} label", command, ("{binary}", "{prompt}"), "arg",
                        tuple(Model(m, m.upper()) for m in models), enabled, False, "")
    return [make("claude", "claude", ("claude-a", "claude-b")), make("codex", "codex", ("gpt-a", "gpt-b")),
            make("qwen", "qwen", ("qwen-a", "qwen-b"), enabled=False)]


def test_first_enabled_provider_and_its_first_model_are_preselected() -> None:
    changes: list[int] = []
    field = provider_field.ProviderField(tk.Tk(), providers(), on_change=lambda: changes.append(1))
    assert field.selection() == provider_field.ProviderSelection("claude", "claude", "claude-a")
    assert field.hint_var.get() == "claude label" and changes


def test_models_follow_the_binary_and_custom_models_are_remembered() -> None:
    field = provider_field.ProviderField(tk.Tk(), providers())
    field.model_var.set("claude-custom")
    field.binary_var.set("codex")
    assert field.selection() == provider_field.ProviderSelection("codex", "codex", "gpt-a")
    field.model_var.set("gpt-b")
    field.binary_var.set("/opt/homebrew/bin/claude")
    assert field.selection() == provider_field.ProviderSelection("claude", "/opt/homebrew/bin/claude",
                                                                 "claude-custom")
    field.binary_var.set("codex.exe")
    assert field.selection().model == "gpt-b"


def test_unknown_and_disabled_binaries() -> None:
    field = provider_field.ProviderField(tk.Tk(), providers(), binary="qwen", model="qwen-b")
    assert field.selection() == provider_field.ProviderSelection("qwen", "qwen", "qwen-b")
    assert "not verified" in field.hint_var.get()
    field.binary_var.set("mystery")
    assert field.selection().provider_id is None and "unknown binary" in field.hint_var.get()
    field.set("", "")
    assert field.selection() == provider_field.ProviderSelection("claude", "claude", "claude-a")
    assert field.selection().to_dict() == {"provider": "claude", "binary": "claude", "model": "claude-a"}
