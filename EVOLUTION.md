# AI-Loop Specification-Driven Development Evolution

**Mission**
You are working on AI-Loop itself. Starting from the current repository state, evolve AI-Loop from a text-goal autonomous coding loop into a system that additionally supports rigorous, user-controlled, specification-driven software development. Implement the complete workflow described below. Do not merely write a proposal. Inspect the existing architecture, implement each milestone, add tests, run the full suite, and leave every completed milestone integrated and usable before proceeding.

The existing Quick Goal workflow must remain available and behaviorally compatible. Formal Specification must be an additional workflow, explicitly selected by the user. A user must still be able to enter a short goal or load a text file and immediately start a normal job without completing forms or answering specification questions.

**Control Model**
- The user owns scope, requirements, architecture decisions, exclusions, and approval. AI-Loop may identify omissions and recommend options, but it must never silently make consequential choices or overwrite user-authored content.
- Manual effort should be progressive. A user may provide only an initial brief, provide a detailed design upfront, or edit every structured field manually. AI analysis should convert available information into a draft, identify gaps, and ask only questions whose answers materially affect implementation or verification.
- Never start formal implementation until the user has explicitly approved a particular immutable specification version. Saving a draft, running AI analysis, resolving choices, and approval must remain distinct actions.
- Preserve exact user-authored non-empty text during AI analysis. Suggestions may fill empty fields, append missing items, and propose choices. Any rewrite, removal, merge, or reinterpretation of existing material requires explicit user action.
- Keep all core concepts domain-neutral. Rendering, physics, game engines, job systems, databases, compilers, services, and GUI applications are examples, not schema concepts. Domain-specific verification must be expressed through generic commands, metrics, evidence, invariants, and adapters.
- Do not push, force-push, reset branches, delete user work, or rewrite history unless the surrounding job explicitly requests it. Do not modify unrelated behavior while introducing the formal workflow.
- Use the repository’s existing process, database, configuration, provider, GUI, controller, worker, artifact, and testing patterns. Add abstractions only where they create a clear ownership boundary.
- Keep an implementation-status document listing each milestone, its acceptance criteria, tests, completion state, and known limitations. Update it after every milestone so progress remains auditable.

**Baseline Audit**
Before editing, inspect `ai_loop_gui.py`, `controller.py`, `worker.py`, `ai_loop/db.py`, `ai_loop/jobs.py`, `ai_loop/artifacts.py`, `ai_loop/structured_output.py`, existing schemas, lifecycle services, process launch code, prompt construction, and tests. Record where job creation, controller decisions, worker prompts, task persistence, artifacts, model selection, GUI background work, and job completion are currently implemented.

Run the complete existing test suite before making changes and record its result. Treat that result as the regression baseline. If a baseline test already fails, document the failure and distinguish it from failures introduced by this work.

Do not replace the existing job lifecycle. Formal jobs should ultimately become ordinary managed jobs carrying additional pinned specification metadata and an execution manifest.

**Module Boundaries**
Create focused modules if equivalent modules do not already exist: `ai_loop/specifications.py` for models, validation, revisions, decisions, approval, and integrity checks; `ai_loop/specification_workflow.py` for frontend-neutral stage assessment and formal-job input derivation; `ai_loop/specification_gui.py` for the guided editor; `ai_loop/elicitation.py` for model-assisted analysis; `ai_loop/specification_compiler.py` for deterministic manifest generation; and `ai_loop/verification_orchestrator.py` for execution, evidence, retries, and completion gates.

Keep `ai_loop_gui.py` responsible for top-level integration and lifecycle actions rather than placing specification persistence or validation logic directly in Tk callbacks. Keep controller and worker files focused on prompt construction and state transitions rather than database-format details.

Use strict JSON schemas for portable artifacts and structured model output. Runtime validation must remain authoritative even when a provider claims to enforce a schema.

**Specification Model**
Define a versioned `SpecificationDocument` with `schema_version`, `title`, `summary`, `objectives`, `in_scope`, `out_of_scope`, `stakeholders`, `assumptions`, `constraints`, `dependencies`, `use_cases`, `requirements`, `decisions`, `risks`, `verification`, and `open_questions`.

