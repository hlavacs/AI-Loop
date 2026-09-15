# Narration

<!-- Spoken word count: 1559. At 2.28 words/second: 683.8 seconds raw + 24 × 0.5 seconds padding = 695.8 seconds projected. The allowed 1450–1600-word range projects to 636.0–701.8 seconds raw, plus the same 12.0 seconds padding. -->

## Slide 01 — 61 words

Hello, I am Helmut Hlavacs from the University of Vienna. This is ICODA, Interactive Code Development and Analysis. ICODA joins a written specification, graphical views of a codebase, and developer-controlled coding-agent proposals. The project advances through specification, architecture, and implementation. At every stage, the developer can inspect what is proposed, see measured evidence, and decide what becomes part of the repository.

## Slide 02 — 55 words

I am a professor in the Faculty of Computer Science at the University of Vienna. The university website is www dot univie dot ac dot at. My university email is helmut dot hlavacs at univie dot ac dot at. ICODA is open source in the AI-Loop repository on GitHub. The exact addresses are visible here.

## Slide 03 — 63 words

ICODA is for understanding and developing software when text files alone do not show the whole problem. It supports new projects and existing systems, especially when architecture, test coverage, public interfaces, and requirements matter. Instead of asking an agent for an opaque bulk rewrite, ICODA makes each proposed change a reviewable decision with scope, source differences, build output, test output, and durable history.

## Slide 04 — 63 words

The basic idea is to combine three inputs: written intent, the current source tree, and the developer's request. ICODA parses the repository into a derived model, then projects that model into file, call, class, mind-map, coverage, and issue views. A coding agent works on an isolated candidate. Only after ICODA builds and tests that candidate does the developer approve, reject, or adapt it.

## Slide 05 — 60 words

A useful mental model is two truths held side by side. The specification describes intent: goals, boundaries, requirements, prior decisions, and coding rules. The repository describes implementation: files, entities, relationships, tests, and change history. ICODA is the lens between them. It derives structure and exposes gaps, but it does not take ownership away from the developer. Consequential decisions remain explicit.

## Slide 06 — 68 words

Here is the operating loop. ICODA parses the project and stores a derived code model. The current phase selects what kind of proposal is legal. The configured agent prepares a candidate in a separate Git worktree. ICODA calculates the delta and runs build and test gates. The developer reviews all evidence, then approves, rejects with a reason, or adapts the proposal. Approved work is promoted, logged, and committed.

## Slide 07 — 64 words

The File View is the main spatial overview. In the large white area, clusters contain files, and files contain selectable code entities. Across the top are shared filtering, neighborhood, collapse, zoom, and view controls. On the right, Binary and Model choose the coding agent, while the tree names entities. The lower panel keeps phase, request, proposal evidence, and developer actions visible beside every diagram.

## Slide 08 — 65 words

The Call View replaces containment with behavior. Labeled nodes are functions or methods, and directed arrows show who calls whom. Depth and fit controls keep a large call graph readable, while expandable hierarchy provides context around the selected code. The entity tree on the right identifies the current selection. The lower workflow panel remains unchanged, so exploration and proposal review stay in one operational window.

## Slide 09 — 64 words

The Class View focuses on data types. Class and structure boxes list methods and signatures, while connections express inheritance and type relationships. The legend distinguishes implementation states, and the toolbar supports zooming, panning, and fitting the graph. Selecting a box synchronizes the entity context on the right. Below it, the same phase controls and evidence tabs connect structural understanding directly to the next decision.

## Slide 10 — 67 words

The Mind Map gives a navigable outline of the project. The expanded branch here moves from project to cluster, then file, then individual entity. Branch controls reveal detail only where it is useful, and historical steps can also be selected from this map. The contextual entity list stays on the right, while the proposal panel below shows that this view is part of the same development session.

## Slide 11 — 63 words

The Coverage view connects specification and verification. Its summary reports covered and uncovered callable entities. The rows show which requirement is served, which entity implements it, and which recorded tests can reach that entity. This is more informative than a percentage alone: it ties intended behavior to source and evidence. The selected item can open its source, while workflow controls remain available below.

## Slide 12 — 65 words

The Issues view turns architectural and coding rules into an actionable table. Each row has a severity, rule, affected entity, suggested action, and source location. The summary counts errors and warnings, and selecting or opening a row leads back to the relevant code. The right side preserves entity context. The lower panel stays visible, so a discovered issue can inform the next bounded agent request.

