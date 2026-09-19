"""Build the illustrated ICODA handbook as a searchable, offline PDF."""

from __future__ import annotations

import argparse
import io
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
BUILD_INVOCATION = ".icoda-venv/bin/python tools/build_handbook_pdf.py"

A4 = (595.28, 841.89)
A4_LANDSCAPE = (A4[1], A4[0])
IMAGE_RE = re.compile(r"^!\[(?P<caption>.+)]\((?P<path>[^)]+)\)$")
HEADING_RE = re.compile(r"^(?P<marks>#{1,3})\s+(?P<title>.+)$")
TABLE_RULE_RE = re.compile(r"^\|?(?:\s*:?-+:?\s*\|)+\s*$")


def _plain_markdown(value: str) -> str:
    value = re.sub(r"\[([^]]+)]\([^)]+\)", r"\1", value)
    value = re.sub(r"!\[([^]]+)]\([^)]+\)", r"\1", value)
    value = value.replace("**", "").replace("__", "").replace("`", "")
    value = re.sub(r"(?<!\w)[*_](.+?)[*_](?!\w)", r"\1", value)
    return value.strip()


def _pdf_text(value: str) -> bytes:
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
    encoded = value.encode("cp1252", errors="replace")
    return encoded.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


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
        average_width = size * (0.60 if font == "F4" else 0.50)
        columns = max(18, int(available / average_width))
        return textwrap.wrap(
            text,
            width=columns,
            break_long_words=True,
            break_on_hyphens=False,
            replace_whitespace=False,
        ) or [""]

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
    ) -> None:
        text = _plain_markdown(text)
        lines = self._wrapped(text, size=size, indent=indent, font=font)
        page = self._ensure_space(before + leading * len(lines) + after)
        self._y -= before
        for line in lines:
            page.text(52 + indent, self._y, line, font=font, size=size)
            self._y -= leading
        self._y -= after

    def heading(self, level: int, title: str) -> None:
        title = _plain_markdown(title)
        styles = {
            1: ("F2", 20.0, 25.0, 10.0, 11.0),
            2: ("F2", 14.5, 18.0, 9.0, 7.0),
            3: ("F2", 11.2, 14.0, 7.0, 4.0),
        }
        font, size, leading, before, after = styles[level]
        lines = self._wrapped(title, size=size, font=font)
        page = self._ensure_space(before + leading * len(lines) + after + 12)
        if level <= 2:
            self.toc.append((level, title, page.number))
        self._y -= before
        for line in lines:
            page.text(52, self._y, line, font=font, size=size)
            self._y -= leading
        self._y -= after

    def code(self, lines: list[str]) -> None:
        page = self._ensure_space(15)
        page.line(52, self._y + 5, A4[0] - 52, self._y + 5)
        self._y -= 5
        for raw_line in lines or [""]:
            wrapped = self._wrapped(raw_line.expandtabs(4), size=7.4, indent=8, font="F4")
            for line in wrapped:
                page = self._ensure_space(10)
                page.text(60, self._y, line, font="F4", size=7.4)
                self._y -= 9.6
        page = self._ensure_space(9)
        page.line(52, self._y + 3, A4[0] - 52, self._y + 3)
        self._y -= 7

    def table_row(self, line: str) -> None:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        self.paragraph(" | ".join(cells), font="F4", size=7.2, leading=9.2, after=2)

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
        page.place_image(image.name, (page.width - width) / 2, 62, width, height)
        clean_caption = _plain_markdown(caption)
        caption_width = min(len(clean_caption) * 4.4, page.width - 80)
        page.text((page.width - caption_width) / 2, 45, clean_caption, font="F3", size=8.2)
        self.pages.append(page)
        self.page_break()

    def document(self, source: Path) -> None:
        if self.pages:
            self.page_break()
        lines = source.read_text(encoding="utf-8").splitlines()
        index = 0
        while index < len(lines):
            line = lines[index]
            if not line.strip():
                index += 1
                continue
            if line.startswith("```"):
                index += 1
                code_lines: list[str] = []
                while index < len(lines) and not lines[index].startswith("```"):
                    code_lines.append(lines[index])
                    index += 1
                if index == len(lines):
                    raise ValueError(f"unterminated Markdown code fence in {source}")
                self.code(code_lines)
                index += 1
                continue
            image_match = IMAGE_RE.match(line)
            if image_match:
                self.figure(source, image_match.group("path"), image_match.group("caption"))
                index += 1
                continue
            heading_match = HEADING_RE.match(line)
            if heading_match:
                self.heading(len(heading_match.group("marks")), heading_match.group("title"))
                index += 1
                continue
            if TABLE_RULE_RE.match(line):
                index += 1
                continue
            if line.lstrip().startswith("|"):
                self.table_row(line)
                index += 1
                continue
            if re.match(r"^\s*(?:[-*+] |\d+\. )", line):
                marker, body = line.lstrip().split(" ", 1)
                self.paragraph(f"{marker} {body}", indent=12, after=3)
                index += 1
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
                    or candidate.lstrip().startswith("|")
                    or re.match(r"^\s*(?:[-*+] |\d+\. )", candidate)
                ):
                    break
                paragraph.append(candidate.strip())
                index += 1
            self.paragraph(" ".join(paragraph))


def _title_page() -> Page:
    page = Page(*A4, 1)
    page.text(58, 650, "ICODA", font="F2", size=38)
    page.text(58, 605, "Illustrated Handbook", font="F2", size=27)
    page.line(58, 583, A4[0] - 58, 583)
    page.text(58, 548, "Production guide, tutorials, and troubleshooting", size=13)
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
