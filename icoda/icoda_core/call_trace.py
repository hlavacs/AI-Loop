"""Load and step through ICODA call-sequence traces.

Trace format ``icoda-call-trace-v1`` is UTF-8, tab-separated text.  Blank lines
and comment lines beginning with ``#`` are ignored.  The required first line is
``# icoda-call-trace-v1``.  Each event then has these eight columns::

    event  timestamp_ns  thread  depth  function  caller  symbol  module

``event`` is ``E`` (entry) or ``X`` (exit); the timestamp is monotonic elapsed
nanoseconds since the recording runtime started; depth is per thread.  Function
is a hexadecimal module-relative address when module is known and an absolute
address otherwise.  Caller is the raw return address.  Symbol and module may be
empty, and tabs/newlines in them are replaced with spaces by the runtime.
File order is the authoritative global event order: the runtime serializes a
complete event while holding its output lock.
"""

from __future__ import annotations

import json
import re
import shutil
from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path

from icoda_core import process, toolchain
from icoda_core.model import CALLABLE_KINDS, DerivedModel, Entity

FORMAT_HEADER = "# icoda-call-trace-v1"
FIELD_COUNT = 8
_CLANG_MODULE_OWNER = re.compile(
    r"@[A-Za-z_][A-Za-z0-9_.]*(?::(?!:)[A-Za-z_][A-Za-z0-9_.]*)?"
)


class TraceFormatError(ValueError):
    """A trace does not conform to ``icoda-call-trace-v1``."""


class EventKind(str, Enum):
    ENTRY = "E"
    EXIT = "X"


@dataclass(frozen=True)
class CallEvent:
    """One event in recorded order, optionally resolved to an ICODA entity."""

    sequence: int
    kind: EventKind
    timestamp_ns: int
    thread_id: str
    depth: int
    function_id: str
    caller_id: str | None
    function_name: str | None
    module: str | None
    entity: Entity | None = None

    @property
    def identifier(self) -> str:
        """A key unique across modules in one process trace."""
        return f"{self.module}!{self.function_id}" if self.module else self.function_id


@dataclass
class CallTrace:
    """An ordered event sequence with a cursor suitable for playback controls."""

    events: tuple[CallEvent, ...]
    cursor: int = 0

    @property
    def current(self) -> CallEvent | None:
        return self.events[self.cursor - 1] if 0 < self.cursor <= len(self.events) else None

    def event_at(self, index: int) -> CallEvent:
        return self.events[index]

    def seek(self, index: int) -> None:
        """Set the index of the next event returned by :meth:`step`."""
        if not 0 <= index <= len(self.events):
            raise IndexError(index)
        self.cursor = index

    def reset(self) -> None:
        self.cursor = 0

    def step(self) -> CallEvent | None:
        """Return the next entry or exit event, or ``None`` at the end."""
        if self.cursor >= len(self.events):
            return None
        event = self.events[self.cursor]
        self.cursor += 1
        return event

    def step_entry(self) -> CallEvent | None:
        """Return the next called-function entry while advancing past exits."""
        while (event := self.step()) is not None:
            if event.kind == EventKind.ENTRY:
                return event
        return None


@dataclass
class _PlaybackCall:
    entity: Entity
    count: int
    caller_counts: dict[str, int]


