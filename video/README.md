# Video production workspace

This directory holds the production assets for the AI-Loop and ICODA introduction videos.

## Current ICODA pipeline

The release video uses `icoda/storyboard.md` and `icoda/narration.md` as its sources. The voice-over was generated through the ElevenLabs MCP with the voice `Helmut Lecture 2`. `icoda/audio-v2/` is the current 24-file voice-over set; the pre-iteration-27 MP3s remain in `icoda/audio/` as a fallback. `icoda/timing.json` is the generated timing manifest measured from `audio-v2/`.

The iteration-31 render used two ffconcat manifests in a system temporary directory and this exact command:

```sh
ffmpeg -hide_banner -y -f concat -safe 0 -i "$scratch/slides.ffconcat" -f concat -safe 0 -i "$scratch/audio.ffconcat" -filter_complex '[0:v:0]scale=1920:1080:flags=lanczos,fps=30,format=yuv420p[vout]' -map '[vout]' -map 1:a:0 -c:v libx264 -preset medium -crf 18 -r 30 -pix_fmt yuv420p -c:a aac -b:a 192k -movflags +faststart -shortest "$scratch/icoda-intro.mp4"
```

The successful temporary result was moved to `icoda/icoda-intro.mp4`. ffprobe measured 714.066848 seconds (11.901114 minutes), H.264 at 1920×1080 and 30/1 fps, AAC audio, and 26,293,695 bytes. It is inside the required 10–12 minute window.

The shared University of Vienna logo is `assets/university-of-vienna-logo.png`.
