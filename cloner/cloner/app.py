"""Cloner web server: http://127.0.0.1:8765/"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel

from . import config, jobs, media, sources

app = FastAPI(title="Cloner")


@app.on_event("startup")
def _startup() -> None:
    jobs.start_worker()


class JobIn(BaseModel):
    url: str = ""                 # older single-link form
    urls: List[str] = []          # page links (top N each) and/or single-ad links (?id=...)
    count: int = 3
    language: str = "Danish"
    brand: str = ""
    offer: str = ""
    safe_claims: bool = True
    voice_id: str = ""
    model_id: str = ""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (config.STATIC / "index.html").read_text(encoding="utf-8")


@app.get("/api/health")
def health() -> dict:
    return {"tools": media.check_tools(), "settings": config.public_view(),
            "languages": list(jobs.LANGUAGES), "hyperframes_local": (config.ROOT / "node_modules" / ".bin" / "hyperframes").exists()}


@app.get("/api/settings")
def get_settings() -> dict:
    return config.public_view()


@app.post("/api/settings")
def post_settings(values: dict) -> dict:
    vals = {k: (v or "").strip() for k, v in values.items() if isinstance(v, str)}
    el = vals.get("ELEVENLABS_API_KEY")
    if el and not el.startswith("sk_"):
        raise HTTPException(400, "That ElevenLabs value is a Key ID, not the API key. Use the secret key that "
                                 "starts with sk_ (elevenlabs.io/app/settings/api-keys; it is shown once when "
                                 "the key is created).")
    an = vals.get("ANTHROPIC_API_KEY")
    if an and not an.startswith("sk-ant-"):
        raise HTTPException(400, "Anthropic API keys start with sk-ant- (platform.claude.com/settings/keys).")
    config.save(vals)
    return config.public_view()


@app.get("/api/jobs")
def list_jobs() -> list:
    return jobs.list_jobs()


@app.post("/api/jobs")
def create_job(body: JobIn) -> dict:
    if not 1 <= body.count <= 10:
        raise HTTPException(400, "Number of ads must be between 1 and 10.")
    if body.language not in jobs.LANGUAGES:
        raise HTTPException(400, "Unsupported language.")
    links = [u.strip() for u in (body.urls or [body.url]) if u.strip()]
    if not 1 <= len(links) <= 10:
        raise HTTPException(400, "Add between 1 and 10 Ad Library links.")
    try:
        sources.classify(links)
    except sources.SourceError as e:
        raise HTTPException(400, str(e)) from e
    missing = [k for k in ("APIFY_TOKEN", "ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY") if not config.get(k)]
    if missing:
        raise HTTPException(400, "Missing keys: " + ", ".join(missing) + " (Settings tab).")
    opts = body.model_dump()
    opts["urls"], opts["url"] = links, links[0]
    return jobs.create_from_library(opts)


@app.post("/api/jobs/upload")
async def create_upload_job(files: List[UploadFile] = File(...), language: str = Form("Danish"),
                            brand: str = Form(""), offer: str = Form(""), safe_claims: bool = Form(True),
                            voice_id: str = Form(""), model_id: str = Form("")) -> dict:
    if language not in jobs.LANGUAGES:
        raise HTTPException(400, "Unsupported language.")
    missing = [k for k in ("ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY") if not config.get(k)]
    if missing:
        raise HTTPException(400, "Missing keys: " + ", ".join(missing) + " (Settings tab).")
    data = [(f.filename or "upload", await f.read()) for f in files[:10]]
    opts = {"url": "", "count": len(data), "language": language, "brand": brand, "offer": offer,
            "safe_claims": safe_claims, "voice_id": voice_id, "model_id": model_id}
    return jobs.create_from_uploads(opts, data)


def _job_or_404(job_id: str) -> dict:
    if not (jobs.job_dir(job_id) / "job.json").exists() or "/" in job_id or ".." in job_id:
        raise HTTPException(404, "Job not found.")
    return jobs.load(job_id)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    return _job_or_404(job_id)


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str) -> dict:
    job = _job_or_404(job_id)
    if job["status"] in ("queued", "running"):
        raise HTTPException(409, "Job is still running.")
    jobs.delete(job_id)
    return {"ok": True}


class RerenderIn(BaseModel):
    voiceover: Optional[str] = None
    end_card_lines: Optional[List[str]] = None
    end_card_cta: Optional[str] = None
    blocks: Optional[list] = None
    ad_copy: Optional[dict] = None


@app.post("/api/jobs/{job_id}/ads/{idx}/rerender")
def rerender(job_id: str, idx: int, body: RerenderIn) -> dict:
    job = _job_or_404(job_id)
    if not 0 <= idx < len(job["ads"]):
        raise HTTPException(404, "Ad not found.")
    if job["ads"][idx]["status"] in ("queued", "running"):
        raise HTTPException(409, "This ad is already being processed.")
    try:
        jobs.queue_rerender(job_id, idx, body.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return jobs.load(job_id)


@app.get("/files/{job_id}/{path:path}")
def files(job_id: str, path: str):
    _job_or_404(job_id)
    root = jobs.job_dir(job_id).resolve()
    p = (root / path).resolve()
    if root not in p.parents or not p.is_file():
        raise HTTPException(404)
    return FileResponse(p)


def _copy_md(ad: dict) -> str:
    c = ad.get("ad_copy") or {}
    lines = [f"## Ad {ad['idx'] + 1} ({ad['kind']})", "",
             f"**Primary text**\n\n{c.get('primary_text', '')}", "",
             f"**Headline:** {c.get('headline', '')}", f"**Description:** {c.get('description', '')}",
             f"**CTA:** {c.get('cta', '')}", ""]
    if ad["kind"] == "video" and ad.get("plan"):
        lines += ["**Voiceover**", "", ad["plan"].get("voiceover", ""), ""]
    if ad.get("changes"):
        lines += ["**Changes from the original**", ""] + [f"- {x}" for x in ad["changes"]] + [""]
    return "\n".join(lines)


@app.get("/api/jobs/{job_id}/zip")
def zip_job(job_id: str):
    job = _job_or_404(job_id)
    root = jobs.job_dir(job_id)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        md = [f"# Cloner job {job_id}", "", f"Language: {job['input'].get('language')}", ""]
        for ad in job["ads"]:
            if ad.get("output"):
                src = root / ad["output"]
                z.write(src, f"ad{ad['idx'] + 1}_{job['input'].get('lang_code', '')}{src.suffix}")
            md.append(_copy_md(ad))
        z.writestr("ad_copy.md", "\n".join(md))
        z.writestr("job.json", json.dumps(job, indent=2, ensure_ascii=False))
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="cloner-{job_id}.zip"'})
