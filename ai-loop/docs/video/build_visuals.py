#!/usr/bin/env python3
"""Render the deterministic still-image sequence for the AI-Loop video.

Run from ``ai-loop``::

    python3 docs/video/build_visuals.py

The renderer deliberately uses only repository screenshots and synthetic,
sanitized examples.  It does not capture a live desktop or access a network.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[2]
IMAGE_DIR = ROOT / "docs" / "images"
OUTPUT = Path(__file__).resolve().parent / "assets"

WIDTH = 1920
HEIGHT = 1080
EMAIL = "helmut.hlavacs@gmail.com"
REPOSITORY_URL = "https://github.com/hlavacs/AI-Loop.git"
AFFILIATION = "University of Vienna and Robimo GmbH, Vienna, Austria"
WEBSITE = "https://robimo.at/"

BACKGROUND = "#07111f"
BACKGROUND_2 = "#10243b"
PANEL = "#12283f"
PANEL_LIGHT = "#17334f"
INK = "#f4f8fb"
MUTED = "#a8bed0"
CYAN = "#44d7d1"
BLUE = "#5a8cff"
GOLD = "#ffca6b"
GREEN = "#62d692"
RED = "#ff7285"
PURPLE = "#bd8cff"

FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
FONT_REGULAR = FONT_DIR / "DejaVuSans.ttf"
FONT_BOLD = FONT_DIR / "DejaVuSans-Bold.ttf"
FONT_MONO = FONT_DIR / "DejaVuSansMono.ttf"

ASSET_NAMES = (
    "s01_title.png",
    "s01_presenter.png",
    "s01_repository.png",
    "s02_mental_model.png",
    "s03_architecture.png",
    "s03_promotion.png",
    "s04_email_thread.png",
    "s05_gui_overview.png",
    "s05_gui_create_jobs.png",
    "s05_gui_tabs_toolbar.png",
    "s06_quick_job_setup.png",
    "s06_quick_job_progress.png",
    "s06_quick_job_complete.png",
    "s07_spec_overview.png",
    "s07_spec_guidance.png",
    "s07_spec_scope.png",
    "s07_spec_requirements.png",
    "s07_spec_choices_review.png",
    "s07_spec_workflow.png",
    "s08_code_analysis.png",
    "s09_comparison.png",
    "s09_repair_resume.png",
    "s09_feedback.png",
)


def font(size: int, *, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont:
    """Return the repository renderer's bundled-system font choice."""
    path = FONT_MONO if mono else FONT_BOLD if bold else FONT_REGULAR
    if not path.is_file():
        raise RuntimeError(f"required font is missing: {path}")
    return ImageFont.truetype(str(path), size)


def _hex(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))


def new_frame(section: int, kicker: str) -> Image.Image:
    """Create the shared 16:9 background and section chrome."""
    top = _hex(BACKGROUND)
    bottom = _hex(BACKGROUND_2)
    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    pixels = ImageDraw.Draw(image)
    for y in range(HEIGHT):
        amount = y / (HEIGHT - 1)
        colour = tuple(round(a + (b - a) * amount) for a, b in zip(top, bottom))
        pixels.line((0, y, WIDTH, y), fill=colour)
    draw = ImageDraw.Draw(image)
    draw.ellipse((1420, -470, 2250, 360), fill="#102e4c")
    draw.ellipse((-390, 790, 380, 1560), fill="#0b293f")
    draw.rounded_rectangle((72, 54, 260, 112), radius=28, fill=CYAN)
    draw.text((166, 83), "AI-LOOP", font=font(25, bold=True), fill=BACKGROUND, anchor="mm")
    draw.text((292, 83), f"SECTION {section:02d}  /  {kicker.upper()}", font=font(25, bold=True), fill=MUTED, anchor="lm")
    draw.line((72, 1022, 1848, 1022), fill="#31506a", width=2)
    draw.text((72, 1047), "AI-Loop introduction", font=font(20), fill=MUTED, anchor="lm")
    draw.text((1848, 1047), "1920 × 1080", font=font(20), fill=MUTED, anchor="rm")
    return image


def wrap_lines(draw: ImageDraw.ImageDraw, value: str, face: ImageFont.FreeTypeFont, width: int) -> list[str]:
    """Wrap text using measured pixel width rather than character count."""
    result: list[str] = []
    for paragraph in value.splitlines() or [""]:
        words = paragraph.split()
        if not words:
            result.append("")
            continue
        line = words[0]
        for word in words[1:]:
            candidate = f"{line} {word}"
            if draw.textlength(candidate, font=face) <= width:
                line = candidate
            else:
                result.append(line)
                line = word
        result.append(line)
    return result


