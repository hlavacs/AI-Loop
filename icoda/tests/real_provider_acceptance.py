"""Run ICODA's explicit, usage-consuming real-provider M2 acceptance scenario.

This is intentionally not a pytest test and is not part of ``verify.bash``. It calls a real LLM once (with
ICODA's normal retry behavior), then retains enough evidence to audit proposal, approval and undo independently.
"""

from __future__ import annotations

import argparse
import json
import shlex
import traceback
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from time import monotonic
from typing import Any

from icoda_core import agent, generator, git, persistence, prompt, specification, steplog, steps
from icoda_core.model import EdgeKind, Kind
from icoda_core.process import ProcessResult

REQUEST = (
    "Add exactly one new architecture entity: an exported `int answer()` function inside the existing exported "
    "namespace `app` in `src/app/app.cppm`. Give it a Doxygen `@brief` and `@satisfies UC-1, R-1`. This is an "
    "architecture stub, so its body must return the default value `{}`, not compute 42. Change existing "
    "`app::run()` only enough to call and discard `answer()` before it still returns success. Modify no other "
    "file and add no module, namespace, type, variable, test, or other callable."
)


class AcceptanceFailure(RuntimeError):
    """The real provider completed, but its result violated the acceptance contract."""


class Evidence:
    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=False)

    def write(self, name: str, text: str) -> None:
        (self.root / name).write_text(text, encoding="utf-8")

    def json(self, name: str, value: object) -> None:
        self.write(name, json.dumps(value, indent=2, default=str) + "\n")

    def progress(self, message: str) -> None:
        print(message, flush=True)
        with (self.root / "progress.log").open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")


@dataclass
class ProviderInvoker:
    provider: agent.Provider
    model: str
    binary: str
    evidence: Evidence
    result: ProcessResult | None = None

    def __call__(self, prompt_text: str, cwd: Path) -> str:
        self.evidence.write("prompt.txt", prompt_text)
        argv, _stdin = agent.build_command(self.provider, self.model, prompt_text, cwd, self.binary)
        shown = ["<PROMPT: prompt.txt>" if item == prompt_text else item for item in argv]
        self.evidence.write("provider-command.txt", shlex.join(shown) + "\n")
        self.result = agent.run_provider(self.provider, self.model, prompt_text, cwd, binary=self.binary)
        self.evidence.write("provider-stdout.txt", self.result.stdout)
        self.evidence.write("provider-stderr.txt", self.result.stderr)
        self.evidence.json("provider-process.json", asdict(self.result))
        if not self.result.ok:
            raise steps.StepError(f"provider failed with exit code {self.result.returncode}")
        return self.result.stdout


def acceptance_specification() -> specification.Specification:
    spec = specification.default_specification("ICODA provider acceptance")
    spec["summary"] = "A minimal project used to prove ICODA's complete real-provider architecture loop."
    spec["goals"] = ["Expose a placeholder answer through the application module."]
    spec["out_of_scope"] = ["Computing or returning the actual answer 42."]
    spec["done_when"] = ["The architecture contains an app::answer stub called by app::run."]
    spec["use_cases"] = [{"id": "UC-1", "title": "Request an answer",
                          "description": "The application route reaches the answer operation."}]
    spec["requirements"] = [{"id": "R-1", "title": "Answer boundary", "priority": "must",
                             "use_cases": ["UC-1"], "description": "Expose an integer answer operation."}]
    return spec


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceFailure(message)


def qualify(args: argparse.Namespace, evidence: Evidence) -> tuple[agent.Provider, str, str]:
    try:
        provider = agent.find_provider(agent.load_providers(), args.provider)
    except KeyError as exc:
        raise AcceptanceFailure(f"unknown provider: {args.provider}") from exc
    configured = replace(provider, command=args.binary) if args.binary else provider
    check = agent.check_provider(configured, Path.cwd())
    evidence.json("provider-qualification.json", asdict(check))
    require(provider.enabled and provider.verified, f"provider {provider.id} is not enabled and verified")
    require(check.installed and check.compatible, f"provider qualification failed: {check.detail}")
    return provider, args.binary or check.path, args.model or provider.default_model


def save_proposal(proposal: steps.Proposal, evidence: Evidence) -> None:
    evidence.write("proposal-reply.txt", proposal.reply)
    evidence.write("proposal-source.diff", proposal.source_diff + "\n")
    evidence.write("proposal-build.log", proposal.build.output)
    if proposal.delta is not None:
        evidence.write("proposal-delta.txt", proposal.delta.summary() + "\n")


