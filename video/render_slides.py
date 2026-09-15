#!/usr/bin/env python3
"""Render the AI-Loop or ICODA 24-slide storyboard with Pillow."""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


VIDEO_DIR = Path(__file__).resolve().parent
SCREENSHOT_DIR = VIDEO_DIR / "ai-loop" / "screenshots"
OUTPUT_DIR = VIDEO_DIR / "ai-loop" / "slides"
LOGO_PATH = VIDEO_DIR / "assets" / "university-of-vienna-logo.png"

FRAME_SIZE = (1920, 1080)
WHITE = "#FFFFFF"
DARK = "#1D2733"
MUTED = "#52606D"
BLUE = "#0063A6"
PALE_BLUE = "#EAF3F8"
PALE_GRAY = "#F4F6F8"
PALE_GREEN = "#EAF5EA"
RED = "#D71920"
PALE_RED = "#FCEBEC"
GOLD = "#E6A700"

LOGO_BOX = (1600, 38, 1840, 138)
LOGO_RENDERED_BOX = (1620, 38, 1820, 138)
TITLE_BOX = (90, 50, 1500, 145)
COMMON_TARGET = (120, 190, 1800, 1000)

REGULAR_FONT = Path("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf")
BOLD_FONT = Path("/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf")
MONO_FONT = Path("/usr/share/fonts/truetype/noto/NotoSansMono-Regular.ttf")


