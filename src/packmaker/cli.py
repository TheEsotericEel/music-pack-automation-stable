import sys, shutil, random, math
from pathlib import Path
from .utils import need, load_yaml_min, ensure_initialized, sanitize, timestamp
from .utils import has_encoder, sh, zip_without_sku
from .names import load_name_list, next_random_name
from .preview import build_smart_snips, render_preview_video, mux_preview
from .audio import crossfade_sequence
from .uploader import upload_to_youtube


def main():
    need("ffmpeg")
    need("ffprobe")

    ROOT = Path.cwd().resolve()
    ensure_initialized(ROOT)
    CONF = load_yaml_min(ROOT / "config.yaml")

    ASSETS = ROOT / "assets"
    INBOX  = ROOT / "inbox"
    OUTROOT= ROOT / CONF.get("output_root","dist")
    PREVIEW_BG = ASSETS / "preview_bg" / "preview_bg.mp4"

    title = input("Enter Pack Title (folder name): ").strip()
    if not title: sys.exit("Pack title is required.")
    genre = input("Enter Genre: ").strip()
    mood  = input("Enter Mood: ").strip()
    _ = input("Enter Thumbnail Text (optional, ignored): ").strip()

    sku = f"{CONF.get('sku_prefix','PK')}-{timestamp()[-6:]}"
    video_res    = CONF.get("video_res","1280x720")
    preview_sec  = int(CONF.get("preview_per_track_sec",15))
    bitrate_mp3  = CONF.get("bitrate_mp3","320k")
    fps = 30
    xfade_preview = 0.5
    xfade_full    = 2.0

    # === quality + mux settings ===
    preview_crf    = int(CONF.get("preview_crf", 20))
    preview_preset = str(CONF.get("preview_preset", "veryfast"))

    raw_size = CONF.get("preview_max_size_mb", None)
    if raw_size in (None, "", "null", "None"):
        max_size_mb = None    # no size constraint
    else:
        max_size_mb = int(raw_size)

    override_kbps = CONF.get("preview_mux_video_kbps", None)
    override_kbps = int(override_kbps) if override_kbps not in (None, "",) else None
    # ==============================

    pack_dir   = OUTROOT / f"{sanitize(title)}_{sku}"
    tracks_dir = pack_dir / "tracks_mp3"
    preview_dir= pack_dir / "preview"
    mix_dir    = pack_dir / "mix"
    tmp_dir    = pack_dir / "_tmp"
    for d in (OUTROOT, pack_dir, tracks_dir, preview_dir, mix_dir, tmp_dir):
        d.mkdir(parents=True, exist_ok=True)

    # license/readme from master assets
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

    # preview audio from transcoded MP3s
    seg_snips, preview_starts = build_smart_snips(mp3_outputs, tmp_dir, preview_sec)
    preview_audio = tmp_dir / "preview_audio.m4a"
    crossfade_sequence(seg_snips, preview_audio, xfade_d=xfade_preview, codec="aac", bitrate="192k",
                       inter_codec="pcm_s16le", threads=4, filter_threads=2)

    N = len(mp3_outputs)
    slot = preview_sec - xfade_preview
    total_d_audio = preview_sec + max(0, (N - 1)) * slot
    total_d_video = total_d_audio

    video_full = render_preview_video(
        bg_path=PREVIEW_BG,
        tmp_dir=tmp_dir,
        video_res=video_res,
        fps=fps,
        total_d_video=total_d_video,
        N=N,
        slot=slot,
        preview_sec=preview_sec,
        xfade_preview=xfade_preview,
        amf_available=False,
        preview_crf=preview_crf,
        preview_preset=preview_preset,
    )

    preview_out = preview_dir / "preview.mp4"
    mux_preview(
        video_full, preview_audio, preview_out, total_d_video,
        max_size_mb=max_size_mb,
        override_video_kbps=override_kbps,
        audio_kbps=192,
    )

    print("== Full mix (WAV intermeds; final MP3) ==")
    mix_mp3 = mix_dir / "mix.mp3"
    crossfade_sequence(mp3_outputs, mix_mp3, xfade_d=xfade_full, codec="libmp3lame",
                       bitrate=bitrate_mp3, inter_codec="pcm_s16le", threads=4, filter_threads=2)

    zip_file = zip_without_sku(pack_dir)
    print(f"Zipped pack to: {zip_file}")

    # === YouTube upload (config-gated) ===
    if CONF.get("upload_to_youtube", False):
        # sanitize privacy value
        privacy = str(CONF.get("youtube_privacy", "unlisted")).strip().lower()
        if privacy not in ("public", "unlisted", "private"):
            privacy = "unlisted"
        tags = CONF.get("youtube_tags", []) or []

        desc_lines = []
        if genre: desc_lines.append(f"Genre: {genre}")
        if mood:  desc_lines.append(f"Mood: {mood}")
        desc_lines.append("Preview rendered automatically.")
        description = "\n".join(desc_lines)

        print("== Uploading preview to YouTube ==")
        url = upload_to_youtube(
            preview_out,
            title=title,
            description=description,
            privacy_status=privacy,
            tags=tags,
            root=ROOT,
            client_secret_filename=CONF.get("youtube_client_secret", "client_secret1.json"),
        )
        (preview_dir / "preview_youtube_url.txt").write_text(url + "\n", encoding="utf-8")
        print(f"YouTube URL: {url}")
    # =====================================

    shutil.rmtree(tmp_dir, ignore_errors=True)
    print("\n== DONE ==")
    print(f"Pack ready: {pack_dir}")

if __name__ == "__main__":
    main()
