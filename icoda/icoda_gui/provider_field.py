"""The Binary/Model field: two editable combo boxes whose model options follow the chosen binary.

A typed binary (a full path, or an unlisted command) is resolved to a provider by its base name. The model chosen
or typed for one binary is remembered for the session and restored when that binary is chosen again.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import PurePath
from tkinter import ttk
from typing import Any

from icoda_core.agent import Provider


@dataclass(frozen=True)
class ProviderSelection:
    """What the developer chose: the provider (None for an unknown binary), the binary text and the model."""

    provider_id: str | None
    binary: str
    model: str

    def to_dict(self) -> dict[str, str]:
        return {"provider": self.provider_id or "", "binary": self.binary, "model": self.model}


def resolve_provider(providers: Sequence[Provider], binary: str) -> Provider | None:
    """The provider whose command matches ``binary`` (a command or a path), or None."""
    name = PurePath(binary.strip()).name.lower()
    for suffix in (".exe", ".cmd", ".bat"):
        name = name.removesuffix(suffix)
    return next((p for p in providers if p.command.lower() == name or p.id == name), None)


class ProviderField:
    """Labelled Binary and Model combo boxes in a frame; ``selection()`` reads them."""

    def __init__(self, parent: Any, providers: Sequence[Provider], on_change: Callable[[], None] | None = None,
                 binary: str = "", model: str = "") -> None:
        self.providers = list(providers)
        self.on_change = on_change
        self.remembered: dict[str, str] = {}
        self.current_provider: Provider | None = None
        self._updating = False
        self.frame = ttk.Frame(parent)
        self.binary_var = tk.StringVar(value="")
        self.model_var = tk.StringVar(value="")
        self.hint_var = tk.StringVar(value="")
        ttk.Label(self.frame, text="Binary").grid(row=0, column=0, sticky="w", padx=(0, 4))
        self.binary_box = ttk.Combobox(self.frame, textvariable=self.binary_var, width=18,
                                       values=[p.command for p in self.providers if p.enabled])
        self.binary_box.grid(row=0, column=1, sticky="ew", padx=(0, 10))
        ttk.Label(self.frame, text="Model").grid(row=0, column=2, sticky="w", padx=(0, 4))
        self.model_box = ttk.Combobox(self.frame, textvariable=self.model_var, width=26)
        self.model_box.grid(row=0, column=3, sticky="ew")
        ttk.Label(self.frame, textvariable=self.hint_var, foreground="#666666").grid(row=1, column=0, columnspan=4,
                                                                                   sticky="w", pady=(2, 0))
        self.frame.columnconfigure(3, weight=1)
        self.binary_var.trace_add("write", self._on_binary_written)
        self.model_var.trace_add("write", self._on_model_written)
        self.set(binary, model)

    # -- state ----------------------------------------------------------------------------

    def set(self, binary: str = "", model: str = "") -> None:
        """Select ``binary`` (the first enabled provider when empty) and ``model`` (its first model when empty)."""
        if not binary:
            first = next((p for p in self.providers if p.enabled), None)
            binary = first.command if first else ""
        self._updating = True
        try:
            self.binary_var.set(binary)
            self._follow_binary()
            if model:
                self.model_var.set(model)
                self._remember(model)
        finally:
            self._updating = False
        self._changed()

    def selection(self) -> ProviderSelection:
        provider = resolve_provider(self.providers, self.binary_var.get())
        return ProviderSelection(provider.id if provider else None, self.binary_var.get().strip(),
                                 self.model_var.get().strip())

    # -- reactions ------------------------------------------------------------------------

    def _on_binary_written(self, *_args: Any) -> None:
        if self._updating:
            return
        self._updating = True
        try:
            self._follow_binary()
        finally:
            self._updating = False
        self._changed()

    def _on_model_written(self, *_args: Any) -> None:
        if self._updating:
            return
        self._remember(self.model_var.get().strip())
        self._changed()

    def _remember(self, model: str) -> None:
        if self.current_provider is not None and model:
            self.remembered[self.current_provider.id] = model

    def _follow_binary(self) -> None:
        """Swap the model options to the resolved provider's models; restore the model last used with it."""
        provider = resolve_provider(self.providers, self.binary_var.get())
        self.current_provider = provider
        if provider is None:
            self.model_box.configure(values=[])
            self.hint_var.set("unknown binary — ICODA does not know how to call it (see providers.json)")
            return
        self.model_box.configure(values=[m.id for m in provider.models])
        self.model_var.set(self.remembered.get(provider.id, provider.default_model))
        self.hint_var.set(provider.label + ("" if provider.enabled else " — not verified yet"))

    def _changed(self) -> None:
        if self.on_change is not None:
            self.on_change()
