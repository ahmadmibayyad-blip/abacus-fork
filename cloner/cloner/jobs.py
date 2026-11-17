"""Job store + the clone pipeline. One worker thread runs jobs in order (HyperFrames
renders one at a time per machine anyway)."""
from __future__ import annotations

import json
import queue
import shutil
import threading
import time
import traceback
import uuid
from pathlib import Path

from PIL import Image

from . import ai, builder, compose, imagetext, media, sources, voice
from .config import JOBS_DIR

LANGUAGES = {
    "Danish": "da", "Swedish": "sv", "Norwegian": "no", "Finnish": "fi", "German": "de",
    "Dutch": "nl", "English": "en", "French": "fr", "Spanish": "es", "Italian": "it",
    "Portuguese": "pt", "Polish": "pl",
}

_lock = threading.RLock()
_q: "queue.Queue[tuple]" = queue.Queue()


# ---------- persistence ----------

def job_dir(job_id: str) -> Path:
    return JOBS_DIR / job_id


def load(job_id: str) -> dict:
    with _lock:
        return json.loads((job_dir(job_id) / "job.json").read_text(encoding="utf-8"))


def save(job: dict) -> None:
    with _lock:
        p = job_dir(job["id"]) / "job.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(job, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)


def update(job_id: str, fn) -> dict:
    with _lock:
        job = load(job_id)
        fn(job)
        job["updated"] = time.time()
        save(job)
        return job


def set_ad(job_id: str, idx: int, **kw) -> None:
    update(job_id, lambda j: j["ads"][idx].update(kw))


def list_jobs() -> list[dict]:
    out = []
    for d in sorted(JOBS_DIR.iterdir(), reverse=True):
        f = d / "job.json"
        if f.exists():
            j = json.loads(f.read_text(encoding="utf-8"))
            out.append({k: j.get(k) for k in ("id", "created", "status", "error", "input")} |
                       {"ads": len(j.get("ads", [])), "done": sum(a.get("status") == "done" for a in j.get("ads", []))})
    out.sort(key=lambda j: j["created"], reverse=True)
    return out


def delete(job_id: str) -> None:
    shutil.rmtree(job_dir(job_id), ignore_errors=True)


# ---------- creation ----------

def _new(opts: dict, ads: list[dict] | None = None) -> dict:
    job_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    job_dir(job_id).mkdir(parents=True)
    opts["lang_code"] = LANGUAGES.get(opts.get("language", "Danish"), "da")
    job = {"id": job_id, "created": time.time(), "updated": time.time(), "status": "queued",
           "step": "Waiting", "error": None, "input": opts, "ads": ads or []}
    save(job)
    return job


def create_from_library(opts: dict) -> dict:
    job = _new(opts)
    _q.put(("library", job["id"]))
    return job


def create_from_uploads(opts: dict, files: list[tuple[str, bytes]]) -> dict:
    job = _new(opts)
    ads = []
    for i, (name, data) in enumerate(files):
        ext = Path(name).suffix.lower() or ".bin"
        d = job_dir(job["id"]) / f"ad{i + 1}"
        d.mkdir()
        p = d / f"source{ext}"
        p.write_bytes(data)
        kind = "video" if ext in (".mp4", ".mov", ".webm", ".m4v") else "image"
        ads.append(_ad_record(i, {"ad_id": name, "kind": kind, "media_url": None, "page_name": "",
                                  "copy": {"primary_text": "", "headline": "", "description": "", "cta": ""},
                                  "library_url": ""}, source=f"ad{i + 1}/source{ext}"))
    update(job["id"], lambda j: j.update(ads=ads))
    _q.put(("process", job["id"]))
    return load(job["id"])


def create_build(opts: dict, files: list[tuple[str, bytes]]) -> dict:
    """One ad built from the user's own product videos."""
    opts["mode"] = "build"
    job = _new(opts)
    d = job_dir(job["id"]) / "ad1" / "footage"
    d.mkdir(parents=True)
    names = []
    for n, (name, data) in enumerate(files):
        ext = Path(name).suffix.lower()
        if ext not in builder.VIDEO_EXT:
            continue
        fn = f"video_{n + 1:02d}{ext}"
        (d / fn).write_bytes(data)
        names.append(fn)
    rec = _ad_record(0, {"ad_id": "My clips", "kind": "video", "media_url": None, "page_name": "", "library_url": "",
                         "copy": {"primary_text": "", "headline": "", "description": "", "cta": ""}})
    rec.update(mode="build", footage=names, clips=[], scripts=[])
    if not names:
        rec.update(status="error", error="No video files were uploaded (mp4, mov, webm, m4v, mkv).")
    update(job["id"], lambda j: j.update(ads=[rec]))
    _q.put(("process", job["id"]))
    return load(job["id"])


