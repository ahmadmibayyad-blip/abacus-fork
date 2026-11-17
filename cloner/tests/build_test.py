"""Offline test of "Build from my clips": Claude and ElevenLabs are stubbed; scene
splitting, cut planning, montage and the HyperFrames render run for real.

    python tests/build_test.py
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["CLONER_DATA"] = tempfile.mkdtemp(prefix="cloner-build-")
os.environ["CLONER_SETTINGS"] = os.path.join(os.environ["CLONER_DATA"], "settings.json")
sys.path.insert(0, str(ROOT))

from cloner import ai, builder, jobs, voice  # noqa: E402
from cloner.config import JOBS_DIR  # noqa: E402

work = Path(os.environ["CLONER_DATA"]) / "fx"
work.mkdir(parents=True)


def make_video(name: str, sources: list[str], size: str) -> bytes:
    """A video with hard cuts between different pictures (3 s each)."""
    parts = []
    for n, src in enumerate(sources):
        p = work / f"{name}_{n}.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"{src}=s={size}:d=3:r=30",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(p)], check=True)
        parts.append(p)
    lst = work / f"{name}.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in parts))
    out = work / f"{name}.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", str(out)], check=True)
    return out.read_bytes()


FILES = [("portrait.mp4", make_video("a", ["testsrc2", "smptebars", "rgbtestsrc"], "360x640")),
         ("landscape.mov", make_video("b", ["yuvtestsrc", "testsrc"], "640x360")),
         ("notes.txt", b"not a video")]

# ---- unit checks on the pure functions ----
words = [[0.2, 0.5, "Stop"], [0.5, 0.9, "scrolling."], [1.1, 1.5, "This"], [1.5, 2.0, "board"], [2.0, 2.6, "glows."],
         [2.9, 3.3, "Kids"], [3.3, 3.8, "love"], [3.8, 4.2, "it."]]
segs = builder.segments(words)
assert [s["text"] for s in segs] == ["Stop scrolling.", "This board glows.", "Kids love it."], segs
assert segs[0]["start"] == 0 and abs(sum(s["dur"] for s in segs) - (4.2 + 0.6)) < 0.01, segs
clips = [{"id": i, "file": "f.mp4", "start": 0, "dur": d, "usable": True} for i, d in enumerate([0.5, 3.0, 3.0, 3.0])]
cuts = builder.plan_cuts(segs, clips, {0: [0], 1: [99], 2: []})        # short clip, unknown id, nothing chosen
for s in segs:
    assert abs(sum(c["dur"] for c in cuts if c["seg"] == s["i"]) - s["dur"]) < 0.01, (s, cuts)
assert cuts[0]["clip"] == 0 and len([c for c in cuts if c["seg"] == 0]) == 2, cuts   # 0.5 s clip topped up

# ---- stubs ----
SCRIPT = "Stop med at scrolle. Den her tavle lyser i mørket. Børn elsker den. Bestil i dag."
calls = {"describe": 0, "script": 0}


def fake_describe(clips, thumbs, product, opts):
    calls["describe"] += 1
    assert all((thumbs / c["thumb"]).exists() for c in clips)
    return ai.ClipLibrary(product_summary="A glowing drawing board.", clips=[
        ai.ClipInfo(id=c["id"], description=f"shot {c['id']}", shows="product_in_use", has_burned_text=False,
                    usable=c["id"] != 1) for c in clips])


def fake_script(library, product, script, previous, opts):
    calls["script"] += 1
    vo = script or (SCRIPT if not previous else "Ny vinkel. Tavlen lyser. Prøv den nu.")
    return ai.BuildScript(voiceover=vo, ad_copy=ai.AdCopy(primary_text="Lysende tavle ✨", headline="Glow board",
                          description="I dag", cta="Shop nu"), end_card_lines=["GLOW BOARD", "Bestil i dag"],
                          end_card_cta="SHOP NU", changes=[])


def fake_match(segs, clips, opts):
    usable = [c["id"] for c in clips if c.get("usable", True)]
    return ai.Matching(assignments=[ai.Assignment(segment=s["i"], clip_ids=[usable[(s["i"] * 2) % len(usable)]]) for s in segs])


def fake_speak(text, out_mp3, voice_id=None, model_id=None):
    ws = text.split()
    dur = 0.4 * len(ws) + 0.6
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={dur:.2f}",
                    "-c:a", "libmp3lame", str(out_mp3)], check=True)
    return [[0.3 + 0.4 * i, 0.3 + 0.4 * i + 0.34, w] for i, w in enumerate(ws)]


ai.describe_clips, ai.write_build_script, ai.match_clips, voice.speak = fake_describe, fake_script, fake_match, fake_speak


def wait(job_id):
    t0 = time.time()
    while time.time() - t0 < 900:
        j = jobs.load(job_id)
        if j["status"] in ("done", "error") and j["ads"][0]["status"] in ("done", "error"):
            return j
        time.sleep(2)
    return jobs.load(job_id)


jobs.start_worker()
job = jobs.create_build({"url": "", "urls": [], "count": 1, "language": "Danish", "brand": "", "offer": "",
                         "safe_claims": True, "product": "Glow board", "script": ""}, FILES)
j = wait(job["id"])
a = j["ads"][0]
print(a["status"], a.get("error"), a.get("output"), "| clips:", len(a["clips"]), "| cuts:", len(a.get("cuts") or []))
ok = a["status"] == "done" and len(a["footage"]) == 2 and len(a["clips"]) >= 5
out1 = a.get("output")
ok &= bool(out1) and (JOBS_DIR / j["id"] / out1).exists()
ok &= all(c["clip"] != 1 for c in a["cuts"])                       # the unusable clip is never used
ok &= a["plan"]["voiceover"] == SCRIPT and len(a["beats"]) == 4

# "New script, new ad": clips are reused (no second describe), script is rewritten
jobs.queue_rerender(j["id"], 0, {"new_script": True})
time.sleep(1)
j = wait(j["id"])
a = j["ads"][0]
print(a["status"], a.get("error"), a.get("output"), "| scripts:", len(a["scripts"]))
ok &= a["status"] == "done" and a["output"] != out1 and calls == {"describe": 1, "script": 2}
ok &= a["plan"]["voiceover"].startswith("Ny vinkel") and len(a["scripts"]) == 2
print("JOB DIR:", JOBS_DIR / j["id"])
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
