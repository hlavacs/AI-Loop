# ICODA introduction video

This directory defines a 24-slide, roughly 10–12 minute introduction to ICODA. The video moves from purpose, basic idea, mental model, and operation into a six-view GUI tour, then follows one new project without skipping any developer input or visible output: directory selection, specification, tool settings, architecture decisions, implementation approaches, verified proposals, and completion.

`storyboard.md` is the visual source of truth. It names the exact deterministic capture for every screenshot slide, its contain target, and the red focus overlays. `narration.md` supplies the matching spoken text and timing budget for slides 01–24. The captures themselves are specified by `../screenshot-plan.md`; later production stages will place them, render slides, generate speech with the configured voice, and build the final MP4.
