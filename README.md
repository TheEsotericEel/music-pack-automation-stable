# Music Pack Automation

- Drop audio files into `inbox/` (subfolders OK).
- Ensure `assets/preview_bg/preview_bg.mp4` and `assets/names/name_list.txt` exist.
- Run: `python -m packmaker.cli`

Outputs per pack:
- `tracks_mp3/` (mirrors `inbox/`, random file names)
- `preview/preview.mp4` (continuous BG video with track index overlays)
- `mix/mix.mp3` (full crossfaded mix)

Requires: ffmpeg/ffprobe in PATH. AMD AMF used if present, fallback to libx264.
