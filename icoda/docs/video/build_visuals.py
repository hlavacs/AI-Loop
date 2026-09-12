#!/usr/bin/env python3
"""Render the 27 still images for the ICODA introduction video.

Run from the ICODA repository root::

    python3 docs/video/build_visuals.py

The renderer uses deterministic Pillow drawings and the existing handbook
screenshots.  It creates no audio or video.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlretrieve

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
IMAGE_DIR = ROOT / "docs" / "images" / "handbook"
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
LINE = "#b8c7d1"
PALE = "#f5f8fa"

FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
FONT_REGULAR = FONT_DIR / "DejaVuSans.ttf"
FONT_BOLD = FONT_DIR / "DejaVuSans-Bold.ttf"
FONT_MONO = FONT_DIR / "DejaVuSansMono.ttf"

LOGO_URL = (
    "https://www.univie.ac.at/fileadmin/user_upload/univie/Logos/"
    "Logos_Universitaet_Wien/Uni_Logo.png"
)
LOGO_DOWNLOAD = OUTPUT / "Uni_Logo.png"
LOGO_RECT = (1590, 35, 1840, 135)

ASSET_NAMES = (
    "s01_title.png",
    "s02_presenter.png",
    "s03_purpose.png",
    "s04_basic_idea.png",
    "s05_mental_model.png",
    "s06_workflow.png",
    "s07_gui_overview.png",
    "s08_file_view.png",
    "s09_call_view.png",
    "s10_class_view.png",
    "s11_mind_map.png",
    "s12_coverage.png",
    "s13_issues.png",
    "s14_provider_selection.png",
    "s15_architecture_step.png",
    "s16_proposal_evidence.png",
    "s17_developer_decision.png",
    "s18_quick_architecture.png",
    "s19_quick_approach.png",
    "s20_quick_result.png",
    "s21_spec_overview.png",
    "s22_spec_scope.png",
    "s23_spec_requirements.png",
    "s24_spec_code_profile.png",
    "s25_code_analysis.png",
    "s26_llm_choices.png",
    "s27_closing.png",
)

SCREENSHOT_SPECS = {
    "s07_gui_overview": (
        "sim-10-terminal-overview.png",
        (70, 180, 1850, 1030),
    ),
    "s08_file_view": ("python-file-view.png", (70, 180, 1850, 1030)),
    "s09_call_view": ("uncertain-dynamic-call.png", (70, 180, 1850, 1030)),
    "s10_class_view": ("python-class-view.png", (70, 180, 1850, 1030)),
    "s11_mind_map": ("mind-map.png", (70, 180, 1850, 1030)),
    "s12_coverage": ("requirements-coverage.png", (70, 180, 1850, 1030)),
    "s13_issues": ("rule-issues.png", (70, 180, 1850, 1030)),
    "s14_provider_selection": ("provider-selection.png", (70, 180, 1850, 1030)),
    "s16_proposal_evidence": ("proposal-source-diff.png", (70, 180, 1850, 1030)),
    "s17_developer_decision": ("signature-confirmation.png", (70, 180, 1850, 1030)),
    "s18_quick_architecture": ("sim-04-architecture-approve.png", (70, 180, 1850, 1030)),
    "s19_quick_approach": ("implementation-approach.png", (70, 180, 1850, 1030)),
    "s20_quick_result": ("sim-07-normalize-build-test.png", (70, 180, 1850, 1030)),
    "s21_spec_overview": ("specification-overview.png", (160, 180, 1760, 1030)),
    "s22_spec_scope": ("specification-scope.png", (160, 180, 1760, 1030)),
    "s23_spec_requirements": ("specification-requirements.png", (160, 180, 1760, 1030)),
    "s24_spec_code_profile": ("specification-code-profile.png", (160, 180, 1760, 1030)),
    "s25_code_analysis": ("diagram-filtered.png", (70, 180, 1850, 1030)),
}

_logo_image: Image.Image | None = None
_logo_source = ""


def font(size: int, *, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont:
    """Return the renderer's system font choice."""
    path = FONT_MONO if mono else FONT_BOLD if bold else FONT_REGULAR
    if not path.is_file():
        raise RuntimeError(f"required font is missing: {path}")
    return ImageFont.truetype(str(path), size)


