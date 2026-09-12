# ICODA introduction video script

Target length: 10–12 minutes at approximately 140 spoken words per minute. Word counts include narration only and use whitespace-delimited words. A later production task must generate every narration segment with the ElevenLabs voice `Helmut Lecture 2` through the configured OAuth connector, never through the REST API.

Pronunciation direction: the displayed family name remains `Hlavacs`. In narration it is written phonetically as `Lawatsch`; voice it with a soft, slightly sloppy Viennese L at the front.

## s01 — ICODA

Slide ID: `s01_title`

Narration:

Hello, I am Helmut Lawatsch. My family name is written Hlavacs and pronounced Lawatsch, with a soft, slightly sloppy Viennese L at the front. I am from the University of Vienna. Welcome to ICODA: Interactive Code Development and Analysis. This introduction shows why it exists, how its visual model works, and how you develop one checked step at a time.

Visual description: Title, `Helmut Hlavacs`, `University of Vienna`, `https://entertain.univie.ac.at/~hlavacs/`, and a single specification-to-code loop.

## s02 — About the presenter

Slide ID: `s02_presenter`

Narration:

I am a professor at the Faculty of Computer Science and lead the University of Vienna research group for Education, Didactics and Entertainment Computing. The university website is W W W dot univie dot A C dot at. My email is helmut dot Lawatsch at univie dot A C dot at. ICODA is open source at github dot com slash hlavacs slash A I dash Loop, in the icoda directory. The exact addresses are on screen.

Visual description: A restrained contact card with affiliation, university website, university email, GitHub repository, and personal web page.

## s03 — What ICODA is for

Slide ID: `s03_purpose`

Narration:

ICODA is for software work where architecture and review matter as much as speed. A coding chat can change many files before you understand the structural consequences. ICODA keeps the developer in the loop. It can start a specified project, extend an existing one, explain unfamiliar code, and implement small units whose source, structure, build, and tests remain inspectable.

Visual description: A simple comparison between an opaque large change and several small, visible, approved steps.

## s04 — The basic idea

Slide ID: `s04_basic_idea`

Narration:

The basic idea has two truths. The specification says what the system should do; source code says what exists. ICODA derives diagrams from source instead of maintaining a separate architecture document. For each step, an L L M changes an isolated worktree. ICODA builds, tests, parses, and compares the candidate. Only then does the developer approve, reject, adapt, or edit it.

Visual description: Specification and source as two anchors feeding a derived model and a checked proposal loop.

## s05 — The mental model

Slide ID: `s05_mental_model`

Narration:

Think of ICODA as a workbench with a live map of files, classes, functions, calls, requirements, and test evidence. The workbench holds one candidate outside the real project. The L L M proposes; ICODA measures; the developer decides. Because the map is rebuilt from code, manual edits remain legitimate. Because proposals are isolated, examining one does not silently change the project.

Visual description: One central workbench, a live map above it, and three roles labelled propose, measure, decide.

## s06 — How it works

Slide ID: `s06_workflow`

Narration:

Work moves through three phases. A lean specification records goals, boundaries, behavior, requirements, decisions, and conventions. Architecture steps add a small structural skeleton. Implementation fills stubs bottom-up, so callees come before callers. Each accepted step becomes one Git commit. Build and test gates stay separate, and an API signature change requires explicit confirmation.

Visual description: A three-phase path from specification to architecture to implementation, with review and Git commit gates.

## s07 — GUI overview

Slide ID: `s07_gui_overview`

Narration:

This is the main ICODA window. The left side contains six analysis views. The upper right selects the command-line L L M and lists selected entities. The lower strip controls the phase and next request. At the bottom, the review panel shows an approach or proposal with build and test state. One window connects understanding, generation, evidence, and decision.

Visual description: Full-window screenshot with three small margin callouts for views, provider, and proposal review.

## s08 — File View

Slide ID: `s08_file_view`

Narration:

File View organizes sources into dependency clusters. The hierarchy moves from clusters through files and classes down to functions. Relations tell you which file uses another. Filters and neighborhood controls reduce a large project to the relevant part. This Python example is deliberately small, so the hierarchy and selected entities are easy to recognize without reading every control.

