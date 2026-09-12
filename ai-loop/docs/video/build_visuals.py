#!/usr/bin/env python3
"""Render the version 2 still-image sequence for the AI-Loop video.

Run from ``ai-loop``::

    python3 docs/video/build_visuals.py

The renderer uses only repository screenshots and deterministic Pillow
drawings. It does not capture a desktop, access a network, or create audio.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
IMAGE_DIR = ROOT / "docs" / "images"
OUTPUT = Path(__file__).resolve().parent / "assets"

WIDTH = 1920
HEIGHT = 1080
BACKGROUND = "#ffffff"
INK = "#172b3a"
MUTED = "#526574"
BLUE = "#0063a6"
LIGHT_BLUE = "#e8f3fa"
GREEN = "#2d8a58"
LIGHT_GREEN = "#e8f5ed"
ORANGE = "#d47716"
LIGHT_ORANGE = "#fff1df"
RED = "#bc3c3c"
LINE = "#b8c7d1"

FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
FONT_REGULAR = FONT_DIR / "DejaVuSans.ttf"
FONT_BOLD = FONT_DIR / "DejaVuSans-Bold.ttf"
FONT_MONO = FONT_DIR / "DejaVuSansMono.ttf"

ASSET_NAMES = (
    "s01_title.png",
    "s02_presenter.png",
    "s03_purpose.png",
    "s04_basic_idea.png",
    "s05_mental_model.png",
    "s06_actors.png",
    "s07_lifecycle.png",
    "s08_email.png",
    "s09_gui_overview.png",
    "s10_gui_create.png",
    "s11_gui_jobs.png",
    "s12_gui_plan.png",
    "s13_gui_task_controller.png",
    "s14_gui_worker.png",
    "s15_gui_logs.png",
    "s16_gui_repair.png",
    "s17_quick_job.png",
    "s18_quick_progress.png",
    "s19_spec_overview.png",
    "s20_spec_requirements.png",
    "s21_code_analysis.png",
    "s22_closing.png",
)


def font(size: int, *, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont:
    """Return the renderer's established system font choice."""
    path = FONT_MONO if mono else FONT_BOLD if bold else FONT_REGULAR
    if not path.is_file():
        raise RuntimeError(f"required font is missing: {path}")
    return ImageFont.truetype(str(path), size)


def university_wordmark(draw: ImageDraw.ImageDraw) -> None:
    """Draw the wordmark fallback; the repository has no university logo asset."""
    draw.rectangle((1510, 42, 1520, 126), fill=BLUE)
    draw.text((1542, 49), "UNIVERSITY", font=font(26, bold=True), fill=INK)
    draw.text((1542, 84), "OF VIENNA", font=font(26, bold=True), fill=BLUE)


def new_frame(title: str = "") -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)
    if title:
        draw.text((80, 54), title, font=font(52, bold=True), fill=INK)
        draw.line((80, 126, 1420, 126), fill=LINE, width=2)
    university_wordmark(draw)
    return image


def arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    fill: str = BLUE,
    width: int = 6,
) -> None:
    draw.line((*start, *end), fill=fill, width=width)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    length = 20
    spread = 0.55
    draw.polygon(
        (
            end,
            (
                round(end[0] - length * math.cos(angle - spread)),
                round(end[1] - length * math.sin(angle - spread)),
            ),
            (
                round(end[0] - length * math.cos(angle + spread)),
                round(end[1] - length * math.sin(angle + spread)),
            ),
        ),
        fill=fill,
    )


def box_label(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    title: str,
    detail: str = "",
    *,
    fill: str = LIGHT_BLUE,
    outline: str = BLUE,
) -> None:
    draw.rounded_rectangle(box, radius=20, fill=fill, outline=outline, width=3)
    x = (box[0] + box[2]) // 2
    y = (box[1] + box[3]) // 2
    draw.text((x, y - (18 if detail else 0)), title, font=font(28, bold=True), fill=INK, anchor="mm")
    if detail:
        draw.text((x, y + 29), detail, font=font(20), fill=MUTED, anchor="mm")


