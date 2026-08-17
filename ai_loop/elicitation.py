"""Frontend-neutral, provider-neutral formal-specification elicitation.

The provider boundary accepts the same ingredients used by AI-Loop's
structured controller calls: a prompt, a strict JSON schema, a repository
working directory, and an explicit read-only policy.  Provider adapters own
Codex/Claude/Gemini CLI details; this module owns the domain contract,
authoritative runtime validation, one bounded repair, and persistence.
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

from ai_loop.config import sanitized_child_env
from ai_loop.specifications import (
    SpecificationDocument,
    SpecificationError,
    SpecificationService,
    SpecificationStateError,
    StoredSpecificationAnalysis,
    StoredSpecificationVersion,
    canonical_json,
    sha256_text,
)


RESULT_FIELDS = frozenset({"summary", "suggested_specification", "choices", "warnings"})
CHOICE_FIELDS = frozenset(
    {"topic", "question", "context", "options", "recommendation", "blocking"}
)
OPTION_FIELDS = frozenset({"name", "description", "tradeoffs"})


class ElicitationError(SpecificationError):
    """Base error for model-assisted specification analysis."""


class ElicitationValidationError(ElicitationError):
    """Provider output failed strict shape, domain, or preservation validation."""


class StaleElicitationError(ElicitationError):
    """The exact source version ceased to be current while analysis ran."""


@dataclass(frozen=True)
class ChoiceOption:
    name: str
    description: str
    tradeoffs: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "tradeoffs": list(self.tradeoffs),
        }


@dataclass(frozen=True)
class DecisionProposal:
    topic: str
    question: str
    context: str
    options: tuple[ChoiceOption, ...]
    recommendation: str
    blocking: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "question": self.question,
            "context": self.context,
            "options": [option.to_dict() for option in self.options],
            "recommendation": self.recommendation,
            "blocking": self.blocking,
        }


@dataclass(frozen=True)
class ElicitationResult:
    summary: str
    suggested_specification: SpecificationDocument
    choices: tuple[DecisionProposal, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "suggested_specification": self.suggested_specification.to_dict(),
            "choices": [choice.to_dict() for choice in self.choices],
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class StructuredOutputRequest:
    """Portable request passed to an existing structured-output adapter."""

    prompt: str
    schema: dict[str, Any]
    repository_path: Path
    read_only: bool = True
    repair: bool = False


class StructuredOutputProvider(Protocol):
    """Minimal adapter contract implemented by CLI and fake providers."""

    provider: str
    model: str

    def generate_structured_output(self, request: StructuredOutputRequest) -> Any:
        """Return a mapping or JSON string for ``request``."""


@dataclass(frozen=True)
class CompletedElicitation:
    stored: StoredSpecificationAnalysis
    result: ElicitationResult
    repair_used: bool


@dataclass(frozen=True)
class AppliedElicitation:
    """Result of applying one immutable analysis to a fresh draft revision."""

    snapshot: StoredSpecificationVersion
    analysis: StoredSpecificationAnalysis
    decisions_created: int
    additions: tuple[dict[str, Any], ...]
    application_mode: str


@dataclass(frozen=True)
class CliStructuredOutputProvider:
    """Structured-output adapter for the controller CLI selected by the GUI.

    The adapter follows the command shapes already used by AI-Loop's
    controller/worker process layer and adds no provider SDK dependency.  One
    call launches one process; the elicitation engine remains the sole owner
    of the bounded structured-output repair.
    """

    provider: str
    binary: str
    model: str = ""
    timeout: int = 7200

    @staticmethod
    def _unwrap_cli_output(output: str) -> Any:
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError:
            return output
        if isinstance(parsed, dict) and isinstance(parsed.get("structured_output"), dict):
            return parsed["structured_output"]
        if isinstance(parsed, dict):
            for key in ("result", "response", "text", "content", "output"):
                if isinstance(parsed.get(key), str):
                    return parsed[key]
        return parsed

    def generate_structured_output(self, request: StructuredOutputRequest) -> Any:
        provider = self.provider.strip().lower()
        if provider not in {"codex", "claude", "gemini"}:
            raise ElicitationError(f"unsupported structured-output provider: {provider!r}")
        if not request.read_only:
            raise ElicitationError("formal elicitation CLI requests must be read-only")
        repository = request.repository_path.expanduser().resolve()
        if not repository.is_dir():
            raise ElicitationError(f"repository path is not a directory: {repository}")
        if shutil.which(self.binary) is None:
            raise ElicitationError(
                f"configured {provider} controller executable was not found: {self.binary}"
            )

        temporary_paths: list[Path] = []
        stdin: str | None = None
        if provider == "codex":
            with tempfile.NamedTemporaryFile(
                "w", suffix="-elicitation-schema.json", encoding="utf-8", delete=False
            ) as schema_handle:
                json.dump(request.schema, schema_handle, ensure_ascii=False)
                schema_path = Path(schema_handle.name)
            with tempfile.NamedTemporaryFile(
                "w", suffix="-elicitation-result.json", encoding="utf-8", delete=False
            ) as result_handle:
                result_path = Path(result_handle.name)
            temporary_paths.extend((schema_path, result_path))
            command = [
                self.binary,
                "exec",
                "--cd",
                str(repository),
                "--sandbox",
                "read-only",
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(result_path),
            ]
            if self.model:
                command.extend(["-m", self.model])
            command.append("-")
            stdin = request.prompt
        elif provider == "claude":
            command = [
                self.binary,
                "-p",
                "--output-format",
                "json",
                "--json-schema",
                json.dumps(request.schema, sort_keys=True, separators=(",", ":")),
                "--permission-mode",
                "plan",
                "--allowedTools",
                "Read,Glob,Grep",
            ]
            if self.model:
                command.extend(["--model", self.model])
            command.append(request.prompt)
        else:
            command = [self.binary]
            if self.model:
                command.extend(["-m", self.model])
            command.extend(["--sandbox", "-p", request.prompt, "--output-format", "json"])

        try:
            process = subprocess.run(
                command,
                cwd=str(repository),
                input=stdin,
                text=True,
                capture_output=True,
                timeout=self.timeout,
                env=sanitized_child_env(),
            )
            combined = (process.stdout + "\n" + process.stderr).strip()
            if process.returncode != 0:
                raise ElicitationError(
                    f"{provider} elicitation failed with rc={process.returncode}: "
                    f"{combined[-4000:]}"
                )
            output = process.stdout.strip()
            if provider == "codex":
                try:
                    output = result_path.read_text(encoding="utf-8").strip() or output
                except OSError:
                    pass
            return self._unwrap_cli_output(output)
        except subprocess.TimeoutExpired as exc:
            raise ElicitationError(
                f"{provider} elicitation timed out after {exc.timeout:g} seconds"
            ) from exc
        finally:
            for path in temporary_paths:
                path.unlink(missing_ok=True)


def _specification_schema_path() -> Path:
    return Path(__file__).resolve().parents[1] / "specification.schema.json"


def elicitation_result_schema(schema_path: str | Path | None = None) -> dict[str, Any]:
    """Build the strict result schema with the specification schema inlined.

    Specification-local references are resolved by copying its definitions to
    this schema's root.  The result therefore has no external schema
    dependency and can be sent as one provider schema document.
    """

    path = Path(schema_path) if schema_path is not None else _specification_schema_path()
    specification_schema = json.loads(path.read_text(encoding="utf-8"))
    specification_contract = {
        key: copy.deepcopy(value)
        for key, value in specification_schema.items()
        if key not in {"$schema", "$id", "$defs", "title"}
    }
    definitions = copy.deepcopy(specification_schema["$defs"])
    definitions.update(
        {
            "choiceOption": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "description": {"type": "string", "minLength": 1},
                    "tradeoffs": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string", "minLength": 1},
                    },
                },
                "required": ["name", "description", "tradeoffs"],
            },
            "decisionProposal": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "topic": {"type": "string", "minLength": 1},
                    "question": {"type": "string", "minLength": 1},
                    "context": {"type": "string", "minLength": 1},
                    "options": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 5,
                        "items": {"$ref": "#/$defs/choiceOption"},
                    },
                    "recommendation": {"type": "string", "minLength": 1},
                    "blocking": {"type": "boolean"},
                },
                "required": [
                    "topic",
                    "question",
                    "context",
                    "options",
                    "recommendation",
                    "blocking",
                ],
            },
        }
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://ai-loop.local/schemas/elicitation-result.schema.json",
        "title": "AI-Loop Formal Specification Elicitation Result",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "summary": {"type": "string", "minLength": 1},
            "suggested_specification": specification_contract,
            "choices": {
                "type": "array",
                "items": {"$ref": "#/$defs/decisionProposal"},
            },
            "warnings": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": ["summary", "suggested_specification", "choices", "warnings"],
        "$defs": definitions,
    }


def build_repository_analysis_prompt(
    source: StoredSpecificationVersion,
    schema: Mapping[str, Any] | None = None,
) -> str:
    """Build a deterministic, explicitly read-only repository-analysis prompt."""

    result_schema = dict(schema or elicitation_result_schema())
    return f"""You are analyzing a repository to improve a user-owned formal specification.

