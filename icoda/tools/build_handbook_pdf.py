"""Build the illustrated ICODA handbook as a searchable, offline PDF."""

from __future__ import annotations

import argparse
import io
import json
import re
import textwrap
import zlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = (
    ROOT / "HANDBOOK.md",
    ROOT / "docs" / "GETTING_STARTED.md",
    ROOT / "docs" / "TUTORIAL.md",
    ROOT / "docs" / "TROUBLESHOOTING.md",
)
OUTPUT = ROOT / "output" / "pdf" / "ICODA-Handbook.pdf"
HIGHLIGHTS = ROOT / "tools" / "handbook_highlights.json"
BUILD_INVOCATION = ".icoda-venv/bin/python tools/build_handbook_pdf.py"

A4 = (595.28, 841.89)
A4_LANDSCAPE = (A4[1], A4[0])
IMAGE_RE = re.compile(r"^!\[(?P<caption>.+)]\((?P<path>[^)]+)\)$")
HEADING_RE = re.compile(r"^(?P<marks>#{1,3})\s+(?P<title>.+)$")
TABLE_RULE_RE = re.compile(r"^\|?(?:\s*:?-+:?\s*\|)+\s*$")
LIST_RE = re.compile(r"^(?P<indent> *)(?P<marker>[-*+]|\d+[.)]) +(?P<body>.*)$")
# Standard PDF Helvetica advances in 1/1000 em, for WinAnsi bytes 32 through 255.
# Keep the offline builder independent of installed fonts and extra PDF packages.
HELVETICA_WIDTHS = (
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,
    1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
    333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
    556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584, 350,
    556, 350, 222, 556, 333, 1000, 556, 556, 333, 1000, 667, 333, 1000, 350, 611, 350,
    350, 222, 222, 333, 333, 350, 556, 1000, 333, 1000, 500, 333, 944, 350, 500, 667,
    278, 333, 556, 556, 556, 556, 260, 556, 333, 737, 370, 556, 584, 333, 737, 333,
    400, 584, 333, 333, 333, 556, 537, 278, 333, 333, 365, 556, 834, 834, 834, 611,
    667, 667, 667, 667, 667, 667, 1000, 722, 667, 667, 667, 667, 278, 278, 278, 278,
    722, 722, 778, 778, 778, 778, 778, 584, 778, 722, 722, 722, 722, 667, 667, 611,
    556, 556, 556, 556, 556, 556, 889, 500, 556, 556, 556, 556, 278, 278, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 584, 611, 556, 556, 556, 556, 500, 556, 500,
)
HELVETICA_BOLD_WIDTHS = (
    278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 333, 333, 584, 584, 584, 611,
    975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556,
    333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611,
    611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584, 350,
    556, 350, 278, 556, 500, 1000, 556, 556, 333, 1000, 667, 333, 1000, 350, 611, 350,
    350, 278, 278, 500, 500, 350, 556, 1000, 333, 1000, 556, 333, 944, 350, 500, 667,
    278, 333, 556, 556, 556, 556, 280, 556, 333, 737, 370, 556, 584, 333, 737, 333,
    400, 584, 333, 333, 333, 611, 556, 278, 333, 333, 365, 556, 834, 834, 834, 611,
    722, 722, 722, 722, 722, 722, 1000, 722, 667, 667, 667, 667, 278, 278, 278, 278,
    722, 722, 778, 778, 778, 778, 778, 584, 778, 722, 722, 722, 722, 667, 667, 611,
    556, 556, 556, 556, 556, 556, 889, 556, 556, 556, 556, 556, 278, 278, 278, 278,
    611, 611, 611, 611, 611, 611, 611, 584, 611, 611, 611, 611, 611, 556, 611, 556,
)


def _list_item(lines: list[str], index: int) -> tuple[list[str], int]:
    """Dedent a whole item, retaining its paragraphs, nested lists and code blocks."""
    match = LIST_RE.match(lines[index])
    assert match is not None
    content_indent = match.start("body")
    item = [match.group("body")]
    index += 1
    after_blank = False
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            item.append("")
            after_blank = True
            index += 1
            continue
        indentation = len(line) - len(line.lstrip())
        if indentation < content_indent:
            # Markdown allows unindented soft continuations of the first paragraph,
            # but a blank line or a new block ends that lazy continuation.
            if after_blank or LIST_RE.match(line) or HEADING_RE.match(line) \
                    or IMAGE_RE.match(line) or line.startswith(("```", "|", ">")):
                break
            item.append(line.strip())
        else:
            item.append(line[content_indent:])
        after_blank = False
        index += 1
    return item, index