def fit_rect(
    source_size: tuple[int, int],
    reserved: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    """Contain a source proportionally and assert that no edge overflows."""
    source_width, source_height = source_size
    left, top, right, bottom = reserved
    if source_width <= 0 or source_height <= 0 or right <= left or bottom <= top:
        raise RuntimeError(f"invalid image geometry: source={source_size}, reserved={reserved}")
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
        raise RuntimeError(f"image overflow: reserved={reserved}, placement={placement}")
    return placement


def prepare_logo() -> None:
    """Download and cache the official logo, with the documented fallback."""
    global _logo_image, _logo_source
    OUTPUT.mkdir(parents=True, exist_ok=True)
    try:
        if not LOGO_DOWNLOAD.is_file():
            urlretrieve(LOGO_URL, LOGO_DOWNLOAD)
        with Image.open(LOGO_DOWNLOAD) as opened:
            _logo_image = opened.convert("RGBA")
        _logo_source = "official University of Vienna logo"
    except (OSError, URLError) as exc:
        _logo_image = None
        _logo_source = f"drawn wordmark fallback ({exc})"
    finally:
        # Keep assets/ as the requested 27-slide sequence.  The downloaded
        # logo has already been decoded into memory for this render.
        LOGO_DOWNLOAD.unlink(missing_ok=True)
    print(f"branding: {_logo_source}")


def university_wordmark(draw: ImageDraw.ImageDraw) -> None:
    """Draw the AI-Loop renderer's blue wordmark fallback."""
    left, top, right, bottom = LOGO_RECT
    draw.rectangle((left + 4, top + 8, left + 12, bottom - 8), fill=BLUE)
    draw.text((left + 32, top + 20), "UNIVERSITY", font=font(22, bold=True), fill=INK)
    draw.text((left + 32, top + 53), "OF VIENNA", font=font(22, bold=True), fill=BLUE)


def university_brand(image: Image.Image) -> None:
    """Place the complete official logo inside the common logo rectangle."""
    if _logo_image is None:
        university_wordmark(ImageDraw.Draw(image))
        return
    placement = fit_rect(_logo_image.size, LOGO_RECT)
    rendered = _logo_image.resize(
        (placement[2] - placement[0], placement[3] - placement[1]),
        Image.Resampling.LANCZOS,
    )
    image.paste(rendered, placement[:2], rendered)


def new_frame(title: str = "") -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)
    if title:
        draw.text((80, 48), title, font=font(46, bold=True), fill=INK)
        draw.line((80, 132, 1480, 132), fill=LINE, width=2)
    university_brand(image)
    return image


def arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    fill: str = BLUE,
    width: int = 5,
) -> None:
    draw.line((*start, *end), fill=fill, width=width)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    length = 18
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
    title_size: int = 25,
) -> None:
    draw.rounded_rectangle(box, radius=18, fill=fill, outline=outline, width=3)
    x = (box[0] + box[2]) // 2
    y = (box[1] + box[3]) // 2
    draw.text((x, y - (16 if detail else 0)), title, font=font(title_size, bold=True), fill=INK, anchor="mm")
    if detail:
        draw.text((x, y + 27), detail, font=font(19), fill=MUTED, anchor="mm")


def tags(draw: ImageDraw.ImageDraw, values: Iterable[str]) -> None:
    """Draw short labels only in the white strip above a screenshot."""
    x = 80
    face = font(17, bold=True)
    for value in values:
        width = round(draw.textlength(value, font=face)) + 28
        draw.rounded_rectangle((x, 145, x + width, 175), radius=14, fill=LIGHT_BLUE)
        draw.text((x + 14, 160), value, font=face, fill=BLUE, anchor="lm")
        x += width + 12


