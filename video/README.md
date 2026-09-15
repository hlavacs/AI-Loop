# Video production workspace

This directory is the clean production workspace for the AI-Loop and ICODA introduction videos. The current task inventories both applications and completes the AI-Loop storyboard and narration only. It intentionally contains no generated speech, rendered slide, or MP4 file.

## Production contract

- Master frame: 1920×1080, white background.
- Every slide contains the complete University of Vienna logo in the upper-right logo box `[1600,38]–[1840,138]`. The 2:1 asset is contained without cropping at 200×100 pixels, centered in that box.
- Styling is restrained: dark text, University blue as the principal accent, and red only for screenshot focus rectangles/arrows.
- Screenshots are always scaled proportionally and contained inside their declared target box. They are never stretched or cropped unless a storyboard entry explicitly names a preplanned source crop.
- Narration voice: ElevenLabs `Helmut Lecture 2`, voice ID `T22wMY2gj3hkNGpCJOwd`. It was confirmed through the configured ElevenLabs MCP OAuth connector with `creative_list_voices` on 2026-09-15. No audio has been generated.
- All future generated artifacts must remain below `video/`.

Machine-readable production settings are in `config.json`. Project findings are in `inventory.md`; reproducible GUI states are in `screenshot-plan.md`.

## Verified toolchain

Checks were run from the worktree root on 2026-09-15.

| Check | Observed output | Exit status |
| --- | --- | ---: |
| `ffmpeg -version` | `ffmpeg version 6.1.1-3ubuntu5` | 0 |
| `ffprobe -version` | `ffprobe version 6.1.1-3ubuntu5` | 0 |
| `python3 -c 'from PIL import Image, ImageDraw, ImageFont; print("Pillow", Image.__version__)'` | `Pillow 10.2.0` | 0 |

The selected slide-rendering approach is Python/Pillow. It is already used by the repository's earlier video tooling, requires no browser, gives deterministic 1920×1080 pixel geometry, and supports explicit contain-without-crop assertions for screenshots. FFmpeg will later combine the rendered stills with narration; ffprobe will validate the final media. Neither rendering nor media assembly is part of this task.

## University logo asset

- File: `assets/university-of-vienna-logo.png`
- Official downloads page: <https://www.univie.ac.at/en/about-us/organisation-and-structure/corporate-communications/downloads>
- Direct official file URL: <https://www.univie.ac.at/fileadmin/user_upload/univie/Logos/Logos_Universitaet_Wien/Uni_Logo.png>
- Format/mode: PNG, RGBA with alpha transparency
- Dimensions: 2000×1000 pixels
- File size: 102,332 bytes
- SHA-256: `09373739cb54146839230ce9efb25a9d7b9f6873c32cdce02e4741dbe3f915aa`

The downloads page states that use requires University consent and limits the logo to permitted University work-related use. Production must retain the original colors, proportions, and clear space.

## Workspace map

- `assets/`: shared official visual assets.
- `ai-loop/storyboard.md`: complete ordered visual specification for the AI-Loop video.
- `ai-loop/narration.md`: final AI-Loop spoken script, keyed to the storyboard.
- `icoda/README.md`: scope marker for the later ICODA production task.
- `screenshot-plan.md`: exact capture states and commands for both applications.

