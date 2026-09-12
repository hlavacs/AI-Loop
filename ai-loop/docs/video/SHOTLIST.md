# AI-Loop introduction video shot list

This shot list follows the numbered sections and measured narration timings in
`docs/video/audio/durations.json`. Every named asset is generated at 1920×1080 by the deterministic Pillow renderer:

```bash
python3 docs/video/build_visuals.py
```

All assets are still frames. During video assembly they can be held, dissolved, or animated with editor-side pans
and zooms synchronized to the final narration.

## 1. Introduction and about Helmut — 0:00.00 to 0:40.49

- `assets/s01_title.png` — opening AI-Loop title card.
- `assets/s01_presenter.png` — Helmut Hlavacs presenter card with `University of Vienna and Robimo GmbH, Vienna,
  Austria`, `https://robimo.at/`, `helmut.hlavacs@gmail.com`, and the confirmed repository URL.
- `assets/s01_repository.png` — sanitized static browser mockup of the confirmed repository URL.
- Substitution: the planned browser recording is represented by `assets/s01_repository.png`; it contains no live or
  private browser data.

## 2. What AI-Loop is for — 0:40.49 to 1:30.88

- `assets/s02_mental_model.png` — a single-chat dead end contrasted with the persistent loop, durable plan, tasks,
  decisions, results, progress, terminal state, and pause/resume center.
- The still supplies the complete motion-graphic layout; editor-side highlights can follow its loop without needing
  any additional source image.

## 3. How the controller and worker loop works — 1:30.88 to 2:22.29

- `assets/s03_architecture.png` — controller/task/worker/worktree loop, return result, SQLite, Redis Streams, and
  watcher architecture.
- `assets/s03_promotion.png` — worktree validation, conflict gate, promotion, target-checkout validation, and durable
  done state.

## 4. Email feedback — 2:22.29 to 2:57.48

- `assets/s04_email_thread.png` — sanitized four-beat thread for job start, twelve-hour status, attention request,
  and a fictional reply command that resumes the same job.
- All job IDs, mailbox addresses, status, and command text in the mockup are fictional; no mailbox was accessed.

## 5. The GUI — 2:57.48 to 3:47.94

- `assets/s05_gui_overview.png` — full `docs/images/ai-loop-gui.png` overview on a 16:9 canvas.
- `assets/s05_gui_create_jobs.png` — legible left-side Create Job and Jobs crop.
- `assets/s05_gui_tabs_toolbar.png` — toolbar crop followed by the right-side inspection tabs crop.
- Substitution: this three-frame crop sequence replaces the planned live pan. It is derived only from the existing
  repository screenshot and requires no new GUI capture.

## 6. A simple quick job — 3:47.94 to 4:37.68

- `assets/s06_quick_job_setup.png` — Create Job crop plus the overlaid sanitized example goal and settings.
- `assets/s06_quick_job_progress.png` — fictional Plan, Task, Worker, and Logs states.
- `assets/s06_quick_job_complete.png` — promotion and target-validation completion state.
- Substitution: these three static frames replace the planned disposable-repository screen recording. No live GUI,
  real repository path, or private process output is used.

## 7. Specification details — 4:37.68 to 5:21.65

- `assets/s07_spec_overview.png` — eight-tab opening and compact common-path overview, derived from
  `specification-empty-new.png` and `specification-overview-more-fields.png`.
- `assets/s07_spec_guidance.png` — Overview fields with the `specification-field-help.png` dialog.
- `assets/s07_spec_scope.png` — outcome and boundaries, derived from `specification-overview.png` and
  `specification-scope.png`.
- `assets/s07_spec_requirements.png` — stable requirements and acceptance-detail views, derived from
  `specification-requirements.png` and `specification-requirement-dialog.png`.
- `assets/s07_spec_choices_review.png` — Analyze/choices and completion checklist, derived from
  `specification-choices.png` and `specification-review.png`.
- `assets/s07_spec_workflow.png` — authoring-to-completion path, derived from
  `specification-process-help.png` with an adjacent seven-step diagram.
- The six-frame montage uses every existing `docs/images/specification-*.png` screenshot; no additional capture is
  required.

## 8. Code analysis — 5:21.65 to 5:59.52

- `assets/s08_code_analysis.png` — sanitized repository tree, failing test output, successful worker report, and a
  crop of the GUI's Controller, Worker, Details, and Logs region.
- The fictional `demo-project` content is an overlay; the GUI portion is derived from
  `docs/images/ai-loop-gui.png`.

## 9. Direct LLM use and external repair help — 5:59.52 to 6:44.98

- `assets/s09_comparison.png` — direct-model versus persistent AI-Loop split-screen comparison.
- `assets/s09_repair_resume.png` — five-step provider repair and same-job resume sequence over a sanitized GUI crop.
- `assets/s09_feedback.png` — closing feedback card with `helmut.hlavacs@gmail.com`.
- Substitution: `assets/s09_repair_resume.png` replaces the planned live Fix binary / Fix It recording. The source GUI
  crop comes from `docs/images/ai-loop-gui.png`; the repair sequence is synthetic and sanitized.

## Source and metadata record

- Confirmed repository URL: `https://github.com/hlavacs/AI-Loop.git`, from `git remote -v` and
  `git config --get remote.origin.url`.
- Affiliation: `University of Vienna and Robimo GmbH, Vienna, Austria`, from the application window title in
  `ai_loop_gui.py`.
- Website: `https://robimo.at/`, from the application window title in `ai_loop_gui.py`.
- Screenshot sources: `docs/images/ai-loop-gui.png` and all ten existing
  `docs/images/specification-*.png` files.
- The renderer does not access the network, record the desktop, generate audio, or generate video.

## Toolchain

Verified from the worktree on 12 September 2026:

```text
ffmpeg version 6.1.1-3ubuntu5 Copyright (c) 2000-2023 the FFmpeg developers
ffprobe version 6.1.1-3ubuntu5 Copyright (c) 2007-2023 the FFmpeg developers
```

Both executables are on `PATH`. The narration audio durations are recorded in
`docs/video/audio/durations.json` and drive the final assembly below.

## Final export

Built from the worktree root with the deterministic assembler:

```bash
python3 docs/video/build_video.py
```

- Container duration: 405.000000 seconds (6:45.00).
- Stream layout: one H.264 video stream and one AAC audio stream.
- Video: 1920×1080, `yuv420p`, 30 fps (`r_frame_rate=30/1`, `avg_frame_rate=30/1`).
- Output: `docs/video/ai-loop-introduction.mp4`, with `+faststart` enabled by the build command.
