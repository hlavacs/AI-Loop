#!/usr/bin/env python3
"""Assemble and validate the deterministic AI-Loop introduction video.

Run from ``ai-loop``::

    python3 docs/video/build_video.py

The assembler reads the measured narration timings and shot mapping from the
repository.  It does not access a network, capture a desktop, generate speech,
or render source stills.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

VIDEO_DIR = Path(__file__).resolve().parent
AUDIO_DIR = VIDEO_DIR / "audio"
ASSET_DIR = VIDEO_DIR / "assets"
SHOTLIST = VIDEO_DIR / "SHOTLIST.md"
DURATIONS = AUDIO_DIR / "durations.json"
OUTPUT = VIDEO_DIR / "ai-loop-introduction.mp4"

SECTION_COUNT = 9
WIDTH = 1920
HEIGHT = 1080
FRAME_RATE = Fraction(30, 1)
FRAME_RATE_RATIO = f"{FRAME_RATE.numerator}/{FRAME_RATE.denominator}"

SECTION_HEADING = re.compile(r"^## ([1-9])\. ")
ASSET_REFERENCE = re.compile(r"^- `assets/([^`]+\.png)`")


@dataclass(frozen=True)
class Section:
    """One measured narration section and its ordered still-image sequence."""

    number: int
    duration: float
    assets: tuple[Path, ...]


@dataclass(frozen=True)
class TimelineEntry:
    """One still's half-open interval on the assembled video timeline."""

    section: int
    asset: Path
    start: float
    end: float


def require_file(path: Path) -> None:
    """Fail with a useful error when an authoritative input is unavailable."""
    if not path.is_file():
        raise RuntimeError(f"required input is missing: {path}")