Define `UseCase` with a stable ID, title, actors, preconditions, trigger, ordered main flow, alternate flows, postconditions, error and edge cases, and linked requirement IDs. Main behavior and failure behavior must both be required before approval.

Define `Requirement` with stable ID, category, priority, title, normative statement, rationale, measurable acceptance criteria, and source. Support functional, quality, interface, data, operational, and compliance categories. Priorities should include must, should, and could.

Define `SpecificationDecision` for choices already resolved by the user. Store topic, selected decision, rationale, rejected alternatives, and consequences. Do not confuse a materialized decision with an unresolved question.

Define `Risk` with stable ID, title, description, severity, uncertainty, failure modes, observable detection signals, mitigations, and linked verification IDs. Support low, medium, high, and critical severity and low, medium, and high uncertainty.

Define `ValidationLoop` with maximum correction attempts, repetitions per attempt, stagnation limit, escalation condition, and evidence-retention flag. All numeric bounds must be positive.

Define `MetricAssertion` with emitted metric name, operator, numeric threshold, and optional non-negative absolute tolerance. Support `<`, `<=`, `==`, `!=`, `>=`, and `>`. Reject missing names, unsupported operators, booleans, NaN, infinity, and duplicate assertions for the same metric within a case unless a future explicit range representation supports multiple bounds safely.

Define `VerificationCase` with stable ID, title, requirement IDs, test level, method, independent oracle, fixtures, ordered procedure, pass criteria, declared metrics, metric assertions, coverage targets, automation level, blocking flag, validation loop, optional command override, worktree-relative working directory, timeout, and required evidence declarations.

Support test levels such as static, unit, integration, system, acceptance, property, performance, security, and visual. Support deterministic, differential, metamorphic, statistical, snapshot, manual, and hybrid methods. These are generic classifications, not built-in domain engines.

Manual verification may be retained for documentation or non-blocking review, but a manual case must never block autonomous completion. A manual case must not contain an executable command or machine metric assertions.

**Serialization**
Create `specification.schema.json` using a strict supported JSON Schema version, `additionalProperties: false`, stable identifier patterns, explicit enums, required core fields, and reusable definitions. Keep tuple-like Python fields represented as JSON arrays.

Canonical serialization must be deterministic. Normalize numeric assertion values before hashing so equivalent integer and floating-point inputs do not produce unstable load/store hashes.

Store pretty JSON as a user-inspectable artifact and separately calculate a canonical content hash from sorted compact JSON. Store and verify both the canonical content hash and the artifact file hash.

If a schema evolves later, preserve old artifacts exactly. A document loaded from an older schema must serialize back to its original canonical representation unless explicitly upgraded. Never add default fields to old serialization in a way that invalidates stored hashes.

**Validation**
Implement structural validation separately from approval validation. Structural validation runs whenever a draft is stored and rejects malformed data while allowing incomplete work.

Structural validation must reject unsupported schema versions, malformed or duplicate IDs, invalid enums, non-positive loop bounds or timeouts, broken requirement and verification references, unsafe working directories, duplicate metric assertions, invalid numeric values, and incompatible manual automation settings.

Working directories must be non-empty, relative to the job worktree, and unable to escape through `..`, absolute POSIX paths, absolute Windows paths, symlink resolution, or equivalent traversal. The runtime must repeat containment validation before execution.

Approval validation must require title, summary, objectives, included and excluded scope, stakeholders, at least one complete use case, functional and quality requirements, measurable acceptance criteria, and verification coverage for every must requirement.

Approval must reject unresolved blocking decisions and unresolved open questions. A question may be converted into an explicit non-blocking deferred decision only when implementation can safely proceed without the answer.

Every use case must reference requirements. Every requirement that affects implementation must be covered by at least one verification case. Every blocking verification must be automated and define an oracle, procedure, pass criteria, coverage target, and bounded validation policy.

For high or critical severity or high uncertainty, require failure modes, detection signals, mitigations, linked verification, explicit metrics, multiple attempts or repetitions where appropriate, evidence retention, stagnation detection, and an escalation condition.