READ-ONLY RULE: inspect the repository at {source.repository_path}, but do not edit, create,
delete, rename, format, commit, or otherwise mutate any repository file or external state.
Inspect relevant manifests, architecture and module boundaries, public APIs, tests,
instruction files, build files, configuration, persisted formats, and existing behavior.

The exact source is specification {source.specification_id} version {source.version},
canonical content SHA-256 {source.canonical_content_hash}. The user's current document is:
{source.document.pretty_json()}
Produce ONE JSON object matching the embedded schema below. The suggested_specification
must be the COMPLETE document, not a patch, and must be strictly ADDITIVE:
- preserve every existing non-empty user-authored scalar byte-for-byte and with its type;
- preserve every existing list value and entity in its current order, appending only missing material;
- preserve all stable IDs and all existing references;
- fill only empty string fields, append genuinely missing list items/entities, and repair no user text;
- leave the materialized decisions array exactly unchanged;
- express every genuine tradeoff only as a choice proposal with 2-5 named options,
  a description and tradeoffs for every option, a recommendation, and a blocking flag.
Never materialize a recommended choice into suggested_specification.decisions.

Surface omitted normal flows, alternate flows, errors, edge and boundary cases, invalid
input, cleanup, cancellation, retries, concurrency, ordering, resource ownership,
persistence, compatibility, security, observability, performance, numerical stability,
long-lived state, platform variation, and deployment constraints. Specifically look for
behavior that appears correct in simple examples but fails under repetition, timing,
boundary conditions, resource pressure, numerical drift, non-determinism, race conditions,
unusual state transitions, or environmental variation. Ask only choices whose answers
materially affect implementation or verification; warnings should identify limitations
that are not safely expressible as additive specification content.

