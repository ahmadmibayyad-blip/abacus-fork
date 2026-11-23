"""Offline test of "Generate new ad". Claude, ElevenLabs, Higgsfield and Gemini are stubbed;
the job logic, montage and HyperFrames render run for real.

    python tests/generate_test.py
"""
import base64
import io
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["CLONER_DATA"] = tempfile.mkdtemp(prefix="cloner-gen-")
os.environ["CLONER_SETTINGS"] = os.path.join(os.environ["CLONER_DATA"], "settings.json")
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
from PIL import Image  # noqa: E402

from cloner import ai, config, gen, jobs, voice  # noqa: E402
from cloner.config import JOBS_DIR  # noqa: E402


def jpg(color) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (540, 960), color).save(b, "JPEG")
    return b.getvalue()


# ---------- 1. the request code, against fake HTTP ----------
config.save({"HIGGSFIELD_KEY_ID": "kid", "HIGGSFIELD_KEY_SECRET": "sec", "GEMINI_API_KEY": "gk"})
calls = []
state = {"polls": 0}


def fake_request(method, url, **kw):
    calls.append((method, url, kw))
    req = httpx.Request(method, url)
    if url.endswith("/files/generate-upload-url"):
        return httpx.Response(200, json={"public_url": "https://cdn/in.jpg", "upload_url": "https://store/put",
                                         "upload_headers": {"Content-Type": "image/jpeg", "x-amz-tagging": "t"}}, request=req)
    if url == "https://store/put":
        return httpx.Response(200, request=req)
    if "/estimate/" in url:
        return httpx.Response(200, json={"usd": "0.12"}, request=req)
    if url.endswith("/status"):
        state["polls"] += 1
        if state["polls"] < 2:
            return httpx.Response(200, json={"status": "in_progress"}, request=req)
        return httpx.Response(200, json={"status": "completed", "video": {"url": "https://cdn/out.mp4"}}, request=req)
    if "generativelanguage" in url:
        return httpx.Response(200, json={"id": "x", "steps": [{"content": [{"type": "text", "text": "ok"}, {
            "type": "image", "mime_type": "image/jpeg", "data": base64.b64encode(jpg("red")).decode()}]}]}, request=req)
    return httpx.Response(200, json={"status": "queued", "request_id": "r1"}, request=req)


real_request, real_sleep = httpx.request, time.sleep
httpx.request = fake_request
gen.time.sleep = lambda s: None
tmp = Path(os.environ["CLONER_DATA"])
(tmp / "p.jpg").write_bytes(jpg("teal"))

assert gen.hf_upload(tmp / "p.jpg") == "https://cdn/in.jpg"
put = [c for c in calls if c[0] == "PUT"][0]
assert put[2]["headers"]["x-amz-tagging"] == "t" and "Authorization" not in put[2]["headers"]   # no key sent to storage
assert gen.hf_estimate("xai/grok-imagine-image-2.0", {"prompt": "x"}) == 0.12
st = gen.hf_run(config.get("HF_VIDEO_MODEL"), gen.video_body("move", "https://cdn/in.jpg", 5))
sub = [c for c in calls if c[1].endswith("/reference-to-video")][0]
assert sub[2]["headers"]["Authorization"] == "Key kid:sec" and sub[2]["headers"]["Idempotency-Key"]
assert sub[2]["json"] == {"prompt": "move", "image_url": "https://cdn/in.jpg", "duration": 5,
                          "resolution": "720p", "aspect_ratio": "9:16"}, sub[2]["json"]
assert gen._first_url(st, ("video", "videos")) == "https://cdn/out.mp4" and state["polls"] == 2
out = gen._gemini_image("a photo", [tmp / "p.jpg"], tmp / "g.jpg")
g = [c for c in calls if "generativelanguage" in c[1]][0][2]
assert g["headers"]["x-goog-api-key"] == "gk" and g["json"]["model"] == "gemini-nano-banana-2.1"
assert g["json"]["input"][1]["type"] == "image" and g["json"]["response_format"]["aspect_ratio"] == "9:16"
assert Image.open(out).size == (540, 960)
assert config.get("IMAGE_PROVIDER") == "higgsfield" and gen.missing_keys() == []
assert gen.hf_credential() == "kid:sec"
config.save({"HIGGSFIELD_KEY_ID": "Key abc:xyz", "HIGGSFIELD_KEY_SECRET": ""})
assert gen.hf_credential() == "abc:xyz" and gen.missing_keys() == []          # one combined string
config.save({"HIGGSFIELD_KEY_ID": "abc"})
assert gen.missing_keys() == ["Higgsfield API key and secret"]                 # key without its secret
config.save({"HIGGSFIELD_KEY_ID": "kid", "HIGGSFIELD_KEY_SECRET": "sec"})
for status, expect in ((402, "balance"), (401, "API key")):
    httpx.request = lambda m, u, **kw: httpx.Response(status, json={}, request=httpx.Request(m, u))
    try:
        gen.hf_run("x/y", {})
        raise AssertionError("no error")
    except gen.GenError as e:
        assert expect in str(e), str(e)
