"""Build an ad from the user's own raw product videos:
split them into scenes, have Claude describe each clip, match clips to the script line
by line, and cut a montage that the normal HyperFrames step captions and finishes."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from . import media

W, H, FPS = 1080, 1920, 30
MAX_CLIPS = 60
VIDEO_EXT = (".mp4", ".mov", ".webm", ".m4v", ".mkv")


def _scene_cuts(video: Path, threshold: float = 0.32) -> list[float]:
    """Timestamps where the picture changes (ffmpeg scene detection)."""
    p = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(video), "-an",
                        "-vf", f"select='gt(scene,{threshold})',showinfo", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
    return [float(x) for x in re.findall(r"pts_time:([0-9.]+)", p.stderr)]


def split_scenes(videos: list[Path], thumbs_dir: Path, min_len: float = 0.9, max_len: float = 5.0) -> list[dict]:
    """[{id, file, start, end, dur, thumb}] over all videos. Long scenes are chopped into
    pieces of at most max_len so there are many clips to choose from."""
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    per_video = []
    for v in videos:
        info = media.probe(v)
        dur = info["duration"]
        if not info["width"] or dur < min_len:
            continue
        cuts = [0.0] + [c for c in _scene_cuts(v) if 0.2 < c < dur - 0.2] + [dur]
        scenes = []
        for a, b in zip(cuts, cuts[1:]):
            a, b = a + 0.08, b - 0.08            # stay clear of the cut frames
            n = max(1, round((b - a) / max_len + 0.35))
            step = (b - a) / n
            for k in range(n):
                s, e = a + k * step, a + (k + 1) * step
                if e - s >= min_len:
                    scenes.append((s, e))
        per_video.append((v, scenes))
    # keep at most MAX_CLIPS, spread evenly over the videos
    total = sum(len(s) for _, s in per_video)
    clips = []
    for v, scenes in per_video:
        keep = len(scenes) if total <= MAX_CLIPS else max(1, len(scenes) * MAX_CLIPS // total)
        idx = [round(i * (len(scenes) - 1) / max(keep - 1, 1)) for i in range(keep)] if keep < len(scenes) else range(len(scenes))
        for i in sorted(set(idx)):
            s, e = scenes[i]
            cid = len(clips)
            thumb = thumbs_dir / f"clip_{cid:02d}.jpg"
            media._grab(v, (s + e) / 2, thumb, "scale=320:-2", 5)
            clips.append({"id": cid, "file": v.name, "start": round(s, 2), "end": round(e, 2),
                          "dur": round(e - s, 2), "thumb": thumb.name})
    return clips


def segments(words: list, max_len: float = 3.6) -> list[dict]:
    """Split the voiceover into beats (sentence ends, or every ~max_len seconds).
    Each beat is shown with one clip. Times are relative to the voiceover audio."""
    segs, cur = [], []
    for w in words:
        cur.append(w)
        if re.search(r"[.!?…]$", w[2]) or (w[1] - cur[0][0] >= max_len and re.search(r"[,;:]$", w[2])) \
                or w[1] - cur[0][0] >= max_len + 1.2:
            segs.append(cur)
            cur = []
    if cur:
        segs.append(cur)
    out = []
    for i, g in enumerate(segs):
        start = 0.0 if i == 0 else g[0][0]
        end = segs[i + 1][0][0] if i + 1 < len(segs) else g[-1][1] + 0.6
        out.append({"i": i, "start": round(start, 2), "end": round(end, 2), "dur": round(end - start, 2),
                    "text": " ".join(x[2] for x in g)})
    return out


def plan_cuts(segs: list[dict], clips: list[dict], assignments: dict[int, list[int]]) -> list[dict]:
    """Turn Claude's clip choices into an exact cut list covering every beat:
    [{clip, file, start, dur, seg}]. Fills gaps with unused clips, never leaves a hole."""
    by_id = {c["id"]: c for c in clips}
    usable = [c for c in clips if c.get("usable", True)] or clips
    used: set[int] = set()

    def next_unused(prefer_after: int | None) -> dict:
        pool = [c for c in usable if c["id"] not in used] or usable
        if prefer_after is not None:       # stay close to the previous clip: same video, next scene
            pool = sorted(pool, key=lambda c: (abs(c["id"] - prefer_after - 1), c["id"]))
        return pool[0]

    cuts = []
    for s in segs:
        need = s["dur"]
        want = [by_id[c] for c in assignments.get(s["i"], []) if c in by_id]
        last = None
        while need > 0.05:
            c = want.pop(0) if want else next_unused(last)
            used.add(c["id"])
            take = min(c["dur"], need)
            if need - take < 0.6 < need and c["dur"] >= need:   # avoid a sliver at the end of a beat
                take = need
            cuts.append({"clip": c["id"], "file": c["file"], "start": c["start"], "dur": round(take, 3), "seg": s["i"],
                         "blur": text_box(c)})
            need -= take
            last = c["id"]
            if take < 0.05:
                break
    return cuts


def text_box(c: dict) -> list | None:
    """[x, y, w, h] as fractions of the frame for burned-in text to hide, or None."""
    if not c.get("has_burned_text"):
        return None
    x, y, w, h = (float(c.get(k) or 0) / 100 for k in ("text_x_pct", "text_y_pct", "text_w_pct", "text_h_pct"))
    x, y = max(x - 0.01, 0.0), max(y - 0.01, 0.0)
    w, h = min(w + 0.02, 1 - x), min(h + 0.02, 1 - y)
    if w < 0.05 or h < 0.02 or w * h > 0.45:      # nothing sensible to blur, or it would hide the shot
        return None
    return [round(v, 4) for v in (x, y, w, h)]


def montage(cuts: list[dict], files_dir: Path, work: Path, out: Path) -> Path:
    """Cut each piece to 1080x1920 / 30 fps (cropped to fill) and join them, without sound."""
    work.mkdir(parents=True, exist_ok=True)
    fit = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},setsar=1,format=yuv420p"
    parts = []
    for n, c in enumerate(cuts):
        part = work / f"part_{n:03d}.mp4"
        if c.get("blur"):     # hide captions burned into the source before fitting it to 9:16
            x, y, w, h = c["blur"]
            graph = (f"[0:v]split[a][b];[b]crop=iw*{w}:ih*{h}:iw*{x}:ih*{y},boxblur=20:3[bl];"
                     f"[a][bl]overlay=main_w*{x}:main_h*{y},{fit}[v]")
        else:
            graph = f"[0:v]{fit}[v]"
        media._run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{c['start']:.3f}", "-i", str(files_dir / c["file"]),
                    "-t", f"{c['dur']:.3f}", "-an", "-filter_complex", graph, "-map", "[v]",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", str(part)])
        parts.append(part)
    lst = work / "parts.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
    media._run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                "-c", "copy", "-movflags", "+faststart", str(out.resolve())], timeout=900)
    for p in parts:
        p.unlink(missing_ok=True)
    return out
