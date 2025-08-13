import re, tempfile, shutil, subprocess
from pathlib import Path
from .utils import ffprobe_duration, sh

_silence_re_start = re.compile(r"silence_start:\s*([0-9.]+)")
_silence_re_end   = re.compile(r"silence_end:\s*([0-9.]+)")

def find_non_silent_start(src: Path, want: float) -> float:
    dur = float(ffprobe_duration(src) or 0.0)
    if want >= dur:
        return 0.0
    r = subprocess.run(
        f'ffmpeg -hide_banner -nostats -i "{src}" -af "silencedetect=noise=-35dB:d=0.35" -f null -',
        shell=True, text=True, capture_output=True
    )
    silences, cur = [], None
    for line in r.stderr.splitlines():
        m1 = _silence_re_start.search(line)
        m2 = _silence_re_end.search(line)
        if m1:
            cur = float(m1.group(1))
        if m2 and cur is not None:
            silences.append((cur, float(m2.group(1))))
            cur = None

    non_silent, t = [], 0.0
    for s, e in sorted(silences):
        if s > t:
            non_silent.append((t, s))
        t = max(t, e)
    if t < dur:
        non_silent.append((t, dur))

    for a, b in non_silent:
        if b - a >= want + 0.5:
            return max(a + 0.25, 0.0)

    if non_silent:
        a, b = max(non_silent, key=lambda ab: ab[1] - ab[0])
        mid = (a + b) / 2.0
        return max(min(mid - want / 2, dur - want - 0.2), 0.0)

    start = max(dur * 0.10, 15.0)
    if start + want > dur:
        start = max(0.0, dur - want - 0.2)
    return start

def find_energy_peak_start(src: Path, want: float) -> float:
    try:
        import numpy as np
        import librosa
    except Exception:
        return find_non_silent_start(src, want)

    try:
        y, sr = librosa.load(str(src), mono=True, sr=22050)
        if y.size == 0:
            return find_non_silent_start(src, want)

        dur = float(ffprobe_duration(src) or 0.0)
        if want >= dur:
            return 0.0

        hop = 512
        frame_sec = hop / sr
        oenv = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
        win_frames = max(1, int(want / frame_sec))
        if len(oenv) <= win_frames:
            return find_non_silent_start(src, want)

        # moving-sum over the window (left-aligned index)
        s = np.convolve(oenv, np.ones(win_frames, dtype=float), mode="valid")
        best_i = int(s.argmax())
        start = max(best_i * frame_sec, 0.0)

        if start + want > dur:
            start = max(0.0, dur - want - 0.2)
        return float(start)
    except Exception:
        return find_non_silent_start(src, want)

def crossfade_sequence(
    files,
    out_path,
    xfade_d=0.8,
    codec="aac",
    bitrate="192k",
    inter_codec="pcm_s16le",
    threads=4,
    filter_threads=2,
):
    tmpdir = Path(tempfile.mkdtemp(prefix="_xf_"))
    try:
        if not files:
            raise RuntimeError("No files to crossfade.")
        if len(files) == 1:
            sh(
                f'ffmpeg -y -hide_banner -i "{files[0]}" -vn -sn -dn '
                f'-c:a {codec} -b:a {bitrate} -threads {threads} "{out_path}"'
            )
            return

        cur = files[0]
        for idx, nxt in enumerate(files[1:], start=1):
            mid = tmpdir / f"xf_{idx:02d}.wav"
            cmd = (
                f'ffmpeg -y -hide_banner -i "{cur}" -i "{nxt}" '
                f'-filter_complex_threads {filter_threads} '
                f'-filter_complex '
                f'"[0:a]aformat=sample_rates=44100:channel_layouts=stereo,aresample=44100[a0];'
                f'[1:a]aformat=sample_rates=44100:channel_layouts=stereo,aresample=44100[a1];'
                f'[a0][a1]acrossfade=d={xfade_d}:c1=tri:c2=tri[aout]" '
                f'-map "[aout]" -vn -sn -dn -c:a {inter_codec} -threads {threads} "{mid}"'
            )
            sh(cmd)
            cur = mid

        sh(
            f'ffmpeg -y -hide_banner -i "{cur}" -vn -sn -dn '
            f'-c:a {codec} -b:a {bitrate} -threads {threads} "{out_path}"'
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
