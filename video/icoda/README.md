# ICODA introduction video

The 24-slide production uses `storyboard.md` and `narration.md` as its sources. Its voice-over was generated through the ElevenLabs MCP with the voice `Helmut Lecture 2`. `audio-v2/` is the current 24-file voice-over set; the pre-iteration-27 MP3s in `audio/` are retained as a fallback. `timing.json` is the generated manifest of ffprobe-measured audio durations, cumulative slide offsets, and matching image/audio paths.

The iteration-31 render used two ffconcat manifests in a system temporary directory and this exact command:

```sh
ffmpeg -hide_banner -y -f concat -safe 0 -i "$scratch/slides.ffconcat" -f concat -safe 0 -i "$scratch/audio.ffconcat" -filter_complex '[0:v:0]scale=1920:1080:flags=lanczos,fps=30,format=yuv420p[vout]' -map '[vout]' -map 1:a:0 -c:v libx264 -preset medium -crf 18 -r 30 -pix_fmt yuv420p -c:a aac -b:a 192k -movflags +faststart -shortest "$scratch/icoda-intro.mp4"
```

The successful temporary result was moved to `icoda-intro.mp4`. ffprobe measured 714.066848 seconds (11.901114 minutes), H.264 at 1920×1080 and 30/1 fps, AAC audio, and 26,293,695 bytes. The result is inside the required 10–12 minute window and differs from the measured 714.083266-second audio total by 0.016418 seconds.
