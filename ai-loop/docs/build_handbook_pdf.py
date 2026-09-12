#!/usr/bin/env python3
"""Build the illustrated AI-Loop specification handbook with ReportLab."""

from __future__ import annotations

import html
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.fonts import addMapping
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    KeepTogether,
    ListFlowable,
    ListItem,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
)
from reportlab.platypus.tableofcontents import TableOfContents

DOCS_DIR = Path(__file__).resolve().parent
SOURCE = DOCS_DIR / "HANDBOOK.md"
OUTPUT = DOCS_DIR / "AI-Loop-Handbook.pdf"
IMAGE_RE = re.compile(r"^!\[(?P<caption>.+)]\((?P<path>[^)]+)\)$")
HEADING_RE = re.compile(r"^(?P<marks>#{1,3})\s+(?P<title>.+)$")
LIST_RE = re.compile(r"^(?P<indent>\s*)(?P<marker>-|\d+\.)\s+(?P<text>.+)$")


def _register_fonts() -> tuple[str, str, str, str]:
    font_dir = Path("/usr/share/fonts/truetype/dejavu")
    regular = font_dir / "DejaVuSans.ttf"
    bold = font_dir / "DejaVuSans-Bold.ttf"
    italic = font_dir / "DejaVuSans-Oblique.ttf"
    mono = font_dir / "DejaVuSansMono.ttf"
    if not all(path.exists() for path in (regular, bold, italic, mono)):
        return "Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Courier"
    pdfmetrics.registerFont(TTFont("HandbookSans", regular))
    pdfmetrics.registerFont(TTFont("HandbookSans-Bold", bold))
    pdfmetrics.registerFont(TTFont("HandbookSans-Italic", italic))
    pdfmetrics.registerFont(TTFont("HandbookMono", mono))
    addMapping("HandbookSans", 0, 0, "HandbookSans")
    addMapping("HandbookSans", 1, 0, "HandbookSans-Bold")
    addMapping("HandbookSans", 0, 1, "HandbookSans-Italic")
    return "HandbookSans", "HandbookSans-Bold", "HandbookSans-Italic", "HandbookMono"


BODY_FONT, BOLD_FONT, ITALIC_FONT, MONO_FONT = _register_fonts()


def _inline(value: str) -> str:
    escaped = html.escape(value, quote=False)
    escaped = re.sub(
        r"`([^`]+)`",
        lambda match: f'<font name="{MONO_FONT}" size="8.3">{match.group(1)}</font>',
        escaped,
    )
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", escaped)
    return escaped


def _styles() -> dict[str, ParagraphStyle]:
    sample = getSampleStyleSheet()
    body = ParagraphStyle(
        "Body",
        parent=sample["BodyText"],
        fontName=BODY_FONT,
        fontSize=9.2,
        leading=13.2,
        textColor=colors.HexColor("#263238"),
        spaceAfter=5,
    )
    return {
        "body": body,
        "h1": ParagraphStyle(
            "Heading1",
            parent=sample["Heading1"],
            fontName=BOLD_FONT,
            fontSize=19,
            leading=23,
            textColor=colors.HexColor("#153E5C"),
            spaceBefore=8,
            spaceAfter=10,
            keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "Heading2",
            parent=sample["Heading2"],
            fontName=BOLD_FONT,
            fontSize=14,
            leading=18,
            textColor=colors.HexColor("#176B87"),
            spaceBefore=9,
            spaceAfter=6,
            keepWithNext=True,
        ),
        "h3": ParagraphStyle(
            "Heading3",
            parent=sample["Heading3"],
            fontName=BOLD_FONT,
            fontSize=11,
            leading=14,
            textColor=colors.HexColor("#176B87"),
            spaceBefore=7,
            spaceAfter=4,
            keepWithNext=True,
        ),
        "bullet": ParagraphStyle(
            "Bullet",
            parent=body,
            leftIndent=0,
            firstLineIndent=0,
            spaceAfter=2,
        ),
        "caption": ParagraphStyle(
            "Caption",
            parent=body,
            fontName=ITALIC_FONT,
            fontSize=8.2,
            leading=11,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#455A64"),
            spaceBefore=7,
            spaceAfter=0,
        ),
        "code": ParagraphStyle(
            "Code",
            parent=body,
            fontName=MONO_FONT,
            fontSize=7.8,
            leading=10.2,
            leftIndent=8,
            rightIndent=8,
            borderColor=colors.HexColor("#CFD8DC"),
            borderWidth=0.5,
            borderPadding=6,
            backColor=colors.HexColor("#F4F7F8"),
            spaceBefore=4,
            spaceAfter=7,
        ),
    }


STYLES = _styles()