MAX_ADS = 20


def _placeholder(ad_id: str, link: str) -> dict:
    return {"ad_id": ad_id, "kind": "unknown", "media_url": None, "page_name": "", "library_url": link,
            "copy": {"primary_text": "", "headline": "", "description": "", "cta": ""}}


def _ad_record(i: int, ad: dict, source: str | None = None) -> dict:
    return {"idx": i, "ad_id": ad["ad_id"], "kind": ad["kind"], "page_name": ad.get("page_name", ""),
            "library_url": ad.get("library_url", ""), "media_url": ad.get("media_url"),
            "src_copy": ad["copy"], "source": source, "thumb": None, "status": "queued", "step": "Waiting",
            "progress": 0, "error": None, "plan": None, "output": None, "ad_copy": None, "changes": []}


def queue_rerender(job_id: str, idx: int, payload: dict) -> None:
    def fn(j):
        a = j["ads"][idx]
        if not a.get("source") and a.get("mode") != "build":
            raise ValueError("This ad has no downloaded media to re-render.")
        p = payload if a.get("plan") else {}
        if a.get("mode") == "build" and a.get("plan"):
            a["new_script"] = bool(p.get("new_script"))
            changed = "voiceover" in p and p["voiceover"].strip() != (a["plan"].get("voiceover") or "").strip()
            a["redo_voice"] = bool(a["new_script"] or p.get("new_take") or changed)
            if p.get("caption_style") in ("bold_upper", "clean", "none"):
                a["plan"]["captions"]["style"] = p["caption_style"]
            ids = {c["id"] for c in a.get("clips") or []}
            for beat, clip in (p.get("swaps") or {}).items():
                if int(clip) in ids:
                    a.setdefault("swaps", {})[str(int(beat))] = int(clip)
        if a["kind"] == "video" and "voiceover" in p:
            a["plan"]["voiceover"] = p["voiceover"]
            if "end_card_lines" in p:
                a["plan"]["end_card_lines"] = p["end_card_lines"]
            if "end_card_cta" in p:
                a["plan"]["end_card_cta"] = p["end_card_cta"]
        if a["kind"] == "image" and "blocks" in p:
            a["plan"]["blocks"] = p["blocks"]
        if "ad_copy" in p:
            a["ad_copy"] = p["ad_copy"]
        a.update(status="queued", step="Waiting to re-render", error=None, progress=0)
    update(job_id, fn)
    _q.put(("rerender", job_id, idx))


# ---------- pipeline ----------

def _run_library(job_id: str) -> None:
    job = load(job_id)
    update(job_id, lambda j: j.update(status="running", step="Fetching ads from the Ad Library"))
    inp = job["input"]
    links = sources.classify(inp.get("urls") or [inp.get("url", "")])
    count = int(inp.get("count", 3))
    root = job_dir(job_id)

    # single-ad links: one Apify run for all of them
    ids = [l["id"] for l in links if l["type"] == "ad"]
    singles = sources.fetch_single_ads(ids, raw_path=root / "apify_single_ads.json") if ids else {}

    ads, errors = [], []          # errors[i] is the error for ads[i] (None if fine)
    for n, l in enumerate(links):
        if l["type"] == "ad":
            if l["id"] in singles:
                ads.append(singles[l["id"]]); errors.append(None)
            else:
                ads.append(_placeholder(l["id"], l["link"]))
                errors.append(f"Ad {l['id']} was not found in the Ad Library (removed, restricted, or the link is wrong).")
        else:
            try:
                for a in sources.fetch_ads(l["url"], count, raw_path=root / f"apify_page_{n + 1}.json"):
                    ads.append(a); errors.append(None)
            except sources.SourceError as e:
                ads.append(_placeholder("", l["link"])); errors.append(str(e))
    ads, errors = ads[:MAX_ADS], errors[:MAX_ADS]

    records = [_ad_record(i, a) for i, a in enumerate(ads)]
    for r, err in zip(records, errors):
        if err:
            r.update(status="error", error=err, step="Failed")
    update(job_id, lambda j: j.update(ads=records))
    for i, a in enumerate(records):
        if a["status"] == "error":
            continue
        if not a["media_url"]:
            set_ad(job_id, i, status="error", error="No image or video found on this ad.")
            continue
        d = job_dir(job_id) / f"ad{i + 1}"
        d.mkdir(exist_ok=True)
        ext = ".mp4" if a["kind"] == "video" else ".jpg"
        set_ad(job_id, i, step="Downloading media")
        try:
            sources.download(a["media_url"], d / f"source{ext}")
            set_ad(job_id, i, source=f"ad{i + 1}/source{ext}")
        except Exception as e:  # noqa: BLE001 - surface any download failure on the card
            set_ad(job_id, i, status="error", error=str(e))
    _run_process(job_id)