def wrapped_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    value: str,
    *,
    face: ImageFont.FreeTypeFont,
    fill: str,
    width: int,
    spacing: int = 10,
) -> int:
    """Draw wrapped text and return its lower y coordinate."""
    x, y = xy
    line_height = face.getbbox("Ag")[3] - face.getbbox("Ag")[1]
    for line in wrap_lines(draw, value, face, width):
        draw.text((x, y), line, font=face, fill=fill)
        y += line_height + spacing
    return y


def panel(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    fill: str = PANEL,
    outline: str = "#294b68",
    radius: int = 28,
    width: int = 2,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def heading(image: Image.Image, title: str, subtitle: str = "") -> int:
    draw = ImageDraw.Draw(image)
    draw.text((72, 160), title, font=font(64, bold=True), fill=INK)
    if subtitle:
        return wrapped_text(draw, (76, 242), subtitle, face=font(29), fill=MUTED, width=1710, spacing=6)
    return 242


def arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    fill: str = CYAN,
    width: int = 8,
) -> None:
    draw.line((*start, *end), fill=fill, width=width)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    length = 24
    spread = 0.55
    points = [
        end,
        (
            round(end[0] - length * math.cos(angle - spread)),
            round(end[1] - length * math.sin(angle - spread)),
        ),
        (
            round(end[0] - length * math.cos(angle + spread)),
            round(end[1] - length * math.sin(angle + spread)),
        ),
    ]
    draw.polygon(points, fill=fill)