def _plain_markdown(value: str) -> str:
    value = re.sub(r"\[([^]]+)]\([^)]+\)", r"\1", value)
    value = re.sub(r"!\[([^]]+)]\([^)]+\)", r"\1", value)
    value = value.replace("**", "").replace("__", "").replace("`", "")
    value = re.sub(r"(?<!\w)[*_](.+?)[*_](?!\w)", r"\1", value)
    return value.strip()


def _encoded_text(value: str) -> bytes:
    replacements = {
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2026": "...",
        "\u2192": "->",
        "\u25b8": ">",
        "\u2318": "Cmd-",
        "\u00a0": " ",
    }
    for source, target in replacements.items():
        value = value.replace(source, target)
    return value.encode("cp1252", errors="replace")


def _pdf_text(value: str) -> bytes:
    encoded = _encoded_text(value)
    return encoded.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _text_width(text: str, *, font: str, size: float) -> float:
    encoded = _encoded_text(text)
    if font == "F4":
        return len(encoded) * size * 0.60
    widths = HELVETICA_BOLD_WIDTHS if font == "F2" else HELVETICA_WIDTHS
    return sum(widths[code - 32] for code in encoded if code >= 32) * size / 1000


@dataclass
class Page:
    width: float
    height: float
    number: int
    commands: list[bytes] = field(default_factory=list)
    image_name: str | None = None

    def text(self, x: float, y: float, value: str, *, font: str = "F1", size: float = 9.2) -> None:
        command = (
            f"BT /{font} {size:.2f} Tf 1 0 0 1 {x:.2f} {y:.2f} Tm (".encode()
            + _pdf_text(value)
            + b") Tj ET\n"
        )
        self.commands.append(command)

    def line(self, x1: float, y1: float, x2: float, y2: float) -> None:
        self.commands.append(f"0.72 G 0.5 w {x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S\n".encode())

    def place_image(self, name: str, x: float, y: float, width: float, height: float) -> None:
        self.image_name = name
        self.commands.append(
            f"q {width:.2f} 0 0 {height:.2f} {x:.2f} {y:.2f} cm /{name} Do Q\n".encode()
        )

    def highlight(self, x: float, y: float, width: float, height: float) -> None:
        """Draw an unfilled red vector rectangle without affecting other page content."""
        self.commands.append(
            f"q 1 0 0 RG 1.4 w {x:.2f} {y:.2f} {width:.2f} {height:.2f} re S Q\n".encode()
        )


@dataclass(frozen=True)
class PdfImage:
    name: str
    path: Path
    width: int
    height: int
    jpeg: bytes


