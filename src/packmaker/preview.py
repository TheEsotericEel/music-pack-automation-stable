# src/packmaker/preview.py
from pathlib import Path
import subprocess
from .utils import ffprobe_video_duration, windows_fontfile, ffmpeg_escape_fontfile
from .audio import crossfade_sequence, find_energy_peak_start


def _run(cmd_argv):
    """Run a subprocess with argv list (no shell)."""
    subprocess.run(cmd_argv, check=True)


def build_smart_snips(sources, out_dir: Path, sec: int):
    """
    Extract short audio snips for preview from each source at an energy-based start.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    snips, starts = [], []
    for i, s in enumerate(sources, 1):
        start = find_energy_peak_start(s, float(sec))
        snip = out_dir / f"snip_{i:02d}.m4a"
        _run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{start:.3f}", "-i", str(s), "-t", str(sec),
            "-vn", "-sn", "-dn",
            "-c:a", "aac", "-b:a", "192k",
            "-threads", "4", str(snip)
        ])
        snips.append(snip)
        starts.append(start)
    return snips, starts


def _make_filter_chain(*, video_res: str, N: int, slot: float, preview_sec: float, xfade_preview: float) -> str:
    """
    Filter chain: ONLY centered, time-sliced numbers (01..N).
    """
    font_path_raw = windows_fontfile()               # e.g., C:\Windows\Fonts\arial.ttf
    fontfile = ffmpeg_escape_fontfile(font_path_raw)

    first = f"[0:v]scale={video_res},setsar=1[v0]"
    parts = [first]
    prev = "v0"

    for idx in range(N):
        start = round(idx * slot, 6)
        end   = round(start + preview_sec - xfade_preview - 0.02, 6)
        label = f"{idx+1:02d}"
        nxt   = f"v{idx+1}"
        parts.append(
            f"[{prev}]drawtext=fontfile='{fontfile}':text='{label}':"
            f"fontcolor=white:borderw=6:bordercolor=black:fontsize=200:"
            f"x=(w-tw)/2:y=(h-th)/2:enable=between(t\\,{start}\\,{end})[{nxt}]"
        )
        prev = nxt

    parts.append(f"[{prev}]format=yuv420p[out]")
    return ";".join(parts)


def _run_ffmpeg_video(
    *,
    bg_argv_prefix: list,
    filter_chain: str,
    total_d_video: float,
    fps: int,
    video_full: Path,
    crf: int,
    preset: str,
    loglevel: str = "warning",
):
    """
    Render preview video with libx264 + CRF/preset controls.
    """
    argv = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", loglevel,
        *bg_argv_prefix,
        "-filter_complex", filter_chain, "-map", "[out]",
        "-t", f"{total_d_video}", "-r", f"{fps}",
        "-filter_threads", "1", "-filter_complex_threads", "1",
        "-c:v", "libx264", "-preset", str(preset), "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-threads", "2", "-max_muxing_queue_size", "1024",
        str(video_full)
    ]
    _run(argv)


def render_preview_video(
    bg_path: Path,
    tmp_dir: Path,
    video_res: str,
    fps: int,
    total_d_video: float,
    N: int,
    slot: float,
    preview_sec: float,
    xfade_preview: float,
    amf_available: bool,   # ignored; kept for signature compatibility
    *,
    preview_crf: int = 20,
    preview_preset: str = "veryfast",
    **_kwargs,
) -> Path:
    """
    Build preview video with quality controls (CRF + preset).
    """
    tmp_dir.mkdir(parents=True, exist_ok=True)
    video_full = tmp_dir / "preview_video_full.mp4"

    filter_chain = _make_filter_chain(
        video_res=video_res, N=N, slot=slot, preview_sec=preview_sec, xfade_preview=xfade_preview
    )

    # Try 1) stream_loop, 2) concat, 3) solid color
    if bg_path.exists():
        try:
            _run_ffmpeg_video(
                bg_argv_prefix=["-stream_loop", "-1", "-i", str(bg_path)],
                filter_chain=filter_chain,
                total_d_video=total_d_video,
                fps=fps,
                video_full=video_full,
                crf=preview_crf,
                preset=preview_preset,
            )
            return video_full
        except subprocess.CalledProcessError:
            pass

        try:
            bg_len = max(0.001, ffprobe_video_duration(bg_path))
            reps = int((total_d_video // bg_len) + 2)
            concat_list = tmp_dir / "bg_concat.txt"
            with concat_list.open("w", encoding="utf-8") as f:
                p = str(bg_path).replace("\\", "/")
                for _ in range(reps):
                    f.write(f"file '{p}'\n")
            _run_ffmpeg_video(
                bg_argv_prefix=["-f", "concat", "-safe", "0", "-i", str(concat_list)],
                filter_chain=filter_chain,
                total_d_video=total_d_video,
                fps=fps,
                video_full=video_full,
                crf=preview_crf,
                preset=preview_preset,
            )
            return video_full
        except subprocess.CalledProcessError:
            pass

    _run_ffmpeg_video(
        bg_argv_prefix=["-f", "lavfi", "-i", f"color=c=black:s={video_res}:r={fps}:d={total_d_video}"],
        filter_chain=filter_chain,
        total_d_video=total_d_video,
        fps=fps,
        video_full=video_full,
        crf=preview_crf,
        preset=preview_preset,
    )
    return video_full


def mux_preview(
    video_full: Path,
    preview_audio: Path,
    out_path: Path,
    total_d_video: float,
    *,
    max_size_mb: int | None = 100,
    override_video_kbps: int | None = None,
    audio_kbps: int = 192,
):
    """
    Mux final preview with three modes:
      1) override_video_kbps -> fixed video bitrate
      2) max_size_mb (int)   -> compute target bitrate to fit size budget (clamped)
      3) max_size_mb is None -> no size constraint: stream-copy video
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Practical encoder caps
    MAX_FFMPEG_KBPS = 2_147_483        # ~2.147e9 bps (int32 cap in kbps)
    SOFT_CAP_KBPS   = 100_000          # 100 Mbps upper soft cap for sanity

    # --- Mode 1: explicit bitrate override ---
    if override_video_kbps and override_video_kbps > 0:
        vkbps = int(override_video_kbps)
        vkbps = max(200, min(vkbps, SOFT_CAP_KBPS, MAX_FFMPEG_KBPS))
        subprocess.run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(video_full), "-i", str(preview_audio),
            "-map", "0:v", "-map", "1:a",
            "-c:v", "libx264", "-b:v", f"{vkbps}k",
            "-maxrate", f"{vkbps}k", "-bufsize", f"{vkbps*2}k",
            "-c:a", "aac", "-b:a", f"{audio_kbps}k",
            "-movflags", "+faststart", "-shortest",
            str(out_path)
        ], check=True)
        return

    # --- Mode 3: no size constraint -> stream-copy video, encode audio only ---
    if max_size_mb is None:
        subprocess.run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(video_full), "-i", str(preview_audio),
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", f"{audio_kbps}k",
            "-movflags", "+faststart", "-shortest",
            str(out_path)
        ], check=True)
        return

    # --- Mode 2: size-targeted bitrate (float math + clamps) ---
    max_bytes_total = int(max_size_mb) * 1024 * 1024
    audio_bits = int(audio_kbps * 1000 * max(total_d_video, 0.001))
    container_overhead_bits = int(max_bytes_total * 8 * 0.02)  # ~2%
    available_video_bits = max(1, max_bytes_total * 8 - audio_bits - container_overhead_bits)

    # Use float seconds to avoid integer truncation
    seconds = max(0.001, float(total_d_video))
    vkbps = int(available_video_bits / seconds / 1000.0)  # bits -> kbps

    # Clamp to sane/FFmpeg ranges
    vkbps = max(200, min(vkbps, SOFT_CAP_KBPS, MAX_FFMPEG_KBPS))

    subprocess.run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video_full), "-i", str(preview_audio),
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-b:v", f"{vkbps}k",
        "-maxrate", f"{vkbps}k", "-bufsize", f"{vkbps*2}k",
        "-c:a", "aac", "-b:a", f"{audio_kbps}k",
        "-movflags", "+faststart", "-shortest",
        str(out_path)
    ], check=True)
