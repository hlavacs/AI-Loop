# ICODA introduction video shot list

This shot list maps one 1920×1080 still to each narration segment in `docs/video/SCRIPT.md`. Visual production must use a white background, one restrained University blue accent, and no decorative texture, photographic background, or paragraph text on a slide.

## Common frame and fit contract

- Frame: 1920×1080 pixels.
- Branding on every slide, `s01` through `s27`: use the official blue University of Vienna logo from `https://www.univie.ac.at/fileadmin/user_upload/univie/Logos/Logos_Universitaet_Wien/Uni_Logo.png`. Contain the complete logo proportionally, without cropping, in `[1590, 35]–[1840, 135]` (250×100 pixels) in the upper-right corner. Keep its original colors and clear space.
- Logo source page and use guidance: `https://www.univie.ac.at/en/about-us/organisation-and-structure/corporate-communications/downloads`.
- Headline safe area: `[80, 45]–[1480, 140]`. It must never enter the logo area.
- Screenshot rule: preserve the complete source image. Scale it proportionally with `scale = min(target_width/source_width, target_height/source_height)`, center it in the stated target area, and assert all four rendered edges remain inside that area. No source crop, stretch, overflow, or covered screenshot content is allowed.
- Screenshot callouts: at most three short labels, placed only in unused white margin. Do not layer opaque boxes over application content.
- Source paths below are relative to the ICODA project root. Every listed screenshot already exists; no new capture is required for this cut.

## s01 — `s01_title`

- Visual type: Diagram.
- Source image path: Not applicable.
- Target slide area: Main diagram in `[120, 245]–[1800, 900]` (1680×655 pixels); common logo area remains clear.
- Content: `ICODA`, expansion `Interactive Code Development and Analysis`, `Helmut Hlavacs`, `University of Vienna`, `https://entertain.univie.ac.at/~hlavacs/`, and one thin specification → proposal → evidence → decision loop.
- Simplicity: One loop, title, and three identity lines.

## s02 — `s02_presenter`

- Visual type: Diagram.
- Source image path: Not applicable.
- Target slide area: Contact card in `[180, 225]–[1740, 900]` (1560×675 pixels).
- Content: `Helmut Hlavacs`; `Faculty of Computer Science, University of Vienna`; `https://www.univie.ac.at/`; `helmut.hlavacs@univie.ac.at`; `https://github.com/hlavacs/AI-Loop/tree/main/icoda`; `https://entertain.univie.ac.at/~hlavacs/`.
- Simplicity: Six aligned text rows with small line icons; no portrait is required.

## s03 — `s03_purpose`

- Visual type: Diagram.
- Source image path: Not applicable.
- Target slide area: Comparison in `[120, 250]–[1800, 885]` (1680×635 pixels).
- Content: Left, one opaque large code change; right, four small changes with visible architecture, build, tests, and approvals.
- Simplicity: One left-right comparison and four compact evidence labels.

## s04 — `s04_basic_idea`

- Visual type: Diagram.
- Source image path: Not applicable.
- Target slide area: Truth-and-proposal flow in `[100, 220]–[1820, 920]` (1720×700 pixels).
- Content: Specification and source feed a derived model; LLM proposal enters an isolated worktree; build, tests, parse, and compare lead to the developer decision.
- Simplicity: One flow diagram with short node labels only.

## s05 — `s05_mental_model`

- Visual type: Diagram.
- Source image path: Not applicable.
- Target slide area: Workbench diagram in `[160, 225]–[1760, 900]` (1600×675 pixels).
- Content: Live map above an isolated workbench; arrows labelled `LLM proposes`, `ICODA measures`, `developer decides`.
- Simplicity: One central metaphor, three arrows, no prose blocks.

## s06 — `s06_workflow`

- Visual type: Diagram.
- Source image path: Not applicable.
- Target slide area: Phase path in `[100, 260]–[1820, 850]` (1720×590 pixels).
- Content: `Specification` → `Architecture` → `Implementation`; beneath each transition show `worktree` → `build` → `tests` → `parse/delta` → `decision` → `Git commit`.
- Simplicity: One horizontal phase path and one repeated gate strip.

## s07 — `s07_gui_overview`

- Visual type: Screenshot.
- Source image path: `docs/images/handbook/sim-10-terminal-overview.png` (2800×1440).
- Target slide area: `[70, 180]–[1850, 1030]` (1780×850 pixels); contain full source, expected rendered size approximately 1653×850 pixels.
- Content: Full main window at the completed lifecycle; label only `analysis views`, `LLM + entities`, and `workflow + evidence` in the surrounding white margin.