class MarkdownRenderer:
    def __init__(self, *, first_page: int) -> None:
        self.pages: list[Page] = []
        self.images: list[PdfImage] = []
        self.toc: list[tuple[int, str, int]] = []
        self._next_number = first_page
        self._page: Page | None = None
        self._y = 0.0
        self._highlights = json.loads(HIGHLIGHTS.read_text(encoding="utf-8"))

    def _decorate(self, page: Page) -> None:
        page.text(48, page.height - 27, "ICODA / ILLUSTRATED HANDBOOK", font="F2", size=7.5)
        page.line(48, page.height - 34, page.width - 48, page.height - 34)
        page.text(page.width / 2 - 3, 21, str(page.number), size=8)

    def _new_portrait(self) -> None:
        page = Page(*A4, self._next_number)
        self._next_number += 1
        self._decorate(page)
        self.pages.append(page)
        self._page = page
        self._y = page.height - 58

    def _ensure_space(self, height: float) -> Page:
        if self._page is None or self._y - height < 45:
            self._new_portrait()
        assert self._page is not None
        return self._page

    def page_break(self) -> None:
        self._page = None

    def _wrapped(self, text: str, *, size: float, indent: float = 0, font: str = "F1") -> list[str]:
        available = A4[0] - 104 - indent
        lines: list[str] = []
        line = ""
        for chunk in re.findall(r"\s*\S+", text):
            if line and _text_width(line + chunk, font=font, size=size) > available:
                lines.append(line.rstrip())
                line = chunk.lstrip()
            else:
                line += chunk
            # Split only tokens too wide for an entire line (for example, a long path).
            while _text_width(line, font=font, size=size) > available:
                width = 0.0
                cut = 0
                for character in line:
                    width += _text_width(character, font=font, size=size)
                    if width > available:
                        break
                    cut += 1
                cut = max(1, cut)
                lines.append(line[:cut])
                line = line[cut:]
        if line:
            lines.append(line.rstrip())
        return lines or [""]

    def paragraph(
        self,
        text: str,
        *,
        font: str = "F1",
        size: float = 9.2,
        leading: float = 12.2,
        indent: float = 0,
        before: float = 0,
        after: float = 6,
        marker: str | None = None,
    ) -> None:
        text = _plain_markdown(text)
        lines = self._wrapped(text, size=size, indent=indent, font=font)
        page = self._ensure_space(before + leading * len(lines) + after)
        self._y -= before
        if marker is not None:
            marker_width = _text_width(marker, font=font, size=size)
            page.text(52 + indent - 6 - marker_width, self._y, marker, font=font, size=size)
        for line in lines:
            page.text(52 + indent, self._y, line, font=font, size=size)
            self._y -= leading
        self._y -= after

    def heading(self, level: int, title: str, *, following: str = "",
                following_code: list[str] | None = None) -> None:
        title = _plain_markdown(title)
        styles = {
            1: ("F2", 20.0, 25.0, 10.0, 11.0),
            2: ("F2", 14.5, 18.0, 9.0, 7.0),
            3: ("F2", 11.2, 14.0, 7.0, 4.0),
        }
        font, size, leading, before, after = styles[level]
        lines = self._wrapped(title, size=size, font=font)
        following_lines = self._wrapped(_plain_markdown(following), size=9.2) if following else []
        keep_next = max(4 * 12.2, len(following_lines) * 12.2 + 6)
        if following_code is not None:
            listing_height = len(self._code_lines(following_code)) * 9.6 + 14
            group_height = len(following_lines) * 12.2 + 6 + listing_height
            heading_height = before + leading * len(lines) + after
            if heading_height + group_height <= A4[1] - 103:
                keep_next = max(keep_next, group_height)
        page = self._ensure_space(before + leading * len(lines) + after + keep_next)
        if level <= 2:
            self.toc.append((level, title, page.number))
        self._y -= before
        for line in lines:
            page.text(52, self._y, line, font=font, size=size)
            self._y -= leading
        self._y -= after

    def _code_lines(self, lines: list[str], *, indent: float = 0) -> list[str]:
        return [
            line
            for raw_line in lines or [""]
            for line in self._wrapped(raw_line.expandtabs(4), size=7.4,
                                      indent=indent + 8, font="F4")
        ]

    def code(self, lines: list[str], *, indent: float = 0) -> None:
        wrapped = self._code_lines(lines, indent=indent)
        height = len(wrapped) * 9.6 + 14
        page = self._ensure_space(height if height <= A4[1] - 103 else 15)
        page.line(52 + indent, self._y + 5, A4[0] - 52, self._y + 5)
        self._y -= 5
        for line in wrapped:
            page = self._ensure_space(10)
            page.text(60 + indent, self._y, line, font="F4", size=7.4)
            self._y -= 9.6
        page = self._ensure_space(9)
        page.line(52 + indent, self._y + 3, A4[0] - 52, self._y + 3)
        self._y -= 7

    def table_row(self, line: str, *, indent: float = 0) -> None:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        self.paragraph(" | ".join(cells), font="F4", size=7.2, leading=9.2, after=2, indent=indent)

    def figure(self, source: Path, path_text: str, caption: str) -> None:
        from PIL import Image as PillowImage

        image_path = (source.parent / path_text).resolve()
        if not image_path.is_file() or ROOT not in image_path.parents:
            raise FileNotFoundError(f"handbook image is missing or outside icoda: {path_text}")
        with PillowImage.open(image_path) as original:
            rgba = original.convert("RGBA")
            background = PillowImage.new("RGB", rgba.size, "white")
            background.paste(rgba, mask=rgba.getchannel("A"))
            data = io.BytesIO()
            background.save(data, format="JPEG", quality=88, optimize=True)
            image = PdfImage(
                name=f"Im{len(self.images) + 1}",
                path=image_path,
                width=background.width,
                height=background.height,
                jpeg=data.getvalue(),
            )
        self.images.append(image)
        self.page_break()
        page = Page(*A4_LANDSCAPE, self._next_number)
        self._next_number += 1
        self._decorate(page)
        max_width = page.width - 72
        max_height = page.height - 112
        scale = min(max_width / image.width, max_height / image.height)
        width = image.width * scale
        height = image.height * scale
        x, y = (page.width - width) / 2, 62
        page.place_image(image.name, x, y, width, height)
        # Boxes use top-left coordinates in the manifest's reference image size.
        # Keep screenshots untouched and scale the overlays with each placed image.
        annotation = self._highlights[image.path.name]
        reference_width, reference_height = annotation["size"]
        if reference_width <= 0 or reference_height <= 0 or \
                reference_width * image.height != reference_height * image.width:
            raise ValueError(f"highlight reference size does not match {image.path}")
        if not annotation["regions"]:
            raise ValueError(f"screenshot has no highlight regions: {image.path}")
        for region in annotation["regions"]:
            left, top, right, bottom = region["box"]
            if not (0 <= left < right <= reference_width and
                    0 <= top < bottom <= reference_height):
                raise ValueError(f"invalid highlight box for {image.path}: {region}")
            page.highlight(
                x + left / reference_width * width,
                y + (reference_height - bottom) / reference_height * height,
                (right - left) / reference_width * width,
                (bottom - top) / reference_height * height,
            )
        clean_caption = _plain_markdown(caption)
        caption_width = min(len(clean_caption) * 4.4, page.width - 80)
        page.text((page.width - caption_width) / 2, 45, clean_caption, font="F3", size=8.2)
        self.pages.append(page)
        self.page_break()

    def document(self, source: Path) -> None:
        if self.pages:
            self.page_break()
        lines = source.read_text(encoding="utf-8").expandtabs(4).splitlines()
        self._blocks(lines, source)

    def _blocks(self, lines: list[str], source: Path, *, indent: float = 0,
                marker: str | None = None) -> None:
        index = 0
        ordered_number: int | None = None
        while index < len(lines):
            line = lines[index]
            if not line.strip():
                index += 1
                continue
            list_match = LIST_RE.match(line)
            if list_match:
                token = list_match.group("marker")
                if token[0].isdigit():
                    ordered_number = int(token[:-1]) if ordered_number is None else ordered_number + 1
                    item_marker = f"{ordered_number}."
                else:
                    ordered_number = None
                    item_marker = "\u2022"
                item, index = _list_item(lines, index)
                self._blocks(item, source, indent=indent + 24, marker=item_marker)
                continue
            ordered_number = None
            if line.startswith("```"):
                index += 1
                code_lines: list[str] = []
                while index < len(lines) and not lines[index].startswith("```"):
                    code_lines.append(lines[index])
                    index += 1
                if index == len(lines):
                    raise ValueError(f"unterminated Markdown code fence in {source}")
                self.code(code_lines, indent=indent)
                index += 1
                continue
            if line.startswith(">"):
                quote = []
                while index < len(lines) and lines[index].startswith(">"):
                    quote.append(lines[index][1:].lstrip())
                    index += 1
                self.paragraph(" ".join(quote), indent=indent + 12, font="F3")
                continue
            image_match = IMAGE_RE.match(line)
            if image_match:
                self.figure(source, image_match.group("path"), image_match.group("caption"))
                index += 1
                continue
            heading_match = HEADING_RE.match(line)
            if heading_match:
                following_index = index + 1
                while following_index < len(lines) and not lines[following_index].strip():
                    following_index += 1
                following = []
                for candidate in lines[following_index:]:
                    if not candidate.strip() or candidate.startswith(("```", "|", ">", "#")) \
                            or LIST_RE.match(candidate) or IMAGE_RE.match(candidate):
                        break
                    following.append(candidate.strip())
                code_index = following_index + len(following)
                while code_index < len(lines) and not lines[code_index].strip():
                    code_index += 1
                following_code = None
                if code_index < len(lines) and lines[code_index].startswith("```"):
                    following_code = []
                    for candidate in lines[code_index + 1:]:
                        if candidate.startswith("```"):
                            break
                        following_code.append(candidate)
                self.heading(len(heading_match.group("marks")), heading_match.group("title"),
                             following=" ".join(following), following_code=following_code)
                index += 1
                continue
            if TABLE_RULE_RE.match(line):
                index += 1
                continue
            if line.lstrip().startswith("|"):
                self.table_row(line, indent=indent)
                index += 1
                continue
            paragraph = [line.strip()]
            index += 1
            while index < len(lines):
                candidate = lines[index]
                if (
                    not candidate.strip()
                    or candidate.startswith(("```", ">"))
                    or IMAGE_RE.match(candidate)
                    or HEADING_RE.match(candidate)
                    or candidate.lstrip().startswith("|")
                    or LIST_RE.match(candidate)
                ):
                    break
                paragraph.append(candidate.strip())
                index += 1
            self.paragraph(" ".join(paragraph), indent=indent, marker=marker,
                           after=3 if marker is not None else 6)
            marker = None


