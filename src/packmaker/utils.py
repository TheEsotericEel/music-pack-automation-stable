import sys, json, shutil, subprocess, datetime
from pathlib import Path

def sh(cmd, check=True):
    print(">", cmd)
    return subprocess.run(cmd, shell=True, check=check)

def need(bin_name):
    if shutil.which(bin_name) is None:
        sys.exit(f"Missing {bin_name} in PATH.")

def has_encoder(name: str) -> bool:
    r = subprocess.run('ffmpeg -hide_banner -encoders', shell=True, capture_output=True, text=True)
    return (r.returncode == 0) and (name in r.stdout)

def timestamp():
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")

def sanitize(name):
    return "".join(c for c in name if c.isalnum() or c in (" ","-","_")).strip()

def load_yaml_min(path: Path):
    conf = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or ":" not in s: continue
            k,v = s.split(":",1)
            conf[k.strip()] = v.strip().strip('"').strip("'")
    conf.setdefault("sku_prefix", "PK")
    conf.setdefault("make_mp3", True)
    conf.setdefault("make_wav", False)
    conf.setdefault("preview_per_track_sec", 10)
    conf.setdefault("output_root", "dist")
    conf.setdefault("video_res", "1280x720")
    conf.setdefault("bitrate_mp3", "320k")
    conf.setdefault("wav_bit_depth", 24)
    if isinstance(conf["make_mp3"], str): conf["make_mp3"] = conf["make_mp3"].lower() == "true"
    if isinstance(conf["make_wav"], str): conf["make_wav"] = conf["make_wav"].lower() == "true"
    try: conf["preview_per_track_sec"] = int(conf["preview_per_track_sec"])
    except: pass
    return conf

def ensure_initialized(root: Path):
    (root / "assets" / "preview_bg").mkdir(parents=True, exist_ok=True)
    (root / "assets" / "names").mkdir(parents=True, exist_ok=True)
    (root / "inbox").mkdir(parents=True, exist_ok=True)
    (root / "dist").mkdir(parents=True, exist_ok=True)
    cfg = root / "config.yaml"
    if not cfg.exists():
        cfg.write_text(
            """# Fixed defaults (edit as needed)
sku_prefix: "PK"
make_wav: true
make_mp3: true
preview_per_track_sec: 10
output_root: "dist"
video_res: "1280x720"
bitrate_mp3: "320k"
wav_bit_depth: 24
""",
            encoding="utf-8"
        )

def ffprobe_duration(path: Path) -> float:
    r = subprocess.run(
        f'ffprobe -v error -show_entries format=duration -of json "{path}"',
        shell=True, capture_output=True, text=True, check=True
    )
    j = json.loads(r.stdout)
    return float(j["format"]["duration"])

def ffprobe_video_duration(path: Path) -> float:
    r = subprocess.run(
        f'ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "{path}"',
        shell=True, capture_output=True, text=True, check=True
    )
    return float(r.stdout.strip())

def windows_fontfile(default="C:/Windows/Fonts/arial.ttf") -> str:
    p = Path(default)
    if not p.exists():
        for alt in [
            "C:/Windows/Fonts/ARIAL.TTF",
            "C:/Windows/Fonts/segoeui.ttf",
            "C:/Windows/Fonts/calibri.ttf",
        ]:
            if Path(alt).exists():
                return alt.replace("\\", "/")
        return default.replace("\\", "/")
    return default.replace("\\", "/")

def ffmpeg_escape_fontfile(path_str: str) -> str:
    return path_str.replace(":", r"\:")