def place_screenshot(
    image: Image.Image,
    slide_id: str,
) -> tuple[int, int, int, int]:
    source_name, reserved = SCREENSHOT_SPECS[slide_id]
    source_path = IMAGE_DIR / source_name
    if not source_path.is_file():
        raise RuntimeError(f"missing source screenshot: {source_path}")
    with Image.open(source_path) as opened:
        source = opened.convert("RGB")
    placement = fit_rect(source.size, reserved)
    rendered = source.resize(
        (placement[2] - placement[0], placement[3] - placement[1]),
        Image.Resampling.LANCZOS,
    )
    image.paste(rendered, placement[:2])
    source_ratio = source.width / source.height
    rendered_ratio = rendered.width / rendered.height
    ratio_error = abs(rendered_ratio - source_ratio) / source_ratio
    if ratio_error > 0.001:
        raise RuntimeError(
            f"aspect-ratio drift for {slide_id}: source={source.size}, rendered={rendered.size}"
        )
    print(
        f"{slide_id}: source={source.width}x{source.height} "
        f"target={reserved} rendered={rendered.width}x{rendered.height} "
        f"edges={placement} ratio_error={ratio_error:.6f}"
    )
    return placement


def screenshot_slide(slide_id: str, title: str, callouts: tuple[str, ...]) -> Image.Image:
    image = new_frame(title)
    tags(ImageDraw.Draw(image), callouts)
    place_screenshot(image, slide_id)
    return image


def s01_title() -> Image.Image:
    image = new_frame()
    draw = ImageDraw.Draw(image)
    draw.text((120, 230), "ICODA", font=font(108, bold=True), fill=INK)
    draw.text((125, 350), "Interactive Code Development and Analysis", font=font(37), fill=BLUE)
    draw.text((125, 455), "Helmut Hlavacs", font=font(37, bold=True), fill=INK)
    draw.text((125, 510), "University of Vienna", font=font(30), fill=MUTED)
    draw.text((125, 560), "https://entertain.univie.ac.at/~hlavacs/", font=font(25), fill=MUTED)
    labels = ("SPECIFICATION", "PROPOSAL", "EVIDENCE", "DECISION")
    centers = (280, 710, 1140, 1570)
    for index, (label, x) in enumerate(zip(labels, centers)):
        draw.ellipse((x - 100, 650, x + 100, 850), fill=LIGHT_BLUE, outline=BLUE, width=4)
        draw.text((x, 750), label, font=font(20, bold=True), fill=INK, anchor="mm")
        if index < len(centers) - 1:
            arrow(draw, (x + 110, 750), (centers[index + 1] - 110, 750))
    arrow(draw, (1570, 875), (280, 875), width=4)
    return image


def s02_presenter() -> Image.Image:
    image = new_frame("About Helmut Hlavacs")
    draw = ImageDraw.Draw(image)
    rows = (
        ("NAME", "Helmut Hlavacs"),
        ("AFFILIATION", "Faculty of Computer Science, University of Vienna"),
        ("UNIVERSITY", "https://www.univie.ac.at/"),
        ("EMAIL", "helmut.hlavacs@univie.ac.at"),
        ("GITHUB", "https://github.com/hlavacs/AI-Loop/tree/main/icoda"),
        ("WEB PAGE", "https://entertain.univie.ac.at/~hlavacs/"),
    )
    draw.rounded_rectangle((180, 225, 1740, 900), radius=24, outline=LINE, width=2)
    y = 275
    for index, (label, value) in enumerate(rows):
        draw.ellipse((225, y - 4, 251, y + 22), fill=LIGHT_BLUE, outline=BLUE, width=2)
        draw.text((280, y), label, font=font(18, bold=True), fill=BLUE)
        draw.text((535, y - 6), value, font=font(27, bold=True), fill=INK)
        if index < len(rows) - 1:
            draw.line((225, y + 58, 1695, y + 58), fill=LINE, width=1)
        y += 100
    return image


