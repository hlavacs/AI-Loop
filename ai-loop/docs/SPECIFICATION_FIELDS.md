# Specification fields shared with ICODA

AI-Loop's **Specification** area uses ICODA's fields, controls and entry workflow across all six tabs:

| Tab | Fields and meaning |
| --- | --- |
| Overview | **Title** names the project. **Description** (`summary` in JSON) explains what it does and who uses it. |
| Scope | **Goals** lists desired outcomes. **Not in scope** lists deliberately excluded work. **Not allowed** prohibits libraries, techniques or features. **Done when** lists observable conditions for completion. Enter one item per line. |
| Use cases | **Use case** describes a user activity; optional **Details** describes steps, results and special cases. New records receive IDs such as `UC-1`. |
| Requirements | **Requirement** is one testable statement. **Priority** is `must` (essential), `should` (important), or `could` (optional). **Use cases** links comma- or semicolon-separated IDs, such as `UC-1, UC-3`. Optional **Details** gives numbers, limits and formats. New IDs use `R-1`. |
| Decisions | **Decision** records a choice already made. Optional **Why** explains it. New IDs use `D-1`. |
| Code profile | Language, standard, modules, platforms, test framework and runner, test-file convention, source extension, naming styles, library policy, size limits and style rules. |

In **Use cases**, **Requirements** and **Decisions**, type directly into the form beside the list, then press **Add** or Return in its first field. The record receives an ID and the form clears for the next entry. A blank title leaves the form open with an inline hint. Click a row to edit it; those edits are retained when selecting another row, choosing **New**, saving or validating. **Add** while editing an existing row saves its edits and starts a new entry. **Remove** deletes the selected row. New requirements start with priority `must`.

Hover over a field or its label for the same explanation and example as ICODA. Description and Details support multiline text and undo. Select target platforms using the **macOS**, **Linux** and **Windows** checkboxes.

New drafts start with ICODA's C++23 profile, C++20 modules, CMake/Ninja and doctest. Imported Python profiles retain their Python settings. As in ICODA, changing **Language** leaves the other inputs unchanged; edit the standard, test tools and file conventions for the chosen language. The saved `build` setting is preserved but not displayed. Example and demo source belongs in `examples/`; reusable library code stays in `src/`.

The two function-size settings have distinct meanings: **Max function lines** asks for larger functions to be split; **Hard max function lines** is a limit the implementation must not exceed. **Max methods per class** and **Max data members** identify oversized classes. Style rules and all other profile settings become instructions for the controller and worker.

The separate **Execution & review** area contains AI-Loop's **Risks**, **Verification**, **Choices**, and **Review** tabs, plus the analysis, submission, approval and implementation controls. These support autonomous execution: every requirement needs verification coverage before approval, blocking checks still need their oracle, procedure, pass criteria and validation policy, and completion still requires runtime evidence. A checklist in Done when does not replace those checks. A verification case's command override takes precedence over the Code profile test runner, which takes precedence over the job's default test command.

**Execution & review → Legacy fields** preserves the extended fields from older AI-Loop specifications, including stakeholders, actors, detailed flows, categories, sources, and decision consequences. Select a use case, requirement or decision in its authoring tab, then use the corresponding details button in Legacy fields to edit that record's extended fields. New drafts do not require those older descriptive fields for approval. Requirement-to-use-case links are edited on the requirement, as in ICODA.

## Loading, saving and existing projects

**Validate** checks the current data, displays problems inline and opens the first affected tab. **Save** (Ctrl+S, or ⌘S on macOS) validates and stores a draft revision without changing the selected record. Changes to a specification under review or already approved create a draft that needs approval again. Merely saving unchanged content under review leaves it in review.

Use **Add** before saving a new record: text in a fresh record form is not yet part of the specification. **Reread specification** reloads the latest stored revision or the JSON file last loaded or exported, asking before discarding unsaved edits, including text not yet added. After **Save**, rereading follows the saved project revision. **Close** (Ctrl+W, or ⌘W on macOS) offers to save unsaved edits; a validation failure keeps the editor open.

Use **Load JSON** to import an ICODA `.icoda/specification.json` (version 2) or an AI-Loop draft save file. **Save JSON** writes an AI-Loop envelope including its execution and verification data. AI-Loop uses schema version `1.1` for new drafts because it retains this additional data.

Existing version `1.0` revisions, approvals and hashes remain valid. Opening one presents an editable copy: objectives become Goals, existing statements and flows become Details, and requirement links are transferred. Historical text remains available in Legacy fields. No language is inferred for an older project; choose its Code profile before saving an upgraded draft. An unchanged approved historical revision can still be started directly.

After a new revision is approved and adopted by an existing job, changes to goals, exclusions, prohibitions, completion conditions, use cases, decisions or the code profile cause affected work to be planned and verified again.

For a small C++ example, use `Score clamp` as the title, add the goal `Provide a reusable integer clamp function`, the use case `Clamp a score`, and requirement `Clamp to the supplied bounds`, linked to `UC-1`. Put `Keep in-range scores unchanged` in Details and `Boundary tests pass and the example prints the clamped score` in Done when. Select C++ in Code profile, implement reusable code in `src/` and its demonstration in `examples/`, and add an automated verification case covering `R-1` before approval.