**Persistence**
Add database tables through additive idempotent migrations. Existing databases must open without manual migration and existing jobs must remain readable.

Store a specification identity separately from its versions. The specification record should include ID, repository path, current status, current version, title or display metadata, creation time, update time, and approval information.

Store immutable specification versions with specification ID, version number, schema version, canonical JSON, canonical content hash, artifact path, artifact hash, change summary, creator, creation time, and version-specific approval metadata. Use a composite uniqueness constraint for specification ID and version.

Store unresolved and resolved suggested choices in a dedicated decisions table with specification ID, source version, topic, question, context, options JSON, recommendation, blocking flag, status, selected option, rationale, and timestamps.

Store AI analyses with analysis ID, specification ID, source version, provider, model, status, prompt hash, validated result JSON, artifact path and hash, error, application metadata, and timestamps. Bind every analysis to the exact source version so it cannot be applied to a later modified draft.

Add nullable specification ID and version columns to jobs. Add requirement-ID and verification-ID arrays to tasks using the project’s established JSON-column pattern.

Provide a `SpecificationService` with methods for creating, listing, loading, revising, submitting for review, returning to draft, approving, superseding, resolving decisions, attaching approved versions to jobs, and verifying integrity. Service methods, not GUI code, must enforce state transitions and hashes.

Do not overwrite immutable version artifacts. A convenience `latest.json` may be updated atomically, but it must never replace versioned artifacts as the source of truth.

**GUI Workflow**
Add a `Formal Spec` action beside `Quick Job`. Keep Quick Goal behavior unchanged. The current repository path and optional Goal text should initialize the formal editor without forcing duplicated entry.

Create a resizable staged editor with Overview, Scope, Use Cases, Requirements, Risks, Verification, Choices, and Review tabs. Provide a selector for reopening existing specifications associated with the selected repository.

Overview should edit title, summary, objectives, and stakeholders. Scope should edit included scope, excluded scope, assumptions, constraints, and dependencies. Use Cases, Requirements, Risks, and Verification should use tables with Add, Edit, and Remove actions.

Use scrollable record dialogs for structured items. Use entries for short strings, multiline text controls for prose, one-item-per-line controls for lists, read-only comboboxes for enums, checkboxes for booleans, and spinboxes for positive integer bounds.

The verification editor must expose oracle, fixtures, procedure, pass criteria, metrics, metric assertions, coverage targets, automation, blocking status, command override, working directory, timeout, correction attempts, repetitions, stagnation limit, escalation condition, and evidence retention.

Keep common verification fields prominent and advanced execution and loop settings compact. Do not make users edit raw JSON. Metric assertions may use one compact expression per line in the form `name operator threshold [tolerance]`, with parser errors identifying the exact line.

Allow `Save Draft` at any time. Allow `Submit for Review` only for a stored draft. Allow `Approve` only when all validation and blocking-decision gates pass. Allow `Start Implementation` only for an approved immutable version.

The Review tab must list every issue with owning stage, path, severity, and actionable message. Mark tabs containing issues without changing layout dimensions or hiding information.

All AI calls must run off the Tk main thread. Update widgets through the GUI’s established thread-safe callback mechanism. Disable conflicting actions while analysis runs and restore them on success or failure.

**AI Elicitation**
Use the selected controller binary and model already configured in the GUI. Reuse the existing structured-output provider layer for Codex, Claude, and Gemini rather than adding provider-specific SDK dependencies.

Run repository analysis read-only. The prompt should inspect relevant manifests, architecture, public APIs, tests, instructions, build files, configuration, and existing behavior. It must not edit the repository during elicitation.

Ask the model to identify omitted normal flows, alternate flows, errors, edge cases, invalid input, cleanup, cancellation, retries, concurrency, ordering, resource ownership, persistence, compatibility, security, observability, performance, numerical stability, long-lived state, platform variation, and deployment constraints.

Ask it to identify behavior that may look correct in simple examples but fail under repetition, timing, boundary conditions, resource pressure, numerical drift, non-determinism, race conditions, unusual state transitions, or environmental variation.