def s03_purpose() -> Image.Image:
    image = new_frame("Small, visible steps")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((120, 250, 750, 885), radius=24, fill=PALE, outline=LINE, width=3)
    draw.text((435, 315), "ONE LARGE CHANGE", font=font(27, bold=True), fill=INK, anchor="mm")
    draw.rectangle((235, 420, 635, 695), fill="#dce3e8", outline=MUTED, width=3)
    draw.text((435, 558), "?", font=font(94, bold=True), fill=MUTED, anchor="mm")
    draw.text((435, 775), "opaque consequences", font=font(24), fill=MUTED, anchor="mm")
    draw.rounded_rectangle((850, 250, 1800, 885), radius=24, fill=BACKGROUND, outline=BLUE, width=3)
    draw.text((1325, 315), "FOUR CHECKED STEPS", font=font(27, bold=True), fill=INK, anchor="mm")
    labels = ("ARCHITECTURE", "BUILD", "TESTS", "APPROVAL")
    xs = (985, 1215, 1445, 1675)
    for index, (label, x) in enumerate(zip(labels, xs)):
        draw.ellipse((x - 74, 475, x + 74, 623), fill=LIGHT_BLUE, outline=BLUE, width=3)
        draw.text((x, 549), str(index + 1), font=font(34, bold=True), fill=BLUE, anchor="mm")
        draw.text((x, 690), label, font=font(17, bold=True), fill=INK, anchor="mm")
        if index < 3:
            arrow(draw, (x + 82, 549), (xs[index + 1] - 82, 549), width=4)
    return image


def s04_basic_idea() -> Image.Image:
    image = new_frame("Truth into a checked proposal")
    draw = ImageDraw.Draw(image)
    box_label(draw, (100, 250, 390, 380), "SPECIFICATION", "what should exist")
    box_label(draw, (100, 540, 390, 670), "SOURCE", "what exists")
    arrow(draw, (400, 315), (570, 440))
    arrow(draw, (400, 605), (570, 480))
    box_label(draw, (580, 365, 910, 555), "DERIVED MODEL", "files • classes • calls")
    box_label(draw, (580, 690, 910, 835), "LLM PROPOSAL", "isolated worktree")
    arrow(draw, (745, 565), (745, 680))
    gate_names = ("BUILD", "TESTS", "PARSE", "COMPARE")
    gate_xs = (1060, 1260, 1460, 1660)
    for index, (label, x) in enumerate(zip(gate_names, gate_xs)):
        box_label(draw, (x - 78, 405, x + 78, 535), label, title_size=18)
        if index < 3:
            arrow(draw, (x + 84, 470), (gate_xs[index + 1] - 84, 470), width=4)
    arrow(draw, (920, 760), (1060, 545))
    box_label(draw, (1180, 690, 1740, 835), "DEVELOPER DECISION", "approve • reject • adapt • edit")
    arrow(draw, (1660, 545), (1510, 680))
    return image


def s05_mental_model() -> Image.Image:
    image = new_frame("A workbench with a live map")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((440, 225, 1480, 440), radius=26, fill=LIGHT_BLUE, outline=BLUE, width=4)
    draw.text((960, 295), "LIVE MAP", font=font(35, bold=True), fill=INK, anchor="mm")
    draw.text((960, 360), "files  •  classes  •  functions  •  calls  •  tests", font=font(23), fill=MUTED, anchor="mm")
    arrow(draw, (960, 450), (960, 535))
    draw.rounded_rectangle((510, 535, 1410, 840), radius=28, fill=PALE, outline=BLUE, width=4)
    draw.text((960, 620), "ISOLATED WORKBENCH", font=font(31, bold=True), fill=INK, anchor="mm")
    box_label(draw, (630, 700, 930, 825), "CANDIDATE", "outside real project")
    box_label(draw, (1010, 700, 1290, 825), "EVIDENCE", "measured from code")
    draw.text((270, 580), "LLM proposes", font=font(23, bold=True), fill=BLUE, anchor="mm")
    arrow(draw, (360, 610), (505, 680))
    draw.text((1650, 580), "ICODA measures", font=font(23, bold=True), fill=BLUE, anchor="mm")
    arrow(draw, (1560, 610), (1415, 680))
    draw.text((960, 880), "developer decides", font=font(25, bold=True), fill=BLUE, anchor="mm")
    arrow(draw, (960, 860), (960, 840))
    return image


