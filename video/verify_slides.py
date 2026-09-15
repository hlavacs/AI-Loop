#!/usr/bin/env python3
"""Mechanically verify AI-Loop or ICODA slide geometry and image placement."""

from __future__ import annotations

import argparse

from PIL import Image, ImageChops

import render_slides as render


def expected_source(placement: dict[str, object]) -> Image.Image:
    source = Image.open(render.SCREENSHOT_DIR / str(placement["filename"])).convert("RGB")
    source_crop = placement.get("source_crop")
    if source_crop is not None:
        source = source.crop(source_crop)
    return source


def verify_screenshot(slide: Image.Image, placement: dict[str, object]) -> str:
    source = expected_source(placement)
    target = placement["target"]
    rendered = render.contain_rect(source.size, target)
    if target == render.COMMON_TARGET and source.size == (1408, 812):
        assert rendered == (258, 190, 1662, 1000)
    assert rendered[0] >= target[0] and rendered[1] >= target[1]
    assert rendered[2] <= target[2] and rendered[3] <= target[3]
    assert (rendered[2] <= render.LOGO_BOX[0] or rendered[0] >= render.LOGO_BOX[2]
            or rendered[3] <= render.LOGO_BOX[1] or rendered[1] >= render.LOGO_BOX[3]), \
        "screenshot overlaps logo box"
    source_aspect = source.width / source.height
    rendered_aspect = (rendered[2] - rendered[0]) / (rendered[3] - rendered[1])
    assert abs(rendered_aspect / source_aspect - 1.0) <= 0.01

    expected = source.resize(
        (rendered[2] - rendered[0], rendered[3] - rendered[1]), Image.Resampling.LANCZOS
    )
    actual = slide.crop(rendered)
    difference = ImageChops.difference(actual, expected)
    differing = sum(1 for pixel in difference.getdata() if pixel != (0, 0, 0))
    difference_ratio = differing / (expected.width * expected.height)
    # Focus rectangles and leader lines intentionally modify a small part of the
    # screenshot.  Requiring at least 88% exact source pixels still detects a
    # missing or misplaced capture while allowing those storyboard overlays.
    assert difference_ratio < 0.12, f"source pixels differ by {difference_ratio:.2%}"
    return f"{placement['filename']}@{rendered} aspect-ok"


def _red_near(slide: Image.Image, point: tuple[int, int], radius: int = 4) -> bool:
    red = Image.new("RGB", (1, 1), render.RED).getpixel((0, 0))
    x, y = point
    region = slide.crop((max(0, x - radius), max(0, y - radius),
                         min(slide.width, x + radius + 1), min(slide.height, y + radius + 1)))
    return any(pixel == red for pixel in region.getdata())


def verify_focus_overlays(slide: Image.Image, spec: dict[str, object]) -> str:
    rectangles = spec.get("focus_rectangles", [])
    arrows = spec.get("focus_arrows", [])
    for x1, y1, x2, y2 in rectangles:
        for point in (((x1 + x2) // 2, y1), ((x1 + x2) // 2, y2),
                      (x1, (y1 + y2) // 2), (x2, (y1 + y2) // 2)):
            assert _red_near(slide, point), f"missing 6px red rectangle border near {point}"
    for start, end in arrows:
        assert _red_near(slide, start), f"missing 6px red arrow start near {start}"
        assert _red_near(slide, end), f"missing 6px red arrow end near {end}"
    parts = []
    if rectangles:
        parts.append(f"rectangles={rectangles}")
    if arrows:
        parts.append(f"arrows={arrows}")
    return (" focus[" + "; ".join(parts) + "] stroke=6") if parts else ""


def verify_logo(slide: Image.Image) -> None:
    assert render.LOGO_RENDERED_BOX == (1620, 38, 1820, 138)
    assert render.LOGO_BOX == (1600, 38, 1840, 138)
    assert render.LOGO_RENDERED_BOX[0] >= render.LOGO_BOX[0]
    assert render.LOGO_RENDERED_BOX[2] <= render.LOGO_BOX[2]
    source = Image.open(render.LOGO_PATH).convert("RGBA").resize((200, 100), Image.Resampling.LANCZOS)
    expected = Image.new("RGBA", (200, 100), render.WHITE)
    expected.alpha_composite(source)
    actual = slide.crop(render.LOGO_RENDERED_BOX).convert("RGBA")
    assert ImageChops.difference(actual, expected).getbbox() is None, "logo pixels differ"


def verify_background(slide: Image.Image) -> None:
    assert render.WHITE == "#FFFFFF"
    safe_points = ((0, 0), (1919, 0), (0, 1079), (1919, 1079), (10, 540), (1909, 540))
    assert all(slide.getpixel(point) == (255, 255, 255) for point in safe_points)
    white_pixels = sum(1 for pixel in slide.getdata() if pixel == (255, 255, 255))
    assert white_pixels > (slide.width * slide.height) // 2


def verify_visible_content(slide: Image.Image) -> None:
    title_region = slide.crop(render.TITLE_BOX)
    assert title_region.getbbox() is not None
    title_nonwhite = sum(1 for pixel in title_region.getdata() if pixel != (255, 255, 255))
    frame_nonwhite = sum(1 for pixel in slide.getdata() if pixel != (255, 255, 255))
    assert title_nonwhite > 100, "title region is blank"
    assert frame_nonwhite > 1000, "slide is blank"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deck", choices=sorted(render.DECKS), default="ai-loop")
    args = parser.parse_args(argv)
    render.configure_deck(args.deck)
    expected_names = [f"slide-{number:02d}.png" for number in range(1, 25)]
    actual_names = sorted(path.name for path in render.OUTPUT_DIR.glob("slide-*.png"))
    assert actual_names == expected_names, "slides directory must contain exactly slide-01.png through slide-24.png"
    assert [spec["number"] for spec in render.SLIDES] == list(range(1, 25))

    for spec in render.SLIDES:
        path = render.OUTPUT_DIR / f"slide-{spec['number']:02d}.png"
        with Image.open(path) as opened:
            slide = opened.convert("RGB")
        assert slide.size == render.FRAME_SIZE
        verify_background(slide)
        verify_visible_content(slide)
        verify_logo(slide)
        placements = [verify_screenshot(slide, item) for item in render.screenshot_placements(spec)]
        placement_output = "; ".join(placements) if placements else "no screenshots"
        focus_output = verify_focus_overlays(slide, spec)
        print(
            f"{path.name}: PASS canvas=1920x1080 background=white "
            f"logo=(1620,38)-(1820,138) 200x100; {placement_output}{focus_output}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