class CallPlayback:
    """Navigate grouped calls or step recorded function frames on one thread."""

    def __init__(self, trace: CallTrace) -> None:
        self._events = trace.events
        self._frames: dict[int, int | None] = {}
        self._returns: dict[int, int] = {}
        self._stops: dict[str, list[int]] = defaultdict(list)
        self._entry_calls: dict[int, int] = {}
        self._call_entries: list[int] = []
        calls: list[_PlaybackCall] = []
        stacks: dict[str, list[int | None]] = defaultdict(list)
        for index, event in enumerate(trace.events):
            stack = stacks[event.thread_id]
            if event.kind == EventKind.EXIT:
                entry = stack[event.depth] if event.depth < len(stack) else None
                del stack[event.depth:]
                if entry is None or trace.events[entry].identifier != event.identifier:
                    continue
                self._returns[entry] = index
                parent = next((frame for frame in reversed(stack)
                               if frame is not None and trace.events[frame].entity is not None), None)
                if trace.events[entry].entity is not None or parent is not None:
                    self._frames[index] = parent
                    self._stops[event.thread_id].append(index)
                continue
            del stack[event.depth:]
            stack.extend([None] * (event.depth - len(stack)))
            caller = trace.events[stack[-1]].entity if stack and stack[-1] is not None else None
            stack.append(index)
            if event.entity is None:
                continue
            self._frames[index] = index
            self._stops[event.thread_id].append(index)
            if calls and calls[-1].entity.usr == event.entity.usr:
                calls[-1].count += 1
                if caller is not None:
                    calls[-1].caller_counts[caller.usr] = calls[-1].caller_counts.get(caller.usr, 0) + 1
            else:
                caller_counts = {caller.usr: 1} if caller is not None else {}
                calls.append(_PlaybackCall(event.entity, 1, caller_counts))
                self._call_entries.append(index)
            self._entry_calls[index] = len(calls)
        self._calls = tuple(calls)
        self.reset()

    @property
    def position(self) -> int:
        """One-based position of the selected call, or zero before the first call."""
        return self._position

    @property
    def total(self) -> int:
        return len(self._calls)

    @property
    def entities(self) -> tuple[Entity, ...]:
        """Each function represented by playback, in first-call order."""
        return tuple({call.entity.usr: call.entity for call in self._calls}.values())

    @property
    def current_entity(self) -> Entity | None:
        frame = self._frames.get(self._event_index)
        return self._events[frame].entity if frame is not None else None

    @property
    def current_repeat_count(self) -> int:
        if self._stepping:
            return 1 if self.current_entity is not None else 0
        return self._calls[self._position - 1].count if self._position else 0

    @property
    def current_caller_counts(self) -> Mapping[str, int]:
        if self._stepping:
            return {}
        return self._calls[self._position - 1].caller_counts if self._position else {}

    @property
    def status(self) -> str:
        if not self.total:
            return "No project calls resolved. Check the executable/PDB and reload the trace."
        if self._stepping:
            event = self._events[self._event_index]
            entity = self.current_entity
            frame = self._frames[self._event_index]
            location = (f"depth {self._events[frame].depth}: {entity.qualified_name or entity.name}"
                        if frame is not None and entity is not None else "no resolved caller")
            action = (f" — returned from {event.function_name or event.function_id}"
                      if event.kind == EventKind.EXIT else "")
            return (f"event {self._event_index + 1} of {len(self._events)} · "
                    f"thread {event.thread_id} · {location}{action}")
        if self._position == 0:
            return f"call 0 of {self.total}"
        call = self._calls[self._position - 1]
        status = f"call {self._position} of {self.total}: {call.entity.qualified_name or call.entity.name}"
        return status if call.count == 1 else f"{status} — {call.count} consecutive calls"

    def next_call(self) -> Entity | None:
        """Select and return the next resolved entry, or ``None`` at the end."""
        index = bisect_right(self._call_entries, self._event_index)
        if index >= self.total:
            return None
        return self._select_event(self._call_entries[index], stepping=False)

    def previous_call(self) -> Entity | None:
        """Select and return the preceding resolved entry, or ``None`` at the start."""
        index = bisect_left(self._call_entries, self._event_index) - 1
        if index < 0:
            self.reset()
            return None
        return self._select_event(self._call_entries[index], stepping=False)

    def seek_first_call(self, usr: str) -> Entity | None:
        """Select the first visual call of ``usr`` without moving when it is absent."""
        for index, call in enumerate(self._calls):
            if call.entity.usr == usr:
                return self._select_event(self._call_entries[index], stepping=False)
        return None

    def reset(self) -> None:
        self._position = 0
        self._event_index = -1
        self._stepping = False
        self._targets: dict[str, int | None] = {}

    def _select_event(self, index: int, *, stepping: bool = True) -> Entity | None:
        self._event_index = index
        frame = self._frames[index]
        self._position = self._entry_calls[frame] if frame is not None else 0
        self._stepping = stepping
        self._targets.clear()
        return self.current_entity

    def _step_target(self, mode: str) -> int | None:
        if self._event_index < 0:
            return self._call_entries[0] if self._call_entries and mode != "out" else None
        frame = self._frames[self._event_index]
        if mode == "out":
            target = self._returns.get(frame) if frame is not None else None
            return target if target is not None and target > self._event_index else None
        event = self._events[self._event_index]
        stops = self._stops[event.thread_id]
        start = bisect_right(stops, self._event_index)
        if mode == "into" or frame is None:
            return stops[start] if start < len(stops) else None
        # At function granularity, Over skips the next child invocation, stopping
        # after its return (or after this frame returns if it has no more children).
        depth = self._events[frame].depth
        for offset in range(start, len(stops)):
            index = stops[offset]
            candidate = self._events[index]
            if candidate.kind == EventKind.EXIT and candidate.depth <= depth + 1:
                return index
        return None

    def can_step(self, mode: str) -> bool:
        """Whether a recorded destination exists for Into, Over, or Out."""
        if mode not in ("into", "over", "out"):
            raise ValueError(mode)
        if mode not in self._targets:
            self._targets[mode] = self._step_target(mode)
        return self._targets[mode] is not None

    def _step(self, mode: str) -> Entity | None:
        if not self.can_step(mode):
            return None
        target = self._targets[mode]
        assert target is not None
        return self._select_event(target)

    def step_into(self) -> Entity | None:
        """Select the next resolved entry or return on the selected thread."""
        return self._step("into")

    def step_over(self) -> Entity | None:
        """Skip a child invocation and select the frame active after its return."""
        return self._step("over")

    def step_out(self) -> Entity | None:
        """Run to this invocation's recorded return and select its known caller."""
        return self._step("out")