class HandbookDocTemplate(BaseDocTemplate):
    def afterFlowable(self, flowable: object) -> None:
        if not isinstance(flowable, Paragraph):
            return
        levels = {"Heading2": 0}
        level = levels.get(flowable.style.name)
        if level is None:
            return
        title = flowable.getPlainText()
        key = f"section-{self.seq.nextf('section')}"
        self.canv.bookmarkPage(key)
        self.canv.addOutlineEntry(title, key, level=level, closed=level > 0)
        self.notify("TOCEntry", (level, title, self.page, key))


def _page_decor(canvas: object, doc: BaseDocTemplate) -> None:
    canvas.saveState()
    width, height = canvas._pagesize
    if doc.page > 1:
        canvas.setFont(BOLD_FONT, 7.5)
        canvas.setFillColor(colors.HexColor("#546E7A"))
        canvas.drawString(16 * mm, height - 10 * mm, "AI-LOOP / SPECIFICATION HANDBOOK")
        canvas.drawRightString(width - 16 * mm, height - 10 * mm, "ILLUSTRATED EDITION")
        canvas.setStrokeColor(colors.HexColor("#CFD8DC"))
        canvas.line(16 * mm, height - 12 * mm, width - 16 * mm, height - 12 * mm)
        canvas.setFont(BODY_FONT, 7.5)
        canvas.drawString(16 * mm, 9 * mm, "Specification guide")
        canvas.drawRightString(width - 16 * mm, 9 * mm, str(doc.page))
    canvas.restoreState()


def _document() -> HandbookDocTemplate:
    doc = HandbookDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        title="AI-Loop Specification Handbook",
        author="AI-Loop Project",
        subject="Illustrated guide to the AI-Loop specification process",
    )
    portrait_frame = Frame(
        18 * mm,
        16 * mm,
        A4[0] - 36 * mm,
        A4[1] - 32 * mm,
        topPadding=11 * mm,
        bottomPadding=2 * mm,
        id="portrait-frame",
    )
    landscape_size = landscape(A4)
    landscape_frame = Frame(
        12 * mm,
        14 * mm,
        landscape_size[0] - 24 * mm,
        landscape_size[1] - 28 * mm,
        topPadding=10 * mm,
        bottomPadding=0,
        id="landscape-frame",
    )
    doc.addPageTemplates(
        [
            PageTemplate(
                id="portrait", pagesize=A4, frames=[portrait_frame], onPage=_page_decor
            ),
            PageTemplate(
                id="landscape",
                pagesize=landscape_size,
                frames=[landscape_frame],
                onPage=_page_decor,
            ),
        ]
    )
    return doc


def _cover() -> list[object]:
    return [
        Spacer(1, 42 * mm),
        Paragraph(
            "AI-Loop",
            ParagraphStyle(
                "CoverProduct",
                fontName=BOLD_FONT,
                fontSize=38,
                leading=42,
                textColor=colors.HexColor("#153E5C"),
                alignment=TA_LEFT,
            ),
        ),
        Paragraph(
            "Specification Handbook",
            ParagraphStyle(
                "CoverTitle",
                fontName=BOLD_FONT,
                fontSize=27,
                leading=34,
                textColor=colors.HexColor("#176B87"),
                spaceBefore=4,
            ),
        ),
        Spacer(1, 8 * mm),
        Paragraph(
            "From a compact draft to approved, verified work",
            ParagraphStyle(
                "CoverSubtitle",
                fontName=BODY_FONT,
                fontSize=14,
                leading=19,
                textColor=colors.HexColor("#455A64"),
            ),
        ),
        Spacer(1, 80 * mm),
        Paragraph(
            "USER EDITION / 10 GUI SCREENSHOTS",
            ParagraphStyle(
                "CoverEdition",
                fontName=BOLD_FONT,
                fontSize=10,
                leading=14,
                textColor=colors.HexColor("#607D8B"),
            ),
        ),
        PageBreak(),
    ]


def _contents() -> list[object]:
    toc = TableOfContents()
    toc.levelStyles = [
        ParagraphStyle(
            "TOC1",
            fontName=BOLD_FONT,
            fontSize=10,
            leading=15,
            leftIndent=0,
            firstLineIndent=0,
            textColor=colors.HexColor("#153E5C"),
        ),
        ParagraphStyle(
            "TOC2",
            fontName=BODY_FONT,
            fontSize=8.5,
            leading=12,
            leftIndent=12,
            firstLineIndent=0,
            textColor=colors.HexColor("#455A64"),
        ),
        ParagraphStyle(
            "TOC3",
            fontName=BODY_FONT,
            fontSize=7.8,
            leading=10,
            leftIndent=24,
            firstLineIndent=0,
            textColor=colors.HexColor("#607D8B"),
        ),
    ]
    contents_heading = ParagraphStyle(
        "ContentsHeading",
        parent=STYLES["h1"],
    )
    return [
        Paragraph("Contents", contents_heading),
        Paragraph(
            "Use the contents or PDF bookmarks to navigate. Screenshots appear on dedicated landscape pages.",
            STYLES["body"],
        ),
        Spacer(1, 5 * mm),
        toc,
        PageBreak(),
    ]