## Slide 13 — 53 words

Start a project with File, New Project, and enter slash tmp slash icoda dash demo slash formatter. ICODA creates that directory and its dot icoda state. The phase becomes specification, and the specification editor opens. Those are the immediate outputs from the first two inputs; no source proposal or code model exists yet.

## Slide 14 — 68 words

Before entering the specification, let us deliberately try to request code. The screenshot still shows a sparse project, the provider selectors, and phase controls. The lower panel reports that the project is in the specification phase and refuses the proposal. The detail says to save the specification before proposing, and the status line repeats the reason. No source, history, or persisted project state changes after this refused input.

## Slide 15 — 93 words

The editor collects all project input. Enter title and description. Scope holds goals, exclusions, constraints, and done conditions. Add use cases, prioritized requirements with links, decisions with rationale, and a Python code profile covering pytest, naming, and size rules. Press Save, confirm Build now, set the Test Command to python dash m pytest dash q, choose Codex under Binary, and keep the default Model. ICODA writes the specification and step zero, creates and builds the skeleton, analyses it, fills every view, and enters architecture. The inset shows its tabs, diagram, tree, and workflow.

## Slide 16 — 61 words

Leave Request blank so the agent chooses, and keep Max entities at five. Click Propose. Draft formatter architecture contains Formatter, normalize, and main. The panel shows rationale, delta, diff, prompt, reply, and passing build and test gates. Inspect every tab, click Reject, and enter Keep the public API smaller. The candidate is discarded, but its feedback remains for the next request.

## Slide 17 — 66 words

Click Propose again. The agent now returns Add formatter architecture, adapted using the rejection reason. The screenshot shows the new proposal title, highlighted entity delta, structured summary, and the same passing build and test evidence. After comparing the smaller public surface with the specification, click Approve. ICODA promotes the candidate source into the project, records the decision, creates a Git commit, and refreshes its derived model.

## Slide 18 — 66 words

The refreshed File View shows the approved architecture, while the proposal area is empty because that candidate has been decided. The only phase gate is Approve architecture. Clicking it closes architectural design and derives an implementation queue with Formatter dot normalize first and main second. The phase changes to implementation, the queue becomes active, and controls for batch size, scope, grouping, and automatic approval become available.

## Slide 19 — 66 words

For the first target, keep batch size one, queue order, one-entity grouping, and automatic approval off. The queue names service dot Formatter dot normalize with two targets remaining. Click Propose approach. ICODA asks only for prose, not code. The Approach tab says to replace the normalize stub directly and add one focused test, and lists the expected entity and files. Review it, then click Approve approach.

## Slide 20 — 70 words

Now click Propose to request code for the approved approach. ICODA shows Implement Formatter dot normalize. The delta adds return value dot strip and a focused test in tests slash test service dot py. The build tab reports the Python syntax gate passed, and Tests reports python dash m pytest dash q passed. After checking Diff, Delta, Prompt, and Reply, click Approve. The commit is recorded and normalize becomes tested.

## Slide 21 — 67 words

The queue advances without another hidden choice. Its next visible target is service dot main, with one remaining. Click Propose approach again. In the Mind Map above, the source hierarchy provides context; below, the Approach tab proposes completing main through Formatter and adding an observable result test. The expected entity and files match the target. Keep the same queue settings, inspect the prose, and click Approve approach.

## Slide 22 — 66 words

Click Propose for the final code candidate. The Issues view remains visible while the lower panel shows Implement main. In the source diff, main returns ready colon followed by the normalized value, and test main expects ready colon item. Both build and test indicators pass. Inspect the diff and evidence, then click Approve. ICODA promotes and commits the source, refreshes analysis, and marks main as tested.

## Slide 23 — 66 words

This is the terminal output of the walkthrough. Coverage now links both implemented callables to tests slash test service dot py, and both appear tested. The right-side tree still provides entity context. Below, the implementation queue explicitly says empty, no proposal remains, and proposal actions are disabled. Approved decisions are preserved in history, the working tree is clean, and every expected agent reply has been consumed.

## Slide 24 — 59 words

ICODA keeps intent, code structure, evidence, and developer decisions together. Specify the system, inspect derived architecture and verification, and approve only trusted changes. Find ICODA in the AI-Loop repository shown here. My university email and page at entertain dot univie dot ac dot at slash tilde hlavacs are shown. Robimo dot at is an AI-tooling service provider. Thank you.
