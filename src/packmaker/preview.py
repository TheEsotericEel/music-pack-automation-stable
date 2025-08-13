import math, subprocess, shutil
from pathlib import Path
from .utils import sh, ffprobe_video_duration, windows_fontfile, ffmpeg_escape_fontfile
from .audio import crossfade_sequence, find_energy_peak_start

def build_smart_snips(sources, out_dir: Path, sec: int):
    out_dir.mkdir(parents=True, exist_ok=True)
    snips = []
    starts = []
    for i, s in enumerate(sources, 1):
        start = find_energy_peak_start(s, float(sec))
        snip = out_dir / f"snip_{i:02d}.m4a"
        sh(f'ffmpeg -y -hide_banner -loglevel error -ss {start:.3f} -i "{s}" -t {sec} -vn -sn -dn -c:a aac -b:a 192k -threads 4 "{snip}"')
        snips.append(snip)
        starts.append(start)
    return snips, starts

def render_preview_video(bg_path: Path, tmp_dir: Path, video_res: str, fps: int, total_d_video: float, N: int, slot: float, preview_sec: float, xfade_preview: float, amf_available: bool) -> Path:
    concat_list = None
    if bg_path.exists():
        try:
            bg_len = ffprobe_video_duration(bg_path)
            reps = max(1, math.ceil(total_d_video / max(bg_len, 0.001)))
            concat_list = tmp_dir / "bg_concat.txt"
            with concat_list.open("w", encoding="utf-8") as f:
                for _ in range(reps):
                    f.write(f"file '{str(bg_path).replace('\\', '/')}'\n")
            bg_in = f'-f concat -safe 0 -i "{concat_list}"'
            first_stage = f"[0:v]scale={video_res},setsar=1[v0]"
        except Exception:
            bg_in = f'-f lavfi -i "color=c=black:s={video_res}:r={fps}:d={total_d_video}"'
            first_stage = "[0:v]setsar=1[v0]"
    else:
        bg_in = f'-f lavfi -i "color=c=black:s={video_res}:r={fps}:d={total_d_video}"'
        first_stage = "[0:v]setsar=1[v0]"

    # time-windowed number overlays
    draws = []
    prev = "v0"
    raw_font = windows_fontfile()
    font_path = ffmpeg_escape_fontfile(raw_font)
    for idx in range(N):
        start = round(idx * slot, 6)
        end   = round(start + preview_sec - xfade_preview - 0.02, 6)
        label = f"{idx+1:02d}"
        nxt = f"v{idx+1}"
        draws.append(
            f'[{prev}]drawtext=fontfile=\'{font_path}\':text=\'{label}\':fontcolor=white:borderw=6:'
            f'bordercolor=black:fontsize=200:x=(w-tw)/2:y=(h-th)/2:enable=between(t\\,{start}\\,{end})[{nxt}]'
        )
        prev = nxt

    filter_chain = ";".join([first_stage] + draws + [f"[{prev}]format=yuv420p[out]"])
    video_full = tmp_dir / "preview_video_full.mp4"

    vcodec_build = ('-c:v h264_amf -quality speed -usage transcoding -rc cqp -qp_i 23 -qp_p 23 -g 240 -pix_fmt yuv420p'
                    if amf_available else
                    '-c:v libx264 -preset veryfast -tune fastdecode -pix_fmt yuv420p')

    cmd = (
        f'ffmpeg -y -hide_banner -loglevel error {bg_in} '
        f'-filter_complex "{filter_chain}" -map "[out]" -t {total_d_video} -r {fps} {vcodec_build} '
        f'-threads 4 "{video_full}"'
    )
    try:
        sh(cmd)
    except subprocess.CalledProcessError:
        sh(
            f'ffmpeg -y -hide_banner -loglevel error {bg_in} '
            f'-filter_complex "{filter_chain}" -map "[out]" -t {total_d_video} -r {fps} '
            f'-c:v libx264 -preset veryfast -tune fastdecode -pix_fmt yuv420p -threads 4 "{video_full}"'
        )
    return video_full

def mux_preview(video_full: Path, preview_audio: Path, out_path: Path, total_d_video: float):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    max_bytes_total = 100 * 1024 * 1024
    audio_kbps = 192
    audio_bits = int(audio_kbps * 1000 * total_d_video)
    container_overhead_bits = int(max_bytes_total * 8 * 0.02)
    available_video_bits = max(1, max_bytes_total * 8 - audio_bits - container_overhead_bits)
    target_video_kbps = max(200, available_video_bits // int(max(total_d_video, 0.001)) // 1000)
    sh(
        f'ffmpeg -y -hide_banner -loglevel error -i "{video_full}" -i "{preview_audio}" '
        f'-map 0:v -map 1:a '
        f'-c:v libx264 -b:v {target_video_kbps}k -maxrate {target_video_kbps}k -bufsize {target_video_kbps*2}k '
        f'-c:a aac -b:a {audio_kbps}k -movflags +faststart -shortest "{out_path}"'
    )