Require one strict result containing a summary, a complete additive suggested specification, explicit decision proposals, and warnings. Embed the formal specification schema in the elicitation schema so no external schema resolution is required.

Every genuine tradeoff must become a suggested choice with topic, question, context, two to five options, each option’s description and tradeoffs, recommendation, and blocking flag. Do not permit the model to materialize its recommended choice directly into the specification.

Validate preservation before accepting results. Reject removal of existing list values or entities, modification of non-empty user-authored scalars, type changes, ID changes, broken references, and unauthorized new materialized decisions.

Store validated analyses as immutable artifacts. Present an exact JSON diff and a separate choice summary. Let the user select `Choices Only`, `Apply All`, or `Cancel`.

Applying results must create a new draft revision. It must fail if the source specification changed after analysis began. Record which analysis was applied, what was added, and how many decisions were created.

Allow one bounded structured-output repair request when provider output is invalid. Do not create an unbounded prompt-repair loop.

**Job Inputs**
Derive formal job inputs from an approved snapshot through frontend-neutral workflow code. The goal should identify the approved contract. Constraints must include exclusions, assumptions that constrain implementation, approved decisions, compatibility boundaries, and an instruction to treat the pinned specification as authoritative.

Acceptance should include requirement acceptance criteria and blocking verification pass criteria, but the full structured specification and execution manifest must also be supplied directly to controller and worker prompts. Do not flatten away traceability.

Creating a formal job must pin specification ID and version and record a specification content hash. Attaching a specification to an existing Quick Goal job must require an approved version and compile the same manifest as creating a formal job initially.

**Manifest Compiler**
Create a strict, versioned `verification_manifest.schema.json`. Compile an approved specification deterministically before the formal job is committed.

Create a work item for every requirement containing requirement ID, category, priority, title, statement, acceptance criteria, linked use-case IDs, linked risk IDs, and linked verification IDs.

Create a manifest verification entry containing verification ID, title, requirement IDs, risk IDs, test level, method, automation, blocking flag, command, command source, working directory, timeout, oracle, fixtures, procedure, pass criteria, metrics, metric assertions, coverage targets, required evidence, and validation loop.

An automated case with a non-empty specification command uses that command and records `command_source: specification`. Otherwise it uses the concrete resolved job test command and records `command_source: job_default`. A manual case uses no command and records `command_source: manual`.

Formal jobs must reject unresolved `auto` test commands if no concrete executable command can be derived. Quick Goal jobs may retain existing automatic command behavior.

Store the manifest canonically in SQLite and as `artifacts/jobs/<job-id>/specification/verification-manifest.json`, with independent canonical and artifact hashes. Treat it as immutable.

When an older formal job has an approved specification reference but no manifest, compile it lazily on first controller or worker access, initialize verification state, and record a backfill event. Do not create manifests for Quick Goal jobs.

**Task Traceability**
Extend the controller decision schema so `next_task` contains `requirement_ids` and `verification_ids`. For formal jobs, require at least one valid ID. For Quick Goal jobs, require both arrays to remain empty.

Validate controller output against the manifest after JSON parsing. Reject unknown IDs, duplicates, missing formal traceability, and Quick Goal tasks carrying formal IDs. Use the existing bounded decision-remake mechanism for invalid output.

Controller planning should group work by coherent requirement, architecture, dependency, and risk boundaries rather than by individual files. Each task must state which requirement or verification contract it advances.

Include the approved specification, execution manifest, current task IDs, and runtime verification summary in worker prompts. Tell workers to implement tests and instrumentation required by linked cases, not merely production code.

Strengthen the worker rule from “add tests when useful” to requiring the tests, fixtures, metrics, and evidence explicitly demanded by the linked formal verification cases. Keep the weaker existing behavior for Quick Goal jobs.

**Verification Realization**
Do not assume that a textual verification case corresponds to an existing test. Track whether each automated case has executable realization.

Before production behavior can be considered complete, ensure linked test targets, fixtures, independent references, instrumentation, and evidence emitters exist. When they are missing, the controller must create a focused verification-infrastructure task.