Visual description: Existing Python File View capture, fully contained, with emphasis on the view tabs and hierarchy.

## s09 — Call View

Slide ID: `s09_call_view`

Narration:

Call View answers: which function calls which? Choose a root and depth, then switch between callees and callers. Here, dispatch has one fixed target and one uncertain dynamic target. The dashed arrow and question mark preserve uncertainty instead of pretending runtime dispatch is known. Status colors distinguish stubs, implemented functions, and functions with recorded test evidence.

Visual description: Existing Call View capture with one fixed and one uncertain dynamic edge.

## s10 — Class View

Slide ID: `s10_class_view`

Narration:

Class View presents classes and structs with fields, methods, signatures, and status. Relations represent inheritance, composition, aggregation, or type use. Here the Python Store class has one load method. The same view works for C plus plus. It reviews an interface structurally without turning the slide into a source listing.

Visual description: Existing Python Class View capture, showing the Store class and its load signature.

## s11 — Mind Map

Slide ID: `s11_mind_map`

Narration:

The Mind Map is the persistent overview as the system grows. Clusters expand into files, classes, and functions. Nodes carry status, requirement identifiers, and the introducing step. Selecting historical work loads its evidence below. The project becomes easier to revisit because structure, purpose, and history remain connected instead of scattered across prompts and commits.

Visual description: Existing Mind Map capture with the source cluster expanded to `main`.

## s12 — Coverage

Slide ID: `s12_coverage`

Narration:

Coverage separates two often-confused facts. Specification coverage asks whether code has exact `at satisfies` links to goals and requirements. Test coverage asks whether successful recorded tests reach a callable through the call graph. The screen shows both independently. A green suite does not claim every requirement is represented, and a requirement tag does not prove behavior was executed.

Visual description: Existing Coverage view capture with specification coverage above and callable test coverage below.

## s13 — Issues

Slide ID: `s13_issues`

Narration:

Issues turns the Code Profile and model into a review queue. It flags large functions, too many parameters, missing documentation or requirement links, direct platform calls, and absent test evidence. Most findings are advisory. Double-clicking a row opens its source location, turning a graphical observation into a focused repair task.

Visual description: Existing Issues capture with errors and warnings linked to entities and source locations.

## s14 — Choose an LLM

Slide ID: `s14_provider_selection`

Narration:

The compact L L M panel separates command-line binary from model. Here Codex CLI is selected. Another locally qualified provider can be chosen before a step. ICODA sends a bounded prompt with the specification, Code Profile, relevant model neighborhood, and earlier feedback. The provider proposes content, but ICODA computes the resulting delta and gate results itself.

Visual description: Existing provider-selection capture with the Binary and Model fields emphasized.

## s15 — An architecture step

Slide ID: `s15_architecture_step`

Narration:

During architecture, a maximum entity count limits the requested change. The provider adds declarations and stubs in the isolated worktree. ICODA builds, tests, reparses, and compares the candidate with the current model. A proposal appears with its measured delta and gate state. The goal is to grow an understandable skeleton step by step, not design everything at once.

Visual description: A simple architecture-step diagram with request, bounded candidate, measured delta, and decision.

## s16 — Review the evidence

Slide ID: `s16_proposal_evidence`

Narration:

The review panel keeps evidence separate. Rationale explains intent. Delta lists entities added, changed, removed, or renamed. Entity summary captures structured intent. Source diff shows the exact patch. Build and Tests contain their own output. This screenshot is on Source diff. The key point is that candidate code, not the provider's description, is authoritative.

Visual description: Existing proposal Source diff capture, fully visible with the review tabs and passing gate summary.

## s17 — The developer decides

Slide ID: `s17_developer_decision`

Narration:

Approval promotes the candidate, repeats checks in the project, records the step, and commits. Rejection records a reason for another attempt. Adaptation revises the request, structured summary, or candidate code. Signature changes receive a dedicated tab and confirmation. Undo creates a Git revert. These controls make human authority explicit in the workflow.