def s06_workflow() -> Image.Image:
    image = new_frame("Specification to implementation")
    draw = ImageDraw.Draw(image)
    phases = ((300, "SPECIFICATION"), (960, "ARCHITECTURE"), (1620, "IMPLEMENTATION"))
    for index, (x, label) in enumerate(phases):
        draw.ellipse((x - 130, 260, x + 130, 520), fill=LIGHT_BLUE, outline=BLUE, width=4)
        draw.text((x, 390), label, font=font(23, bold=True), fill=INK, anchor="mm")
        if index < 2:
            arrow(draw, (x + 142, 390), (phases[index + 1][0] - 142, 390))
    draw.text((100, 635), "EACH ACCEPTED STEP", font=font(19, bold=True), fill=BLUE)
    gates = ("WORKTREE", "BUILD", "TESTS", "PARSE / DELTA", "DECISION", "GIT COMMIT")
    xs = (220, 510, 780, 1080, 1400, 1700)
    for index, (x, label) in enumerate(zip(xs, gates)):
        box_label(draw, (x - 105, 690, x + 105, 810), label, title_size=17)
        if index < len(xs) - 1:
            arrow(draw, (x + 112, 750), (xs[index + 1] - 112, 750), width=4)
    return image


def s07_gui_overview() -> Image.Image:
    return screenshot_slide("s07_gui_overview", "One window, one checked lifecycle", ("ANALYSIS VIEWS", "LLM + ENTITIES", "WORKFLOW + EVIDENCE"))


def s08_file_view() -> Image.Image:
    return screenshot_slide("s08_file_view", "Files and entities at a glance", ("VIEW TABS", "EXPANDABLE HIERARCHY", "SELECTED ENTITIES"))


def s09_call_view() -> Image.Image:
    return screenshot_slide("s09_call_view", "Calls include uncertainty", ("FIXED TARGET", "DASHED = UNCERTAIN", "DEPTH + STATUS"))


def s10_class_view() -> Image.Image:
    return screenshot_slide("s10_class_view", "Classes, methods, and signatures", ("service.Store", "load SIGNATURE", "HIERARCHY + STATUS"))


def s11_mind_map() -> Image.Image:
    return screenshot_slide("s11_mind_map", "The project as a mind map", ("STRUCTURE + REQUIREMENTS + STEP HISTORY",))


def s12_coverage() -> Image.Image:
    return screenshot_slide("s12_coverage", "Coverage connects intent and tests", ("SPECIFICATION LINKS", "RECORDED TEST REACHABILITY"))


def s13_issues() -> Image.Image:
    return screenshot_slide("s13_issues", "Issues point back to code", ("SEVERITY + RULE", "ENTITY + ACTION", "SOURCE LOCATION"))


def s14_provider_selection() -> Image.Image:
    return screenshot_slide("s14_provider_selection", "Choose the model for each step", ("PROVIDER", "BINARY", "MODEL"))


def s15_architecture_step() -> Image.Image:
    image = new_frame("One bounded architecture step")
    draw = ImageDraw.Draw(image)
    steps = (
        (220, "REQUEST", "small change"),
        (560, "ENTITY BUDGET", "maximum size"),
        (920, "CANDIDATE", "isolated"),
        (1280, "CHECKED", "build • tests • parse"),
        (1660, "DELTA", "measured"),
    )
    for index, (x, title, detail) in enumerate(steps):
        colour = GREEN if title == "CHECKED" else BLUE
        fill = LIGHT_GREEN if title == "CHECKED" else LIGHT_BLUE
        box_label(draw, (x - 135, 360, x + 135, 530), title, detail, fill=fill, outline=colour, title_size=21)
        if index < len(steps) - 1:
            arrow(draw, (x + 142, 445), (steps[index + 1][0] - 142, 445), fill=colour)
    for x, label in zip((600, 960, 1320), ("APPROVE", "REJECT", "ADAPT")):
        box_label(draw, (x - 140, 710, x + 140, 835), label, fill=BACKGROUND, title_size=21)
        arrow(draw, (1660, 545), (x, 700), width=4)
    return image