def _run_process(job_id: str) -> None:
    update(job_id, lambda j: j.update(status="running", step="Cloning ads"))
    job = load(job_id)
    for i, a in enumerate(job["ads"]):
        if a["status"] == "error" or (not a.get("source") and a.get("mode") != "build"):
            continue
        try:
            if a.get("mode") == "build":
                _build(job_id, i, fresh=True)
            elif a["kind"] == "video":
                _video(job_id, i, fresh=True)
            else:
                _image(job_id, i, fresh=True)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            set_ad(job_id, i, status="error", error=str(e), step="Failed")
    _finish(job_id)


def _finish(job_id: str) -> None:
    def fn(j):
        states = [a["status"] for a in j["ads"]]
        j["status"] = "done" if states and all(s in ("done", "error") for s in states) else j["status"]
        if states and all(s == "error" for s in states):
            j["status"] = "error"
            j["error"] = j.get("error") or "Every ad failed; open an ad card for the reason."
        j["step"] = "Finished"
    update(job_id, fn)


def _image(job_id: str, i: int, fresh: bool) -> None:
    job = load(job_id)
    a, opts = job["ads"][i], job["input"]
    root = job_dir(job_id)
    src = root / a["source"]
    d = src.parent
    set_ad(job_id, i, status="running", thumb=a["source"], progress=10)
    im = Image.open(src).convert("RGB")
    W, H = im.size
    scale = min(1.0, 1092 / max(W, H))
    if fresh or not a.get("plan"):
        set_ad(job_id, i, step="Claude is reading the image and writing the translation")
        small = d / "analysis.jpg"
        im.resize((int(W * scale), int(H * scale))).save(small, quality=90)
        plan = ai.plan_image(small, int(W * scale), int(H * scale), a["src_copy"], opts).model_dump()
        for b in plan["blocks"]:
            for k in ("x0", "y0", "x1", "y1"):
                b[k] = int(round(b[k] / scale))
        set_ad(job_id, i, plan=plan, ad_copy=plan["ad_copy"], changes=plan["changes"], progress=60)
        a = load(job_id)["ads"][i]
    set_ad(job_id, i, step="Replacing the text on the image", progress=75)
    out = d / f"clone_{int(time.time())}.jpg"
    imagetext.render(src, out, a["plan"]["blocks"])
    set_ad(job_id, i, status="done", step="Done", progress=100, output=str(out.relative_to(root)))