def read_durations() -> tuple[dict[int, float], float]:
    """Read and strictly validate the authoritative section durations."""
    require_file(DURATIONS)
    with DURATIONS.open(encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise TypeError(f"expected a JSON object in {DURATIONS}")

    expected_keys = {f"s{number:02d}.mp3" for number in range(1, SECTION_COUNT + 1)} | {
        "total"
    }
    if set(raw) != expected_keys:
        raise RuntimeError(
            f"unexpected duration keys in {DURATIONS}: "
            f"expected {sorted(expected_keys)}, got {sorted(raw)}"
        )

    durations: dict[int, float] = {}
    for number in range(1, SECTION_COUNT + 1):
        key = f"s{number:02d}.mp3"
        value = raw[key]
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            raise RuntimeError(f"invalid duration for {key}: {value!r}")
        durations[number] = float(value)

    total_value = raw["total"]
    if (
        not isinstance(total_value, (int, float))
        or isinstance(total_value, bool)
        or total_value <= 0
    ):
        raise RuntimeError(f"invalid total duration: {total_value!r}")
    total = float(total_value)
    if abs(sum(durations.values()) - total) > 0.000_001:
        raise RuntimeError(
            f"section durations sum to {sum(durations.values()):.6f}, "
            f"but {DURATIONS} records {total:.6f}"
        )
    return durations, total


def read_shot_mapping() -> dict[int, tuple[Path, ...]]:
    """Parse the ordered per-section PNG mapping from the authoritative shot list."""
    require_file(SHOTLIST)
    mapping: dict[int, list[Path]] = {}
    current_section: int | None = None
    for line in SHOTLIST.read_text(encoding="utf-8").splitlines():
        heading = SECTION_HEADING.match(line)
        if heading:
            current_section = int(heading.group(1))
            if current_section in mapping:
                raise RuntimeError(f"duplicate section {current_section} in {SHOTLIST}")
            mapping[current_section] = []
            continue
        if line.startswith("## "):
            current_section = None
            continue
        asset = ASSET_REFERENCE.match(line)
        if asset and current_section is not None:
            relative = Path(asset.group(1))
            if relative.name != str(relative) or relative.suffix.lower() != ".png":
                raise RuntimeError(
                    f"invalid asset reference in {SHOTLIST}: {asset.group(1)!r}"
                )
            mapping[current_section].append(ASSET_DIR / relative)

    expected_sections = set(range(1, SECTION_COUNT + 1))
    if set(mapping) != expected_sections:
        raise RuntimeError(
            f"shot-list sections must be 1 through {SECTION_COUNT}; got {sorted(mapping)}"
        )
    for number, assets in mapping.items():
        if not assets:
            raise RuntimeError(f"section {number} has no assets in {SHOTLIST}")
        for asset in assets:
            require_file(asset)

    mapped_assets = [asset.resolve() for assets in mapping.values() for asset in assets]
    if len(mapped_assets) != len(set(mapped_assets)):
        raise RuntimeError(f"an asset is mapped more than once in {SHOTLIST}")
    available_assets = {
        path.resolve() for path in ASSET_DIR.glob("*.png") if path.is_file()
    }
    if set(mapped_assets) != available_assets:
        missing = sorted(path.name for path in available_assets - set(mapped_assets))
        unknown = sorted(path.name for path in set(mapped_assets) - available_assets)
        raise RuntimeError(
            f"SHOTLIST/assets mismatch; unmapped assets={missing}, missing assets={unknown}"
        )
    return {number: tuple(assets) for number, assets in mapping.items()}


def build_timeline(sections: tuple[Section, ...]) -> tuple[TimelineEntry, ...]:
    """Split each section evenly among its assets without gaps or overlaps."""
    entries: list[TimelineEntry] = []
    section_start = 0.0
    for section in sections:
        asset_duration = section.duration / len(section.assets)
        section_end = section_start + section.duration
        for index, asset in enumerate(section.assets):
            asset_start = section_start + index * asset_duration
            asset_end = (
                section_end
                if index == len(section.assets) - 1
                else section_start + (index + 1) * asset_duration
            )
            entries.append(TimelineEntry(section.number, asset, asset_start, asset_end))
        section_start = section_end
    return tuple(entries)


def ffconcat_path(path: Path) -> str:
    """Quote an absolute path for FFmpeg's concat-demuxer syntax."""
    return "'" + path.resolve().as_posix().replace("'", "'\\''") + "'"


def write_audio_manifest(path: Path) -> None:
    """Write the narration inputs in strict numeric order."""
    lines = ["ffconcat version 1.0"]
    for number in range(1, SECTION_COUNT + 1):
        audio = AUDIO_DIR / f"s{number:02d}.mp3"
        require_file(audio)
        lines.append(f"file {ffconcat_path(audio)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_video_manifest(path: Path, timeline: tuple[TimelineEntry, ...]) -> None:
    """Write exact still durations, repeating the last file to retain its duration."""
    lines = ["ffconcat version 1.0"]
    for entry in timeline:
        lines.append(f"file {ffconcat_path(entry.asset)}")
        lines.append(f"duration {entry.end - entry.start:.9f}")
    lines.append(f"file {ffconcat_path(timeline[-1].asset)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(command: list[str]) -> None:
    """Run one toolchain command and surface its failure unchanged."""
    subprocess.run(command, check=True)


def probe(path: Path) -> dict[str, Any]:
    """Return ffprobe's machine-readable stream and container description."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=index,codec_type,codec_name,width,height,pix_fmt,r_frame_rate,avg_frame_rate",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def validate_export(description: dict[str, Any], expected_duration: float) -> float:
    """Fail unless the final container has the required YouTube-ready layout."""
    streams = description.get("streams", [])
    video = [stream for stream in streams if stream.get("codec_type") == "video"]
    audio = [stream for stream in streams if stream.get("codec_type") == "audio"]
    if len(video) != 1 or len(audio) != 1 or len(streams) != 2:
        raise RuntimeError(
            f"expected exactly one video and one audio stream; got {streams!r}"
        )
    video_stream = video[0]
    if (
        video_stream.get("codec_name") != "h264"
        or video_stream.get("width") != WIDTH
        or video_stream.get("height") != HEIGHT
        or video_stream.get("pix_fmt") != "yuv420p"
        or video_stream.get("r_frame_rate") != FRAME_RATE_RATIO
        or video_stream.get("avg_frame_rate") != FRAME_RATE_RATIO
    ):
        raise RuntimeError(f"unexpected video stream: {video_stream!r}")
    if audio[0].get("codec_name") != "aac":
        raise RuntimeError(f"unexpected audio stream: {audio[0]!r}")
    duration = float(description["format"]["duration"])
    if abs(duration - expected_duration) > 1.0:
        raise RuntimeError(
            f"export duration {duration:.6f} differs from narration total "
            f"{expected_duration:.6f} by more than one second"
        )
    return duration


def print_timeline(timeline: tuple[TimelineEntry, ...], total: float) -> None:
    """Print the exact mapping used so a build is straightforward to audit."""
    print("Timeline (half-open intervals, seconds):")
    current_section = 0
    for entry in timeline:
        if entry.section != current_section:
            current_section = entry.section
            print(f"  Section {entry.section}: starts {entry.start:.6f}")
        print(f"    {entry.asset.name}: {entry.start:.6f} -> {entry.end:.6f}")
    print(f"  End: {total:.6f}")


def main() -> None:
    """Build the narration, video timeline, final mux, and validate the result."""
    durations, total = read_durations()
    shot_mapping = read_shot_mapping()
    sections = tuple(
        Section(number, durations[number], shot_mapping[number])
        for number in range(1, SECTION_COUNT + 1)
    )
    timeline = build_timeline(sections)
    if abs(timeline[-1].end - total) > 0.000_001:
        raise RuntimeError(
            f"timeline ends at {timeline[-1].end:.6f}, expected {total:.6f}"
        )

    with tempfile.TemporaryDirectory(prefix="ai-loop-video-") as temporary:
        temporary_dir = Path(temporary)
        audio_manifest = temporary_dir / "audio.ffconcat"
        video_manifest = temporary_dir / "video.ffconcat"
        narration = temporary_dir / "narration.mp3"
        candidate = temporary_dir / OUTPUT.name
        write_audio_manifest(audio_manifest)
        write_video_manifest(video_manifest, timeline)

        run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "warning",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(audio_manifest),
                "-map",
                "0:a:0",
                "-c:a",
                "copy",
                str(narration),
            ]
        )
        run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "warning",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(video_manifest),
                "-i",
                str(narration),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-vf",
                f"fps={FRAME_RATE},format=yuv420p",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "18",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
                str(candidate),
            ]
        )
        description = probe(candidate)
        measured_duration = validate_export(description, total)
        candidate.replace(OUTPUT)

    print_timeline(timeline, total)
    print(f"Exported: {OUTPUT}")
    print(f"Measured container duration: {measured_duration:.6f} seconds")
    print(json.dumps(description, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