def tags(draw: ImageDraw.ImageDraw, values: Iterable[str]) -> None:
    """Draw short screenshot callouts in the white strip above the capture."""
    x = 80
    face = font(20, bold=True)
    for value in values:
        width = round(draw.textlength(value, font=face)) + 34
        draw.rounded_rectangle((x, 151, x + width, 193), radius=18, fill=LIGHT_BLUE)
        draw.text((x + 17, 172), value, font=face, fill=BLUE, anchor="lm")
        x += width + 16


def fit_rect(
    source_size: tuple[int, int],
    reserved: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    """Contain a source proportionally and verify the computed placement."""
    source_width, source_height = source_size
    left, top, right, bottom = reserved
    if source_width <= 0 or source_height <= 0 or right <= left or bottom <= top:
        raise RuntimeError(f"invalid screenshot geometry: source={source_size}, reserved={reserved}")
    scale = min((right - left) / source_width, (bottom - top) / source_height)
    rendered_width = max(1, round(source_width * scale))
    rendered_height = max(1, round(source_height * scale))
    x = left + ((right - left) - rendered_width) // 2
    y = top + ((bottom - top) - rendered_height) // 2
    placement = (x, y, x + rendered_width, y + rendered_height)
    if not (
        left <= placement[0] < placement[2] <= right
        and top <= placement[1] < placement[3] <= bottom
    ):
        raise RuntimeError(f"screenshot overflow: reserved={reserved}, placement={placement}")
    return placement


def load_screenshot(source_name: str) -> Image.Image:
    source_path = IMAGE_DIR / source_name
    if not source_path.is_file():
        raise RuntimeError(f"missing source screenshot: {source_path}")
    with Image.open(source_path) as opened:
        source = opened.convert("RGB")
    if source_name == "ai-loop-gui.png":
        # Sanitize the old capture's title-bar byline and private local path in
        # memory. The source file itself remains unchanged.
        draw = ImageDraw.Draw(source)
        draw.rectangle((280, 78, 2700, 145), fill="#f8f8f8")
        draw.text((305, 111), "AI-LOOP", font=font(32, bold=True), fill="#4f4f4f", anchor="lm")
        draw.rectangle((238, 297, 858, 346), fill="#ffffff", outline="#b8b8b8", width=2)
        draw.text((250, 321), "/example/demo-project", font=font(27), fill="#303030", anchor="lm")
    return source


def place_screenshot(
    image: Image.Image,
    source_name: str,
    reserved: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    source = load_screenshot(source_name)
    placement = fit_rect(source.size, reserved)
    rendered = source.resize(
        (placement[2] - placement[0], placement[3] - placement[1]),
        Image.Resampling.LANCZOS,
    )
    image.paste(rendered, placement[:2])
    return placement


def screenshot_slide(
    title: str,
    source_name: str,
    reserved: tuple[int, int, int, int],
    callouts: tuple[str, ...],
) -> Image.Image:
    image = new_frame(title)
    tags(ImageDraw.Draw(image), callouts)
    place_screenshot(image, source_name, reserved)
    return image


def s01_title() -> Image.Image:
    image = new_frame()
    draw = ImageDraw.Draw(image)
    draw.text((140, 245), "AI-Loop", font=font(116, bold=True), fill=INK)
    draw.text((145, 382), "Persistent, supervised coding-agent work", font=font(38), fill=BLUE)
    draw.text((145, 500), "Helmut Hlavacs", font=font(42, bold=True), fill=INK)
    draw.text((145, 559), "University of Vienna", font=font(34), fill=MUTED)
    steps = ("PLAN", "IMPLEMENT", "VALIDATE", "CONTINUE")
    centers = (285, 690, 1095, 1500)
    for index, (label, x) in enumerate(zip(steps, centers)):
        draw.ellipse((x - 102, 708, x + 102, 912), fill=LIGHT_BLUE, outline=BLUE, width=4)
        draw.text((x, 810), label, font=font(24, bold=True), fill=INK, anchor="mm")
        if index < len(centers) - 1:
            arrow(draw, (x + 112, 810), (centers[index + 1] - 112, 810))
    arrow(draw, (1500, 928), (285, 928), fill=GREEN, width=5)
    return image


def s02_presenter() -> Image.Image:
    image = new_frame("About Helmut Hlavacs")
    draw = ImageDraw.Draw(image)
    rows = (
        ("AFFILIATION", "University of Vienna"),
        ("UNIVERSITY WEBSITE", "https://www.univie.ac.at/"),
        ("UNIVERSITY EMAIL", "helmut.hlavacs@univie.ac.at"),
        ("GITHUB REPOSITORY", "https://github.com/hlavacs/AI-Loop"),
    )
    draw.rounded_rectangle((170, 220, 1750, 900), radius=28, fill=BACKGROUND, outline=LINE, width=2)
    y = 290
    for label, value in rows:
        draw.text((240, y), label, font=font(21, bold=True), fill=BLUE)
        draw.text((590, y - 8), value, font=font(32, bold=True), fill=INK)
        if y < 740:
            draw.line((240, y + 76, 1680, y + 76), fill=LINE, width=1)
        y += 150
    return image


def s03_purpose() -> Image.Image:
    image = new_frame("For work larger than one chat")
    draw = ImageDraw.Draw(image)
    box_label(draw, (120, 300, 700, 760), "SINGLE CHAT", "context ends")
    draw.line((260, 570, 560, 570), fill=RED, width=8)
    draw.line((530, 545, 560, 570, 530, 595), fill=RED, width=8)
    draw.text((410, 650), "unfinished", font=font(28, bold=True), fill=RED, anchor="mm")
    arrow(draw, (750, 530), (900, 530), fill=ORANGE)
    draw.text((825, 490), "instead", font=font(22, bold=True), fill=ORANGE, anchor="mm")
    draw.rounded_rectangle((950, 250, 1800, 810), radius=20, fill=LIGHT_GREEN, outline=GREEN, width=3)
    draw.text((1375, 330), "PERSISTENT JOB", font=font(28, bold=True), fill=INK, anchor="mm")
    draw.text((1375, 375), "several checked agent calls", font=font(20), fill=MUTED, anchor="mm")
    for x, label in zip((1080, 1290, 1500, 1710), ("1", "2", "3", "DONE")):
        draw.ellipse((x - 55, 470, x + 55, 580), fill="#ffffff", outline=GREEN, width=4)
        draw.text((x, 525), label, font=font(22, bold=True), fill=INK, anchor="mm")
    draw.line((1135, 525, 1235, 525, 1345, 525, 1445, 525, 1555, 525, 1655, 525), fill=GREEN, width=5)
    for x, value in zip((410, 960, 1510), ("LONG-RUNNING", "TESTABLE", "SUPERVISED")):
        draw.text((x, 885), value, font=font(25, bold=True), fill=BLUE, anchor="mm")
    return image


def s04_basic_idea() -> Image.Image:
    image = new_frame("One goal, checked in small steps")
    draw = ImageDraw.Draw(image)
    for label, y in (("REPOSITORY", 245), ("OUTCOME", 475), ("VALIDATION", 705)):
        box_label(draw, (100, y, 440, y + 120), label)
        arrow(draw, (450, y + 60), (650, 520))
    draw.ellipse((650, 300, 1320, 850), outline=BLUE, width=6)
    box_label(draw, (755, 390, 1045, 520), "CONTROLLER", "review")
    box_label(draw, (1055, 590, 1260, 720), "WORKER", "change", fill=LIGHT_GREEN, outline=GREEN)
    box_label(draw, (700, 650, 955, 780), "EVIDENCE", "checks", fill=LIGHT_ORANGE, outline=ORANGE)
    arrow(draw, (1048, 505), (1135, 585))
    arrow(draw, (1050, 690), (960, 710), fill=GREEN)
    arrow(draw, (790, 645), (830, 525), fill=ORANGE)
    for label, y, colour in (("DONE", 360, GREEN), ("HUMAN INPUT", 520, ORANGE), ("STOPPED", 680, RED)):
        box_label(draw, (1450, y, 1790, y + 110), label, fill="#ffffff", outline=colour)
        arrow(draw, (1325, 570), (1440, y + 55), fill=colour, width=4)
    return image


def s05_mental_model() -> Image.Image:
    image = new_frame("A supervised team with durable memory")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((740, 390, 1180, 730), radius=24, fill=LIGHT_BLUE, outline=BLUE, width=4)
    draw.rectangle((820, 455, 1100, 670), fill="#ffffff", outline=LINE, width=2)
    draw.text((960, 560), "SHARED\nNOTEBOOK", font=font(34, bold=True), fill=INK, anchor="mm", align="center", spacing=12)
    nodes = (
        ((120, 250, 480, 390), "CONTROLLER", "review + plan"),
        ((1440, 250, 1800, 390), "WORKER", "implement"),
        ((120, 735, 480, 875), "TESTS", "observable progress"),
        ((1440, 735, 1800, 875), "WORKTREE", "workshop"),
    )
    for box, title, detail in nodes:
        box_label(draw, box, title, detail)
        x = (box[0] + box[2]) // 2
        y = (box[1] + box[3]) // 2
        arrow(draw, (x + (180 if x < 960 else -180), y), (735 if x < 960 else 1185, 560), width=4)
    arrow(draw, (690, 900), (1230, 900), fill=GREEN)
    arrow(draw, (1230, 950), (690, 950), fill=GREEN)
    draw.text((960, 925), "PAUSE   /   RESUME", font=font(23, bold=True), fill=GREEN, anchor="mm")
    return image


def s06_actors() -> Image.Image:
    image = new_frame("Controller, worker, watcher")
    draw = ImageDraw.Draw(image)
    draw.ellipse((690, 325, 1230, 825), fill=LIGHT_BLUE, outline=BLUE, width=5)
    draw.text((960, 535), "DURABLE", font=font(34, bold=True), fill=INK, anchor="mm")
    draw.text((960, 585), "JOB RECORD", font=font(34, bold=True), fill=INK, anchor="mm")
    box_label(draw, (100, 270, 520, 430), "CONTROLLER", "plan + review")
    box_label(draw, (1400, 270, 1820, 430), "WORKER", "edit + test", fill=LIGHT_GREEN, outline=GREEN)
    box_label(draw, (750, 850, 1170, 990), "WATCHER", "status + replies", fill=LIGHT_ORANGE, outline=ORANGE)
    arrow(draw, (530, 350), (700, 440))
    arrow(draw, (1390, 350), (1220, 440), fill=GREEN)
    arrow(draw, (960, 840), (960, 790), fill=ORANGE)
    box_label(draw, (155, 600, 475, 715), "SQLITE", "durable state", fill="#ffffff")
    box_label(draw, (1445, 600, 1765, 715), "REDIS STREAMS", "coordination", fill="#ffffff")
    box_label(draw, (1420, 800, 1790, 915), "GIT WORKTREE", "isolated", fill="#ffffff", outline=GREEN)
    return image


def s07_lifecycle() -> Image.Image:
    image = new_frame("A job has an explicit lifecycle")
    draw = ImageDraw.Draw(image)
    labels = ("PLANNING", "QUEUED", "IMPLEMENTING", "PROMOTION", "VALIDATION", "DONE")
    centers = (170, 480, 790, 1100, 1410, 1720)
    for index, (label, x) in enumerate(zip(labels, centers)):
        colour = GREEN if label == "DONE" else BLUE
        fill = LIGHT_GREEN if label == "DONE" else LIGHT_BLUE
        draw.ellipse((x - 92, 420, x + 92, 604), fill=fill, outline=colour, width=4)
        draw.text((x, 512), label, font=font(20, bold=True), fill=INK, anchor="mm")
        if index < len(centers) - 1:
            arrow(draw, (x + 102, 512), (centers[index + 1] - 102, 512), fill=colour, width=5)
    box_label(draw, (560, 760, 900, 875), "WAITING", "retry later", fill=LIGHT_ORANGE, outline=ORANGE)
    box_label(draw, (960, 760, 1340, 875), "HUMAN NEEDED", "authorized choice", fill=LIGHT_ORANGE, outline=ORANGE)
    arrow(draw, (790, 614), (730, 750), fill=ORANGE, width=4)
    arrow(draw, (930, 614), (1080, 750), fill=ORANGE, width=4)
    return image


def s08_email() -> Image.Image:
    image = new_frame("The loop reports back")
    draw = ImageDraw.Draw(image)
    draw.line((250, 460, 1670, 460), fill=LINE, width=6)
    messages = (
        (300, "START", "09:00", BLUE),
        (700, "12-HOUR STATUS", "21:00", BLUE),
        (1100, "ATTENTION", "21:14", ORANGE),
        (1500, "COMPLETION", "22:06", GREEN),
    )
    for x, label, time, colour in messages:
        draw.ellipse((x - 62, 398, x + 62, 522), fill="#ffffff", outline=colour, width=6)
        draw.text((x, 460), "@", font=font(34, bold=True), fill=colour, anchor="mm")
        draw.text((x, 570), label, font=font(23, bold=True), fill=INK, anchor="mm")
        draw.text((x, 612), time, font=font(20), fill=MUTED, anchor="mm")
    box_label(draw, (755, 760, 1165, 890), "REPLY", "becomes a constraint", fill=LIGHT_GREEN, outline=GREEN)
    arrow(draw, (1100, 630), (1000, 750), fill=GREEN)
    return image


def s09_gui_overview() -> Image.Image:
    return screenshot_slide("One window for creating and supervising jobs", "ai-loop-gui.png", (100, 220, 1820, 980), ("CREATE", "JOB LIST", "INSPECT"))


def s10_gui_create() -> Image.Image:
    return screenshot_slide("Define the job", "ai-loop-gui.png", (180, 210, 1740, 990), ("GOAL", "VALIDATION", "ROLES", "ISOLATION"))


def s11_gui_jobs() -> Image.Image:
    return screenshot_slide("Find the job and read its state", "s11-gui-jobs-status.png", (120, 210, 1800, 990), ("SELECTED JOB", "STATE", "PROGRESS SUMMARY"))


def s12_gui_plan() -> Image.Image:
    return screenshot_slide("The plan preserves direction", "s12-gui-plan.png", (140, 210, 1780, 990), ("OVERALL OUTCOME", "STAGES", "ACCEPTANCE"))


def s13_gui_task_controller() -> Image.Image:
    return screenshot_slide("Instructions and review stay separate", "s13-gui-task-controller.png", (140, 210, 1780, 990), ("CURRENT ASSIGNMENT", "ACCEPTANCE", "NEXT DECISION"))


def s14_gui_worker() -> Image.Image:
    return screenshot_slide("See what changed and how it was checked", "s14-gui-worker-details.png", (140, 210, 1780, 990), ("RESULT", "CHANGED FILES", "VALIDATION EVIDENCE"))


def s15_gui_logs() -> Image.Image:
    return screenshot_slide("Inspect deeply or change course", "s15-gui-logs-controls.png", (140, 210, 1780, 990), ("LOGS", "RESUME", "FINISH SOON", "FINISH EARLY"))


def s16_gui_repair() -> Image.Image:
    return screenshot_slide("Repair the tool, keep the job", "s16-gui-provider-repair.png", (300, 210, 1620, 970), ("DETECTED PROBLEM", "ASSISTED ACTION", "RESUME SAME JOB"))


def s17_quick_job() -> Image.Image:
    return screenshot_slide("Quick job: repair one failing test", "s17-quick-job-form.png", (220, 210, 1700, 990), ("NARROW GOAL", "TEST COMMAND", "NORMAL GRANULARITY"))


def s18_quick_progress() -> Image.Image:
    return screenshot_slide("Follow evidence to completion", "s18-quick-job-complete.png", (140, 210, 1780, 990), ("CURRENT TASK", "WORKER RESULT", "FINAL VALIDATION"))


def s19_spec_overview() -> Image.Image:
    return screenshot_slide("Turn a goal into a testable contract", "specification-overview.png", (140, 210, 1780, 990), ("OUTCOME", "BOUNDARIES", "ASSUMPTIONS"))


def s20_spec_requirements() -> Image.Image:
    return screenshot_slide("Connect requirements to proof", "specification-requirements.png", (140, 210, 1780, 990), ("IDENTIFIER", "ACCEPTANCE CRITERION", "LINKED VERIFICATION"))


def s21_code_analysis() -> Image.Image:
    image = new_frame("Analysis should end in evidence")
    draw = ImageDraw.Draw(image)
    stages = (
        ("REPOSITORY", "source + tests", BLUE),
        ("DIAGNOSIS", "find the cause", ORANGE),
        ("FOCUSED CHANGE", "small repair", BLUE),
        ("PASSING TEST", "checked outcome", GREEN),
    )
    centers = (260, 720, 1200, 1660)
    for index, ((title, detail, colour), x) in enumerate(zip(stages, centers)):
        fill = LIGHT_GREEN if colour == GREEN else LIGHT_ORANGE if colour == ORANGE else LIGHT_BLUE
        box_label(draw, (x - 185, 380, x + 185, 610), title, detail, fill=fill, outline=colour)
        if index < len(centers) - 1:
            arrow(draw, (x + 195, 495), (centers[index + 1] - 195, 495), fill=colour)
    for x, label in zip((380, 960, 1540), ("REGRESSION FIXED", "COVERAGE ADDED", "MIGRATION CHECKED")):
        draw.text((x, 790), label, font=font(24, bold=True), fill=BLUE, anchor="mm")
    return image


def s22_closing() -> Image.Image:
    image = new_frame("Choose the right level of support")
    draw = ImageDraw.Draw(image)
    paths = (
        ("DIRECT LLM", "one focused change", BLUE),
        ("AI-LOOP", "durable reviewed work", GREEN),
        ("EXTERNAL LLM REPAIR", "fix, then resume", ORANGE),
    )
    y = 245
    for title, detail, colour in paths:
        fill = LIGHT_GREEN if colour == GREEN else LIGHT_ORANGE if colour == ORANGE else LIGHT_BLUE
        box_label(draw, (155, y, 760, y + 150), title, detail, fill=fill, outline=colour)
        arrow(draw, (780, y + 75), (1010, y + 75), fill=colour)
        y += 205
    draw.text((1080, 315), "FEEDBACK", font=font(23, bold=True), fill=BLUE)
    draw.text((1080, 365), "helmut.hlavacs@univie.ac.at", font=font(29, bold=True), fill=INK)
    draw.text((1080, 475), "OPEN SOURCE", font=font(23, bold=True), fill=BLUE)
    draw.text((1080, 525), "https://github.com/hlavacs/AI-Loop", font=font(27, bold=True), fill=INK)
    draw.line((1080, 650, 1780, 650), fill=LINE, width=2)
    draw.text((1080, 725), "RELATED WORK", font=font(23, bold=True), fill=BLUE)
    draw.text((1080, 785), "Robimo.at", font=font(52, bold=True), fill=INK)
    return image


BUILDERS: tuple[tuple[str, Callable[[], Image.Image]], ...] = (
    ("s01_title.png", s01_title),
    ("s02_presenter.png", s02_presenter),
    ("s03_purpose.png", s03_purpose),
    ("s04_basic_idea.png", s04_basic_idea),
    ("s05_mental_model.png", s05_mental_model),
    ("s06_actors.png", s06_actors),
    ("s07_lifecycle.png", s07_lifecycle),
    ("s08_email.png", s08_email),
    ("s09_gui_overview.png", s09_gui_overview),
    ("s10_gui_create.png", s10_gui_create),
    ("s11_gui_jobs.png", s11_gui_jobs),
    ("s12_gui_plan.png", s12_gui_plan),
    ("s13_gui_task_controller.png", s13_gui_task_controller),
    ("s14_gui_worker.png", s14_gui_worker),
    ("s15_gui_logs.png", s15_gui_logs),
    ("s16_gui_repair.png", s16_gui_repair),
    ("s17_quick_job.png", s17_quick_job),
    ("s18_quick_progress.png", s18_quick_progress),
    ("s19_spec_overview.png", s19_spec_overview),
    ("s20_spec_requirements.png", s20_spec_requirements),
    ("s21_code_analysis.png", s21_code_analysis),
    ("s22_closing.png", s22_closing),
)


def save(name: str, image: Image.Image) -> None:
    if image.size != (WIDTH, HEIGHT):
        raise RuntimeError(f"invalid frame size for {name}: {image.size}")
    image.save(OUTPUT / name, format="PNG", compress_level=9)
    print(f"{name}: {image.width}x{image.height}")


def main() -> int:
    if tuple(name for name, _builder in BUILDERS) != ASSET_NAMES:
        raise RuntimeError("ASSET_NAMES and BUILDERS are inconsistent")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    expected = set(ASSET_NAMES)
    for stale in OUTPUT.glob("*.png"):
        if stale.name not in expected:
            stale.unlink()
    for name, builder in BUILDERS:
        save(name, builder())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