def validate_proposal(proposal: steps.Proposal) -> None:
    require(proposal.ok, proposal.error or "provider returned an unusable proposal")
    assert proposal.delta is not None and proposal.model is not None
    added = list(proposal.delta.added)
    require(proposal.delta.architecture_entity_count() == 1, "proposal did not add exactly one architecture entity")
    require([entity.qualified_name for entity in added] == ["app::answer"], "new entity is not app::answer")
    parent = proposal.model.entities.get(added[0].parent or "")
    exported = added[0].exported or bool(parent and parent.kind == Kind.NAMESPACE and parent.exported)
    require(added[0].kind == Kind.FUNCTION and exported, "app::answer is not in the exported interface")
    require(set(added[0].satisfies) == {"UC-1", "R-1"}, "app::answer lacks its specification tags")
    require(proposal.delta.files == ("src/app/app.cppm",), "proposal changed files outside src/app/app.cppm")
    require(not proposal.delta.removed and not proposal.delta.modules, "proposal removed an entity or added a module")
    run = next((entity for entity in proposal.model.entities.values() if entity.qualified_name == "app::run"), None)
    require(bool(run and any(edge.kind == EdgeKind.CALLS and edge.source == run.usr and edge.target == added[0].usr
                             for edge in proposal.model.edges)), "the parsed call graph lacks app::run -> app::answer")
    assert proposal.response is not None
    files = [change for change in proposal.response.files if change.path == "src/app/app.cppm" and not change.delete]
    require(len(files) == 1 and "return {};" in files[0].content and "42" not in files[0].content,
            "app::answer is not a default-returning architecture stub")
    require(not proposal.response.questions, "provider returned unresolved questions")


def log_subjects(project: Path) -> list[str]:
    return git.run_git(["log", "--format=%s"], project).stdout.splitlines()


def prepare_project(project: Path, runner: steps.StepRunner, evidence: Evidence, report: dict[str, Any]) -> str:
    generator.write_skeleton(project, project.name)
    spec = acceptance_specification()
    require(not specification.validate(spec), "acceptance specification is invalid")
    specification.save(persistence.ProjectStore(project).specification_path, spec)
    started = monotonic()
    zero = runner.prepare()
    report["prepare_seconds"] = round(monotonic() - started, 3)
    require(zero is not None and bool(zero.commit), "step 0 was not created")
    require(git.is_clean(project), "step 0 left the project dirty")
    evidence.write("step-log.after-prepare.jsonl", runner.log.path.read_text(encoding="utf-8"))
    return (project / "src/app/app.cppm").read_text(encoding="utf-8")


def propose_and_approve(runner: steps.StepRunner, evidence: Evidence, report: dict[str, Any]) -> steps.StepRecord:
    started = monotonic()
    proposal = runner.propose(prompt.StepRequest(prompt.ARCHITECTURE, 0, REQUEST, max_entities=1))
    report["propose_seconds"] = round(monotonic() - started, 3)
    save_proposal(proposal, evidence)
    validate_proposal(proposal)
    started = monotonic()
    approved = runner.approve(proposal)
    report["approve_seconds"] = round(monotonic() - started, 3)
    require(bool(approved.commit and approved.tests_passed), "approval did not commit a passing build")
    require(git.is_clean(runner.root), "approval left the project dirty")
    evidence.write("step-log.after-approve.jsonl", runner.log.path.read_text(encoding="utf-8"))
    return approved


def undo_and_verify(runner: steps.StepRunner, baseline: str, evidence: Evidence,
                    report: dict[str, Any]) -> steps.StepRecord:
    started = monotonic()
    undone = runner.undo()
    report["undo_seconds"] = round(monotonic() - started, 3)
    source = (runner.root / "src/app/app.cppm").read_text(encoding="utf-8")
    require(source == baseline, "undo did not restore the original source exactly")
    build = steps.build_project(runner.root)
    evidence.write("post-undo-build.log", build.output)
    require(build.ok, "the project did not build and test after undo")
    restored = steps.analyse_tree(runner.root)
    require(all(entity.qualified_name != "app::answer" for entity in restored.entities.values()),
            "app::answer remained in the derived model after undo and re-analysis")
    require(git.is_clean(runner.root), "undo verification left the project dirty")
    evidence.write("step-log.after-undo.jsonl", runner.log.path.read_text(encoding="utf-8"))
    return undone


def execute(args: argparse.Namespace, evidence: Evidence, report: dict[str, Any]) -> None:
    provider, binary, model = qualify(args, evidence)
    report.update({"provider": provider.id, "binary": binary, "model": model})
    invoker = ProviderInvoker(provider, model, binary, evidence)
    project = evidence.root / "project"
    runner = steps.StepRunner(project, persistence.UserConfig(), provider.id, binary, model,
                              invoke=invoker, progress=evidence.progress)
    baseline = prepare_project(project, runner, evidence, report)
    approved = propose_and_approve(runner, evidence, report)
    undone = undo_and_verify(runner, baseline, evidence, report)
    records = steplog.StepLog(runner.store.steps_path).records()
    report.update({"approved_commit": approved.commit, "undo_commit": undone.commit,
                   "step_decisions_after_undo": [record.decision for record in records],
                   "git_log": log_subjects(project), "provider_seconds": invoker.result.duration if invoker.result else 0})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--provider", default="codex")
    parser.add_argument("--binary", default="")
    parser.add_argument("--model", default="gpt-5.6-sol")
    args = parser.parse_args(argv)
    evidence = Evidence(args.output.resolve())
    report: dict[str, Any] = {"passed": False, "request": REQUEST}
    try:
        execute(args, evidence, report)
        report["passed"] = True
    except Exception as exc:  # noqa: BLE001 - preserve every acceptance failure as evidence
        report.update({"error": str(exc), "traceback": traceback.format_exc()})
    evidence.json("result.json", report)
    print(f"{'PASS' if report['passed'] else 'FAIL'}: {evidence.root / 'result.json'}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
