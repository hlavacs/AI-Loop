# Narration

<!-- Spoken word count: 1492. -->
<!-- The title slide displays https://entertain.univie.ac.at/~hlavacs/ as Helmut Hlavacs's personal page; the URL is not spoken. -->

## Slide 01 — 68 words

Hello, I am Helmut Hlavacs from the University of Vienna. This is ICODA, Interactive Code Development and Analysis. My university affiliation and personal page are shown on this title slide. ICODA joins a written specification, graphical views of a codebase, and developer-controlled coding-agent proposals. A project advances through specification, architecture, and implementation. At every stage, the developer inspects the evidence and decides what becomes part of the repository.

## Slide 02 — 61 words

I am a professor in the Faculty of Computer Science at the University of Vienna, where I lead the research group for Education, Didactics and Entertainment Computing. ICODA is open source in the AI-Loop repository on GitHub. My university website, university email address, personal page, and the project repository are listed here, so you can open them directly from the description.

## Slide 03 — 69 words

ICODA is for understanding and developing software when text files alone do not show the whole problem. It supports new projects and existing systems, especially when architecture, public interfaces, tests, and requirements matter. Instead of asking an agent for an opaque bulk rewrite, ICODA makes each proposed change a reviewable decision, with bounded scope, source differences, build output, test output, and a durable history of accepted and rejected steps.

## Slide 04 — 63 words

The basic idea combines written intent, the source tree, and the developer's request. ICODA parses the repository into a derived model, projected into File, Call, Class, Mind Map, Coverage, and Issues views. Sandboxed provider subprocesses cannot edit the checkout, and symlink escapes are refused. Validated candidates are applied in an isolated Git worktree, built and tested, then promoted only after explicit developer approval.

## Slide 05 — 54 words

A useful mental model holds two truths together. The specification describes intent: goals, boundaries, requirements, decisions, and coding rules. The repository describes implementation: files, entities, relationships, tests, and history. ICODA connects them by deriving structure and exposing discrepancies. It neither proves the specification complete nor takes ownership from the developer. Consequential decisions remain explicit.

## Slide 06 — 73 words

Prepare a Python environment using the versions pinned in constraints.txt. The launchers validate Python, Tkinter, required tools, and that prepared environment; they never install or upgrade packages. The loop parses the project, stores a derived model, selects the legal phase and target, and asks the agent for a candidate. It calculates the delta, builds, and tests. The developer approves, rejects with a reason, or adapts. Only approved work is promoted, logged, and committed.

## Slide 07 — 66 words

The File View is the main spatial overview. In the large white area, clusters contain files, and files contain selectable code entities. Across the top are shared filtering, neighborhood, collapse, zoom, and view controls. On the right, Binary and Model select the coding agent, while the tree identifies entities. The lower panel keeps the phase, request, proposal evidence, and developer actions visible next to every diagram.

## Slide 08 — 67 words

The Call View replaces containment with analysed relationships. Labeled nodes are functions or methods, and directed arrows show who calls whom. Depth and fit controls help keep a large graph readable, while the expandable hierarchy supplies context around the selection. The entity tree on the right identifies the current item. The lower workflow panel remains unchanged, so source exploration and proposal review stay within one operational window.

## Slide 09 — 64 words

The Class View focuses on data types. Class and structure boxes list methods and signatures, while connections express inheritance and type relationships. The legend distinguishes implementation states, and the toolbar supports zooming, panning, and fitting the graph. Selecting a box synchronizes the entity context on the right. Below, the same phase controls and evidence tabs connect structural understanding directly to the next developer decision.

## Slide 10 — 66 words

The Mind Map gives a navigable outline of the project. The expanded branch here moves from project to cluster, then file, then individual entity. Branch controls reveal detail only where it is useful, and historical steps can also be selected from this map. The contextual entity list stays on the right, while the proposal panel below shows that this view belongs to the same development session.

## Slide 11 — 63 words

The Coverage view separates specification traceability from recorded test reachability. Requirement rows connect exact specification tags to implementing entities. Recorded test reachability is a structural index built from successful step records and analysed call edges: it tells us that a recorded test identifier can structurally reach a callable. It does not inspect assertions, prove behavior, or measure runtime execution coverage or branch coverage.

## Slide 12 — 60 words