def load_trace(path: Path, model: DerivedModel | None = None,
               symbol_names: Mapping[str, str] | None = None) -> CallTrace:
    """Parse ``path`` and resolve unique symbols to callable entities in ``model``.

    ``symbol_names`` may supply names from an external symbolizer.  Keys can be
    either ``module!function`` identifiers or bare function addresses; supplied
    names take precedence over the trace's optional runtime symbol.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise TraceFormatError(f"{path}: trace is not valid UTF-8") from exc
    first = next((line for line in lines if line.strip()), "")
    if first != FORMAT_HEADER:
        raise TraceFormatError(f"{path}: missing {FORMAT_HEADER!r} header")

    events: list[CallEvent] = []
    for line_number, line in enumerate(lines, 1):
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != FIELD_COUNT:
            raise TraceFormatError(f"{path}:{line_number}: expected {FIELD_COUNT} tab-separated fields")
        kind_text, timestamp_text, thread_id, depth_text, function_id, caller_id, symbol, module = fields
        try:
            kind = EventKind(kind_text)
            timestamp_ns = int(timestamp_text)
            depth = int(depth_text)
        except ValueError as exc:
            raise TraceFormatError(f"{path}:{line_number}: invalid event, timestamp, or depth") from exc
        if timestamp_ns < 0 or depth < 0 or not thread_id or not function_id:
            raise TraceFormatError(f"{path}:{line_number}: negative or missing event value")
        module_name = module or None
        events.append(CallEvent(
            len(events), kind, timestamp_ns, thread_id, depth, function_id, caller_id or None,
            symbol or None, module_name,
        ))

    resolved_names = _symbolize(events)
    resolver = _EntityResolver(model)
    resolved_events = []
    entities: dict[str | None, Entity | None] = {}
    for event in events:
        supplied = symbol_names.get(event.identifier) if symbol_names else None
        if supplied is None and symbol_names:
            supplied = symbol_names.get(event.function_id)
        function_name = supplied or resolved_names.get((event.module, event.function_id))
        if function_name not in entities:
            entities[function_name] = resolver.resolve(function_name)
        resolved_events.append(replace(
            event, function_name=function_name, entity=entities[function_name]))
    return CallTrace(tuple(resolved_events))


def _symbolize(events: list[CallEvent]) -> dict[tuple[str | None, str], str]:
    """Resolve each distinct module/function pair without making tools mandatory."""
    symbols: dict[tuple[str | None, str], str] = {}
    for event in events:
        key = (event.module, event.function_id)
        if event.function_name and key not in symbols:
            symbols[key] = event.function_name

    mangled = sorted({symbol for symbol in symbols.values() if symbol.startswith("_Z")})
    demangled = _demangle(mangled)
    for key, symbol in tuple(symbols.items()):
        symbols[key] = demangled.get(symbol, symbol)

    missing_by_module: dict[str, set[str]] = defaultdict(set)
    for event in events:
        key = (event.module, event.function_id)
        if key not in symbols and event.module:
            missing_by_module[event.module].add(event.function_id)
    for module, function_ids in missing_by_module.items():
        symbols.update({(module, address): name
                        for address, name in _module_symbols(module, function_ids).items()})
    return symbols


def _demangle(symbols: list[str]) -> dict[str, str]:
    if not symbols:
        return {}
    executable = shutil.which("c++filt") or shutil.which("llvm-cxxfilt")
    if executable is None:
        return {}
    try:
        result = process.run_bounded(
            [executable], input_text="\n".join(symbols) + "\n", timeout=5, max_output=1_000_000)
    except OSError:
        return {}
    names = result.stdout.splitlines()
    if not result.ok or len(names) != len(symbols):
        return {}
    return {symbol: name.strip() for symbol, name in zip(symbols, names) if name.strip()}


def _module_symbols(module: str, function_ids: set[str]) -> dict[str, str]:
    if Path(module).suffix.lower() in {".exe", ".dll"}:
        return _windows_module_symbols(module, function_ids)
    executable = shutil.which("nm") or shutil.which("llvm-nm")
    if executable is None:
        return {}
    try:
        result = process.run_bounded(
            [executable, "-C", "--defined-only", module], timeout=10, max_output=2_000_000)
    except OSError:
        return {}
    if not result.ok:
        return {}
    available = _parse_nm(result.stdout)
    if not available:
        return {}
    addresses = [address for address, _name in available]
    resolved: dict[str, str] = {}
    for function_id in function_ids:
        try:
            address = int(function_id, 16)
        except ValueError:
            continue
        index = bisect_right(addresses, address) - 1
        if index >= 0:
            resolved[function_id] = available[index][1]
    return resolved


def _windows_module_symbols(module: str, function_ids: set[str]) -> dict[str, str]:
    """Resolve recorded PE image-relative addresses through the executable's PDB."""
    executable = shutil.which("llvm-symbolizer")
    if executable is None:
        executable = next((str(path) for candidate in toolchain.candidates()
                           if (path := Path(candidate.path).with_name("llvm-symbolizer.exe")).is_file()), None)
    if executable is None:
        return {}
    addresses = sorted(address for address in function_ids
                       if address.startswith("0x") and all(c in "0123456789abcdefABCDEF" for c in address[2:])
                       and len(address) > 2)
    symbols = {}
    for start in range(0, len(addresses), 256):
        try:
            result = process.run_bounded(
                [executable, f"--obj={module}", "--relative-address", "--no-inlines", "--output-style=JSON"],
                input_text="\n".join(addresses[start:start + 256]) + "\n", timeout=30, max_output=2_000_000)
            if not result.ok:
                continue
            for line in result.stdout.splitlines():
                item = json.loads(line)
                frames = item.get("Symbol", [])
                name = frames[0].get("FunctionName") if frames else None
                if name and name != "??":
                    symbols[item["Address"]] = name
        except (OSError, ValueError, KeyError):
            continue
    return symbols