Where feasible, establish a failing baseline before implementing the feature. Do not require failure-first execution when the project cannot build yet or when doing so would be destructive, but record why it was skipped.

A realization check should confirm that the command can be resolved, its working directory exists inside the worktree, referenced fixtures exist or are generated deterministically, expected metrics can be emitted, and required evidence kinds have producers.

Do not mark a case realized merely because a broad test command exits successfully. Require traceable evidence that the command executed the intended case. Support a structured case marker such as `AI_LOOP_CASE={"verification_id":"VT1"}` or an equivalent adapter result.

Maintain separate concepts for unrealized, executable but failing, passing, stagnated, escalated, and manual-pending. Missing infrastructure should generate implementation work, not be misclassified as a product defect.

**Runtime Orchestration**
Select verification cases from explicit task verification IDs plus all cases linked to the task’s requirement IDs. Reject unknown references before running commands.

Use a runner interface accepting command, working directory, and timeout. Reuse existing process helpers where possible. Capture combined output, return code, elapsed time, timeout, launch exceptions, and termination details.

Run every declared repetition. A case attempt passes only when all required repetitions pass. A repetition passes only when the command exits successfully, required evidence is present, and every metric assertion passes.

Parse numeric metrics from `AI_LOOP_METRICS={"metrics":{"name":1.0}}` or a bare JSON line containing the same `metrics` object. Scan bounded output safely and use the last valid payload. Reject booleans, strings, NaN, infinity, and values that cannot be represented as finite floats.

Apply assertion tolerance consistently. Equality passes when absolute difference is at most tolerance. Inequality tolerance may provide the documented absolute grace around the threshold. Persist expected operator, threshold, tolerance, actual value, and pass result.

Treat a declared metric as required evidence. If metrics are declared but no valid metric object is emitted, fail even when the command returns zero. If an asserted key is missing, report that exact key.

Write retained output under `artifacts/jobs/<job-id>/verification/<verification-id>/attempt-NNNN/repetition-NNNN.log`. Do not overwrite previous evidence. Store path, size, media type, and SHA-256 metadata.

Persist every repetition with job, task, worker run, case, attempt, repetition, command context, status, return code, bounded database output, metrics, assertion results, evidence metadata, error, and timestamps.

Maintain aggregate case state with automation, blocking, status, attempts completed, latest attempt, consecutive failures, stagnation count, failure fingerprint, latest metrics, last error, last task, last worker run, finish time, and update time.

**Structured Evidence**
Add a domain-neutral evidence envelope, for example `AI_LOOP_EVIDENCE=<json>`, while retaining compatibility with the metric-only envelope.

Evidence items should include stable name, kind, relative path or inline structured value, media type, description, requirement IDs, verification ID, and optional comparison metadata. The orchestrator, not the command, computes trusted size and hashes.

Permit evidence kinds such as log, structured-data, intermediate-state, trace, image, snapshot, benchmark, coverage, reference-output, and comparison-result. These names describe evidence forms rather than application domains.

Artifact paths must resolve inside the worktree or a dedicated case output directory. Reject traversal, symlink escape, missing files, oversized artifacts beyond configured limits, unsupported inline data, and untrusted claimed hashes.

Store large or binary artifacts in the artifact store, not directly in SQLite. Store only bounded previews and metadata in the database.

Allow external adapters to evaluate domain-specific files and return generic metrics and pass/fail evidence. AI-Loop core must not implement image similarity, shader correctness, physics invariants, or benchmark statistics directly unless such a generic adapter already exists.

**Coverage Enforcement**
Replace purely descriptive coverage with named coverage targets that can optionally define measurement key, operator, threshold, tolerance, required scenarios, and evidence kind.

Support source-line, branch, interface, scenario, state-transition, requirement, fixture, invariant, and platform coverage through generic measurements. Do not impose one global percentage or assume source coverage proves behavioral correctness.

Require each machine-enforced target to map to emitted coverage evidence. Text-only targets remain visible but must be reported as descriptive rather than falsely reported as enforced.

For high-risk behavior, prefer several complementary targets: ordinary cases, boundaries, invalid input, recovery, repeated state transitions, and relevant concurrency or numerical dimensions.