## s08 — `s08_file_view`

- Visual type: Screenshot.
- Source image path: `docs/images/handbook/python-file-view.png` (2800×1440).
- Target slide area: `[70, 180]–[1850, 1030]` (1780×850 pixels); contain full source, expected rendered size approximately 1653×850 pixels.
- Content: Full Python File View; subtle margin labels for tabs, expandable hierarchy, and selected entities.

## s09 — `s09_call_view`

- Visual type: Screenshot.
- Source image path: `docs/images/handbook/uncertain-dynamic-call.png` (2800×1440).
- Target slide area: `[70, 180]–[1850, 1030]` (1780×850 pixels); contain full source, expected rendered size approximately 1653×850 pixels.
- Content: Full Call View with `dispatch`, fixed target, dashed uncertain target, depth control, and status legend visible.

## s10 — `s10_class_view`

- Visual type: Screenshot.
- Source image path: `docs/images/handbook/python-class-view.png` (2800×1440).
- Target slide area: `[70, 180]–[1850, 1030]` (1780×850 pixels); contain full source, expected rendered size approximately 1653×850 pixels.
- Content: Full Class View showing `service.Store`, `load`, its signature, hierarchy, and status legend.

## s11 — `s11_mind_map`

- Visual type: Screenshot.
- Source image path: `docs/images/handbook/mind-map.png` (2800×1440).
- Target slide area: `[70, 180]–[1850, 1030]` (1780×850 pixels); contain full source, expected rendered size approximately 1653×850 pixels.
- Content: Full Mind Map with expanded `src` cluster, `main.cpp`, and `main`; one margin label: `structure + requirements + step history`.

## s12 — `s12_coverage`

- Visual type: Screenshot.
- Source image path: `docs/images/handbook/requirements-coverage.png` (2800×1440).
- Target slide area: `[70, 180]–[1850, 1030]` (1780×850 pixels); contain full source, expected rendered size approximately 1653×850 pixels.
- Content: Full Coverage view; label `specification links` above `recorded test reachability` in the margin, matching the two screenshot sections.

## s13 — `s13_issues`

- Visual type: Screenshot.
- Source image path: `docs/images/handbook/rule-issues.png` (2800×1440).
- Target slide area: `[70, 180]–[1850, 1030]` (1780×850 pixels); contain full source, expected rendered size approximately 1653×850 pixels.
- Content: Full Issues table with severity, rule, entity, action, and location columns visible.

## s14 — `s14_provider_selection`

- Visual type: Screenshot.
- Source image path: `docs/images/handbook/provider-selection.png` (2736×1482).
- Target slide area: `[70, 180]–[1850, 1030]` (1780×850 pixels); contain full source, expected rendered size approximately 1569×850 pixels.
- Content: Full window; one thin outline may emphasize the upper-right Binary and Model fields without obscuring their values.

## s15 — `s15_architecture_step`

- Visual type: Diagram.
- Source image path: Not applicable.
- Target slide area: Architecture-step flow in `[100, 235]–[1820, 900]` (1720×665 pixels).
- Content: Small request plus maximum entity budget → isolated candidate → build/tests/parse → measured delta → approve, reject, or adapt.
- Simplicity: One process row; use only University blue plus green for passed gates.

## s16 — `s16_proposal_evidence`

- Visual type: Screenshot.
- Source image path: `docs/images/handbook/proposal-source-diff.png` (2800×1440).
- Target slide area: `[70, 180]–[1850, 1030]` (1780×850 pixels); contain full source, expected rendered size approximately 1653×850 pixels.
- Content: Full proposal screen with Source diff selected, review tabs visible, and passing Build and Tests summary retained.

## s17 — `s17_developer_decision`

- Visual type: Screenshot.
- Source image path: `docs/images/handbook/signature-confirmation.png` (2800×1440).
- Target slide area: `[70, 180]–[1850, 1030]` (1780×850 pixels); contain full source, expected rendered size approximately 1653×850 pixels.
- Content: Full proposal screen with Signature changes selected and decision controls visible; label `explicit API gate` in the white margin.

## s18 — `s18_quick_architecture`

- Visual type: Screenshot.
- Source image path: `docs/images/handbook/sim-04-architecture-approve.png` (2800×1440).
- Target slide area: `[70, 180]–[1850, 1030]` (1780×850 pixels); contain full source, expected rendered size approximately 1653×850 pixels.
- Content: Full deterministic Python architecture proposal; retain highlighted `service.Formatter.normalize`, three-entity Delta, decision buttons, and passing gates.

