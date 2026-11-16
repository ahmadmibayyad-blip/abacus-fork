"""Offline end-to-end test: stubs the three paid APIs (Apify, Claude, ElevenLabs) and runs
the real pipeline (ffmpeg, image text replacement, HyperFrames render) on generated media.

    python tests/smoke_test.py
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["CLONER_DATA"] = tempfile.mkdtemp(prefix="cloner-test-")
os.environ["CLONER_SETTINGS"] = os.path.join(os.environ["CLONER_DATA"], "settings.json")
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from cloner import ai, fonts, jobs, sources, voice  # noqa: E402
from cloner.config import JOBS_DIR  # noqa: E402

work = Path(os.environ["CLONER_DATA"]) / "fixtures"
work.mkdir(parents=True)

# --- fixtures: a 9:16 video with a burned-in caption, and a square image ad with text ---
VIDEO = work / "src.mp4"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=360x640:d=8:r=30",
                "-f", "lavfi", "-i", "sine=frequency=300:duration=8",
                "-vf", "drawbox=x=60:y=390:w=240:h=50:color=black@0.0:t=fill,"
                       "drawtext=text='TU COMMANDES':x=(w-tw)/2:y=400:fontsize=30:fontcolor=white:borderw=3",
                "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(VIDEO)], check=True)
IMAGE = work / "src.jpg"
im = Image.new("RGB", (1080, 1080), (181, 210, 204))
d = ImageDraw.Draw(im)
d.rectangle([60, 200, 480, 1000], fill=(20, 120, 110))
d.text((600, 120), "LEGGING", font=ImageFont.truetype(str(fonts.path("bold")), 90), fill="#141414")
d.text((600, 860), "1 ACHETÉ", font=ImageFont.truetype(str(fonts.path("black")), 80), fill="#141414")
im.save(IMAGE, quality=92)

# --- stubs ---
ADS = [
    {"ad_id": "111", "page_name": "Src", "start_date": "", "kind": "video", "media_url": "video",
     "copy": {"primary_text": "Deux leggings pour le prix d'un", "headline": "Legging", "description": "", "cta": "Shop now"},
     "library_url": "https://www.facebook.com/ads/library/?id=111"},
    {"ad_id": "222", "page_name": "Src", "start_date": "", "kind": "image", "media_url": "image",
     "copy": {"primary_text": "1 acheté, 1 offert", "headline": "Legging", "description": "", "cta": "Shop now"},
     "library_url": "https://www.facebook.com/ads/library/?id=222"},
]
sources.fetch_ads = lambda url, n, raw_path=None: ADS[:n]
sources.fetch_single_ads = lambda ids, raw_path=None: {i: dict(ADS[1], ad_id=i) for i in ids if i == "1139014535679515"}
sources.download = lambda url, dest: dest.write_bytes((VIDEO if url == "video" else IMAGE).read_bytes()) or dest
voice.transcribe = lambda p: {"language": "fr", "text": "Tu commandes un legging, on t'en envoie un deuxième gratuit.", "words": []}


def fake_speak(text, out_mp3, voice_id=None, model_id=None):
    words = text.split()
    dur = 0.32 * len(words) + 0.6
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={dur:.2f}",
                    "-c:a", "libmp3lame", str(out_mp3)], check=True)
    return [[0.3 + 0.32 * i, 0.3 + 0.32 * i + 0.28, w] for i, w in enumerate(words)]


voice.speak = fake_speak
ai.plan_video = lambda transcript, frames, copy, dur, opts: ai.VideoPlan(
    source_language="fr",
    voiceover="Lige nu: Bestiller du én legging, får du en ekstra helt gratis. Linket er lige her nedenfor.",
    ad_copy=ai.AdCopy(primary_text="To leggings til prisen for én ✨", headline="3D-leggings", description="Kun i dag 🔥", cta="Shop nu"),
    captions=ai.CaptionBox(present=True, x_pct=15, y_pct=60, w_pct=70, h_pct=9, style="bold_upper", highlight_color="#ff8bc3"),
    end_card_lines=["KØB 1", "FÅ 1 GRATIS", "Gratis fragt"], end_card_cta="SHOP NU", changes=["Removed brand name"])
ai.plan_image = lambda image, w, h, copy, opts: ai.ImagePlan(
    blocks=[ai.TextBlock(original="LEGGING", translated="3D LEGGINGS", x0=int(590 * w / 1080), y0=int(125 * h / 1080),
                         x1=int(1040 * w / 1080), y1=int(230 * h / 1080), color="#141414", weight="bold", align="left", uppercase=True),
            ai.TextBlock(original="1 ACHETÉ", translated="KØB 1", x0=int(590 * w / 1080), y0=int(870 * h / 1080),
                         x1=int(1000 * w / 1080), y1=int(960 * h / 1080), color="#141414", weight="black", align="left", uppercase=True)],
    ad_copy=ai.AdCopy(primary_text="Køb 1, få 1 gratis", headline="3D-leggings", description="Kun i dag", cta="Shop nu"),
    changes=[])

# --- run ---
jobs.start_worker()
job = jobs.create_from_library({"urls": ["https://www.facebook.com/ads/library/?view_all_page_id=1",
                                         "https://www.facebook.com/ads/library/?id=1139014535679515",
                                         "https://www.facebook.com/ads/library/?id=1000000000000001"],
                                "count": 1, "language": "Danish", "brand": "", "offer": "", "safe_claims": True})
t0 = time.time()
while time.time() - t0 < 900:
    j = jobs.load(job["id"])
    if j["status"] in ("done", "error"):
        break
    time.sleep(2)
j = jobs.load(job["id"])
print(json.dumps({k: j[k] for k in ("status", "error", "step")}, indent=1))
ok = j["status"] == "done" and len(j["ads"]) == 3
for a in j["ads"]:
    print(a["idx"], a["kind"], a["status"], a.get("error"), a.get("output"))
for a in j["ads"][:2]:   # page link (top 1 = video) + found single ad (image)
    ok &= a["status"] == "done" and bool(a.get("output")) and (JOBS_DIR / j["id"] / a["output"]).exists()
ok &= j["ads"][2]["status"] == "error" and "not found" in (j["ads"][2]["error"] or "")   # missing single ad
print("JOB DIR:", JOBS_DIR / j["id"])
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