**Correction Loops**
After a failed attempt, calculate a deterministic fingerprint from return code, failed assertion identities, normalized errors, selected metrics, and bounded output tail. Use it to detect repeated failure signatures.

Track metric history across attempts. Classify progress as improving, regressing, unchanged, oscillating, or non-deterministic when sufficient data exists. Do not reset stagnation merely because irrelevant log text changed.

A pass resets the consecutive-failure and stagnation series while retaining append-only history. A changed but still failing signature starts a new stagnation series only when the evidence indicates a meaningfully different failure.

When retries remain, give the controller the failed case, failed repetition, expected and actual values, evidence paths, recent metric trend, previous repair goals, and remaining attempt budget. The next task should diagnose or repair that specific failure.

Use stagnation and attempt limits as hard bounds. When a blocking case exhausts either policy, require `HUMAN_NEEDED` rather than generating another equivalent retry.

The escalation report must explain the requirement at risk, failed verification, observed behavior, attempted corrections, metric history, retained evidence, and the precise decision, resource, credential, hardware access, or domain judgment needed from the user.

**Completion Gate**
Create a structured verification summary for controller planning and review. Include case title, blocking flag, automation, status, attempts, limits, latest metrics, failed assertions, stagnation, errors, last task, last worker run, and evidence freshness.

Every blocking case must pass with evidence produced by the worker run currently under review. A pass from an older run is stale after later implementation changes.

When implementation is otherwise complete and blocking evidence is pending or stale, require one final verification-only task containing every blocking verification ID.

Reject controller `DONE` output unless the formal completion gate is ready. Use the same post-schema validator and bounded remake path used for other semantic decision errors.

If a blocking case is escalated, the completion gate must require `HUMAN_NEEDED`. Quick Goal jobs must not use this formal gate.

**Change Impact**
Keep approved versions immutable. A later draft or approved revision must not silently alter a running job.

When attaching a newer approved revision, compare requirements, decisions, risks, verification cases, commands, assertions, and coverage targets by stable ID. Report added, removed, and changed contracts.

Invalidate passing evidence for changed verification cases and requirements linked to changed implementation scope. Preserve unaffected evidence only when traceability proves it remains applicable.

Generate new or repair tasks only for affected work. Record the previous and new specification versions and the impact-analysis result as an artifact and event.

**Dashboard**
Add a formal verification view to the GUI showing each case’s ID, title, requirement links, blocking status, automation, realization state, runtime status, attempt count, repetitions, latest metrics, failed assertions, stagnation, and escalation.

Allow inspection of individual attempts and retained evidence. Open text previews safely and expose binary artifact paths and hashes without loading very large files into Tk controls.

Show whether each oracle, coverage target, and evidence requirement is descriptive, realized, or machine-enforced. Do not imply enforcement where only prose exists.

Do not provide a button that marks an automated case passed. Manual acknowledgements must be auditable, limited to non-blocking manual cases, and clearly distinct from automated evidence.

**Test Strategy**
Add unit tests for model parsing, strict unknown-field rejection, canonical serialization, numeric normalization, IDs, references, approval gates, path containment, assertion operators, tolerances, evidence parsing, coverage evaluation, failure fingerprints, metric trends, and state transitions.

Add migration tests starting from a representative legacy database. Verify new tables and columns appear, existing jobs remain readable, repeated initialization is idempotent, and no old data is rewritten unexpectedly.

Add integrity tests that tamper separately with specification JSON, canonical hashes, artifacts, manifest JSON, manifest hashes, and evidence files. Every mismatch must be detected before trusted use.

Add elicitation tests using fake provider output. Cover valid additive suggestions, malformed JSON, one repair attempt, removal attempts, rewritten text, unapproved decisions, stale source versions, broken traceability, and provider-independent validation.

Add compiler tests for bidirectional requirement-risk-test links, manual cases, command inheritance, command overrides, working directories, timeouts, assertions, required evidence, deterministic round trips, lazy manifest backfill, and Quick Goal isolation.