## s19 — `s19_quick_approach`

- Visual type: Screenshot.
- Source image path: `docs/images/handbook/implementation-approach.png` (2800×1440).
- Target slide area: `[70, 180]–[1850, 1030]` (1780×850 pixels); contain full source, expected rendered size approximately 1653×850 pixels.
- Content: Full implementation screen with the Approach tab selected and the prose plan awaiting approval.

## s20 — `s20_quick_result`

- Visual type: Screenshot.
- Source image path: `docs/images/handbook/sim-07-normalize-build-test.png` (2800×1440).
- Target slide area: `[70, 180]–[1850, 1030]` (1780×850 pixels); contain full source, expected rendered size approximately 1653×850 pixels.
- Content: Full normalize implementation proposal with class node, measured Delta, source/test filenames, and passed gate summary visible.

## s21 — `s21_spec_overview`

- Visual type: Screenshot.
- Source image path: `docs/images/handbook/specification-overview.png` (2240×1360).
- Target slide area: `[160, 180]–[1760, 1030]` (1600×850 pixels); contain full source, expected rendered size approximately 1400×850 pixels.
- Content: Full Overview page with all six tabs, title, description, and Validate, Save, Close actions visible.

## s22 — `s22_spec_scope`

- Visual type: Screenshot.
- Source image path: `docs/images/handbook/specification-scope.png` (2240×1360).
- Target slide area: `[160, 180]–[1760, 1030]` (1600×850 pixels); contain full source, expected rendered size approximately 1400×850 pixels.
- Content: Full Scope page with Goals, Not in scope, Not allowed, and Done when fields visible.

## s23 — `s23_spec_requirements`

- Visual type: Screenshot.
- Source image path: `docs/images/handbook/specification-requirements.png` (2240×1360).
- Target slide area: `[160, 180]–[1760, 1030]` (1600×850 pixels); contain full source, expected rendered size approximately 1400×850 pixels.
- Content: Full Requirements page; preserve the requirement list and the selected record's ID, priority, use-case link, and details.

## s24 — `s24_spec_code_profile`

- Visual type: Screenshot.
- Source image path: `docs/images/handbook/specification-code-profile.png` (2240×1360).
- Target slide area: `[160, 180]–[1760, 1030]` (1600×850 pixels); contain full source, expected rendered size approximately 1400×850 pixels.
- Content: Full Code Profile page with language, standard, build, test, naming, library, and style fields retained.

## s25 — `s25_code_analysis`

- Visual type: Screenshot.
- Source image path: `docs/images/handbook/diagram-filtered.png` (2800×1440).
- Target slide area: `[70, 180]–[1850, 1030]` (1780×850 pixels); contain full source, expected rendered size approximately 1653×850 pixels.
- Content: Full filtered derived graph with filter controls, graph nodes, hierarchy, status, and toolchain line visible.

## s26 — `s26_llm_choices`

- Visual type: Diagram.
- Source image path: Not applicable.
- Target slide area: Three-path comparison in `[100, 235]–[1820, 900]` (1720×665 pixels).
- Content: `Direct LLM` → one focused edit; `ICODA` → proposal and checked evidence; `External LLM repair` → open worktree → repair → Rebuild → ICODA gates.
- Simplicity: Three horizontal paths with the ICODA gate icon reused; no vendor logos.

## s27 — `s27_closing`

- Visual type: Diagram.
- Source image path: Not applicable.
- Target slide area: Closing card in `[180, 225]–[1740, 900]` (1560×675 pixels).
- Content: `https://github.com/hlavacs/AI-Loop/tree/main/icoda`; `helmut.hlavacs@univie.ac.at`; `https://entertain.univie.ac.at/~hlavacs/`; and `Robimo.at — service provider specialized in AI tooling`.
- Simplicity: Four aligned contact rows and a small closing ICODA loop mark.

## Coverage and screenshot inventory

- Diagram slides: `s01`–`s06`, `s15`, `s26`, and `s27` (9 slides).
- Screenshot slides: `s07`–`s14`, `s16`–`s25` (18 slides).
- GUI overview and analysis views: `s07`–`s14`.
- Proposal and developer-control views: `s16`–`s17`.
- Quick-job walkthrough: `s18`–`s20`.
- Specification details: `s21`–`s24`.
- Code analysis: `s25`.
- Direct and external LLM choices: `s26`.
- Closing identity and service-provider mention: `s27`.