def _video(job_id: str, i: int, fresh: bool) -> None:
    job = load(job_id)
    a, opts = job["ads"][i], job["input"]
    root = job_dir(job_id)
    src = root / a["source"]
    d = src.parent
    info = media.probe(src)
    if not info["width"]:
        raise media.MediaError("Could not read the video.")
    thumb = d / "thumb.jpg"
    if not thumb.exists():
        media.thumbnail(src, thumb)
    last = media.last_frame(src, d / "last.jpg")
    set_ad(job_id, i, status="running", thumb=str(thumb.relative_to(root)), progress=5)

    if fresh or not a.get("plan"):
        transcript = ""
        if info["has_audio"]:
            set_ad(job_id, i, step="Transcribing the original voiceover")
            t = voice.transcribe(media.extract_audio(src, d / "audio.wav"))
            transcript = t["text"]
            (d / "transcript.json").write_text(json.dumps(t, ensure_ascii=False, indent=1), encoding="utf-8")
        set_ad(job_id, i, step="Claude is watching the ad and writing the new script", progress=15)
        frames = media.sample_frames(src, d / "frames", n=6)
        plan = ai.plan_video(transcript, frames, a["src_copy"], info["duration"], opts).model_dump()
        plan["source_transcript"] = transcript
        set_ad(job_id, i, plan=plan, ad_copy=plan["ad_copy"], changes=plan["changes"], progress=30)
        a = load(job_id)["ads"][i]
    plan = a["plan"]

    set_ad(job_id, i, step="Recording the new voiceover", progress=35)
    raw = d / "vo_raw.mp3"
    words = voice.speak(plan["voiceover"], raw, voice_id=opts.get("voice_id") or None,
                        model_id=opts.get("model_id") or None)
    if not words:
        raise voice.VoiceError("The voiceover came back without timings.")
    start, end = max(words[0][0] - 0.05, 0), words[-1][1] + 0.2
    vo = media.cut_audio(raw, d / "vo_cut.wav", start, end)
    words = [[w0 - start, w1 - start, t] for w0, w1, t in words]
    length = end - start
    target = info["duration"] + 1.5
    if length > target:                       # too long for the footage: speed up a little
        f = min(length / target, 1.2)
        vo = media.tempo(vo, d / "vo_fit.wav", f)
        words = [[w0 / f, w1 / f, t] for w0, w1, t in words]

    set_ad(job_id, i, step="Building the HyperFrames composition", progress=45)
    proj = d / "hyperframes"
    meta = compose.build(proj, src_video=src, last_jpg=last, vo_audio=vo, words=words, probe=info,
                         plan=plan, lang_code=opts.get("lang_code", "da"))
    set_ad(job_id, i, step="Rendering with HyperFrames", progress=50, render=meta)
    raw_out = d / "render_raw.mp4"
    compose.render(proj, raw_out, on_progress=lambda p: set_ad(job_id, i, progress=50 + int(p * 0.45)))
    set_ad(job_id, i, step="Compressing", progress=96)
    out = d / f"clone_{int(time.time())}.mp4"
    media.compress(raw_out, out)
    raw_out.unlink(missing_ok=True)
    set_ad(job_id, i, status="done", step="Done", progress=100, output=str(out.relative_to(root)))


