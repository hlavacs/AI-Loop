# Specification fields shared with ICODA

New AI-Loop drafts use the same authoring fields and meanings as ICODA. The first six tabs are:

| Tab | Fields and meaning |
| --- | --- |
| Overview | **Title** names the project. **Description** (`summary` in JSON) explains what it does and who uses it. |
| Scope | **Goals** lists desired outcomes. **Not in scope** lists deliberately excluded work. **Not allowed** prohibits libraries, techniques or features. **Done when** lists observable conditions for completion. Enter one item per line. |
| Use Cases | **Use case** describes a user activity; optional **Details** describes steps, results and special cases. New records receive IDs such as `UC-1`. |
| Requirements | **Requirement** is one testable statement. **Priority** is `must` (essential), `should` (important), or `could` (optional). **Use cases** links comma-separated IDs, such as `UC-1, UC-3`. Optional **Details** gives numbers, limits and formats. New IDs use `R-1`. |
| Decisions | **Decision** records a choice already made. Optional **Why** explains it. New IDs use `D-1`. |
| Code profile | Language, standard, modules, build, platforms, test framework and runner, test-file convention, source extension, naming styles, library policy, size limits and style rules. |

Code profile defaults match ICODA: C++23, C++20 modules, CMake/Ninja and doctest, or Python 3.12 and pytest. Changing Language updates settings that still have the previous language's defaults and preserves custom values. Example and demo source belongs in `examples/`; reusable library code stays in `src/`.

The two function-size settings have distinct meanings: **Max function lines** asks for larger functions to be split; **Hard max function lines** is a limit the implementation must not exceed. **Max methods per class** and **Max data members** identify oversized classes. Style rules and all other profile settings become instructions for the controller and worker.

AI-Loop also retains its **Risks**, **Verification**, **Choices**, and **Review** tabs. These support autonomous execution: every requirement needs verification coverage before approval, blocking checks still need their oracle, procedure, pass criteria and validation policy, and completion still requires runtime evidence. A checklist in Done when does not replace those checks. A verification case's command override takes precedence over the Code profile test runner, which takes precedence over the job's default test command.

**More fields** preserves the extended fields from older AI-Loop specifications, including stakeholders, actors, detailed flows, categories, sources, and decision consequences. New drafts do not require those older descriptive fields for approval. Requirement-to-use-case links are now edited on the requirement, as in ICODA.

## Loading, saving and existing projects

Use **Load JSON** to import an ICODA `.icoda/specification.json` (version 2) or an AI-Loop draft save file. **Save JSON** writes an AI-Loop envelope including its execution and verification data. AI-Loop uses schema version `1.1` for new drafts because it retains this additional data.

Existing version `1.0` revisions, approvals and hashes remain valid. Opening one presents an editable copy: objectives become Goals, existing statements and flows become Details, and requirement links are transferred. Historical text remains available in More fields. No language is inferred for an older project; choose its Code profile before saving an upgraded draft. An unchanged approved historical revision can still be started directly.

After a new revision is approved and adopted by an existing job, changes to goals, exclusions, prohibitions, completion conditions, use cases, decisions or the code profile cause affected work to be planned and verified again.

For a small C++ example, use `Score clamp` as the title, add the goal `Provide a reusable integer clamp function`, the use case `Clamp a score`, and requirement `Clamp to the supplied bounds`, linked to `UC-1`. Put `Keep in-range scores unchanged` in Details and `Boundary tests pass and the example prints the clamped score` in Done when. Select C++ in Code profile, implement reusable code in `src/` and its demonstration in `examples/`, and add an automated verification case covering `R-1` before approval.
