#!/usr/bin/env python3
"""Assemble and validate the deterministic AI-Loop introduction video.

Run from ``ai-loop``::

    python3 docs/video/build_video.py

The assembler reads the measured narration timings and the numbered slide and
audio files from the repository. It does not access a network, generate speech,
or render source stills.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

VIDEO_DIR = Path(__file__).resolve().parent
AUDIO_DIR = VIDEO_DIR / "audio"
ASSET_DIR = VIDEO_DIR / "assets"
DURATIONS = AUDIO_DIR / "durations.json"
OUTPUT = VIDEO_DIR / "ai-loop-introduction.mp4"

SEGMENT_COUNT = 22
WIDTH = 1920
HEIGHT = 1080
FRAME_RATE = "30/1"


def require_file(path: Path) -> None:
    """Fail with a useful error when a required input is unavailable."""
    if not path.is_file():
        raise RuntimeError(f"required input is missing: {path}")


def read_durations() -> tuple[dict[int, float], float]:
    """Read and strictly validate the measured per-segment durations."""
    require_file(DURATIONS)
    with DURATIONS.open(encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise TypeError(f"expected a JSON object in {DURATIONS}")

    expected_keys = {
        f"s{number:02d}.mp3" for number in range(1, SEGMENT_COUNT + 1)
    } | {"total"}
    if set(raw) != expected_keys:
        raise RuntimeError(
            f"unexpected duration keys in {DURATIONS}: "
            f"expected {sorted(expected_keys)}, got {sorted(raw)}"
        )

    durations: dict[int, float] = {}
    for number in range(1, SEGMENT_COUNT + 1):
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
            f"segment durations sum to {sum(durations.values()):.6f}, "
            f"but {DURATIONS} records {total:.6f}"
        )
    return durations, total


def find_inputs() -> tuple[dict[int, Path], dict[int, Path]]:
    """Pair each numeric segment ID with exactly one slide and one MP3."""
    slides: dict[int, Path] = {}
    audio: dict[int, Path] = {}
    for number in range(1, SEGMENT_COUNT + 1):
        segment = f"s{number:02d}"
        matches = sorted(ASSET_DIR.glob(f"{segment}_*.png"))
        if len(matches) != 1:
            names = [path.name for path in matches]
            raise RuntimeError(
                f"expected exactly one slide matching {segment}_*.png in "
                f"{ASSET_DIR}, found {len(matches)}: {names}"
            )
        slides[number] = matches[0]

        audio_path = AUDIO_DIR / f"{segment}.mp3"
        require_file(audio_path)
        audio[number] = audio_path
    return slides, audio


def ffconcat_path(path: Path) -> str:
    """Quote an absolute path for FFmpeg's concat-demuxer syntax."""
    return "'" + path.resolve().as_posix().replace("'", "'\\''") + "'"


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
        or video_stream.get("r_frame_rate") != FRAME_RATE
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


def main() -> None:
    """Build the 22-segment video and validate the finished export."""
    durations, total = read_durations()
    slides, audio = find_inputs()

    with tempfile.TemporaryDirectory(prefix="ai-loop-video-") as temporary:
        temporary_dir = Path(temporary)
        candidate = temporary_dir / OUTPUT.name
        parts: list[Path] = []
        for number in range(1, SEGMENT_COUNT + 1):
            part = temporary_dir / f"part_{number:02d}.mp4"
            run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "warning",
                    "-y",
                    "-loop",
                    "1",
                    "-i",
                    str(slides[number]),
                    "-i",
                    str(audio[number]),
                    "-t",
                    f"{durations[number]:.9f}",
                    "-threads",
                    "1",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-tune",
                    "stillimage",
                    "-crf",
                    "20",
                    "-pix_fmt",
                    "yuv420p",
                    "-r",
                    FRAME_RATE,
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-shortest",
                    str(part),
                ]
            )
            parts.append(part)

        parts_manifest = temporary_dir / "parts.ffconcat"
        parts_manifest.write_text(
            "\n".join(
                ["ffconcat version 1.0"]
                + [f"file {ffconcat_path(part)}" for part in parts]
            )
            + "\n",
            encoding="utf-8",
        )
        run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "warning",
                "-y",
                "-threads",
                "1",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(parts_manifest),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(candidate),
            ]
        )
        description = probe(candidate)
        measured_duration = validate_export(description, total)
        candidate.replace(OUTPUT)

    elapsed = 0.0
    print("Timeline (half-open intervals, seconds):")
    for number in range(1, SEGMENT_COUNT + 1):
        end = elapsed + durations[number]
        print(
            f"  s{number:02d}: {elapsed:.6f} -> {end:.6f} "
            f"({slides[number].name})"
        )
        elapsed = end
    print(f"Exported: {OUTPUT}")
    print(f"Measured container duration: {measured_duration:.6f} seconds")
    print(json.dumps(description, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
