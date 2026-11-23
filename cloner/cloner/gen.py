"""Generate new visuals instead of reusing a competitor's footage.

Images: Google Gemini image models ("Nano Banana") or a Higgsfield image model.
Videos: a Higgsfield image-to-video model (default: Grok Imagine Video 1.5).

Higgsfield API (docs.higgsfield.ai): POST https://api.higgsfield.ai/<model path> with
"Authorization: Key <id>:<secret>", then poll /requests/<id>/status. Local files go through
/files/generate-upload-url. Costs come out of the Higgsfield Console balance (USD), which
is separate from the credits of the Higgsfield web app.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import time
import uuid
from pathlib import Path

import httpx

from . import config

HF = "https://api.higgsfield.ai"
GEMINI = "https://generativelanguage.googleapis.com/v1beta/interactions"
GEMINI_REVISION = "2026-05-20"


class GenError(RuntimeError):
    pass


def _json_setting(key: str) -> dict:
    raw = config.get(key)
    if not raw:
        return {}
    try:
        v = json.loads(raw)
    except json.JSONDecodeError as e:
        raise GenError(f"{key} in Settings is not valid JSON.") from e
    if not isinstance(v, dict):
        raise GenError(f"{key} in Settings must be a JSON object.")
    return v


def _hf_headers() -> dict:
    kid, sec = config.get("HIGGSFIELD_KEY_ID").strip(), config.get("HIGGSFIELD_KEY_SECRET").strip()
    if not kid or not sec:
        raise GenError("Higgsfield API key ID and secret are not set (Settings tab). "
                       "Create them at console.higgsfield.ai.")
    return {"Authorization": f"Key {kid}:{sec}", "Content-Type": "application/json"}


def _req(method: str, url: str, what: str, **kw) -> httpx.Response:
    try:
        r = httpx.request(method, url, **kw)
    except httpx.HTTPError as e:
        raise GenError(f"Could not reach {what} ({type(e).__name__}).") from e
    if r.status_code in (401, 403):
        raise GenError(f"{what} rejected the API key ({r.status_code}). Check it on the Settings tab.")
    if r.status_code == 402:
        raise GenError(f"{what}: not enough balance. Add funds, then press Re-render.")
    if r.status_code >= 400:
        raise GenError(f"{what} error {r.status_code}: {r.text[:300]}")
    return r


# ---------- Higgsfield ----------

def hf_upload(path: Path) -> str:
    """Upload a local file; returns a public URL usable as image_url / image_urls."""
    ctype = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    up = _req("POST", f"{HF}/files/generate-upload-url", "Higgsfield", headers=_hf_headers(),
              json={"content_type": ctype}, timeout=60).json()
    headers = up.get("upload_headers") or {"Content-Type": ctype}
    _req("PUT", up["upload_url"], "Higgsfield upload", headers=headers, content=path.read_bytes(), timeout=300)
    return up["public_url"]


def hf_estimate(model: str, body: dict) -> float | None:
    """USD estimate for one request, or None when the estimate endpoint has no answer."""
    try:
        r = _req("POST", f"{HF}/estimate/{model.strip('/')}", "Higgsfield", headers=_hf_headers(),
                 json=body, timeout=60)
        return float(r.json().get("usd"))
    except (GenError, TypeError, ValueError):
        return None


def hf_run(model: str, body: dict, timeout_s: int = 900, on_wait=None) -> dict:
    """Submit a generation and wait for it. Returns the final status JSON."""
    headers = dict(_hf_headers(), **{"Idempotency-Key": str(uuid.uuid4())})
    sub = _req("POST", f"{HF}/{model.strip('/')}", "Higgsfield", headers=headers, json=body, timeout=120).json()
    rid = sub.get("request_id")
    if not rid:
        raise GenError(f"Higgsfield did not return a request id: {str(sub)[:200]}")
    t0, delay = time.time(), 3.0
    while True:
        st = _req("GET", f"{HF}/requests/{rid}/status", "Higgsfield", headers=_hf_headers(), timeout=60).json()
        status = (st.get("status") or "").lower()
        if status == "completed":
            return st
        if status == "nsfw":
            raise GenError("Higgsfield's content filter blocked this shot. Edit its prompt and regenerate it.")
        if status in ("failed", "canceled", "cancelled"):
            raise GenError(f"Higgsfield generation {status}: {str(st.get('error') or st)[:200]}")
        if time.time() - t0 > timeout_s:
            raise GenError("Higgsfield took too long; press Re-render to try again.")
        if on_wait:
            on_wait()
        time.sleep(delay)
        delay = min(delay * 1.3, 10)


def _first_url(st: dict, keys: tuple) -> str:
    for k in keys:
        v = st.get(k)
        if isinstance(v, dict) and v.get("url"):
            return v["url"]
        if isinstance(v, list) and v and isinstance(v[0], dict) and v[0].get("url"):
            return v[0]["url"]
    raise GenError(f"Higgsfield finished but returned no file: {str(st)[:200]}")


def _download(url: str, dest: Path) -> Path:
    with httpx.stream("GET", url, timeout=300, follow_redirects=True) as r:
        if r.status_code >= 400:
            raise GenError(f"Could not download the generated file ({r.status_code}).")
        with open(dest, "wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    return dest


# ---------- images ----------

def _find_image_b64(obj) -> str | None:
    """Gemini's Interactions response nests the image; find the first base64 image block."""
    if isinstance(obj, dict):
        if obj.get("type") == "image" and isinstance(obj.get("data"), str) and len(obj["data"]) > 200:
            return obj["data"]
        for v in obj.values():
            hit = _find_image_b64(v)
            if hit:
                return hit
    elif isinstance(obj, list):
        for v in obj:
            hit = _find_image_b64(v)
            if hit:
                return hit
    return None