Visual description: Existing signature-confirmation capture with the decision buttons and dedicated signature gate visible.

## s18 — Quick job: add the shape

Slide ID: `s18_quick_architecture`

Narration:

Here is a quick ICODA job using the deterministic Python example. We ask for a tiny formatting service. The architecture proposal adds a Formatter class and normalize method without behavior. The call graph highlights the proposed structure in green, Delta reports three added entities, and both gates pass. We can now review and approve this small shape.

Visual description: Existing architecture proposal capture for `service.Formatter.normalize`, with Delta selected.

## s19 — Quick job: approve the approach

Slide ID: `s19_quick_approach`

Narration:

After architecture approval, implementation uses two rounds. First, the provider proposes prose only. For normalize, it keeps the signature, uses a standard-library operation, and adds a focused test. Expected entities and files are listed, but source has not changed. This is the cheap moment to reject or adapt the direction before generating a patch.

Visual description: Existing implementation Approach capture with the prose plan awaiting developer approval.

## s20 — Quick job: code and tests

Slide ID: `s20_quick_result`

Narration:

The second round produces code and a focused test in the worktree. Here, one method changes, a test is added, and both gates pass. The class node exposes the signature while Delta summarizes the measured effect. Approval reruns checks in the project and commits only this step. That completes the quick job with reviewable evidence.

Visual description: Existing normalize implementation capture with changed code, new test, Delta, and passing gates.

## s21 — Specification overview

Slide ID: `s21_spec_overview`

Narration:

For new or risky work, the specification is the stable contract. Overview starts with a title and a description of product, audience, and outcome. The six-page editor validates its JSON structure before saving. It is deliberately lean: enough information to constrain later proposals, but not a large document that immediately becomes stale.

Visual description: Existing Specification Overview capture, fully contained with all six page tabs visible.

## s22 — Scope and completion

Slide ID: `s22_spec_scope`

Narration:

Scope records goals, exclusions, forbidden choices, and observable completion conditions. Exclusions matter because a model may otherwise add attractive but unwanted features. A useful done condition names behavior and verification, not merely that code exists. This page gives later steps boundaries that survive beyond one prompt and remain reviewable.

Visual description: Existing Specification Scope capture emphasizing goals, exclusions, forbidden choices, and done conditions.

## s23 — Use cases and requirements

Slide ID: `s23_spec_requirements`

Narration:

Use cases describe behavior, including normal paths, boundaries, failure, and recovery. Requirements receive stable identifiers such as R one, a priority, use-case links, and measurable details. Here a must-level scheduling requirement links to U C one. Those identifiers can appear in source documentation, letting Coverage connect specifications to implementing entities without unreliable text similarity.

Visual description: Existing Requirements page capture with the stable ID, priority, use-case link, and measurable details visible.

## s24 — Decisions and Code Profile

Slide ID: `s24_spec_code_profile`

Narration:

Decisions preserve choices that should not be reopened, with their rationale. The Code Profile makes conventions explicit: language and standard, platforms, build and test tools, file patterns, naming, library policy, and size limits. These fields feed later prompts and rule checks. The screenshot shows a C plus plus profile; Python projects use Python-specific conventions.

Visual description: Existing Code Profile capture with language, build, test, naming, and library conventions.

## s25 — Code analysis

Slide ID: `s25_code_analysis`

Narration:

ICODA analyses C plus plus with libclang and current compile commands, so overloads, member calls, templates, types, and locations come from the compiler's model. Python uses the standard A S T parser without importing or executing the project. Analysis is incremental and cached. After a step or external edit, changed sources are reparsed. If C plus plus stops compiling, the last model remains visible but stale. This filtered graph turns derived facts into a navigable view rather than a wall of diagnostics.

Visual description: Existing filtered-diagram capture showing a narrowed derived graph and retained surrounding context.

## s26 — Direct LLM or checked workflow

Slide ID: `s26_llm_choices`

Narration:

For a tiny edit, asking an L L M directly may be fastest. Use ICODA for specifications, architectural visibility, isolated proposals, repeatable gates, and explicit approval. A repair path sits between them: open the proposal worktree, ask an external L L M to diagnose or fix it, then press Rebuild. ICODA reparses the files and recomputes delta, build, and tests before approval. The external model helps without bypassing evidence.

Visual description: Three simple paths: direct request, ICODA checked loop, and external repair returning through Rebuild.

## s27 — Closing

Slide ID: `s27_closing`

Narration:

ICODA combines specification, analysis, graphical architecture, L L M proposals, Git isolation, and developer decisions in one workflow. The repository and my contact details are shown again, with my page at entertain dot univie dot A C dot at slash tilde hlavacs. For professional support, Robimo dot at is a service provider specialized in A I tooling. Thank you for watching.

Visual description: Closing contact card with GitHub, university email, personal page, and `Robimo.at — specialized in AI tooling`.

## Topic-to-slide map

| Required topic | Slide IDs |
|---|---|
| Introduction and title identity | `s01_title` |
| Presenter, university affiliation, university website, email, repository | `s02_presenter` |
| What ICODA is for | `s03_purpose` |
| Basic idea | `s04_basic_idea` |
| Mental model | `s05_mental_model` |
| How it works | `s06_workflow`, `s15_architecture_step`, `s16_proposal_evidence`, `s17_developer_decision` |
| GUI walkthrough with screenshots | `s07_gui_overview` through `s14_provider_selection`, plus `s16_proposal_evidence` through `s25_code_analysis` |
| Simple quick job | `s18_quick_architecture` through `s20_quick_result` |
| Specification details | `s21_spec_overview` through `s24_spec_code_profile` |
| Code analysis | `s25_code_analysis` |
| Direct LLM and external LLM fixing | `s26_llm_choices` |
| Personal page and Robimo.at closing | `s27_closing` |

## Running-time table

Timing is estimated from narration word counts at 140 words per minute. Segment and cumulative times are rounded to the nearest second; the final total uses the exact unrounded sum.

| Slide ID | Words | Segment estimate | Cumulative estimate |
|---|---:|---:|---:|
| `s01_title` | 60 | 0:26 | 0:26 |
| `s02_presenter` | 76 | 0:33 | 0:58 |
| `s03_purpose` | 59 | 0:25 | 1:24 |
| `s04_basic_idea` | 61 | 0:26 | 1:50 |
| `s05_mental_model` | 61 | 0:26 | 2:16 |
| `s06_workflow` | 53 | 0:23 | 2:39 |
| `s07_gui_overview` | 59 | 0:25 | 3:04 |
| `s08_file_view` | 58 | 0:25 | 3:29 |
| `s09_call_view` | 56 | 0:24 | 3:53 |
| `s10_class_view` | 50 | 0:21 | 4:14 |
| `s11_mind_map` | 54 | 0:23 | 4:37 |
| `s12_coverage` | 58 | 0:25 | 5:02 |
| `s13_issues` | 50 | 0:21 | 5:24 |
| `s14_provider_selection` | 56 | 0:24 | 5:48 |
| `s15_architecture_step` | 58 | 0:25 | 6:12 |
| `s16_proposal_evidence` | 54 | 0:23 | 6:36 |
| `s17_developer_decision` | 52 | 0:22 | 6:58 |
| `s18_quick_architecture` | 57 | 0:24 | 7:22 |
| `s19_quick_approach` | 54 | 0:23 | 7:45 |
| `s20_quick_result` | 55 | 0:24 | 8:09 |
| `s21_spec_overview` | 52 | 0:22 | 8:31 |
| `s22_spec_scope` | 49 | 0:21 | 8:52 |
| `s23_spec_requirements` | 54 | 0:23 | 9:15 |
| `s24_spec_code_profile` | 54 | 0:23 | 9:39 |
| `s25_code_analysis` | 82 | 0:35 | 10:14 |
| `s26_llm_choices` | 69 | 0:30 | 10:43 |
| `s27_closing` | 61 | 0:26 | 11:09 |
| **Total** | **1,562** | **11:09** | **11:09** |
