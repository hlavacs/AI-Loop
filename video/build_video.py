#!/usr/bin/env python3
"""Build the narrated AI-Loop or ICODA introduction video with ffmpeg."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any


VIDEO_DIR = Path(__file__).resolve().parent
PROJECT_DIR = VIDEO_DIR / "ai-loop"
SLIDE_DIR = PROJECT_DIR / "slides"
AUDIO_DIR = PROJECT_DIR / "audio"
OUTPUT_PATH = PROJECT_DIR / "ai-loop-intro.mp4"
TIMING_PATH = PROJECT_DIR / "timing.json"

SLIDE_COUNT = 24
PAD_SECONDS = 0.5
FRAME_SIZE = (1920, 1080)
FPS = 30

DECKS: dict[str, tuple[Path, Path, Path, Path, Path]] = {
    "ai-loop": (
        VIDEO_DIR / "ai-loop",
        VIDEO_DIR / "ai-loop" / "slides",
        VIDEO_DIR / "ai-loop" / "audio",
        VIDEO_DIR / "ai-loop" / "ai-loop-intro.mp4",
        VIDEO_DIR / "ai-loop" / "timing.json",
    ),
    "icoda": (
        VIDEO_DIR / "icoda",
        VIDEO_DIR / "icoda" / "slides",
        VIDEO_DIR / "icoda" / "audio",
        VIDEO_DIR / "icoda" / "icoda-intro.mp4",
        VIDEO_DIR / "icoda" / "timing.json",
    ),
}


def configure_deck(deck: str) -> None:
    global PROJECT_DIR, SLIDE_DIR, AUDIO_DIR, OUTPUT_PATH, TIMING_PATH
    PROJECT_DIR, SLIDE_DIR, AUDIO_DIR, OUTPUT_PATH, TIMING_PATH = DECKS[deck]


def media_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def input_paths() -> list[tuple[Path, Path]]:
    paths = [
        (
            SLIDE_DIR / f"slide-{number:02d}.png",
            AUDIO_DIR / f"slide-{number:02d}.mp3",
        )
        for number in range(1, SLIDE_COUNT + 1)
    ]
    missing = [str(path) for pair in paths for path in pair if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing video input: {', '.join(missing)}")
    return paths


def timing_data(paths: list[tuple[Path, Path]]) -> dict[str, Any]:
    slides: list[dict[str, Any]] = []
    start = 0.0
    for number, (_, audio_path) in enumerate(paths, start=1):
        audio_duration = media_duration(audio_path)
        slide_duration = audio_duration + PAD_SECONDS
        slides.append(
            {
                "slide": number,
                "start_seconds": start,
                "audio_duration_seconds": audio_duration,
                "pad_seconds": PAD_SECONDS,
                "slide_duration_seconds": slide_duration,
            }
        )
        start += slide_duration
    return {
        "fps": FPS,
        "frame_size": list(FRAME_SIZE),
        "pad_seconds": PAD_SECONDS,
        "total_seconds": start,
        "slides": slides,
    }


def concat_manifest(paths: list[tuple[Path, Path]], durations: list[float]) -> str:
    lines = ["ffconcat version 1.0"]
    for (slide_path, _), duration in zip(paths, durations):
        lines.extend((f"file '{slide_path.resolve()}'", f"duration {duration:.9f}"))
    lines.append(f"file '{paths[-1][0].resolve()}'")
    return "\n".join(lines) + "\n"


def build_command(manifest_path: Path, paths: list[tuple[Path, Path]], timing: dict[str, Any]) -> list[str]:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(manifest_path),
    ]
    for _, audio_path in paths:
        command.extend(("-i", str(audio_path)))

    filters = [
        f"[0:v:0]scale={FRAME_SIZE[0]}:{FRAME_SIZE[1]}:flags=lanczos,"
        f"fps={FPS},format=yuv420p[vout]"
    ]
    audio_labels: list[str] = []
    for input_index, slide in enumerate(timing["slides"], start=1):
        label = f"a{input_index:02d}"
        audio_labels.append(f"[{label}]")
        filters.append(
            f"[{input_index}:a:0]aresample=48000,"
            "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=mono,"
            "asetpts=PTS-STARTPTS,"
            f"apad=whole_dur={slide['slide_duration_seconds']:.9f},"
            f"atrim=duration={slide['slide_duration_seconds']:.9f}[{label}]"
        )
    filters.append(f"{''.join(audio_labels)}concat=n={SLIDE_COUNT}:v=0:a=1[aout]")

    command.extend(
        (
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-r",
            str(FPS),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            "-shortest",
            str(OUTPUT_PATH),
        )
    )
    return command


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deck", choices=sorted(DECKS), default="ai-loop")
    args = parser.parse_args(argv)
    configure_deck(args.deck)
    paths = input_paths()
    timing = timing_data(paths)
    durations = [slide["slide_duration_seconds"] for slide in timing["slides"]]

    with tempfile.TemporaryDirectory(prefix=f"{args.deck}-build-", dir=PROJECT_DIR) as temp_dir:
        manifest_path = Path(temp_dir) / "slides.ffconcat"
        manifest_path.write_text(concat_manifest(paths, durations), encoding="utf-8")
        subprocess.run(build_command(manifest_path, paths, timing), check=True)

    TIMING_PATH.write_text(json.dumps(timing, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH.relative_to(VIDEO_DIR)} ({media_duration(OUTPUT_PATH):.3f} seconds)")
    print(f"Wrote {TIMING_PATH.relative_to(VIDEO_DIR)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
