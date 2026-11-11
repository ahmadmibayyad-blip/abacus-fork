"""ffmpeg / ffprobe helpers."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


class MediaError(RuntimeError):
    pass


def _run(cmd: list[str], timeout: int = 600) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise MediaError(f"{cmd[0]} failed: {p.stderr.strip()[-600:]}")
    return p.stdout


def check_tools() -> dict:
    return {t: bool(shutil.which(t)) for t in ("ffmpeg", "ffprobe", "node", "npx")}


def probe(path: Path) -> dict:
    out = json.loads(_run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]))
    v = next((s for s in out.get("streams", []) if s.get("codec_type") == "video"), {})
    a = next((s for s in out.get("streams", []) if s.get("codec_type") == "audio"), None)
    return {
        "duration": float(out.get("format", {}).get("duration") or 0),
        "width": int(v.get("width") or 0),
        "height": int(v.get("height") or 0),
        "has_audio": a is not None,
    }


def extract_audio(video: Path, wav: Path) -> Path:
    _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(wav)])
    return wav


def sample_frames(video: Path, out_dir: Path, n: int = 6, width: int = 540) -> list[Path]:
    """n evenly spaced frames (skipping the very first/last 3%)."""
    dur = probe(video)["duration"] or 1
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i in range(n):
        t = dur * (0.03 + 0.94 * i / max(n - 1, 1))
        p = out_dir / f"frame_{i:02d}.jpg"
        _run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(video),
              "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "4", str(p)])
        paths.append(p)
    return paths


def last_frame(video: Path, out: Path) -> Path:
    _run(["ffmpeg", "-y", "-loglevel", "error", "-sseof", "-0.15", "-i", str(video), "-frames:v", "1", "-q:v", "3", str(out)])
    return out


def trim_silence(src: Path, dst: Path) -> Path:
    f = ("silenceremove=start_periods=1:start_threshold=-45dB,areverse,"
         "silenceremove=start_periods=1:start_threshold=-45dB,areverse")
    _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-af", f, "-ar", "44100", str(dst)])
    return dst


def cut_audio(src: Path, dst: Path, start: float, end: float) -> Path:
    start = max(start, 0)
    _run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}",
          "-i", str(src), "-ar", "44100", "-ac", "2", str(dst)])
    return dst


def tempo(src: Path, dst: Path, factor: float) -> Path:
    _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-af", f"atempo={factor:.4f}", str(dst)])
    return dst


def compress(src: Path, dst: Path) -> Path:
    _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-c:v", "libx264", "-preset", "veryfast",
          "-crf", "21", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(dst)],
         timeout=1800)
    return dst


def thumbnail(video: Path, out: Path) -> Path:
    _run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1", "-i", str(video), "-frames:v", "1",
          "-vf", "scale=360:-2", "-q:v", "4", str(out)])
    return out