httpx.request = real_request
gen.time.sleep = real_sleep
print("request code OK")

# ---------- 2. the whole job, with the services stubbed ----------
made = {"image": 0, "video": 0, "speak": 0, "script": 0, "shots": 0}
COLORS = ["navy", "teal", "maroon", "olive", "purple", "gray", "orange"]


def fake_image(prompt, refs, ref_urls, dest):
    made["image"] += 1
    Image.new("RGB", (540, 960), COLORS[made["image"] % len(COLORS)]).save(dest)
    return dest


def fake_video(prompt, image_url, duration, dest, on_wait=None):
    made["video"] += 1
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=s=360x640:d={duration}:r=30",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(dest)], check=True)
    return dest


def fake_script(product, photos, script, previous, opts):
    made["script"] += 1
    assert photos, "product photos must reach Claude"
    vo = script or f"Variant {len(previous) + 1}. Stoffet er blødt. Høj talje. Bestil i dag."
    return ai.BuildScript(voiceover=vo, ad_copy=ai.AdCopy(primary_text="Ny", headline="H", description="D", cta="Shop nu"),
                          end_card_lines=["LEGGINGS", "Bestil i dag"], end_card_cta="SHOP NU", changes=[])


def fake_shots(segs, product, photos, opts):
    made["shots"] += 1
    return ai.ShotList(shots=[ai.Shot(segment=s["i"], image_prompt=f"photo for beat {s['i']}", motion_prompt="slow move",
                                      shows_product=s["i"] != 0) for s in segs])


def fake_speak(text, out_mp3, voice_id=None, model_id=None):
    made["speak"] += 1
    ws = text.split()
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={0.45 * len(ws) + 0.6:.2f}",
                    "-c:a", "libmp3lame", str(out_mp3)], check=True)
    return [[0.3 + 0.45 * i, 0.3 + 0.45 * i + 0.38, w] for i, w in enumerate(ws)]


gen.image, gen.video, gen.hf_upload = fake_image, fake_video, lambda p: "https://cdn/" + Path(p).name
gen.hf_estimate = lambda model, body: 0.10
ai.write_gen_script, ai.plan_shots, voice.speak = fake_script, fake_shots, fake_speak


def wait(job_id):
    t0 = time.time()
    while time.time() - t0 < 900:
        j = jobs.load(job_id)
        if j["status"] in ("done", "error") and all(a["status"] in ("done", "error") for a in j["ads"]):
            return j
        time.sleep(2)
    return jobs.load(job_id)


jobs.start_worker()
opts = {"url": "", "urls": [], "count": 2, "language": "Danish", "brand": "", "offer": "", "safe_claims": True,
        "product": "3D leggings", "script": "", "caption_style": "bold_upper"}
job = jobs.create_generate(dict(opts), [("a.jpg", jpg("teal")), ("b.png", jpg("teal")), ("notes.txt", b"x")], 2)
j = wait(job["id"])
ok = j["status"] == "done" and len(j["ads"]) == 2
for a in j["ads"]:
    print(a["status"], a.get("error"), a.get("output"), "| shots:", len(a["shots"]), "| est $", a.get("est_usd"))
    ok &= a["status"] == "done" and bool(a.get("output")) and (JOBS_DIR / j["id"] / a["output"]).exists()
    ok &= len(a["shots"]) == 4 and all(sh["image"] and sh["clip"] for sh in a["shots"])
ok &= j["ads"][0]["plan"]["voiceover"] != j["ads"][1]["plan"]["voiceover"]          # variations differ
ok &= made == {"image": 8, "video": 8, "speak": 2, "script": 2, "shots": 2}
print(made)

# redo one shot with a new description: only that shot is generated again, the voiceover is kept
a0 = j["ads"][0]
old_out, old_img = a0["output"], a0["shots"][2]["image"]
jobs.queue_rerender(j["id"], 0, {"voiceover": a0["plan"]["voiceover"], "shot_prompts": {"2": "a different photo"},
                                  "regen_shots": [], "caption_style": "clean"})
time.sleep(1)
j = wait(j["id"])
a0 = j["ads"][0]
print(a0["status"], a0.get("error"), "| redo:", made)
ok &= a0["status"] == "done" and a0["output"] != old_out and a0["shots"][2]["image"] != old_img
ok &= a0["shots"][2]["image_prompt"] == "a different photo" and a0["plan"]["captions"]["style"] == "clean"
ok &= made == {"image": 9, "video": 9, "speak": 2, "script": 2, "shots": 2}

# cost limit: nothing is generated when the estimate is above the limit
config.save({"GEN_MAX_USD": "0.05"})
job2 = jobs.create_generate(dict(opts, count=1), [("a.jpg", jpg("teal"))], 1)
j2 = wait(job2["id"])
a = j2["ads"][0]
print(a["status"], (a.get("error") or "")[:70])
ok &= a["status"] == "error" and "above your limit" in a["error"] and made["image"] == 9 and made["video"] == 9
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