def _gemini_image(prompt: str, refs: list[Path], dest: Path) -> Path:
    key = config.get("GEMINI_API_KEY").strip()
    if not key:
        raise GenError("Gemini API key is not set (Settings tab). Create one at aistudio.google.com.")
    inp = [{"type": "text", "text": prompt}]
    for p in refs[:4]:
        inp.append({"type": "image", "mime_type": mimetypes.guess_type(p.name)[0] or "image/jpeg",
                    "data": base64.b64encode(p.read_bytes()).decode()})
    body = {"model": config.get("GEMINI_IMAGE_MODEL"), "input": inp,
            "response_format": {"type": "image", "mime_type": "image/jpeg", "aspect_ratio": "9:16", "image_size": "1K"}}
    r = _req("POST", GEMINI, "Gemini", headers={"x-goog-api-key": key, "Content-Type": "application/json",
                                                 "Api-Revision": GEMINI_REVISION}, json=body, timeout=300)
    data = _find_image_b64(r.json())
    if not data:
        raise GenError(f"Gemini returned no image (it may have declined the prompt): {r.text[:200]}")
    dest.write_bytes(base64.b64decode(data))
    return dest


def image(prompt: str, refs: list[Path], ref_urls: list[str], dest: Path) -> Path:
    """One 9:16 still. `refs` are local product photos, `ref_urls` the same photos on Higgsfield."""
    if config.get("IMAGE_PROVIDER") == "gemini":
        return _gemini_image(prompt, refs, dest)
    body = dict({"prompt": prompt}, **_json_setting("HF_IMAGE_PARAMS"))
    if ref_urls:
        body["image_urls"] = ref_urls[:4]
    st = hf_run(config.get("HF_IMAGE_MODEL"), body, timeout_s=600)
    return _download(_first_url(st, ("images", "image")), dest)


# ---------- video ----------

def video_body(prompt: str, image_url: str, duration: int) -> dict:
    return dict({"prompt": prompt, "image_url": image_url, "duration": int(duration)}, **_json_setting("HF_VIDEO_PARAMS"))


def video(prompt: str, image_url: str, duration: int, dest: Path, on_wait=None) -> Path:
    """Animate a first frame (public URL) into a clip."""
    st = hf_run(config.get("HF_VIDEO_MODEL"), video_body(prompt, image_url, duration), on_wait=on_wait)
    return _download(_first_url(st, ("video", "videos")), dest)


def missing_keys() -> list[str]:
    need = ["HIGGSFIELD_KEY_ID", "HIGGSFIELD_KEY_SECRET"]
    if config.get("IMAGE_PROVIDER") == "gemini":
        need.append("GEMINI_API_KEY")
    return [k for k in need if not config.get(k)]