The Issues view turns architectural and coding rules into an actionable table with severity, rule, entity, action, and location. Most findings are advisory, including the 30-line function guideline. The 50-line function limit is hard-blocking at both proposal and approval time. ICODA therefore cannot promote a reviewed candidate that was altered, became stale, or leaves a touched function over the limit.

## Slide 13 — 59 words

Now, let us create a small formatter project. Choose File, then New Project, and select the empty formatter directory shown in the dialog. ICODA creates the directory state under .icoda, changes the phase to specification, and opens the specification editor. Those are the immediate visible outputs of the first inputs. No source proposal or derived code model exists yet.

## Slide 14 — 66 words

Before entering the specification, deliberately click Propose. The screenshot still shows a sparse project, the provider selectors, and the phase controls. The lower panel reports that the project is in the specification phase and refuses the request. Its detail tells us to save the specification before proposing, and the status line repeats the reason. No source, history, or persisted project state changes after this refused input.

## Slide 15 — 63 words

The editor captures the project input: title, description, scope, use cases, linked requirements, and decisions. In the Python profile, keep pytest, the 30-line advisory, and hard 50-line limit. Press Validate and Save; confirm Build now; set the test command; choose Codex and the default model. ICODA writes the specification and step zero, builds and analyses the skeleton, fills the views, and enters architecture.

## Slide 16 — 54 words

Leave Request blank, keep Max entities at five, and click Propose. Draft formatter architecture contains Formatter, normalize, and main. Inspect its rationale, delta, diff, prompt, reply, and passing gates. Click Reject and enter, “Keep the public API smaller.” The isolated candidate is discarded, while the reason remains in history to guide the next proposal.

## Slide 17 — 67 words

Click Propose again. The agent now returns Add formatter architecture, adapted using the rejection reason. The screenshot shows the new proposal title, highlighted entity delta, structured summary, and passing build and test evidence. Compare the smaller public surface with the specification, then click Approve. ICODA checks the candidate again, promotes its source into the project, records the decision, creates a Git commit, and refreshes the derived model.

## Slide 18 — 62 words

The refreshed File View shows the approved architecture. The proposal area is empty because that candidate has been decided. The available phase gate is Approve architecture. Clicking it closes architectural design and derives an implementation queue, with Formatter.normalize first and main second. The phase changes to implementation, the queue becomes active, and controls for batch size, scope, grouping, and automatic approval appear.

## Slide 19 — 56 words

For the first target, keep batch size one, queue order, one-entity grouping, and automatic approval off. The queue names service.Formatter.normalize. Click Propose approach. ICODA requests prose, not code. The plan replaces the stub and adds one focused test, listing expected entities and files. Review the plan and click Approve approach. This approach round modifies no source.

## Slide 20 — 54 words

Click Propose for code. ICODA shows Implement Formatter.normalize: a stripped return value and a focused test. Build confirms the syntax gate passed; Tests confirms pytest passed. Check Diff, Delta, Prompt, and Reply, then click Approve. ICODA repeats its checks in the real project, records the commit, refreshes analysis, and the evidence structurally reaches normalize.

## Slide 21 — 55 words

The queue's next target is service.main, with one remaining. Click Propose approach. The Mind Map provides source context; the Approach tab proposes completing main through Formatter and adding an observable-result test. The expected entity and files match. Keep the queue settings, inspect the prose, and approve the approach. This changes the plan, not source files.

## Slide 22 — 57 words

Click Propose for the final code candidate. Issues remains visible while the panel shows Implement main. The diff returns the ready prefix followed by the normalized value; the test expects that result. Build and test indicators pass. Inspect the diff and evidence, then approve. ICODA validates, promotes, commits, refreshes analysis, and records structural test reachability for main.

## Slide 23 — 58 words

The walkthrough ends with recorded test reachability linking both callables to the successful test record. The queue is empty, actions are disabled, history retains decisions, and the tree is clean. Release qualification runs verify.bash: static checks, provider qualification, builds, tests, analysis, real GUI acceptance, and real-provider acceptance. Missing provider authentication fails closed unless a waiver records a skip.

## Slide 24 — 67 words

ICODA keeps intent, code structure, structural evidence, and developer decisions together. Prepare the pinned environment, specify the intended system, inspect derived architecture, and approve only a verified change. Remember that the developer owns the final decision, and recorded test reachability is not runtime coverage. The ICODA repository, my university email, and my personal page are shown here. Robimo.at is an AI-tooling service provider. Thank you for watching.