def _title_page() -> Page:
    page = Page(*A4, 1)
    page.text(58, 650, "ICODA", font="F2", size=38)
    page.text(58, 605, "Illustrated Handbook", font="F2", size=27)
    page.line(58, 583, A4[0] - 58, 583)
    page.text(58, 548, "C++ reference, complete tutorial, and troubleshooting", size=13)
    page.text(58, 510, "ICODA 0.1.0", font="F2", size=11)
    page.text(58, 190, "Built offline from the accepted Markdown documentation", size=10)
    page.text(58, 170, "HANDBOOK.md / GETTING_STARTED.md / TUTORIAL.md / TROUBLESHOOTING.md", size=8)
    return page


def _toc_page(entries: list[tuple[int, str, int]]) -> Page:
    page = Page(*A4, 2)
    page.text(52, 782, "Contents", font="F2", size=22)
    page.line(52, 767, A4[0] - 52, 767)
    y = 744.0
    for level, title, number in entries:
        indent = 0 if level == 1 else 13
        font = "F2" if level == 1 else "F1"
        size = 8.6 if level == 1 else 8.0
        available = 76 if level == 1 else 73
        wrapped = textwrap.wrap(title, width=available, break_long_words=False) or [title]
        if y - len(wrapped) * 10 < 45:
            raise ValueError("table of contents no longer fits on its reserved page")
        for line_index, line in enumerate(wrapped):
            page.text(52 + indent, y, line, font=font, size=size)
            if line_index == 0:
                page.text(A4[0] - 68, y, str(number), font=font, size=size)
            y -= 10
        if level == 1:
            y -= 2
    page.text(A4[0] / 2 - 3, 21, "2", size=8)
    return page