def node(
    draw: ImageDraw.ImageDraw,
    center: tuple[int, int],
    size: tuple[int, int],
    title: str,
    detail: str,
    *,
    accent: str = CYAN,
) -> tuple[int, int, int, int]:
    x, y = center
    w, h = size
    box = (x - w // 2, y - h // 2, x + w // 2, y + h // 2)
    panel(draw, box)
    draw.rounded_rectangle((box[0], box[1], box[0] + 12, box[3]), radius=6, fill=accent)
    draw.text((x, y - 26), title, font=font(29, bold=True), fill=INK, anchor="mm")
    draw.text((x, y + 25), detail, font=font(21), fill=MUTED, anchor="mm")
    return box


def screenshot(
    image: Image.Image,
    source_name: str,
    box: tuple[int, int, int, int],
    *,
    crop: tuple[float, float, float, float] | None = None,
    contain: bool = True,
) -> None:
    """Place one repository screenshot in a bordered card."""
    source_path = IMAGE_DIR / source_name
    if not source_path.is_file():
        raise RuntimeError(f"missing source screenshot: {source_path}")
    with Image.open(source_path) as opened:
        source = opened.convert("RGB")
    if source_name == "ai-loop-gui.png":
        # The source capture contains a personal title-bar byline and a local
        # filesystem path.  Replace both in memory before making any crop.
        source_draw = ImageDraw.Draw(source)
        source_draw.rectangle((280, 78, 2700, 145), fill="#f8f8f8")
        source_draw.text((305, 111), "AI-LOOP", font=font(32, bold=True), fill="#4f4f4f", anchor="lm")
        source_draw.rectangle((238, 297, 858, 346), fill="#ffffff", outline="#b8b8b8", width=2)
        source_draw.text(
            (250, 321),
            "/example/demo-project",
            font=font(27),
            fill="#303030",
            anchor="lm",
        )
    if crop is not None:
        left, top, right, bottom = crop
        source = source.crop(
            (
                round(source.width * left),
                round(source.height * top),
                round(source.width * right),
                round(source.height * bottom),
            )
        )
    x1, y1, x2, y2 = box
    inset = 10
    target = (x2 - x1 - inset * 2, y2 - y1 - inset * 2)
    if contain:
        rendered = ImageOps.contain(source, target, Image.Resampling.LANCZOS)
    else:
        rendered = ImageOps.fit(source, target, Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(image)
    panel(draw, box, fill="#07101a", outline="#42617b", radius=22, width=3)
    paste_x = x1 + (x2 - x1 - rendered.width) // 2
    paste_y = y1 + (y2 - y1 - rendered.height) // 2
    image.paste(rendered, (paste_x, paste_y))


def tag(draw: ImageDraw.ImageDraw, xy: tuple[int, int], value: str, colour: str = CYAN) -> None:
    face = font(21, bold=True)
    width = round(draw.textlength(value, font=face)) + 34
    x, y = xy
    draw.rounded_rectangle((x, y, x + width, y + 44), radius=20, fill=colour)
    draw.text((x + 17, y + 22), value, font=face, fill=BACKGROUND, anchor="lm")


def bullet_list(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    values: Iterable[str],
    *,
    width: int,
    colour: str = CYAN,
    size: int = 28,
    gap: int = 22,
) -> None:
    x, y = xy
    face = font(size)
    for value in values:
        draw.ellipse((x, y + 13, x + 13, y + 26), fill=colour)
        y = wrapped_text(draw, (x + 32, y), value, face=face, fill=INK, width=width - 32, spacing=6) + gap


def save(name: str, image: Image.Image) -> None:
    if image.size != (WIDTH, HEIGHT):
        raise RuntimeError(f"invalid frame size for {name}: {image.size}")
    image.save(OUTPUT / name, format="PNG", compress_level=9)
    print(f"{name}: {image.width}x{image.height}")


def s01_title() -> Image.Image:
    image = new_frame(1, "Introduction")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((122, 250, 1798, 835), radius=54, fill="#0d2136", outline="#315676", width=3)
    draw.text((960, 415), "AI-LOOP", font=font(138, bold=True), fill=INK, anchor="mm")
    draw.rounded_rectangle((630, 510, 1290, 523), radius=6, fill=CYAN)
    draw.text((960, 610), "Persistent, supervised coding-agent work", font=font(43, bold=True), fill=CYAN, anchor="mm")
    draw.text((960, 700), "Plan  •  Implement  •  Validate  •  Continue", font=font(31), fill=MUTED, anchor="mm")
    return image


def s01_presenter() -> Image.Image:
    image = new_frame(1, "About Helmut")
    draw = ImageDraw.Draw(image)
    heading(image, "Helmut Hlavacs", "AI-Loop introduction and project contact")
    panel(draw, (72, 345, 1848, 918))
    rows = (
        ("Affiliation", AFFILIATION, GOLD),
        ("Website", WEBSITE, GOLD),
        ("Email", EMAIL, CYAN),
        ("GitHub", REPOSITORY_URL, GREEN),
    )
    y = 405
    for label, value, colour in rows:
        draw.text((135, y), label.upper(), font=font(24, bold=True), fill=colour)
        draw.text((440, y - 6), value, font=font(37, bold=True), fill=INK)
        y += 116
    draw.text((135, 862), "Affiliation and website confirmed by the application window title.", font=font(22), fill=MUTED)
    return image


def s01_repository() -> Image.Image:
    image = new_frame(1, "Repository")
    draw = ImageDraw.Draw(image)
    heading(image, "Explore the project", "Confirmed from the worktree's Git origin")
    panel(draw, (110, 340, 1810, 890), fill="#f7f9fb", outline="#365774")
    draw.rounded_rectangle((110, 340, 1810, 414), radius=24, fill="#dce4ea")
    for x, colour in ((152, RED), (188, GOLD), (224, GREEN)):
        draw.ellipse((x - 10, 367, x + 10, 387), fill=colour)
    draw.rounded_rectangle((300, 354, 1728, 400), radius=18, fill="#ffffff")
    draw.text((330, 377), REPOSITORY_URL, font=font(23, mono=True), fill="#263849", anchor="lm")
    draw.text((190, 515), "AI-Loop", font=font(60, bold=True), fill="#13273a")
    draw.text((190, 602), "Persistent, resumable jobs for coding-agent CLIs", font=font(34), fill="#40576a")
    draw.line((190, 670, 1718, 670), fill="#c9d3da", width=2)
    draw.text((190, 727), "README.md", font=font(25, bold=True), fill="#1e6bb8")
    draw.text((190, 782), "Controller  •  Worker  •  Watcher  •  Durable job state", font=font(28), fill="#40576a")
    tag(draw, (1370, 730), "STATIC BROWSER MOCKUP", BLUE)
    return image


def s02_mental_model() -> Image.Image:
    image = new_frame(2, "Mental model")
    draw = ImageDraw.Draw(image)
    heading(image, "A persistent development loop", "Large, checked work continues beyond a single chat session")
    panel(draw, (72, 334, 470, 874), fill="#101f31")
    draw.text((271, 412), "ONE CHAT", font=font(29, bold=True), fill=MUTED, anchor="mm")
    draw.rounded_rectangle((145, 480, 397, 660), radius=28, fill="#213247", outline="#52677a", width=2)
    draw.text((271, 538), "Context", font=font(29, bold=True), fill=INK, anchor="mm")
    draw.text((271, 592), "ends here", font=font(29), fill=RED, anchor="mm")
    draw.line((182, 624, 360, 624), fill=RED, width=6)
    arrow(draw, (484, 604), (606, 604), fill=GOLD)
    draw.text((545, 559), "instead", font=font(21, bold=True), fill=GOLD, anchor="mm")
    center = (1130, 606)
    draw.ellipse((742, 350, 1518, 862), outline=CYAN, width=12)
    for angle, label, colour in zip(
        (205, 245, 285, 325, 5, 45),
        ("PLAN", "TASKS", "DECISIONS", "RESULTS", "PROGRESS", "TERMINAL STATE"),
        (BLUE, CYAN, PURPLE, GREEN, GOLD, RED),
    ):
        radians = math.radians(angle)
        x = round(center[0] + 445 * math.cos(radians))
        y = round(center[1] + 315 * math.sin(radians))
        w = 242 if label == "TERMINAL STATE" else 190
        draw.rounded_rectangle((x - w // 2, y - 34, x + w // 2, y + 34), radius=25, fill=colour)
        draw.text((x, y), label, font=font(19, bold=True), fill=BACKGROUND, anchor="mm")
    draw.rounded_rectangle((930, 500, 1330, 712), radius=35, fill="#e9f4f7")
    draw.text((1130, 557), "DURABLE JOB", font=font(31, bold=True), fill="#10243b", anchor="mm")
    draw.text((1130, 615), "PAUSE  ↔  RESUME", font=font(26, bold=True), fill="#176b87", anchor="mm")
    draw.text((1130, 668), "until acceptance", font=font(22), fill="#40576a", anchor="mm")
    return image


def s03_architecture() -> Image.Image:
    image = new_frame(3, "Architecture")
    draw = ImageDraw.Draw(image)
    heading(image, "Controller, worker, and watcher", "Redis coordinates processes; SQLite preserves the job")
    controller = node(draw, (310, 510), (320, 160), "CONTROLLER", "plans + reviews", accent=BLUE)
    task = node(draw, (735, 510), (250, 140), "TASK", "acceptance", accent=GOLD)
    worker = node(draw, (1115, 510), (300, 160), "WORKER", "edits + tests", accent=CYAN)
    worktree = node(draw, (1585, 510), (360, 160), "GIT WORKTREE", "isolated change", accent=GREEN)
    arrow(draw, (controller[2] + 16, 510), (task[0] - 16, 510), fill=BLUE)
    arrow(draw, (task[2] + 16, 510), (worker[0] - 16, 510), fill=GOLD)
    arrow(draw, (worker[2] + 16, 510), (worktree[0] - 16, 510), fill=CYAN)
    arrow(draw, (1510, 610), (430, 610), fill=GREEN, width=6)
    draw.text((968, 634), "RESULT + VALIDATION", font=font(20, bold=True), fill=GREEN, anchor="mt")
    node(draw, (470, 806), (430, 120), "SQLITE", "durable plans, tasks, runs, state", accent=PURPLE)
    node(draw, (1000, 806), (420, 120), "REDIS STREAMS", "process coordination", accent=RED)
    node(draw, (1515, 806), (390, 120), "WATCHER", "events • email • schedule", accent=GOLD)
    for x in (310, 735, 1115, 1585):
        draw.line((x, 596, x, 746), fill="#43627b", width=3)
    arrow(draw, (1218, 806), (1305, 806), fill=GOLD, width=5)
    return image


def s03_promotion() -> Image.Image:
    image = new_frame(3, "Promotion")
    draw = ImageDraw.Draw(image)
    heading(image, "Promotion is a checked handoff", "Success reaches the target checkout only after conflict and validation gates")
    labels = (
        ("WORKTREE", "task validation passes", CYAN),
        ("PATH CHECK", "no conflicting edits", GOLD),
        ("PROMOTE", "copy successful changes", BLUE),
        ("TARGET CHECKOUT", "validation runs again", PURPLE),
        ("DONE", "durable terminal state", GREEN),
    )
    centers = (210, 585, 960, 1335, 1710)
    for index, ((title, detail, colour), x) in enumerate(zip(labels, centers)):
        node(draw, (x, 570), (290, 190), title, detail, accent=colour)
        draw.ellipse((x - 28, 755, x + 28, 811), fill=colour)
        draw.text((x, 783), str(index + 1), font=font(25, bold=True), fill=BACKGROUND, anchor="mm")
        if index < len(centers) - 1:
            arrow(draw, (x + 160, 570), (centers[index + 1] - 160, 570), fill=colour)
    draw.text((960, 880), "A failed gate returns evidence to the recovery loop.", font=font(29, bold=True), fill=MUTED, anchor="mm")
    return image


def s04_email_thread() -> Image.Image:
    image = new_frame(4, "Email feedback")
    draw = ImageDraw.Draw(image)
    heading(image, "The job can report back by email", "Sanitized example — fictional addresses, job IDs, and commands")
    panel(draw, (170, 318, 1750, 934), fill="#edf3f7", outline="#41617a")
    draw.text((230, 365), "Thread: AI-Loop job demo-184", font=font(30, bold=True), fill="#193147")
    messages = (
        ("AI-Loop <bot@example.test>", "09:00", "Job started", "Goal accepted. Controller is preparing the first task.", BLUE),
        ("AI-Loop <bot@example.test>", "21:00", "12-hour status", "Progress 55% • Current task: repair parser tests", CYAN),
        ("AI-Loop <bot@example.test>", "21:14", "Attention requested", "A product choice needs an authorized reply.", GOLD),
        ("Developer <operator@example.test>", "21:18", "Reply command", "Command: Keep compatibility; use the fallback and continue.", GREEN),
    )
    y = 430
    for sender, timestamp, subject, body, colour in messages:
        draw.rounded_rectangle((224, y, 1696, y + 102), radius=20, fill="#ffffff", outline="#cad6de", width=2)
        draw.rounded_rectangle((224, y, 238, y + 102), radius=7, fill=colour)
        draw.text((264, y + 18), sender, font=font(19, bold=True), fill="#30495c")
        draw.text((1648, y + 18), timestamp, font=font(18), fill="#61798b", anchor="ra")
        draw.text((264, y + 49), subject, font=font(23, bold=True), fill="#13293c")
        draw.text((650, y + 51), body, font=font(20), fill="#496174")
        y += 120
    tag(draw, (1330, 875), "REPLY RESUMES SAME JOB", GREEN)
    return image


def gui_frame(title: str, subtitle: str, name: str, crop: tuple[float, float, float, float] | None = None) -> Image.Image:
    image = new_frame(5, "GUI")
    heading(image, title, subtitle)
    screenshot(image, "ai-loop-gui.png", (72, 322, 1848, 930), crop=crop, contain=crop is None)
    draw = ImageDraw.Draw(image)
    tag(draw, (1455, 855), name, CYAN)
    return image


def s05_gui_overview() -> Image.Image:
    return gui_frame("Create and supervise in one place", "Full-screen overview from the repository screenshot", "FULL VIEW")


def s05_gui_create_jobs() -> Image.Image:
    return gui_frame(
        "Create Job and durable Jobs",
        "A close view of repository, goal, validation, providers, worktree options, and job list",
        "PAN / LEFT",
        (0.035, 0.13, 0.57, 0.91),
    )


def s05_gui_tabs_toolbar() -> Image.Image:
    image = new_frame(5, "GUI")
    heading(image, "Inspect, steer, stop, or resume", "Static crop sequence replaces the planned live pan")
    screenshot(image, "ai-loop-gui.png", (72, 318, 1848, 565), crop=(0.035, 0.04, 0.97, 0.20), contain=False)
    screenshot(image, "ai-loop-gui.png", (72, 602, 1848, 925), crop=(0.56, 0.13, 0.97, 0.83), contain=False)
    draw = ImageDraw.Draw(image)
    tag(draw, (120, 335), "TOOLBAR", GOLD)
    tag(draw, (120, 625), "PLAN • TASK • STATUS • CONTROLLER • WORKER • DETAILS • LOGS", CYAN)
    return image


def s06_quick_job_setup() -> Image.Image:
    image = new_frame(6, "Quick job")
    draw = ImageDraw.Draw(image)
    heading(image, "A small, testable goal", "Static screenshot composition — no live repository or private paths")
    screenshot(image, "ai-loop-gui.png", (72, 320, 1120, 925), crop=(0.035, 0.13, 0.57, 0.77), contain=False)
    panel(draw, (1160, 320, 1848, 925), fill="#0e2439")
    tag(draw, (1210, 368), "EXAMPLE GOAL", GOLD)
    wrapped_text(
        draw,
        (1210, 448),
        "Diagnose the failing test, repair it, and make the test suite pass.",
        face=font(36, bold=True),
        fill=INK,
        width=575,
        spacing=12,
    )
    bullet_list(
        draw,
        (1210, 680),
        ("Validation: auto", "Controller: claude", "Worker: codex", "Granularity: normal", "Isolated worktree: on"),
        width=570,
        size=24,
        gap=8,
    )
    return image


def s06_quick_job_progress() -> Image.Image:
    image = new_frame(6, "Quick job")
    draw = ImageDraw.Draw(image)
    heading(image, "Review progress as the loop runs", "A sanitized multi-frame substitute for the planned screen recording")
    tabs = (
        ("PLAN", "1. Diagnose failure\n2. Repair parser\n3. Run full suite", BLUE),
        ("TASK", "Current: repair edge case\nAcceptance: regression passes", GOLD),
        ("WORKER", "Changed: parser.py, test_parser.py\npytest: 42 passed", CYAN),
        ("LOGS", "$ pytest -q\n42 passed in 1.21s", GREEN),
    )
    x = 72
    for label, body, colour in tabs:
        panel(draw, (x, 354, x + 414, 855), fill="#0f2337")
        draw.rounded_rectangle((x, 354, x + 414, 418), radius=22, fill=colour)
        draw.text((x + 207, 386), label, font=font(25, bold=True), fill=BACKGROUND, anchor="mm")
        wrapped_text(draw, (x + 30, 472), body, face=font(25, mono=True), fill=INK, width=354, spacing=15)
        x += 446
    arrow(draw, (256, 897), (1655, 897), fill=CYAN, width=7)
    draw.text((960, 940), "controller review can produce another checked task", font=font(24), fill=MUTED, anchor="mm")
    return image


def s06_quick_job_complete() -> Image.Image:
    image = new_frame(6, "Quick job")
    draw = ImageDraw.Draw(image)
    heading(image, "Acceptance met", "The target checkout is validated after promotion")
    panel(draw, (260, 350, 1660, 875), fill="#0d263a", outline=GREEN, width=4)
    draw.ellipse((850, 410, 1070, 630), fill=GREEN)
    draw.line((905, 525, 952, 572), fill=BACKGROUND, width=18)
    draw.line((952, 572, 1024, 475), fill=BACKGROUND, width=18)
    draw.text((960, 696), "DONE", font=font(62, bold=True), fill=INK, anchor="mm")
    draw.text((960, 770), "42 tests passed  •  promotion complete  •  target validation passed", font=font(28), fill=MUTED, anchor="mm")
    return image


def two_screens(
    title: str,
    subtitle: str,
    left: str,
    right: str,
    left_tag: str,
    right_tag: str,
) -> Image.Image:
    image = new_frame(7, "Specification")
    heading(image, title, subtitle)
    screenshot(image, left, (72, 340, 940, 914))
    screenshot(image, right, (980, 340, 1848, 914))
    draw = ImageDraw.Draw(image)
    tag(draw, (105, 360), left_tag, BLUE)
    tag(draw, (1014, 360), right_tag, CYAN)
    return image


def s07_spec_overview() -> Image.Image:
    return two_screens(
        "Specification: an explicit contract",
        "Eight tabs organize the outcome, boundaries, behavior, proof, choices, and review",
        "specification-empty-new.png",
        "specification-overview-more-fields.png",
        "EIGHT-TAB OVERVIEW",
        "COMMON PATH",
    )


def s07_spec_guidance() -> Image.Image:
    image = new_frame(7, "Specification")
    draw = ImageDraw.Draw(image)
    heading(image, "Guidance appears where it is needed", "Field help sits beside the compact authoring workflow")
    screenshot(image, "specification-overview-more-fields.png", (72, 330, 1360, 925), contain=False)
    screenshot(image, "specification-field-help.png", (1280, 490, 1848, 889))
    tag(draw, (122, 360), "OVERVIEW FIELDS", BLUE)
    tag(draw, (1320, 520), "ON-DEMAND HELP", GOLD)
    return image


def s07_spec_scope() -> Image.Image:
    return two_screens(
        "Outcome first, boundaries second",
        "Describe the result, then make in-scope and out-of-scope work explicit",
        "specification-overview.png",
        "specification-scope.png",
        "OUTCOME",
        "SCOPE",
    )


def s07_spec_requirements() -> Image.Image:
    return two_screens(
        "Requirements must be testable",
        "Stable IDs, normative statements, acceptance criteria, and linked verification",
        "specification-requirements.png",
        "specification-requirement-dialog.png",
        "REQUIREMENT LIST",
        "EDIT + ACCEPTANCE",
    )


def s07_spec_choices_review() -> Image.Image:
    return two_screens(
        "Resolve choices, then review the gates",
        "Analyze the clean draft and use Review as the live completion checklist",
        "specification-choices.png",
        "specification-review.png",
        "CHOICES + ANALYZE",
        "COMPLETION CHECKLIST",
    )


def s07_spec_workflow() -> Image.Image:
    image = new_frame(7, "Specification")
    draw = ImageDraw.Draw(image)
    heading(image, "From draft to verified completion", "The approved version is pinned; linked verification carries runtime proof")
    screenshot(image, "specification-process-help.png", (72, 320, 700, 925))
    steps = ("SAVE DRAFT", "ANALYZE", "REVIEW", "APPROVE", "IMPLEMENT", "VERIFY", "DONE")
    y = 352
    for index, label in enumerate(steps):
        colour = (BLUE, CYAN, GOLD, PURPLE, BLUE, CYAN, GREEN)[index]
        draw.rounded_rectangle((820, y, 1740, y + 62), radius=26, fill=PANEL_LIGHT, outline=colour, width=3)
        draw.text((860, y + 31), f"{index + 1:02d}", font=font(22, bold=True), fill=colour, anchor="lm")
        draw.text((965, y + 31), label, font=font(25, bold=True), fill=INK, anchor="lm")
        if index < len(steps) - 1:
            arrow(draw, (1782, y + 31), (1782, y + 82), fill=colour, width=4)
        y += 82
    tag(draw, (105, 350), "PROCESS HELP", CYAN)
    return image


def s08_code_analysis() -> Image.Image:
    image = new_frame(8, "Code analysis")
    draw = ImageDraw.Draw(image)
    heading(image, "Turn analysis into observable acceptance", "Sanitized repository, test, worker-report, and GUI evidence in one view")
    panel(draw, (72, 330, 520, 920), fill="#0a1826")
    draw.text((112, 372), "REPOSITORY", font=font(23, bold=True), fill=BLUE)
    tree = "demo-project/\n├── src/\n│   └── parser.py\n├── tests/\n│   └── test_parser.py\n└── pyproject.toml"
    draw.multiline_text((112, 430), tree, font=font(25, mono=True), fill=INK, spacing=16)
    panel(draw, (550, 330, 1165, 590), fill="#080d13", outline=RED)
    draw.text((590, 370), "$ pytest -q", font=font(24, mono=True), fill=MUTED)
    draw.text((590, 430), "FAILED tests/test_parser.py::test_empty", font=font(22, mono=True), fill=RED)
    draw.text((590, 482), "Expected safe fallback; received exception", font=font(20, mono=True), fill=INK)
    panel(draw, (550, 620, 1165, 920), fill="#10273b", outline=GREEN)
    draw.text((590, 662), "WORKER REPORT", font=font(23, bold=True), fill=GREEN)
    bullet_list(draw, (590, 716), ("Changed src/parser.py", "Added regression coverage", "42 tests passed"), width=520, colour=GREEN, size=23, gap=12)
    screenshot(image, "ai-loop-gui.png", (1195, 330, 1848, 920), crop=(0.56, 0.13, 0.97, 0.83), contain=False)
    tag(draw, (1230, 360), "CONTROLLER • WORKER • DETAILS • LOGS", CYAN)
    return image


def s09_comparison() -> Image.Image:
    image = new_frame(9, "Choose the workflow")
    draw = ImageDraw.Draw(image)
    heading(image, "Direct model or AI-Loop?", "Match the workflow to the size and durability of the work")
    panel(draw, (72, 330, 906, 914), fill="#111f31", outline=BLUE)
    panel(draw, (1014, 330, 1848, 914), fill="#10283c", outline=CYAN)
    draw.text((489, 405), "DIRECT CODING MODEL", font=font(34, bold=True), fill=BLUE, anchor="mm")
    draw.text((1431, 405), "AI-LOOP", font=font(34, bold=True), fill=CYAN, anchor="mm")
    bullet_list(draw, (135, 490), ("One focused change", "One conversation", "Fast human review"), width=700, colour=BLUE, size=30, gap=35)
    bullet_list(draw, (1077, 490), ("Durable state", "Multiple reviewed tasks", "Repeated validation", "Unattended continuation"), width=700, colour=CYAN, size=30, gap=22)
    draw.text((960, 620), "OR", font=font(30, bold=True), fill=GOLD, anchor="mm")
    return image


def s09_repair_resume() -> Image.Image:
    image = new_frame(9, "Repair help")
    draw = ImageDraw.Draw(image)
    heading(image, "External help can repair a provider", "A static, sanitized substitute for the planned Fix binary / Fix It recording")
    screenshot(image, "ai-loop-gui.png", (72, 340, 1030, 916), crop=(0.56, 0.70, 0.98, 0.99), contain=False)
    steps = (
        ("1", "Provider needs attention", RED),
        ("2", "Select repair CLI", GOLD),
        ("3", "Fix binary / Fix It", BLUE),
        ("4", "Verify repair", PURPLE),
        ("5", "Resume same job", GREEN),
    )
    y = 365
    for number, label, colour in steps:
        draw.ellipse((1110, y, 1170, y + 60), fill=colour)
        draw.text((1140, y + 30), number, font=font(24, bold=True), fill=BACKGROUND, anchor="mm")
        draw.text((1210, y + 30), label, font=font(29, bold=True), fill=INK, anchor="lm")
        if number != "5":
            draw.line((1140, y + 66, 1140, y + 103), fill="#48667e", width=4)
        y += 108
    return image


def s09_feedback() -> Image.Image:
    image = new_frame(9, "Feedback")
    draw = ImageDraw.Draw(image)
    panel(draw, (150, 250, 1770, 870), fill="#0d263c", outline=CYAN, width=4)
    draw.text((960, 382), "Keep the goal clear.", font=font(59, bold=True), fill=INK, anchor="mm")
    draw.text((960, 468), "Keep the result testable.", font=font(59, bold=True), fill=CYAN, anchor="mm")
    draw.text((960, 615), "Questions, experience, and suggestions", font=font(31), fill=MUTED, anchor="mm")
    draw.rounded_rectangle((420, 676, 1500, 785), radius=50, fill=CYAN)
    draw.text((960, 730), EMAIL, font=font(43, bold=True), fill=BACKGROUND, anchor="mm")
    return image


BUILDERS: tuple[tuple[str, Callable[[], Image.Image]], ...] = (
    ("s01_title.png", s01_title),
    ("s01_presenter.png", s01_presenter),
    ("s01_repository.png", s01_repository),
    ("s02_mental_model.png", s02_mental_model),
    ("s03_architecture.png", s03_architecture),
    ("s03_promotion.png", s03_promotion),
    ("s04_email_thread.png", s04_email_thread),
    ("s05_gui_overview.png", s05_gui_overview),
    ("s05_gui_create_jobs.png", s05_gui_create_jobs),
    ("s05_gui_tabs_toolbar.png", s05_gui_tabs_toolbar),
    ("s06_quick_job_setup.png", s06_quick_job_setup),
    ("s06_quick_job_progress.png", s06_quick_job_progress),
    ("s06_quick_job_complete.png", s06_quick_job_complete),
    ("s07_spec_overview.png", s07_spec_overview),
    ("s07_spec_guidance.png", s07_spec_guidance),
    ("s07_spec_scope.png", s07_spec_scope),
    ("s07_spec_requirements.png", s07_spec_requirements),
    ("s07_spec_choices_review.png", s07_spec_choices_review),
    ("s07_spec_workflow.png", s07_spec_workflow),
    ("s08_code_analysis.png", s08_code_analysis),
    ("s09_comparison.png", s09_comparison),
    ("s09_repair_resume.png", s09_repair_resume),
    ("s09_feedback.png", s09_feedback),
)


def main() -> int:
    if tuple(name for name, _builder in BUILDERS) != ASSET_NAMES:
        raise RuntimeError("ASSET_NAMES and BUILDERS are inconsistent")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for name, builder in BUILDERS:
        save(name, builder())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