def _parse_nm(output: str) -> list[tuple[int, str]]:
    symbols: list[tuple[int, str]] = []
    for line in output.splitlines():
        fields = line.strip().split(None, 2)
        if len(fields) != 3 or fields[1] not in "tTwWiI":
            continue
        try:
            address = int(fields[0], 16)
        except ValueError:
            continue
        symbols.append((address, fields[2].strip()))
    return sorted(symbols)


class _EntityResolver:
    def __init__(self, model: DerivedModel | None) -> None:
        self._entities: dict[str, list[Entity]] = defaultdict(list)
        if model is None:
            return
        for entity in model.entities.values():
            if entity.kind not in CALLABLE_KINDS:
                continue
            for name in _entity_names(entity):
                if name:
                    self._entities[name].append(entity)

    def resolve(self, symbol: str | None) -> Entity | None:
        if not symbol:
            return None
        exact, without_arguments = _symbol_variants(symbol)
        matches = self._matches(exact)
        if matches:
            return next(iter(matches.values())) if len(matches) == 1 else None
        matches = self._matches(without_arguments)
        return next(iter(matches.values())) if len(matches) == 1 else None

    def _matches(self, names: set[str]) -> dict[str, Entity]:
        return {entity.usr: entity for name in names for entity in self._entities.get(name, ())}


def _entity_names(entity: Entity) -> set[str]:
    names = {entity.name, entity.qualified_name, entity.signature, _without_arguments(entity.signature)}
    name_at = entity.signature.find(entity.name)
    if name_at >= 0:
        suffix = entity.signature[name_at + len(entity.name):].strip()
        if suffix.startswith("("):
            names.update({f"{entity.name}{suffix}", f"{entity.qualified_name}{suffix}"})
    return {_normalize_symbol(name) for name in names if name}


def _symbol_variants(symbol: str) -> tuple[set[str], set[str]]:
    symbol = _normalize_symbol(symbol)
    exact = {symbol, _CLANG_MODULE_OWNER.sub("", symbol)}
    for name in tuple(exact):
        if name.startswith("_") and not name.startswith("_Z"):
            exact.add(name[1:])
    without_arguments = {_without_arguments(name) for name in exact}
    return ({name for name in exact if name},
            {name for name in without_arguments if name and name not in exact})


def _normalize_symbol(name: str) -> str:
    return " ".join(name.strip().split())


def _without_arguments(name: str) -> str:
    return name.split("(", 1)[0].strip()