def s16_proposal_evidence() -> Image.Image:
    return screenshot_slide("s16_proposal_evidence", "Review source and evidence together", ("SOURCE DIFF", "REVIEW TABS", "BUILD + TESTS PASSED"))


def s17_developer_decision() -> Image.Image:
    return screenshot_slide("s17_developer_decision", "The developer makes the decision", ("EXPLICIT API GATE", "SIGNATURE CHANGES", "DECISION CONTROLS"))


def s18_quick_architecture() -> Image.Image:
    return screenshot_slide("s18_quick_architecture", "Quick job: add one small shape", ("Formatter.normalize", "THREE-ENTITY DELTA", "PASSING GATES"))


def s19_quick_approach() -> Image.Image:
    return screenshot_slide("s19_quick_approach", "Approve the approach before code", ("APPROACH", "PROSE PLAN", "AWAITING APPROVAL"))


def s20_quick_result() -> Image.Image:
    return screenshot_slide("s20_quick_result", "Code, test, and measured result", ("SOURCE + TEST", "MEASURED DELTA", "GATES PASSED"))


def s21_spec_overview() -> Image.Image:
    return screenshot_slide("s21_spec_overview", "Start with the intended result", ("SIX PAGES", "TITLE + DESCRIPTION", "VALIDATE + SAVE"))


def s22_spec_scope() -> Image.Image:
    return screenshot_slide("s22_spec_scope", "Make the boundaries explicit", ("GOALS", "EXCLUSIONS", "DONE WHEN"))


def s23_spec_requirements() -> Image.Image:
    return screenshot_slide("s23_spec_requirements", "Requirements stay measurable", ("STABLE ID", "PRIORITY + USE CASE", "MEASURABLE DETAILS"))


def s24_spec_code_profile() -> Image.Image:
    return screenshot_slide("s24_spec_code_profile", "Record the project's conventions", ("LANGUAGE + STANDARD", "BUILD + TEST", "NAMING + LIBRARIES"))


def s25_code_analysis() -> Image.Image:
    return screenshot_slide("s25_code_analysis", "Filter the derived code graph", ("FILTER CONTROLS", "FOCUSED GRAPH", "CONTEXT RETAINED"))


