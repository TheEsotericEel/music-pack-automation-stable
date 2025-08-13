import sys, shutil, random, math
from pathlib import Path
from .utils import need, load_yaml_min, ensure_initialized, sanitize, timestamp
from .utils import has_encoder
from .names import load_name_list, next_random_name
from .preview import build_smart_snips, render_preview_video, mux_preview
from .audio import crossfade_sequence
from .utils import sh

def main():
    need("ffmpeg")
    ROOT = Path.cwd().resolve()
    ensure_initialized(ROOT)
    CONF = load_yaml_min(ROOT / "config.yaml")

    ASSETS = ROOT / "assets"
    INBOX  = ROOT / "inbox"
    OUTROOT= ROOT / CONF.get("output_root","dist")
    PREVIEW_BG = ASSETS / "preview_bg" / "preview_bg.mp4"
    AMF_AVAILABLE = has_encoder("h264_amf")

    title = input("Enter Pack Title (folder name): ").strip()
    if not title: sys.exit("Pack title is required.")
    _ = input("Enter Genre: ").strip()
    _ = input("Enter Mood: ").strip()
    _ = input("Enter Thumbnail Text (optional, ignored): ").strip()

    sku = f"{CONF.get('sku_prefix','PK')}-{timestamp()[-6:]}"
    video_res    = CONF.get("video_res","1280x720")
    preview_sec  = int(CONF.get("preview_per_track_sec",15))
    bitrate_mp3  = CONF.get("bitrate_mp3","320k")
    fps = 30
    xfade_preview = 0.5
    xfade_full    = 2.0

    pack_dir   = OUTROOT / f"{sanitize(title)}_{sku}"
    tracks_dir = pack_dir / "tracks_mp3"
    preview_dir= pack_dir / "preview"
    mix_dir    = pack_dir / "mix"
    tmp_dir    = pack_dir / "_tmp"
    for d in (OUTROOT, pack_dir, tracks_dir, preview_dir, mix_dir, tmp_dir):
        d.mkdir(parents=True, exist_ok=True)

    for fname in ["license.pdf", "license.txt", "README.pdf", "README.txt"]:
        src = ASSETS / fname
        if src.exists(): shutil.copy2(src, pack_dir / fname)

    AUDIO_EXTS = {".wav",".mp3",".flac",".m4a",".aac",".ogg"}
    tracks = sorted([p for p in INBOX.rglob("*") if p.is_file() and p.suffix.lower() in AUDIO_EXTS],
                    key=lambda p: str(p.relative_to(INBOX)).lower())
    if not tracks: raise SystemExit("No input audio files found in inbox/.")

    name_list = load_name_list(ROOT)
    used_names = set()

    def to_mp3_random_into_tree(src: Path) -> Path:
        rel_parent = src.parent.relative_to(INBOX)
        out_parent = tracks_dir / rel_parent
        out_parent.mkdir(parents=True, exist_ok=True)
        rnd = next_random_name(used_names, name_list)
        dest = out_parent / f"{rnd}.mp3"
        sh(f'ffmpeg -y -hide_banner -loglevel error -i "{src}" -vn -sn -dn -c:a libmp3lame -b:a {bitrate_mp3} -threads 4 "{dest}"')
        return dest

    print("== Transcoding to MP3 with random names (preserving folder tree) ==")
    mp3_outputs = [to_mp3_random_into_tree(src) for src in tracks]

    seg_snips, preview_starts = build_smart_snips(tracks, tmp_dir, preview_sec)
    preview_audio = tmp_dir / "preview_audio.m4a"
    crossfade_sequence(seg_snips, preview_audio, xfade_d=xfade_preview, codec="aac", bitrate="192k",
                       inter_codec="pcm_s16le", threads=4, filter_threads=2)

    N = len(tracks)
    slot = preview_sec - xfade_preview
    total_d_audio = preview_sec + (N - 1) * slot
    total_d_video = total_d_audio

    video_full = render_preview_video(
        bg_path=ASSETS / "preview_bg" / "preview_bg.mp4",
        tmp_dir=tmp_dir,
        video_res=video_res,
        fps=fps,
        total_d_video=total_d_video,
        N=N,
        slot=slot,
        preview_sec=preview_sec,
        xfade_preview=xfade_preview,
        amf_available=AMF_AVAILABLE
    )

    preview_out = preview_dir / "preview.mp4"
    mux_preview(video_full, preview_audio, preview_out, total_d_video)

    print("== Full mix (WAV intermeds; final MP3) ==")
    mix_mp3 = mix_dir / "mix.mp3"
    crossfade_sequence(tracks, mix_mp3, xfade_d=2.0, codec="libmp3lame", bitrate=CONF.get("bitrate_mp3","320k"),
                       inter_codec="pcm_s16le", threads=4, filter_threads=2)

    shutil.rmtree(tmp_dir, ignore_errors=True)
    print("\n== DONE ==")
    print(f"Pack ready: {pack_dir}")

if __name__ == "__main__":
    main()