def _stream(dictionary: str, data: bytes) -> bytes:
    return f"<< {dictionary} /Length {len(data)} >>\nstream\n".encode() + data + b"\nendstream"


def _build_pdf(pages: list[Page], images: list[PdfImage]) -> bytes:
    font_ids = {"F1": 4, "F2": 5, "F3": 6, "F4": 7}
    image_ids = {image.name: 8 + index for index, image in enumerate(images)}
    page_base = 8 + len(images)
    content_ids = [page_base + index * 2 for index in range(len(pages))]
    page_ids = [identifier + 1 for identifier in content_ids]
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Count {len(pages)} /Kids [{' '.join(f'{item} 0 R' for item in page_ids)}] >>".encode(),
        (
            f"<< /Title (ICODA Handbook) /Author (ICODA Project) "
            f"/Subject (Offline user and maintainer handbook with {len(images)} screenshots) >>".encode()
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Oblique /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>",
    ]
    for image in images:
        objects.append(
            _stream(
                f"/Type /XObject /Subtype /Image /Width {image.width} /Height {image.height} "
                "/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode",
                image.jpeg,
            )
        )
    font_resources = " ".join(f"/{name} {identifier} 0 R" for name, identifier in font_ids.items())
    for page, content_id in zip(pages, content_ids, strict=True):
        content = zlib.compress(b"".join(page.commands), level=9)
        objects.append(_stream("/Filter /FlateDecode", content))
        xobjects = ""
        if page.image_name is not None:
            xobjects = f" /XObject << /{page.image_name} {image_ids[page.image_name]} 0 R >>"
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page.width:.2f} {page.height:.2f}] "
                f"/Resources << /Font << {font_resources} >>{xobjects} >> /Contents {content_id} 0 R >>"
            ).encode()
        )
    output = io.BytesIO()
    output.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for identifier, obj in enumerate(objects, start=1):
        offsets.append(output.tell())
        output.write(f"{identifier} 0 obj\n".encode())
        output.write(obj)
        output.write(b"\nendobj\n")
    xref = output.tell()
    output.write(f"xref\n0 {len(objects) + 1}\n".encode())
    output.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.write(f"{offset:010d} 00000 n \n".encode())
    output.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info 3 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return output.getvalue()


def build() -> tuple[int, int]:
    renderer = MarkdownRenderer(first_page=3)
    for source in SOURCES:
        renderer.document(source)
    pages = [_title_page(), _toc_page(renderer.toc), *renderer.pages]
    image_count = len(renderer.images)
    if image_count == 0:
        raise ValueError("handbook must contain at least one screenshot")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(_build_pdf(pages, renderer.images))
    return len(pages), image_count


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    pages, images = build()
    print(f"Built {OUTPUT} ({pages} pages, {images} images, {OUTPUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