def gate_icon(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    draw.rounded_rectangle((x, y, x + 250, y + 96), radius=16, fill=LIGHT_BLUE, outline=BLUE, width=3)
    draw.text((x + 125, y + 48), "BUILD  •  TEST  •  DELTA", font=font(16, bold=True), fill=INK, anchor="mm")


def s26_llm_choices() -> Image.Image:
    image = new_frame("Choose the right level of support")
    draw = ImageDraw.Draw(image)
    rows = ((300, "DIRECT LLM"), (535, "ICODA"), (770, "EXTERNAL LLM REPAIR"))
    for y, label in rows:
        box_label(draw, (100, y, 480, y + 125), label, title_size=21)
    arrow(draw, (490, 362), (790, 362))
    box_label(draw, (800, 300, 1180, 425), "ONE FOCUSED EDIT", fill=BACKGROUND, title_size=21)
    arrow(draw, (490, 597), (770, 597))
    box_label(draw, (780, 535, 1080, 660), "PROPOSAL", fill=BACKGROUND, title_size=21)
    arrow(draw, (1090, 597), (1240, 597))
    gate_icon(draw, 1250, 549)
    arrow(draw, (490, 832), (690, 832))
    box_label(draw, (700, 770, 980, 895), "OPEN WORKTREE", fill=BACKGROUND, title_size=18)
    arrow(draw, (990, 832), (1120, 832))
    box_label(draw, (1130, 770, 1370, 895), "REPAIR", fill=BACKGROUND, title_size=20)
    arrow(draw, (1380, 832), (1510, 832))
    box_label(draw, (1520, 770, 1770, 895), "REBUILD", "then ICODA gates", fill=BACKGROUND, title_size=20)
    return image


def s27_closing() -> Image.Image:
    image = new_frame("ICODA — develop with evidence")
    draw = ImageDraw.Draw(image)
    rows = (
        ("GITHUB", "https://github.com/hlavacs/AI-Loop/tree/main/icoda"),
        ("UNIVERSITY EMAIL", "helmut.hlavacs@univie.ac.at"),
        ("WEB PAGE", "https://entertain.univie.ac.at/~hlavacs/"),
        ("AI TOOLING", "Robimo.at — service provider specialized in AI tooling"),
    )
    draw.rounded_rectangle((180, 225, 1740, 900), radius=24, outline=LINE, width=2)
    y = 310
    for index, (label, value) in enumerate(rows):
        draw.text((250, y), label, font=font(19, bold=True), fill=BLUE)
        draw.text((570, y - 8), value, font=font(27, bold=True), fill=INK)
        if index < len(rows) - 1:
            draw.line((250, y + 78, 1670, y + 78), fill=LINE, width=1)
        y += 135
    centers = (695, 960, 1225)
    for index, (x, label) in enumerate(zip(centers, ("PROPOSE", "MEASURE", "DECIDE"))):
        draw.ellipse((x - 60, 770, x + 60, 890), fill=LIGHT_BLUE, outline=BLUE, width=3)
        draw.text((x, 830), label, font=font(15, bold=True), fill=INK, anchor="mm")
        if index < 2:
            arrow(draw, (x + 66, 830), (centers[index + 1] - 66, 830), width=3)
    return image


BUILDERS: tuple[tuple[str, Callable[[], Image.Image]], ...] = (
    ("s01_title.png", s01_title),
    ("s02_presenter.png", s02_presenter),
    ("s03_purpose.png", s03_purpose),
    ("s04_basic_idea.png", s04_basic_idea),
    ("s05_mental_model.png", s05_mental_model),
    ("s06_workflow.png", s06_workflow),
    ("s07_gui_overview.png", s07_gui_overview),
    ("s08_file_view.png", s08_file_view),
    ("s09_call_view.png", s09_call_view),
    ("s10_class_view.png", s10_class_view),
    ("s11_mind_map.png", s11_mind_map),
    ("s12_coverage.png", s12_coverage),
    ("s13_issues.png", s13_issues),
    ("s14_provider_selection.png", s14_provider_selection),
    ("s15_architecture_step.png", s15_architecture_step),
    ("s16_proposal_evidence.png", s16_proposal_evidence),
    ("s17_developer_decision.png", s17_developer_decision),
    ("s18_quick_architecture.png", s18_quick_architecture),
    ("s19_quick_approach.png", s19_quick_approach),
    ("s20_quick_result.png", s20_quick_result),
    ("s21_spec_overview.png", s21_spec_overview),
    ("s22_spec_scope.png", s22_spec_scope),
    ("s23_spec_requirements.png", s23_spec_requirements),
    ("s24_spec_code_profile.png", s24_spec_code_profile),
    ("s25_code_analysis.png", s25_code_analysis),
    ("s26_llm_choices.png", s26_llm_choices),
    ("s27_closing.png", s27_closing),
)


def save(name: str, image: Image.Image) -> None:
    if image.size != (WIDTH, HEIGHT):
        raise RuntimeError(f"invalid frame size for {name}: {image.size}")
    image.save(OUTPUT / name, format="PNG", compress_level=9)
    print(f"{name}: {image.width}x{image.height}")


def main() -> int:
    if tuple(name for name, _builder in BUILDERS) != ASSET_NAMES:
        raise RuntimeError("ASSET_NAMES and BUILDERS are inconsistent")
    prepare_logo()
    expected = set(ASSET_NAMES)
    for stale in OUTPUT.glob("*.png"):
        if stale.name not in expected:
            stale.unlink()
    for name, builder in BUILDERS:
        save(name, builder())
    actual = {path.name for path in OUTPUT.glob("*.png")}
    if actual != expected:
        raise RuntimeError(f"unexpected rendered asset set: {sorted(actual ^ expected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