Runtime validation is authoritative even if schema enforcement is available. Return JSON
only, with no markdown or prose outside this single result:
{json.dumps(result_schema, sort_keys=True, separators=(",", ":"), ensure_ascii=False)}
"""


def _strict_object(value: Any, fields: frozenset[str], path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ElicitationValidationError(f"{path} must be an object")
    actual = set(value)
    unknown = sorted(actual - fields)
    missing = sorted(fields - actual)
    if unknown:
        raise ElicitationValidationError(
            f"{path} contains unknown fields: {', '.join(unknown)}"
        )
    if missing:
        raise ElicitationValidationError(f"{path} is missing fields: {', '.join(missing)}")
    return value


def _nonempty_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ElicitationValidationError(f"{path} must be a non-empty string")
    return value


def _string_array(value: Any, path: str, *, nonempty_items: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ElicitationValidationError(f"{path} must be an array")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ElicitationValidationError(f"{path}[{index}] must be a string")
        if nonempty_items and not item.strip():
            raise ElicitationValidationError(f"{path}[{index}] must not be empty")
        result.append(item)
    return tuple(result)


def _parse_choice(value: Any, index: int) -> DecisionProposal:
    path = f"choices[{index}]"
    item = _strict_object(value, CHOICE_FIELDS, path)
    options_value = item["options"]
    if not isinstance(options_value, list) or not 2 <= len(options_value) <= 5:
        raise ElicitationValidationError(f"{path}.options must contain two to five options")
    options: list[ChoiceOption] = []
    names: set[str] = set()
    for option_index, raw_option in enumerate(options_value):
        option_path = f"{path}.options[{option_index}]"
        option = _strict_object(raw_option, OPTION_FIELDS, option_path)
        name = _nonempty_string(option["name"], f"{option_path}.name")
        if name in names:
            raise ElicitationValidationError(f"{path}.options contains duplicate name: {name}")
        names.add(name)
        tradeoffs = _string_array(
            option["tradeoffs"], f"{option_path}.tradeoffs", nonempty_items=True
        )
        if not tradeoffs:
            raise ElicitationValidationError(f"{option_path}.tradeoffs must not be empty")
        options.append(
            ChoiceOption(
                name=name,
                description=_nonempty_string(
                    option["description"], f"{option_path}.description"
                ),
                tradeoffs=tradeoffs,
            )
        )
    recommendation = _nonempty_string(item["recommendation"], f"{path}.recommendation")
    if recommendation not in names:
        raise ElicitationValidationError(
            f"{path}.recommendation must name one of the proposed options"
        )
    if not isinstance(item["blocking"], bool):
        raise ElicitationValidationError(f"{path}.blocking must be a boolean")
    return DecisionProposal(
        topic=_nonempty_string(item["topic"], f"{path}.topic"),
        question=_nonempty_string(item["question"], f"{path}.question"),
        context=_nonempty_string(item["context"], f"{path}.context"),
        options=tuple(options),
        recommendation=recommendation,
        blocking=item["blocking"],
    )


def _preserve_value(source: Any, suggestion: Any, path: str) -> None:
    if type(source) is not type(suggestion):
        raise ElicitationValidationError(
            f"preservation violation at {path}: type changed from "
            f"{type(source).__name__} to {type(suggestion).__name__}"
        )
    if isinstance(source, dict):
        if set(source) != set(suggestion):
            raise ElicitationValidationError(
                f"preservation violation at {path}: object fields changed"
            )
        for key in source:
            _preserve_value(source[key], suggestion[key], f"{path}.{key}")
        return
    if isinstance(source, list):
        if len(suggestion) < len(source):
            raise ElicitationValidationError(
                f"preservation violation at {path}: removed existing list value or entity"
            )
        for index, value in enumerate(source):
            _preserve_value(value, suggestion[index], f"{path}[{index}]")
        for index, value in enumerate(suggestion[len(source) :], len(source)):
            if value in source:
                raise ElicitationValidationError(
                    f"preservation violation at {path}[{index}]: appended material is not missing"
                )
        return
    if isinstance(source, str) and source == "":
        return
    if source != suggestion:
        if path.endswith(".id"):
            raise ElicitationValidationError(
                f"preservation violation at {path}: stable ID changed"
            )
        raise ElicitationValidationError(
            f"preservation violation at {path}: non-empty user-authored scalar was modified"
        )


def validate_preservation(
    source: SpecificationDocument, suggestion: SpecificationDocument
) -> None:
    """Reject every non-additive or decision-materializing suggestion."""

    original = source.to_dict()
    candidate = suggestion.to_dict()
    if candidate["decisions"] != original["decisions"]:
        raise ElicitationValidationError(
            "preservation violation at suggested_specification.decisions: "
            "the model may propose choices but may not add or alter materialized decisions"
        )
    _preserve_value(original, candidate, "suggested_specification")


def validate_elicitation_result(
    value: Any,
    source: SpecificationDocument,
    *,
    worktree: str | Path | None = None,
) -> ElicitationResult:
    """Apply strict runtime parsing, structural validation, and preservation."""

    item = _strict_object(value, RESULT_FIELDS, "elicitation_result")
    try:
        suggestion = SpecificationDocument.from_dict(
            item["suggested_specification"], worktree=worktree
        )
    except SpecificationError as exc:
        raise ElicitationValidationError(f"suggested_specification is invalid: {exc}") from exc
    validate_preservation(source, suggestion)
    choices_value = item["choices"]
    if not isinstance(choices_value, list):
        raise ElicitationValidationError("choices must be an array")
    choices = tuple(_parse_choice(choice, index) for index, choice in enumerate(choices_value))
    topics = [choice.topic for choice in choices]
    if len(topics) != len(set(topics)):
        raise ElicitationValidationError("choices contains duplicate topics")
    return ElicitationResult(
        summary=_nonempty_string(item["summary"], "summary"),
        suggested_specification=suggestion,
        choices=choices,
        warnings=_string_array(item["warnings"], "warnings"),
    )


def _reject_nonfinite_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is not allowed: {value}")


def parse_provider_output(value: Any) -> dict[str, Any]:
    """Decode structured layer output without trusting provider validation."""

    parsed: Any
    if isinstance(value, Mapping):
        parsed = copy.deepcopy(dict(value))
    elif isinstance(value, str):
        try:
            parsed = json.loads(value, parse_constant=_reject_nonfinite_constant)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ElicitationValidationError(f"provider output is not valid JSON: {exc}") from exc
    else:
        raise ElicitationValidationError("provider output must be a JSON object or JSON string")
    if isinstance(parsed, dict) and isinstance(parsed.get("structured_output"), dict):
        parsed = parsed["structured_output"]
    if not isinstance(parsed, dict):
        raise ElicitationValidationError("provider output JSON must be an object")
    return parsed


def build_repair_prompt(original_prompt: str, invalid_output: Any, error: Exception) -> str:
    try:
        rendered = (
            canonical_json(invalid_output)
            if isinstance(invalid_output, Mapping)
            else str(invalid_output)
        )
    except SpecificationError:
        rendered = repr(invalid_output)
    return f"""Your previous structured elicitation result was rejected by authoritative runtime validation.