def _build(job_id: str, i: int, fresh: bool) -> None:
    """Ad from the user's own footage: scenes -> descriptions -> script -> voice -> matched montage -> render.
    Later runs redo only what changed: a clip swap or caption style keeps the voiceover."""
    job = load(job_id)
    a, opts = job["ads"][i], job["input"]
    root = job_dir(job_id)
    d = root / "ad1"
    footage, thumbs = d / "footage", d / "clips"
    set_ad(job_id, i, status="running", progress=3)

    if not a.get("clips"):
        set_ad(job_id, i, step="Cutting your videos into scenes")
        clips = builder.split_scenes([footage / f for f in a["footage"]], thumbs)
        if not clips:
            raise media.MediaError("No usable scenes were found in the uploaded videos.")
        set_ad(job_id, i, step=f"Claude is looking at {len(clips)} clips", progress=10,
               clips=[dict(c, thumb=f"ad1/clips/{c['thumb']}") for c in clips])
        lib = ai.describe_clips(clips, thumbs, opts.get("product", ""), opts).model_dump()
        info = {c["id"]: c for c in lib["clips"]}
        for c in clips:
            c.update({k: v for k, v in info.get(c["id"], {}).items() if k != "id"})
            c.setdefault("description", ""); c.setdefault("usable", True); c.setdefault("shows", "other")
            c["thumb"] = f"ad1/clips/{c['thumb']}"
        set_ad(job_id, i, clips=clips, product_summary=lib["product_summary"], progress=22,
               thumb=clips[0]["thumb"])
        a = load(job_id)["ads"][i]
    clips = a["clips"]

    if fresh or a.get("new_script") or not a.get("plan"):
        set_ad(job_id, i, step="Claude is writing the script", progress=25)
        given = "" if a.get("new_script") else opts.get("script", "")
        lib = {"product_summary": a.get("product_summary", ""), "clips": clips}
        plan = ai.write_build_script(lib, opts.get("product", ""), given, a.get("scripts") or [], opts).model_dump()
        style = (a.get("plan") or {}).get("captions", {}).get("style") or opts.get("caption_style") or "bold_upper"
        plan["captions"] = {"present": False, "x_pct": 0, "y_pct": 0, "w_pct": 0, "h_pct": 0,
                            "style": style, "highlight_color": "#ff8bc3"}
        set_ad(job_id, i, plan=plan, ad_copy=plan["ad_copy"], changes=plan["changes"], new_script=False,
               redo_voice=True, scripts=(a.get("scripts") or []) + [plan["voiceover"]], progress=32)
        a = load(job_id)["ads"][i]
    plan = a["plan"]

    vo, words_file = d / "vo_cut.wav", d / "words.json"
    if fresh or a.get("redo_voice") or not (vo.exists() and words_file.exists() and a.get("assign")):
        set_ad(job_id, i, step="Recording the voiceover", progress=36)
        raw = d / "vo_raw.mp3"
        words = voice.speak(plan["voiceover"], raw, voice_id=opts.get("voice_id") or None,
                            model_id=opts.get("model_id") or None)
        if not words:
            raise voice.VoiceError("The voiceover came back without timings.")
        start, end = max(words[0][0] - 0.05, 0), words[-1][1] + 0.2
        media.cut_audio(raw, vo, start, end)
        words = [[w0 - start, w1 - start, t] for w0, w1, t in words]
        words_file.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")

        set_ad(job_id, i, step="Claude is matching clips to the script", progress=44)
        segs = builder.segments(words)
        match = ai.match_clips(segs, clips, opts).model_dump()
        assign = {str(m["segment"]): m["clip_ids"] for m in match["assignments"]}
        set_ad(job_id, i, assign=assign, swaps={}, redo_voice=False)     # new beats: earlier swaps no longer apply
        a = load(job_id)["ads"][i]
    words = json.loads(words_file.read_text(encoding="utf-8"))
    segs = builder.segments(words)
    segs[0]["dur"] = round(segs[0]["dur"] + 0.15, 2)   # the voiceover starts 0.15 s into the video

    assign = {int(k): v for k, v in (a.get("assign") or {}).items()}
    for beat, clip in (a.get("swaps") or {}).items():
        assign[int(beat)] = [int(clip)]
    cuts = builder.plan_cuts(segs, clips, assign)
    set_ad(job_id, i, step="Cutting the montage", progress=50, cuts=cuts,
           beats=[dict(sg, clips=[c["clip"] for c in cuts if c["seg"] == sg["i"]]) for sg in segs])
    src = builder.montage(cuts, footage, d / "parts", d / "montage.mp4")
    info = media.probe(src)
    last = media.last_frame(src, d / "last.jpg")

    set_ad(job_id, i, step="Building the HyperFrames composition", progress=58)
    proj = d / "hyperframes"
    meta = compose.build(proj, src_video=src, last_jpg=last, vo_audio=vo, words=words, probe=info,
                         plan=plan, lang_code=opts.get("lang_code", "da"))
    set_ad(job_id, i, step="Rendering with HyperFrames", progress=60, render=meta)
    raw_out = d / "render_raw.mp4"
    compose.render(proj, raw_out, on_progress=lambda p: set_ad(job_id, i, progress=60 + int(p * 0.36)))
    set_ad(job_id, i, step="Compressing", progress=97)
    out = d / f"ad_{int(time.time())}.mp4"
    media.compress(raw_out, out)
    raw_out.unlink(missing_ok=True)
    set_ad(job_id, i, status="done", step="Done", progress=100, output=str(out.relative_to(root)))


def _rerender(job_id: str, idx: int) -> None:
    update(job_id, lambda j: j.update(status="running"))
    try:
        a = load(job_id)["ads"][idx]
        if a.get("mode") == "build":
            _build(job_id, idx, fresh=False)
        elif a["kind"] == "video":
            _video(job_id, idx, fresh=False)
        else:
            _image(job_id, idx, fresh=False)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        set_ad(job_id, idx, status="error", error=str(e), step="Failed")
    _finish(job_id)


def _worker() -> None:
    while True:
        task = _q.get()
        kind, job_id = task[0], task[1]
        try:
            if kind == "library":
                _run_library(job_id)
            elif kind == "process":
                _run_process(job_id)
            elif kind == "rerender":
                _rerender(job_id, task[2])
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            update(job_id, lambda j: j.update(status="error", error=str(e), step="Failed"))
        finally:
            _q.task_done()


def start_worker() -> None:
    # jobs interrupted by a restart are marked so the user can re-run them
    for d in JOBS_DIR.iterdir():
        f = d / "job.json"
        if f.exists():
            j = json.loads(f.read_text(encoding="utf-8"))
            if j.get("status") in ("queued", "running"):
                j["status"], j["error"] = "error", "Cloner was restarted while this job ran."
                for a in j.get("ads", []):
                    if a.get("status") in ("queued", "running"):
                        a["status"], a["error"] = "error", "Interrupted by restart; press Re-render."
                f.write_text(json.dumps(j, indent=2, ensure_ascii=False), encoding="utf-8")
    threading.Thread(target=_worker, daemon=True).start()