def font(size: int, *, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont:
    path = MONO_FONT if mono else BOLD_FONT if bold else REGULAR_FONT
    return ImageFont.truetype(str(path), size)


def put(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    value: str,
    size: int,
    *,
    bold: bool = False,
    mono: bool = False,
    fill: str = DARK,
    anchor: str | None = None,
) -> None:
    draw.text(xy, value, font=font(size, bold=bold, mono=mono), fill=fill, anchor=anchor)


def wrap_lines(draw: ImageDraw.ImageDraw, value: str, width: int, text_font: ImageFont.FreeTypeFont) -> list[str]:
    words = value.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if not current or draw.textlength(candidate, font=text_font) <= width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def wrapped(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    value: str,
    size: int,
    *,
    bold: bool = False,
    mono: bool = False,
    fill: str = DARK,
    spacing: int = 7,
    anchor: str = "la",
) -> int:
    x1, y1, x2, _ = box
    text_font = font(size, bold=bold, mono=mono)
    lines = wrap_lines(draw, value, x2 - x1, text_font)
    line_height = size + spacing
    for index, line in enumerate(lines):
        draw.text((x1, y1 + index * line_height), line, font=text_font, fill=fill, anchor=anchor)
    return y1 + len(lines) * line_height


def title(draw: ImageDraw.ImageDraw, value: str) -> None:
    put(draw, (90, 52), value, 48, bold=True)
    draw.line((90, 132, 1500, 132), fill=BLUE, width=4)


def card(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    fill: str = PALE_BLUE,
    outline: str = BLUE,
    radius: int = 20,
    width: int = 3,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    fill: str = BLUE,
    width: int = 5,
) -> None:
    draw.line((start, end), fill=fill, width=width)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    length = 15
    spread = 0.55
    points = [
        end,
        (
            int(end[0] - length * math.cos(angle - spread)),
            int(end[1] - length * math.sin(angle - spread)),
        ),
        (
            int(end[0] - length * math.cos(angle + spread)),
            int(end[1] - length * math.sin(angle + spread)),
        ),
    ]
    draw.polygon(points, fill=fill)


def contain_rect(
    source_size: tuple[int, int], target: tuple[int, int, int, int]
) -> tuple[int, int, int, int]:
    source_width, source_height = source_size
    x1, y1, x2, y2 = target
    scale = min((x2 - x1) / source_width, (y2 - y1) / source_height)
    # Floor dimensions so the common 1408x812 source lands on the storyboard's
    # literal 1404x810 rendered box at (258, 190)-(1662, 1000).
    width = int(source_width * scale)
    height = int(source_height * scale)
    left = x1 + ((x2 - x1) - width) // 2
    top = y1 + ((y2 - y1) - height) // 2
    return left, top, left + width, top + height


def paste_contained(
    canvas: Image.Image,
    filename: str,
    target: tuple[int, int, int, int],
    source_crop: tuple[int, int, int, int] | None = None,
) -> tuple[int, int, int, int]:
    source = Image.open(SCREENSHOT_DIR / filename).convert("RGB")
    if source_crop is not None:
        source = source.crop(source_crop)
    rendered = contain_rect(source.size, target)
    resized = source.resize(
        (rendered[2] - rendered[0], rendered[3] - rendered[1]), Image.Resampling.LANCZOS
    )
    canvas.paste(resized, rendered[:2])
    return rendered


def paste_logo(canvas: Image.Image) -> None:
    logo = Image.open(LOGO_PATH).convert("RGBA").resize((200, 100), Image.Resampling.LANCZOS)
    canvas.alpha_composite(logo, LOGO_RENDERED_BOX[:2])


def highlight(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    draw.rectangle(box, outline=RED, width=6)


def margin_label(
    draw: ImageDraw.ImageDraw,
    side: str,
    y: int,
    value: str,
    target: tuple[int, int],
    *,
    size: int = 19,
) -> None:
    if side == "left":
        box = (18, y, 244, y + 95)
        wrapped(draw, box, value, size, bold=True, fill=RED, spacing=5)
        start = (244, y + 28)
    else:
        box = (1676, y, 1905, y + 95)
        wrapped(draw, box, value, size, bold=True, fill=RED, spacing=5)
        start = (1676, y + 28)
    arrow(draw, start, target, fill=RED, width=3)


def side_note(draw: ImageDraw.ImageDraw, side: str, y: int, value: str) -> None:
    """Place a compact ICODA explanation in the whitespace beside a contained capture."""
    box = (18, y, 306, y + 105) if side == "left" else (1614, y, 1906, y + 105)
    wrapped(draw, box, value, 17, bold=True, fill=BLUE, spacing=5)


def draw_node(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    label: str,
    *,
    fill: str = PALE_BLUE,
    size: int = 25,
) -> None:
    card(draw, box, fill=fill, radius=16)
    put(draw, ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2), label, size, bold=True, anchor="mm")


def contact_icon(draw: ImageDraw.ImageDraw, center: tuple[int, int], index: int) -> None:
    """Draw a small, font-independent line icon for a contact-card row."""
    x, y = center
    if index == 0:  # person
        draw.ellipse((x - 7, y - 17, x + 7, y - 3), outline=BLUE, width=3)
        draw.arc((x - 17, y - 3, x + 17, y + 25), 190, 350, fill=BLUE, width=3)
    elif index == 1:  # book / faculty
        draw.rectangle((x - 18, y - 16, x + 18, y + 18), outline=BLUE, width=3)
        draw.line((x, y - 16, x, y + 18), fill=BLUE, width=2)
    elif index == 2:  # university building
        draw.polygon(((x - 20, y - 10), (x, y - 22), (x + 20, y - 10)), outline=BLUE)
        for column in (-12, 0, 12):
            draw.line((x + column, y - 8, x + column, y + 14), fill=BLUE, width=3)
        draw.line((x - 22, y + 17, x + 22, y + 17), fill=BLUE, width=3)
    elif index == 3:  # web
        draw.ellipse((x - 19, y - 19, x + 19, y + 19), outline=BLUE, width=3)
        draw.ellipse((x - 8, y - 19, x + 8, y + 19), outline=BLUE, width=2)
        draw.line((x - 18, y, x + 18, y), fill=BLUE, width=2)
    elif index == 4:  # email
        draw.rectangle((x - 21, y - 15, x + 21, y + 15), outline=BLUE, width=3)
        draw.line((x - 20, y - 14, x, y + 2, x + 20, y - 14), fill=BLUE, width=2)
    else:  # repository branch
        draw.line((x - 13, y - 14, x - 13, y + 14, x + 13, y + 14), fill=BLUE, width=3)
        draw.line((x - 13, y, x + 13, y - 10), fill=BLUE, width=3)
        for px, py in ((x - 13, y - 14), (x + 13, y - 10), (x + 13, y + 14)):
            draw.ellipse((px - 4, py - 4, px + 4, py + 4), fill=WHITE, outline=BLUE, width=2)


def draw_slide_01(canvas: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    put(draw, (90, 24), "AI-Loop", 72, bold=True, fill=BLUE)
    put(draw, (125, 160), "Persistent, checked coding-agent work", 36, fill=MUTED)
    put(draw, (125, 230), "Helmut Hlavacs", 29, bold=True)
    put(draw, (125, 275), "University of Vienna", 27, fill=BLUE)
    labels = ["PLAN", "IMPLEMENT", "VALIDATE", "CONTINUE"]
    boxes = [(190 + i * 410, 495, 490 + i * 410, 635) for i in range(4)]
    for label, box in zip(labels, boxes):
        draw_node(draw, box, label, size=28)
    for left, right in zip(boxes, boxes[1:]):
        arrow(draw, (left[2] + 16, 565), (right[0] - 16, 565))
    draw.line((boxes[-1][2] - 60, 670, boxes[-1][2] - 60, 790, boxes[0][0] + 60, 790, boxes[0][0] + 60, 670), fill=BLUE, width=5)
    arrow(draw, (boxes[0][0] + 60, 700), (boxes[0][0] + 60, boxes[0][3] + 10))
    put(draw, (960, 830), "repeat until evidence says done", 25, fill=MUTED, anchor="mm")


def draw_slide_02(canvas: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    title(draw, "About Helmut Hlavacs")
    card(draw, (210, 235, 1710, 900), fill=PALE_GRAY)
    rows = [
        ("Helmut Hlavacs", True),
        ("Professor, Faculty of Computer Science", False),
        ("University of Vienna", False),
        ("https://www.univie.ac.at/", False),
        ("helmut.hlavacs@univie.ac.at", False),
        ("https://github.com/hlavacs/AI-Loop", False),
    ]
    for index, (value, bold) in enumerate(rows):
        y = 300 + index * 88
        contact_icon(draw, (303, y + 18), index)
        put(draw, (365, y), value, 30 if index else 36, bold=bold)
        if index < len(rows) - 1:
            draw.line((285, y + 56, 1620, y + 56), fill="#D8DEE4", width=2)


def draw_slide_03(canvas: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    title(draw, "What AI-Loop is for")
    put(draw, (470, 270), "ONE CHAT", 29, bold=True, fill=MUTED, anchor="mm")
    put(draw, (1370, 270), "DURABLE JOB", 29, bold=True, fill=BLUE, anchor="mm")
    draw.rounded_rectangle((180, 390, 735, 455), radius=25, fill="#D9DEE3")
    draw.rectangle((635, 390, 735, 455), fill="#AAB4BE")
    put(draw, (457, 500), "context or usage limit", 25, fill=MUTED, anchor="mm")
    arrow(draw, (457, 470), (690, 470), fill=MUTED, width=3)
    job_boxes = [(930 + i * 220, 375, 1110 + i * 220, 485) for i in range(4)]
    for label, box in zip(("change", "test", "review", "continue"), job_boxes):
        draw_node(draw, box, label, size=22)
    for left, right in zip(job_boxes, job_boxes[1:]):
        arrow(draw, (left[2] + 5, 430), (right[0] - 5, 430), width=4)
    footer = ["multi-file features", "migrations", "repairs", "test coverage"]
    for i, value in enumerate(footer):
        box = (180 + i * 410, 700, 515 + i * 410, 795)
        card(draw, box, fill=PALE_GRAY, outline="#B8C1C9", width=2)
        put(draw, ((box[0] + box[2]) // 2, 748), value, 22, bold=True, anchor="mm")


def draw_slide_04(canvas: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    title(draw, "The basic idea")
    inputs = [(145, 300, 385, 390), (145, 455, 385, 545), (145, 610, 385, 700)]
    for label, box in zip(("Repository", "Goal", "Validation"), inputs):
        draw_node(draw, box, label, fill=PALE_GRAY, size=23)
        arrow(draw, (box[2] + 10, (box[1] + box[3]) // 2), (535, 500), width=3)
    loop_labels = ["Controller", "Task", "Worker", "Evidence", "Controller"]
    loop_boxes = [(535 + i * 205, 445, 705 + i * 205, 555) for i in range(5)]
    for label, box in zip(loop_labels, loop_boxes):
        draw_node(draw, box, label, size=20)
    for left, right in zip(loop_boxes, loop_boxes[1:]):
        arrow(draw, (left[2] + 3, 500), (right[0] - 3, 500), width=4)
    exits = [(1290, 675, 1490, 765), (1510, 675, 1710, 765), (1400, 815, 1640, 890)]
    for label, box in zip(("Done", "Human input", "Stopped safely"), exits):
        draw_node(draw, box, label, fill=PALE_GREEN if label == "Done" else PALE_GRAY, size=21)
    arrow(draw, (1395, 565), (1395, 665), width=4)
    arrow(draw, (1500, 565), (1605, 665), width=4)
    arrow(draw, (1605, 775), (1520, 805), width=4)


def draw_slide_05(canvas: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    title(draw, "A durable shared notebook")
    center = (690, 260, 1230, 820)
    card(draw, center, fill=PALE_BLUE, radius=24, width=4)
    put(draw, (960, 315), "DURABLE JOB RECORD", 31, bold=True, fill=BLUE, anchor="mm")
    for index, value in enumerate(("plan", "tasks", "runs", "decisions", "evidence")):
        y = 390 + index * 76
        draw.rounded_rectangle((780, y, 1140, y + 54), radius=12, fill=WHITE, outline="#B8C9D6", width=2)
        put(draw, (960, y + 27), value, 23, anchor="mm")
    around = [
        ((180, 285, 465, 385), "Controller"),
        ((1450, 285, 1740, 385), "Worker"),
        ((170, 650, 465, 750), "Watcher"),
        ((1415, 650, 1760, 750), "Git worktree"),
        ((790, 870, 1130, 955), "Tests"),
    ]
    for box, label in around:
        draw_node(draw, box, label, fill=PALE_GRAY, size=24)
        start = ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
        end = (max(center[0], min(start[0], center[2])), max(center[1], min(start[1], center[3])))
        arrow(draw, start, end, width=3)
    draw.ellipse((530, 765, 580, 815), outline=GOLD, width=4)
    draw.rectangle((544, 778, 551, 802), fill=GOLD)
    draw.rectangle((559, 778, 566, 802), fill=GOLD)
    put(draw, (555, 845), "resume later", 22, bold=True, fill=MUTED, anchor="mm")
    arrow(draw, (620, 815), (690, 760), fill=GOLD, width=4)


def draw_slide_06(canvas: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    title(draw, "How it works: actors and storage")
    actors = [
        ((155, 275, 630, 405), "Controller: plans + reviews"),
        ((720, 275, 1200, 405), "Worker: edits + validates"),
        ((1290, 275, 1765, 405), "Watcher: supervises + notifies"),
    ]
    for box, label in actors:
        draw_node(draw, box, label, size=21)
    stream = (665, 500, 1255, 635)
    draw_node(draw, stream, "Redis Streams", size=31)
    for box, _ in actors:
        actor_mid = ((box[0] + box[2]) // 2, box[3])
        stream_point = (max(stream[0] + 40, min(actor_mid[0], stream[2] - 40)), stream[1])
        arrow(draw, actor_mid, stream_point, width=4)
        arrow(draw, (stream_point[0] + 18, stream[1]), (actor_mid[0] + 18, actor_mid[1]), width=3)
    stores = [((300, 760, 850, 885), "SQLite job history"), ((1070, 760, 1620, 885), "isolated Git worktree")]
    for box, label in stores:
        draw_node(draw, box, label, fill=PALE_GRAY, size=25)
        arrow(draw, (960, stream[3] + 10), ((box[0] + box[2]) // 2, box[1] - 10), width=4)
    put(draw, (960, 710), "durable state", 21, fill=MUTED, anchor="mm")


def draw_slide_07(canvas: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    title(draw, "How it works: lifecycle")
    labels = ["Create", "Plan", "Queue task", "Implement", "Review", "Promote", "Validate", "Done"]
    width = 190
    gap = 25
    boxes = []
    for index, label in enumerate(labels):
        x = 100 + index * (width + gap)
        box = (x, 400, x + width, 500)
        boxes.append(box)
        draw_node(draw, box, label, fill=PALE_GREEN if label == "Done" else PALE_BLUE, size=18)
    for left, right in zip(boxes, boxes[1:]):
        arrow(draw, (left[2] + 3, 450), (right[0] - 3, 450), width=3)
    branches = [((boxes[3][0], 650, boxes[3][2] + 75, 745), "waiting for tokens"), ((boxes[4][0], 790, boxes[4][2] + 50, 885), "human needed")]
    for (box, label), origin in zip(branches, (boxes[3], boxes[4])):
        draw_node(draw, box, label, fill=PALE_RED, size=18)
        arrow(draw, ((origin[0] + origin[2]) // 2, origin[3] + 5), ((box[0] + box[2]) // 2, box[1] - 5), fill=RED, width=3)
        arrow(draw, (box[0], (box[1] + box[3]) // 2), (origin[0], origin[1] + 25), fill=RED, width=3)
    put(draw, (825, 620), "resume same job", 19, bold=True, fill=RED, anchor="mm")
    put(draw, (1030, 925), "worktree and history remain", 23, fill=MUTED, anchor="mm")


def draw_slide_16(canvas: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    title(draw, "Walkthrough: start with the idea")
    card(draw, (150, 220, 1120, 910), fill=PALE_GRAY)
    put(draw, (210, 280), "Idea: a tiny order-totals project", 34, bold=True, fill=BLUE)
    card(draw, (210, 350, 1040, 475), fill=WHITE, outline="#B8C1C9", width=2)
    wrapped(draw, (255, 382, 995, 455), "Orders of 100 or more receive the discount", 28, bold=True)
    put(draw, (250, 555), "src/totals.py", 24, mono=True)
    put(draw, (250, 605), "tests/test_totals.py", 24, mono=True)
    draw.line((220, 532, 220, 635), fill=BLUE, width=3)
    draw.line((220, 565, 240, 565), fill=BLUE, width=3)
    draw.line((220, 615, 240, 615), fill=BLUE, width=3)
    card(draw, (1200, 300, 1770, 690), fill="#20252B", outline="#20252B")
    put(draw, (1250, 380), "$ python -m pytest -q", 24, mono=True, fill=WHITE)
    put(draw, (1250, 485), "1 failed, 11 passed", 28, bold=True, mono=True, fill="#FF7B7B")
    highlight(draw, (1225, 455, 1735, 535))
    card(draw, (1200, 760, 1770, 890), fill=PALE_BLUE)
    wrapped(draw, (1250, 793, 1720, 875), "Let AI-Loop diagnose and repair it", 26, bold=True)
    arrow(draw, (1500, 550), (1500, 745), fill=RED, width=4)


def draw_slide_19(canvas: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    title(draw, "Walkthrough input 10 and immediate output")
    paste_contained(canvas, "s17-quick-job-form.png", (180, 300, 820, 760), (630, 470, 770, 550))
    paste_contained(canvas, "s11-gui-jobs-status.png", (1060, 300, 1740, 760), (10, 535, 770, 812))
    put(draw, (500, 270), "10  Click Quick Job", 27, bold=True, fill=RED, anchor="mm")
    arrow(draw, (850, 530), (1025, 530), width=8)
    put(draw, (938, 485), "creates durable state", 20, bold=True, fill=BLUE, anchor="mm")
    highlight(draw, (300, 515, 570, 620))
    highlight(draw, (1110, 480, 1665, 620))
    footer = [("job ID", 535), ("worktree", 960), ("controller starts", 1385)]
    for value, x in footer:
        card(draw, (x - 165, 835, x + 165, 920), fill=PALE_GRAY, outline="#B8C1C9", width=2)
        put(draw, (x, 878), value, 23, bold=True, anchor="mm")


def draw_slide_24(canvas: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    title(draw, "Choose the right level, then continue")
    paths = [
        ("Direct model", "focused question"),
        ("AI-Loop", "persistent checked work"),
        ("Repair helper", "fix tooling, resume job"),
    ]
    for index, (source, destination) in enumerate(paths):
        x = 130 + index * 555
        card(draw, (x, 260, x + 500, 540), fill=PALE_BLUE if index == 1 else PALE_GRAY)
        put(draw, (x + 250, 330), source, 28, bold=True, fill=BLUE, anchor="mm")
        arrow(draw, (x + 170, 400), (x + 330, 400), width=5)
        put(draw, (x + 250, 475), destination, 22, bold=True, anchor="mm")
    card(draw, (250, 650, 1670, 960), fill=WHITE, outline=BLUE, width=3)
    contacts = [
        "https://github.com/hlavacs/AI-Loop",
        "helmut.hlavacs@univie.ac.at",
        "https://entertain.univie.ac.at/~hlavacs/",
        "Robimo.at — AI-tooling service provider",
    ]
    for index, value in enumerate(contacts):
        put(draw, (330, 710 + index * 55), value, 26, bold=index == 3, fill=BLUE if index < 3 else DARK)
    put(draw, (1480, 865), "Thank you", 40, bold=True, fill=BLUE, anchor="mm")


def draw_icoda_slide_01(canvas: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    title(draw, "ICODA")
    put(draw, (120, 165), "Interactive Code Development and Analysis", 35, fill=MUTED)
    put(draw, (120, 225), "Helmut Hlavacs", 28, bold=True)
    put(draw, (120, 267), "University of Vienna", 26, fill=BLUE)
    boxes = [(190, 425, 570, 550), (770, 425, 1150, 550), (1350, 425, 1730, 550)]
    for label, box in zip(("SPECIFICATION", "ARCHITECTURE", "IMPLEMENTATION"), boxes):
        draw_node(draw, box, label, size=25)
    for left, right in zip(boxes, boxes[1:]):
        arrow(draw, (left[2] + 20, 487), (right[0] - 20, 487))
    loop_boxes = [(430, 700, 710, 790), (820, 700, 1100, 790), (1210, 700, 1490, 790)]
    for label, box in zip(("propose", "inspect evidence", "decide"), loop_boxes):
        draw_node(draw, box, label, fill=PALE_GRAY, size=21)
    for left, right in zip(loop_boxes, loop_boxes[1:]):
        arrow(draw, (left[2] + 10, 745), (right[0] - 10, 745), width=4)
    draw.line((1350, 810, 1350, 860, 570, 860, 570, 810), fill=BLUE, width=4)
    arrow(draw, (570, 825), (570, 800), width=4)


def draw_icoda_slide_02(canvas: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    title(draw, "About Helmut Hlavacs")
    card(draw, (210, 235, 1710, 900), fill=PALE_GRAY)
    rows = [
        ("Helmut Hlavacs", True),
        ("Professor, Faculty of Computer Science", False),
        ("University of Vienna", False),
        ("https://www.univie.ac.at/", False),
        ("helmut.hlavacs@univie.ac.at", False),
        ("https://github.com/hlavacs/AI-Loop/tree/main/icoda", False),
    ]
    for index, (value, bold) in enumerate(rows):
        y = 300 + index * 88
        contact_icon(draw, (303, y + 18), index)
        put(draw, (365, y), value, 30 if index else 36, bold=bold)
        if index < len(rows) - 1:
            draw.line((285, y + 56, 1620, y + 56), fill="#D8DEE4", width=2)


def draw_icoda_slide_03(canvas: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    title(draw, "What ICODA is for")
    columns = [((140, 250, 805, 755), "CODE AS TEXT"), ((875, 250, 1780, 755), "CODE AS A DECISION SYSTEM")]
    for box, heading in columns:
        card(draw, box, fill=PALE_GRAY if heading == "CODE AS TEXT" else PALE_BLUE)
        put(draw, ((box[0] + box[2]) // 2, 305), heading, 28, bold=True, fill=BLUE, anchor="mm")
    for index, label in enumerate(("files", "symbols", "tests")):
        draw_node(draw, (250, 380 + index * 105, 695, 455 + index * 105), label, fill=WHITE, size=22)
    for index, label in enumerate(("specification", "architecture", "proposals", "evidence", "history")):
        row, column = divmod(index, 2)
        x = 955 + column * 385
        draw_node(draw, (x, 365 + row * 112, x + 325, 445 + row * 112), label, fill=WHITE, size=21)
    for index, label in enumerate(("new projects", "existing systems", "controlled AI-assisted change")):
        x = 180 + index * 540
        card(draw, (x, 820, x + 480, 905), fill=WHITE, outline="#B8C1C9", width=2)
        put(draw, (x + 240, 862), label, 21, bold=True, anchor="mm")


def draw_icoda_slide_04(canvas: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    title(draw, "The basic idea")
    inputs = [(125, 250, 430, 335), (125, 370, 430, 455), (125, 490, 430, 575)]
    for label, box in zip(("Written specification", "Source tree", "Developer intent"), inputs):
        draw_node(draw, box, label, fill=PALE_GRAY, size=20)
        arrow(draw, (box[2] + 10, (box[1] + box[3]) // 2), (605, 415), width=3)
    draw_node(draw, (605, 345, 1015, 485), "Derived code model", size=28)
    view_labels = ("File", "Call", "Class", "Mind Map", "Coverage", "Issues")
    for index, label in enumerate(view_labels):
        x = 1080 + (index % 3) * 230
        y = 255 + (index // 3) * 130
        draw_node(draw, (x, y, x + 190, y + 82), label, fill=PALE_GRAY, size=18)
        arrow(draw, (1018, 415), (x - 8, y + 41), width=3)
    loop = ("Agent proposal", "isolated worktree", "build + tests", "developer decision", "Git commit")
    loop_boxes = []
    for index, label in enumerate(loop):
        x = 110 + index * 350
        box = (x, 720, x + 290, 820)
        loop_boxes.append(box)
        draw_node(draw, box, label, size=18)
    for left, right in zip(loop_boxes, loop_boxes[1:]):
        arrow(draw, (left[2] + 5, 770), (right[0] - 5, 770), width=3)
    arrow(draw, (810, 500), (260, 705), width=3)


def draw_icoda_slide_05(canvas: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    title(draw, "The mental model: two truths")
    columns = [((150, 235, 760, 765), "INTENT", ("goals", "scope", "requirements", "decisions", "code profile")),
               ((1160, 235, 1770, 765), "IMPLEMENTATION", ("files", "entities", "calls", "tests", "history"))]
    for box, heading, entries in columns:
        card(draw, box, fill=PALE_BLUE)
        put(draw, ((box[0] + box[2]) // 2, 295), heading, 31, bold=True, fill=BLUE, anchor="mm")
        for index, value in enumerate(entries):
            draw_node(draw, (box[0] + 110, 355 + index * 75, box[2] - 110, 410 + index * 75), value,
                      fill=WHITE, size=20)
    card(draw, (710, 415, 1210, 585), fill=WHITE, radius=60, width=4)
    wrapped(draw, (775, 448, 1145, 565), "ICODA derives the map and exposes the gaps", 25, bold=True,
            fill=BLUE, spacing=6)
    arrow(draw, (760, 500), (700, 500), width=4)
    arrow(draw, (1160, 500), (1220, 500), width=4)
    put(draw, (960, 875), "the developer owns every consequential decision", 28, bold=True,
        fill=MUTED, anchor="mm")


def draw_icoda_slide_06(canvas: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    title(draw, "How ICODA works")
    labels = (
        "1  Parse the project", "2  Build a derived model", "3  Select a phase and target",
        "4  Ask the configured coding agent", "5  Apply in an isolated worktree", "6  Build and test",
        "7  Approve, reject, or adapt", "8  Commit approved work",
    )
    boxes = []
    for index, label in enumerate(labels):
        row, column = divmod(index, 4)
        x = 120 + column * 425
        y = 250 + row * 220
        box = (x, y, x + 360, y + 115)
        boxes.append(box)
        draw_node(draw, box, label, size=18)
    for index in range(3):
        arrow(draw, (boxes[index][2] + 6, 307), (boxes[index + 1][0] - 6, 307), width=3)
    arrow(draw, (boxes[3][2] - 30, boxes[3][3] + 8), (boxes[7][2] - 30, boxes[7][1] - 8), width=3)
    for index in range(7, 4, -1):
        arrow(draw, (boxes[index][0] - 6, 527), (boxes[index - 1][2] + 6, 527), width=3)
    draw_node(draw, (260, 760, 960, 875), ".icoda specification + state + step log", fill=PALE_GRAY, size=23)
    draw_node(draw, (1120, 760, 1660, 875), "Git history", fill=PALE_GRAY, size=25)
    arrow(draw, (960, 817), (1110, 817), width=4)


def draw_icoda_slide_13(canvas: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    title(draw, "Walkthrough input: create the project")
    card(draw, (110, 250, 570, 820), fill=PALE_GRAY)
    put(draw, (150, 275), "File", 25, bold=True, fill=BLUE)
    menu_items = ("New Project…", "Open Project…", "Open Recent", "Reload", "Quit")
    for index, value in enumerate(menu_items):
        y = 325 + index * 72
        put(draw, (165, y), value, 24, bold=index == 0)
    put(draw, (145, 745), "1  File", 22, bold=True, fill=RED)
    arrow(draw, (225, 760), (270, 760), fill=RED, width=3)
    put(draw, (285, 745), "New Project…", 22, bold=True, fill=RED)
    card(draw, (650, 250, 1780, 700), fill=PALE_GRAY)
    put(draw, (710, 295), "New project: choose an empty directory", 28, bold=True, fill=BLUE)
    put(draw, (720, 380), "2  Directory", 23, bold=True)
    card(draw, (720, 410, 1680, 485), fill=WHITE, outline="#AAB4BE", width=2)
    put(draw, (755, 431), "/tmp/icoda-demo/formatter", 24, mono=True)
    draw_node(draw, (1450, 575, 1680, 645), "Choose", size=20)
    card(draw, (650, 740, 1780, 930), fill=PALE_BLUE)
    outputs = ("directory created", ".icoda state created", "Phase: specification", "Specification editor opens")
    for index, value in enumerate(outputs):
        x = 710 + (index % 2) * 500
        y = 785 + (index // 2) * 70
        put(draw, (x, y), value, 21, bold=True)


def draw_icoda_slide_15(canvas: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    title(draw, "Walkthrough inputs: specify, build, and configure")
    paste_contained(canvas, "lifecycle/sim-02-specification-save.png", (80, 190, 1380, 900))
    paste_contained(canvas, "views/provider-selection.png", (1410, 240, 1810, 560))
    card(draw, (80, 920, 1810, 1010), fill=PALE_GRAY, outline="#B8C1C9", radius=12, width=2)
    put(draw, (110, 936), ".icoda/specification.json  •  step 0 recorded  •  project skeleton written", 19, bold=True)
    put(draw, (110, 970), "build passed  •  analysis populates all views  •  phase", 19, bold=True, fill=BLUE)
    arrow(draw, (660, 982), (705, 982), width=3)
    put(draw, (720, 970), "architecture", 19, bold=True, fill=BLUE)


def draw_icoda_slide_24(canvas: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    title(draw, "Keep intent, evidence, and decisions together")
    labels = ("Specify the intended system", "Inspect structure and evidence", "Approve only verified change")
    boxes = []
    for index, label in enumerate(labels):
        x = 130 + index * 555
        box = (x, 285, x + 500, 520)
        boxes.append(box)
        draw_node(draw, box, label, fill=PALE_BLUE if index == 1 else PALE_GRAY, size=22)
    for left, right in zip(boxes, boxes[1:]):
        arrow(draw, (left[2] + 10, 402), (right[0] - 10, 402), width=5)
    card(draw, (250, 640, 1670, 960), fill=WHITE, outline=BLUE, width=3)
    contacts = (
        "https://github.com/hlavacs/AI-Loop/tree/main/icoda",
        "helmut.hlavacs@univie.ac.at",
        "https://entertain.univie.ac.at/~hlavacs/",
        "Robimo.at - AI-tooling service provider",
    )
    for index, value in enumerate(contacts):
        put(draw, (320, 695 + index * 58), value, 25, bold=index == 3,
            fill=BLUE if index < 3 else DARK)
    put(draw, (1490, 875), "Thank you", 39, bold=True, fill=BLUE, anchor="mm")


SCREEN_SLIDES: dict[int, dict[str, Any]] = {
    8: {
        "title": "GUI tour: one operational view",
        "screenshot": "s11-gui-jobs-status.png",
        "highlights": [(258, 232, 578, 260), (266, 766, 1023, 849), (1044, 268, 1648, 820)],
        "labels": [
            ("left", 205, "Create + select jobs", (420, 246)),
            ("right", 340, "Inspect durable state", (1450, 450)),
            ("right", 730, "Resume or repair", (1535, 805)),
        ],
    },
    9: {
        "title": "GUI tour: Create Job",
        "screenshot": "s17-quick-job-form.png",
        "highlights": [(310, 296, 1015, 541), (310, 547, 1016, 572), (386, 574, 1016, 631), (275, 658, 1016, 725)],
        "labels": [
            ("left", 285, "repository + goal", (315, 360)),
            ("left", 535, "validation command", (315, 558)),
            ("right", 550, "independent roles", (1005, 600)),
            ("right", 680, "safe worktree default", (1005, 700)),
        ],
    },
    10: {
        "title": "GUI tour: Jobs and Status",
        "screenshot": "s11-gui-jobs-status.png",
        "highlights": [(266, 766, 1023, 849), (1046, 294, 1648, 472), (1046, 548, 1648, 817)],
        "labels": [
            ("left", 760, "selected durable job", (330, 805)),
            ("right", 300, "state + progress", (1590, 380)),
            ("right", 600, "process roles", (1590, 680)),
        ],
    },
    11: {
        "title": "GUI tour: immutable Plan",
        "screenshot": "s12-gui-plan.png",
        "highlights": [(1046, 297, 1646, 326), (1046, 336, 1646, 376), (1046, 395, 1646, 490)],
        "labels": [
            ("right", 285, "completed", (1600, 310)),
            ("right", 405, "working here", (1600, 355)),
            ("right", 530, "later", (1600, 440)),
        ],
    },
    12: {
        "title": "GUI tour: Task and Controller",
        "screenshot": "s13-gui-task-controller.png",
        "highlights": [(1045, 300, 1645, 533), (1045, 653, 1645, 752), (1045, 769, 1645, 799), (1170, 268, 1247, 295)],
        "labels": [
            ("right", 315, "bounded assignment", (1600, 390)),
            ("right", 645, "completion checks", (1600, 700)),
            ("right", 790, "validation", (1600, 785)),
            ("left", 210, "Controller", (1205, 280)),
        ],
    },
    13: {
        "title": "GUI tour: Worker and Details",
        "screenshot": "s14-gui-worker-details.png",
        "highlights": [(1046, 300, 1645, 425), (1046, 467, 1645, 620), (1046, 638, 1645, 730), (1305, 268, 1360, 295)],
        "labels": [
            ("right", 315, "execution state", (1600, 370)),
            ("right", 475, "worker report", (1600, 540)),
            ("right", 650, "validation evidence", (1600, 685)),
            ("left", 210, "Details", (1335, 280)),
        ],
    },
    14: {
        "title": "GUI tour: logs and controls",
        "screenshot": "s15-gui-logs-controls.png",
        "highlights": [(1045, 325, 1647, 492), (463, 190, 848, 365)],
        "labels": [
            ("right", 350, "live process log", (1600, 405)),
            ("left", 385, "Finish Soon narrows scope", (520, 225)),
            ("left", 555, "Finish Early preserves progress", (560, 330)),
            ("right", 205, "Sign In + Resume", (590, 280)),
        ],
    },
    15: {
        "title": "GUI tour: recover, do not discard",
        "screenshot": "s16-gui-provider-repair.png",
        "highlights": [(555, 339, 1268, 428), (555, 438, 1268, 606), (1054, 760, 1171, 794)],
        "labels": [
            ("left", 330, "problem detected", (560, 380)),
            ("right", 455, "worktree preserved", (1260, 515)),
            ("right", 730, "same-job resume", (1160, 775)),
        ],
    },
    17: {
        "title": "Walkthrough input 1: repository and goal",
        "screenshot": "s17-quick-job-form.png",
        "highlights": [(310, 296, 1015, 329), (310, 332, 790, 541)],
        "labels": [
            ("left", 270, "1  Choose repository", (315, 312)),
            ("left", 410, "2  State the outcome", (315, 440)),
        ],
    },
    18: {
        "title": "Walkthrough inputs 3 through 9",
        "screenshot": "s17-quick-job-form.png",
        "highlights": [(310, 547, 1016, 572), (386, 575, 1016, 632), (386, 634, 1016, 661), (275, 659, 1016, 716)],
        "labels": [
            ("left", 250, "3  Test: python -m pytest -q", (315, 558)),
            ("left", 390, "4  Controller: claude", (390, 590)),
            ("left", 500, "5  Worker: codex", (390, 620)),
            ("right", 245, "6  Base: HEAD", (1000, 645)),
            ("right", 350, "7  Max iterations: 12", (1000, 645)),
            ("right", 480, "8  Granularity: normal", (1000, 680)),
            ("right", 635, "9  Worktree isolation on; parallel and bypass off", (1000, 705)),
        ],
    },
    20: {
        "title": "Walkthrough output: the plan",
        "screenshot": "s12-gui-plan.png",
        "highlights": [(1046, 336, 1646, 376)],
        "labels": [
            ("left", 260, "Output 1: reproduce", (1100, 310)),
            ("left", 430, "Output 2: focused correction", (1100, 355)),
            ("right", 520, "Output 3: targeted + full tests", (1600, 420)),
            ("right", 680, "Output 4: review clean checkout", (1600, 475)),
        ],
    },
    21: {
        "title": "Walkthrough output: controller creates a task",
        "screenshot": "s13-gui-task-controller.png",
        "highlights": [(1045, 300, 1645, 352), (1045, 548, 1645, 632), (1045, 653, 1645, 752), (1045, 769, 1645, 799)],
        "labels": [
            ("right", 285, "Task: Correct the boundary comparison", (1600, 325)),
            ("right", 475, "Instructions: change one comparison; preserve passing cases", (1600, 590)),
            ("left", 640, "Acceptance: boundary test + all twelve tests", (1050, 700)),
            ("right", 795, "Validation: python -m pytest -q", (1600, 784)),
        ],
    },
    22: {
        "title": "Walkthrough output: worker evidence",
        "screenshot": "s14-gui-worker-details.png",
        "highlights": [(1046, 300, 1645, 425), (1046, 467, 1645, 620), (1046, 638, 1645, 730)],
        "labels": [
            ("right", 285, "Worker runs task", (1600, 355)),
            ("right", 450, "First result diagnoses one comparison", (1600, 530)),
            ("right", 640, "Evidence: 1 failed, 11 passed", (1600, 690)),
            ("left", 210, "Controller decides the next task", (1210, 280)),
        ],
    },
    23: {
        "title": "Walkthrough output: completion",
        "screenshot": "s18-quick-job-complete.png",
        "highlights": [(266, 815, 870, 848), (1046, 466, 1645, 590), (1046, 621, 1645, 720)],
        "labels": [
            ("left", 790, "done — 100%", (330, 832)),
            ("right", 455, "src/totals.py: 2 additions, 1 deletion", (1600, 530)),
            ("right", 620, "target-checkout validation: PASSED", (1600, 660)),
            ("right", 785, "12 passed", (1550, 710)),
        ],
    },
}


SLIDES: list[dict[str, Any]] = [
    {"number": 1, "title": "AI-Loop", "custom": draw_slide_01},
    {"number": 2, "title": "About Helmut Hlavacs", "custom": draw_slide_02},
    {"number": 3, "title": "What AI-Loop is for", "custom": draw_slide_03},
    {"number": 4, "title": "The basic idea", "custom": draw_slide_04},
    {"number": 5, "title": "A durable shared notebook", "custom": draw_slide_05},
    {"number": 6, "title": "How it works: actors and storage", "custom": draw_slide_06},
    {"number": 7, "title": "How it works: lifecycle", "custom": draw_slide_07},
    *({"number": number, **SCREEN_SLIDES[number]} for number in range(8, 16)),
    {"number": 16, "title": "Walkthrough: start with the idea", "custom": draw_slide_16},
    *({"number": number, **SCREEN_SLIDES[number]} for number in (17, 18)),
    {"number": 19, "title": "Walkthrough input 10 and immediate output", "custom": draw_slide_19, "screenshots": [
        {"filename": "s17-quick-job-form.png", "target": (180, 300, 820, 760), "source_crop": (630, 470, 770, 550)},
        {"filename": "s11-gui-jobs-status.png", "target": (1060, 300, 1740, 760), "source_crop": (10, 535, 770, 812)},
    ]},
    *({"number": number, **SCREEN_SLIDES[number]} for number in range(20, 24)),
    {"number": 24, "title": "Choose the right level, then continue", "custom": draw_slide_24},
]


ICODA_SCREEN_SLIDES: dict[int, dict[str, Any]] = {
    7: {
        "title": "GUI tour: File View", "screenshot": "views/file-view.png", "icoda_screen": True,
        "side_notes": [("left", 205, "shared filter + neighborhood controls"),
                       ("left", 470, "clusters, files, and entities"),
                       ("right", 195, "LLM Binary + Model"),
                       ("right", 430, "selectable entity tree"),
                       ("right", 785, "phase, request, evidence, decisions")],
        "focus_rectangles": [(320, 218, 1260, 655), (1262, 218, 1598, 655), (320, 660, 1598, 995)],
        "focus_arrows": [((180, 250), (420, 250))],
    },
    8: {
        "title": "GUI tour: Call View", "screenshot": "views/call-view.png", "icoda_screen": True,
        "side_notes": [("left", 260, "callers and callees"), ("left", 445, "arrow direction"),
                       ("right", 200, "depth + fit controls"),
                       ("right", 470, "hierarchy remains expandable"),
                       ("right", 690, "side panel identifies the selected entity")],
        "focus_rectangles": [(320, 250, 1258, 650), (880, 220, 1258, 250)],
        "focus_arrows": [((180, 330), (520, 360)), ((1740, 350), (1450, 350))],
    },
    9: {
        "title": "GUI tour: Class View", "screenshot": "views/class-view.png", "icoda_screen": True,
        "side_notes": [("left", 270, "classes and structs"), ("left", 470, "methods + signatures"),
                       ("right", 210, "inheritance and type relations"), ("right", 510, "status legend"),
                       ("right", 720, "zoom, pan, fit")],
        "focus_rectangles": [(350, 285, 900, 570), (930, 270, 1235, 600)],
        "focus_arrows": [((1750, 330), (1500, 350))],
    },
    10: {
        "title": "GUI tour: Mind Map", "screenshot": "views/mind-map.png", "icoda_screen": True,
        "side_notes": [("left", 260, "project → cluster → file → entity"), ("left", 490, "expand a branch"),
                       ("right", 250, "select history from the map"),
                       ("right", 720, "same workflow context below")],
        "focus_rectangles": [(340, 260, 1210, 620)],
        "focus_arrows": [((185, 345), (480, 365)), ((1750, 440), (1455, 440))],
    },
    11: {
        "title": "GUI tour: Requirements Coverage", "screenshot": "views/requirements-coverage.png",
        "icoda_screen": True,
        "side_notes": [("left", 220, "covered / uncovered summary"),
                       ("left", 430, "specification requirement"),
                       ("right", 230, "implementing entity"), ("right", 480, "recorded test reachability"),
                       ("right", 720, "open the source")],
        "focus_rectangles": [(335, 255, 1245, 340), (335, 345, 1245, 610)],
        "focus_arrows": [((1760, 400), (1490, 400))],
    },
    12: {
        "title": "GUI tour: Rule Issues", "screenshot": "views/rule-issues.png", "icoda_screen": True,
        "side_notes": [("left", 240, "severity"), ("left", 400, "rule • entity • action"),
                       ("right", 250, "location"), ("right", 600, "double-click to inspect source")],
        "focus_rectangles": [(335, 270, 1245, 600)],
        "focus_arrows": [((180, 330), (410, 330)), ((180, 390), (650, 390)),
                         ((1750, 455), (1480, 455))],
    },
    14: {
        "title": "Walkthrough output: specification blocks code",
        "screenshot": "lifecycle/sim-01-specification-code-refused.png", "icoda_screen": True,
        "side_notes": [("left", 650, "3  Click Propose before saving"),
                       ("right", 650, "no code proposal yet"),
                       ("right", 825, "state unchanged • next action: open the editor")],
        "focus_rectangles": [(320, 665, 1598, 995)],
        "focus_arrows": [((1750, 720), (1510, 720))],
    },
    16: {
        "title": "Walkthrough output and input: inspect, then reject",
        "screenshot": "lifecycle/sim-03-architecture-reject.png", "icoda_screen": True,
        "side_notes": [("left", 660, "15  Request blank • Max entities 5"),
                       ("right", 660, "16  Propose • 17  Inspect evidence"),
                       ("right", 865, "18  Reject… • reason retained")],
        "focus_rectangles": [(320, 665, 760, 740), (790, 745, 1595, 970), (435, 708, 525, 744)],
        "focus_arrows": [((525, 744), (700, 790))],
        "callouts": [((700, 770, 1160, 825), "19  Keep the public API smaller")],
    },
    17: {
        "title": "Walkthrough output and input: approve the adaptation",
        "screenshot": "lifecycle/sim-04-architecture-approve.png", "icoda_screen": True,
        "side_notes": [("left", 660, "20  Propose again • 22  Approve"),
                       ("right", 650, "21  Review adapted Delta"),
                       ("right", 840, "public API smaller • gates passed")],
        "focus_rectangles": [(790, 745, 1595, 970), (320, 665, 1595, 740)],
        "focus_arrows": [((180, 715), (380, 715))],
    },
    18: {
        "title": "Walkthrough gate: enter implementation",
        "screenshot": "lifecycle/sim-05-architecture-gate.png", "icoda_screen": True,
        "side_notes": [("left", 640, "23  Click Approve architecture"),
                       ("right", 650, "completion gate enabled"),
                       ("right", 830, "queue: Formatter.normalize, main")],
        "focus_rectangles": [(320, 220, 1258, 650), (320, 665, 1595, 760)],
        "focus_arrows": [((180, 720), (430, 720))],
    },
    19: {
        "title": "Walkthrough target one: approve the approach",
        "screenshot": "lifecycle/sim-06-normalize-approach.png", "icoda_screen": True,
        "side_notes": [("left", 640, "24  Batch 1 • queue order • one entity"),
                       ("left", 820, "25  Propose approach"),
                       ("right", 650, "26  Review entity + files"),
                       ("right", 850, "27  Approve approach")],
        "focus_rectangles": [(320, 665, 1595, 735), (790, 745, 1595, 970)],
        "focus_arrows": [((180, 715), (500, 715))],
    },
    20: {
        "title": "Walkthrough target one: verify and approve code",
        "screenshot": "lifecycle/sim-07-normalize-build-test.png", "icoda_screen": True,
        "side_notes": [("left", 430, "normalize marked tested"),
                       ("left", 650, "28  Propose • 30  Approve"),
                       ("right", 650, "29  Inspect Delta, Diff, Build, Tests, Prompt, Reply"),
                       ("right", 875, "source promoted + committed")],
        "focus_rectangles": [(320, 665, 780, 740), (790, 745, 1595, 970), (350, 705, 430, 742)],
        "focus_arrows": [((180, 500), (610, 500))],
    },
    21: {
        "title": "Walkthrough target two: approve the approach",
        "screenshot": "lifecycle/sim-08-main-approach.png", "icoda_screen": True,
        "side_notes": [("left", 260, "queue advances automatically"),
                       ("left", 650, "31  Propose approach"),
                       ("right", 650, "32  Review entity + files"),
                       ("right", 850, "33  Approve approach")],
        "focus_rectangles": [(340, 260, 1210, 620), (320, 665, 1595, 735), (790, 745, 1595, 970)],
        "focus_arrows": [((180, 715), (500, 715))],
    },
    22: {
        "title": "Walkthrough target two: verify and approve code",
        "screenshot": "lifecycle/sim-09-main-build-test.png", "icoda_screen": True,
        "side_notes": [("left", 280, "visible Issues view"),
                       ("left", 650, "34  Propose • 36  Approve"),
                       ("right", 650, "35  Inspect source Diff + both gates"),
                       ("right", 860, "main marked tested")],
        "focus_rectangles": [(340, 275, 1240, 595), (790, 745, 1595, 970)],
        "focus_arrows": [((180, 715), (390, 715))],
    },
    23: {
        "title": "Walkthrough output: terminal overview",
        "screenshot": "lifecycle/sim-10-terminal-overview.png", "icoda_screen": True,
        "side_notes": [("left", 250, "Coverage links both callables to tests/test_service.py"),
                       ("left", 665, "queue empty • working tree clean"),
                       ("right", 300, "both targets tested"),
                       ("right", 700, "all scripted provider replies consumed")],
        "focus_rectangles": [(335, 255, 1245, 610), (320, 665, 1595, 760)],
        "focus_arrows": [((1750, 410), (1470, 410)), ((180, 720), (500, 720))],
    },
}


ICODA_SLIDES: list[dict[str, Any]] = [
    {"number": 1, "title": "ICODA", "custom": draw_icoda_slide_01},
    {"number": 2, "title": "About Helmut Hlavacs", "custom": draw_icoda_slide_02},
    {"number": 3, "title": "What ICODA is for", "custom": draw_icoda_slide_03},
    {"number": 4, "title": "The basic idea", "custom": draw_icoda_slide_04},
    {"number": 5, "title": "The mental model: two truths", "custom": draw_icoda_slide_05},
    {"number": 6, "title": "How ICODA works", "custom": draw_icoda_slide_06},
    *({"number": number, **ICODA_SCREEN_SLIDES[number]} for number in range(7, 13)),
    {"number": 13, "title": "Walkthrough input: create the project", "custom": draw_icoda_slide_13,
     "focus_rectangles": [(142, 315, 535, 375), (720, 410, 1680, 485)],
     "focus_arrows": [((1680, 485), (1560, 790))]},
    {"number": 14, **ICODA_SCREEN_SLIDES[14]},
    {"number": 15, "title": "Walkthrough inputs: specify, build, and configure", "custom": draw_icoda_slide_15,
     "screenshots": [
         {"filename": "lifecycle/sim-02-specification-save.png", "target": (80, 190, 1380, 900)},
         {"filename": "views/provider-selection.png", "target": (1410, 240, 1810, 560)},
     ],
     "focus_rectangles": [(180, 220, 1260, 270), (1480, 295, 1770, 365), (620, 935, 1040, 992)],
     "focus_arrows": [((120, 355), (420, 355)), ((1310, 850), (1190, 850))]},
    *({"number": number, **ICODA_SCREEN_SLIDES[number]} for number in range(16, 24)),
    {"number": 24, "title": "Keep intent, evidence, and decisions together", "custom": draw_icoda_slide_24},
]


DECKS: dict[str, tuple[list[dict[str, Any]], Path, Path]] = {
    "ai-loop": (SLIDES, VIDEO_DIR / "ai-loop" / "screenshots", VIDEO_DIR / "ai-loop" / "slides"),
    "icoda": (ICODA_SLIDES, VIDEO_DIR / "icoda" / "screenshots", VIDEO_DIR / "icoda" / "slides"),
}


def configure_deck(deck: str) -> None:
    global SLIDES, SCREENSHOT_DIR, OUTPUT_DIR
    SLIDES, SCREENSHOT_DIR, OUTPUT_DIR = DECKS[deck]


def screenshot_placements(spec: dict[str, Any]) -> list[dict[str, Any]]:
    if "screenshot" in spec:
        return [{"filename": spec["screenshot"], "target": COMMON_TARGET, "source_crop": None}]
    return spec.get("screenshots", [])


def draw_focus_overlays(draw: ImageDraw.ImageDraw, spec: dict[str, Any]) -> None:
    for box in spec.get("focus_rectangles", []):
        highlight(draw, box)
    for start, end in spec.get("focus_arrows", []):
        arrow(draw, start, end, fill=RED, width=6)


def render_slide(spec: dict[str, Any]) -> Image.Image:
    canvas = Image.new("RGBA", FRAME_SIZE, WHITE)
    draw = ImageDraw.Draw(canvas)
    if "custom" in spec:
        spec["custom"](canvas, draw)
        draw_focus_overlays(draw, spec)
    elif spec.get("icoda_screen"):
        title(draw, spec["title"])
        paste_contained(canvas, spec["screenshot"], COMMON_TARGET)
        for side, y, value in spec.get("side_notes", []):
            side_note(draw, side, y, value)
        for box, value in spec.get("callouts", []):
            card(draw, box, fill=PALE_RED, outline=RED, radius=10, width=3)
            put(draw, (box[0] + 18, box[1] + 14), value, 17, bold=True, fill=RED)
        draw_focus_overlays(draw, spec)
    else:
        title(draw, spec["title"])
        paste_contained(canvas, spec["screenshot"], COMMON_TARGET)
        for box in spec["highlights"]:
            highlight(draw, box)
        for side, y, value, target_point in spec["labels"]:
            margin_label(draw, side, y, value, target_point, size=17 if spec["number"] == 18 else 19)
    paste_logo(canvas)
    return canvas.convert("RGB")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deck", choices=sorted(DECKS), default="ai-loop")
    args = parser.parse_args(argv)
    configure_deck(args.deck)
    if len(SLIDES) != 24 or [spec["number"] for spec in SLIDES] != list(range(1, 25)):
        raise RuntimeError("slide specification must contain numbers 1 through 24 exactly once")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for stale in OUTPUT_DIR.glob("slide-*.png"):
        stale.unlink()
    for spec in SLIDES:
        output = OUTPUT_DIR / f"slide-{spec['number']:02d}.png"
        render_slide(spec).save(output)
        print(f"{output.relative_to(VIDEO_DIR)}: {FRAME_SIZE[0]}x{FRAME_SIZE[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