Validation error:
{error}

Invalid output tail:
{rendered[-6000:]}

This is the one permitted repair request. Return one corrected JSON object only. Preserve
all user-authored content and do not materialize any proposed decision. Reuse the exact
analysis context and embedded schema from the original request:
{original_prompt}
"""


def apply_elicitation_analysis(
    service: SpecificationService,
    analysis_id: str,
    *,
    application_mode: str,
    creator: str,
) -> AppliedElicitation:
    """Apply one stored result without trusting frontend-held result objects.

    The immutable analysis artifact is reloaded and revalidated against its
    exact source document.  ``SpecificationService`` then repeats freshness
    checks and commits the revision, choices, and application audit metadata
    atomically.
    """

    if application_mode not in {"choices_only", "apply_all"}:
        raise ElicitationError(
            "application_mode must be choices_only or apply_all"
        )
    stored = service.load_analysis(analysis_id)
    if stored.status != "validated" or stored.validated_result is None:
        raise ElicitationError("only a validated elicitation analysis can be applied")
    source = service.load(stored.specification_id, stored.source_version)
    current = service.load(stored.specification_id)
    if current.current_version != stored.source_version:
        raise StaleElicitationError(
            f"Cannot apply analysis {analysis_id}: it was created from version "
            f"{stored.source_version}, but the current stored draft is version "
            f"{current.current_version}. Run Analyze again from the current draft."
        )
    result = validate_elicitation_result(
        stored.validated_result,
        source.document,
        worktree=source.repository_path,
    )
    document = (
        source.document
        if application_mode == "choices_only"
        else result.suggested_specification
    )
    try:
        snapshot, applied_analysis = service.apply_analysis(
            analysis_id,
            application_mode=application_mode,
            document=document,
            choices=[choice.to_dict() for choice in result.choices],
            creator=creator,
        )
    except SpecificationStateError as exc:
        if "Run Analyze again" in str(exc) or "changed after" in str(exc):
            raise StaleElicitationError(str(exc)) from exc
        raise
    additions_value = applied_analysis.application_metadata.get("added", [])
    additions = tuple(
        dict(item) for item in additions_value if isinstance(item, Mapping)
    )
    return AppliedElicitation(
        snapshot=snapshot,
        analysis=applied_analysis,
        decisions_created=int(
            applied_analysis.application_metadata.get("decisions_created", 0)
        ),
        additions=additions,
        application_mode=application_mode,
    )


class ElicitationEngine:
    """Run one analysis plus at most one structured-output repair request."""

    def __init__(
        self,
        service: SpecificationService,
        provider: StructuredOutputProvider,
        *,
        schema_path: str | Path | None = None,
    ) -> None:
        self.service = service
        self.provider = provider
        self.schema = elicitation_result_schema(schema_path)

    def analyze(
        self,
        specification_id: str,
        source_version: int | None = None,
    ) -> CompletedElicitation:
        source = self.service.load(specification_id, source_version)
        if source.version != source.current_version:
            raise StaleElicitationError(
                "elicitation must start from the specification's exact current version"
            )
        provider_name = str(getattr(self.provider, "provider", "")).strip()
        model_name = str(getattr(self.provider, "model", "")).strip()
        if not provider_name:
            raise ElicitationError("structured-output provider identity must not be empty")
        analysis_id = f"ANALYSIS-{uuid.uuid4().hex.upper()}"
        prompt = build_repository_analysis_prompt(source, self.schema)
        prompt_hash = sha256_text(prompt)
        current_prompt = prompt
        last_error: ElicitationValidationError | None = None

        for attempt in range(2):
            request = StructuredOutputRequest(
                prompt=current_prompt,
                schema=copy.deepcopy(self.schema),
                repository_path=Path(source.repository_path),
                read_only=True,
                repair=attempt == 1,
            )
            try:
                output = self.provider.generate_structured_output(request)
            except Exception as exc:
                error = f"structured-output provider failed: {exc}"
                self.service.record_analysis_failure(
                    analysis_id=analysis_id,
                    specification_id=source.specification_id,
                    source_version=source.version,
                    provider=provider_name,
                    model=model_name,
                    prompt_hash=prompt_hash,
                    error=error,
                )
                raise ElicitationError(error) from exc
            try:
                parsed = parse_provider_output(output)
                result = validate_elicitation_result(
                    parsed,
                    source.document,
                    worktree=source.repository_path,
                )
            except ElicitationValidationError as exc:
                last_error = exc
                if attempt == 0:
                    current_prompt = build_repair_prompt(prompt, output, exc)
                    continue
                error = f"provider output remained invalid after one repair request: {exc}"
                self.service.record_analysis_failure(
                    analysis_id=analysis_id,
                    specification_id=source.specification_id,
                    source_version=source.version,
                    provider=provider_name,
                    model=model_name,
                    prompt_hash=prompt_hash,
                    error=error,
                )
                raise ElicitationValidationError(error) from exc

            try:
                stored = self.service.store_analysis(
                    analysis_id=analysis_id,
                    specification_id=source.specification_id,
                    source_version=source.version,
                    source_content_hash=source.canonical_content_hash,
                    provider=provider_name,
                    model=model_name,
                    prompt_hash=prompt_hash,
                    validated_result=result.to_dict(),
                    application_metadata={
                        "repair_used": attempt == 1,
                        "choice_count": len(result.choices),
                        "warning_count": len(result.warnings),
                    },
                )
            except SpecificationStateError as exc:
                error = str(exc)
                self.service.record_analysis_failure(
                    analysis_id=analysis_id,
                    specification_id=source.specification_id,
                    source_version=source.version,
                    provider=provider_name,
                    model=model_name,
                    prompt_hash=prompt_hash,
                    error=error,
                    status="stale",
                )
                raise StaleElicitationError(error) from exc
            return CompletedElicitation(stored=stored, result=result, repair_used=attempt == 1)

        raise AssertionError(f"unreachable elicitation retry state: {last_error}")


__all__ = [
    "AppliedElicitation",
    "ChoiceOption",
    "CliStructuredOutputProvider",
    "CompletedElicitation",
    "DecisionProposal",
    "ElicitationEngine",
    "ElicitationError",
    "ElicitationResult",
    "ElicitationValidationError",
    "StaleElicitationError",
    "StructuredOutputProvider",
    "StructuredOutputRequest",
    "apply_elicitation_analysis",
    "build_repository_analysis_prompt",
    "build_repair_prompt",
    "elicitation_result_schema",
    "parse_provider_output",
    "validate_elicitation_result",
    "validate_preservation",
]