def _figure(
    path_text: str, caption: str, *, return_to_portrait: bool = True
) -> list[object]:
    image_path = (DOCS_DIR / path_text).resolve()
    if not image_path.is_file() or DOCS_DIR not in image_path.parents:
        raise FileNotFoundError(
            f"handbook image is missing or outside docs: {path_text}"
        )
    image = Image(str(image_path))
    max_width = landscape(A4)[0] - 34 * mm
    max_height = landscape(A4)[1] - 54 * mm
    scale = min(max_width / image.imageWidth, max_height / image.imageHeight)
    image.drawWidth = image.imageWidth * scale
    image.drawHeight = image.imageHeight * scale
    image.hAlign = "CENTER"
    result: list[object] = [
        NextPageTemplate("landscape"),
        PageBreak(),
        KeepTogether(
            [
                image,
                Paragraph(f"Figure — {_inline(caption)}", STYLES["caption"]),
            ]
        ),
    ]
    if return_to_portrait:
        result.extend((NextPageTemplate("portrait"), PageBreak()))
    return result


def _list(lines: list[str], start: int) -> tuple[ListFlowable, int]:
    first = LIST_RE.match(lines[start])
    assert first is not None
    ordered = first.group("marker") != "-"
    items: list[ListItem] = []
    index = start
    while index < len(lines):
        match = LIST_RE.match(lines[index])
        if match is None or (match.group("marker") != "-") != ordered:
            break
        text = match.group("text")
        index += 1
        while index < len(lines):
            continuation = lines[index]
            if not continuation.strip():
                break
            if (
                LIST_RE.match(continuation)
                or HEADING_RE.match(continuation)
                or IMAGE_RE.match(continuation)
            ):
                break
            if continuation.startswith("  "):
                text += " " + continuation.strip()
                index += 1
                continue
            break
        items.append(ListItem(Paragraph(_inline(text), STYLES["bullet"])))
        if index < len(lines) and not lines[index].strip():
            probe = index + 1
            if probe < len(lines):
                next_match = LIST_RE.match(lines[probe])
                if next_match and (next_match.group("marker") != "-") == ordered:
                    index = probe
                    continue
            break
    flowable = ListFlowable(
        items,
        bulletType="1" if ordered else "bullet",
        start="1" if ordered else None,
        leftIndent=17,
        bulletFontName=BODY_FONT,
        bulletFontSize=8.5,
        spaceAfter=5,
    )
    return flowable, index


def _markdown_story() -> list[object]:
    lines = SOURCE.read_text(encoding="utf-8").splitlines()
    story: list[object] = []
    index = 0
    title_skipped = False
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        if line.startswith("```"):
            index += 1
            code: list[str] = []
            while index < len(lines) and not lines[index].startswith("```"):
                code.append(lines[index])
                index += 1
            if index >= len(lines):
                raise ValueError("unterminated Markdown code fence")
            story.append(Preformatted("\n".join(code), STYLES["code"]))
            index += 1
            continue
        image_match = IMAGE_RE.match(line)
        if image_match:
            next_index = index + 1
            while next_index < len(lines) and not lines[next_index].strip():
                next_index += 1
            story.extend(
                _figure(
                    image_match.group("path"),
                    image_match.group("caption"),
                    return_to_portrait=(
                        next_index >= len(lines)
                        or IMAGE_RE.match(lines[next_index]) is None
                    ),
                )
            )
            index += 1
            continue
        heading_match = HEADING_RE.match(line)
        if heading_match:
            level = len(heading_match.group("marks"))
            if level == 1 and not title_skipped:
                title_skipped = True
                index += 1
                continue
            style = STYLES[f"h{level}"]
            story.append(Paragraph(_inline(heading_match.group("title")), style))
            index += 1
            continue
        if LIST_RE.match(line):
            flowable, index = _list(lines, index)
            story.append(flowable)
            continue
        paragraph = [line.strip()]
        index += 1
        while index < len(lines):
            candidate = lines[index]
            if (
                not candidate.strip()
                or candidate.startswith("```")
                or IMAGE_RE.match(candidate)
                or HEADING_RE.match(candidate)
                or LIST_RE.match(candidate)
            ):
                break
            paragraph.append(candidate.strip())
            index += 1
        story.append(Paragraph(_inline(" ".join(paragraph)), STYLES["body"]))
    return story


def main() -> None:
    doc = _document()
    story = [*_cover(), *_contents(), *_markdown_story()]
    doc.multiBuild(story)
    print(f"Built {OUTPUT}")


if __name__ == "__main__":
    main()