Add orchestrator tests with fake runners for success, non-zero exit, exception, timeout, missing output, malformed metrics, missing asserted keys, threshold failures, tolerance passes, repetitions, retained artifacts, failed artifact writes, stagnation, improvement, exhaustion, and reset after success.

Add completion tests for pending evidence, stale passes, fresh passes, final verification scheduling, premature `DONE`, escalated cases, and Quick Goal behavior.

Add GUI-independent tests for list parsing, metric-expression parsing, stage assessment, record conversion, issue routing, and formal-job derivation. Add lightweight GUI smoke coverage only where it is deterministic and does not require a physical display.

Add end-to-end tests using a temporary repository, fake structured-output provider, approved specification, compiled manifest, fake worker run, verification execution, controller review, and completion gate.

Keep tests deterministic. Do not use paid model calls, arbitrary sleeps, external internet access, or real user credentials. Use fake clocks, temporary directories, fake runners, fake providers, and controlled subprocesses.

**Milestones**
1. Formal foundation: models, strict schema, validation, immutable revisions, database migrations, artifact hashes, service API, and tests.
2. Guided workflow: staged GUI, draft lifecycle, review issue routing, approval, formal-job derivation, Quick Goal compatibility, and tests.
3. AI elicitation: provider-neutral structured analysis, additive preservation validation, choices, diff review, immutable analysis artifacts, and tests.
4. Manifest compilation: deterministic traceability, job pinning, task-ID schema, controller and worker prompt integration, persistence, lazy backfill, and tests.
5. Verification realization: infrastructure state, test and fixture realization tasks, case markers, missing-producer detection, and tests.
6. Runtime orchestration: selected cases, repetitions, commands, timeouts, metrics, assertions, append-only attempts, evidence retention, state aggregation, and tests.
7. Completion enforcement: fresh-run gate, final verification task, premature-DONE rejection, bounded escalation, and tests.
8. Structured execution contracts: per-case commands, directories, timeouts, metric bounds, portability, legacy serialization compatibility, and tests.
9. Evidence and coverage: structured artifacts, adapters, coverage measurements, enforcement status, security limits, and tests.
10. Adaptive correction: trend analysis, meaningful fingerprints, focused repair context, stagnation policy, escalation reports, and tests.
11. Dashboard: verification status, attempts, metrics, assertions, artifacts, realization, and escalation visibility.
12. Change management: specification diff, impact analysis, selective evidence invalidation, controlled job retargeting, and tests.

**Milestone Discipline**
Complete milestones in order unless repository architecture demonstrates a necessary dependency change. Before each milestone, inspect the relevant current code and tests. After each milestone, run focused tests, run the full suite, update the implementation-status document, inspect the diff for unrelated changes, and only then proceed.

Do not leave half-integrated schemas, unused tables, disconnected GUI buttons, unenforced metadata, or tests that validate only construction while runtime behavior remains absent.

If a later milestone requires changing an earlier artifact schema, implement explicit compatibility rather than rewriting stored history. Test round trips against artifacts produced by the earlier milestone.

If blocked, continue with independent safe work. Use `HUMAN_NEEDED` only when a concrete user decision or inaccessible external resource is genuinely required. Report the exact blocker and preserve a green repository.

**Acceptance**
The project is complete only when an existing user can still run Quick Goal unchanged; a formal user can create and revise a draft; AI can identify omissions without rewriting user input; the user can resolve choices and explicitly approve an immutable version; an approved version compiles into a hash-checked manifest; controller tasks are traceable; workers create required verification infrastructure; commands execute with bounded repetitions and safe paths; structured metrics, assertions, coverage, and artifacts are evaluated and retained; failed cases produce focused bounded correction loops; stale or missing evidence blocks completion; exhausted cases escalate clearly; formal status and evidence are inspectable in the GUI; specification revisions produce impact analysis; legacy data remains valid; and the complete deterministic test suite passes.

At final delivery, report completed milestones, architectural changes, schemas, migrations, GUI workflows, prompt changes, runtime behavior, evidence protocol, tests run, skipped tests, compatibility guarantees, known limitations, and genuinely remaining work. Do not call a milestone complete when its data is merely stored or shown but not enforced by the execution path.



