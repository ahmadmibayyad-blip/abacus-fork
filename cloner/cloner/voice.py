"""ElevenLabs: speech-to-text for the source ad, text-to-speech (with timings) for the clone."""
from __future__ import annotations

import base64
from pathlib import Path

import httpx

from . import config

API = "https://api.elevenlabs.io/v1"


class VoiceError(RuntimeError):
    pass


def _key() -> str:
    k = config.get("ELEVENLABS_API_KEY")
    if not k:
        raise VoiceError("ELEVENLABS_API_KEY is not set (Settings tab).")
    return k


def _explain(step: str, r: httpx.Response) -> str:
    """Turn ElevenLabs account errors into something actionable."""
    detail = {}
    try:
        detail = (r.json() or {}).get("detail") or {}
    except ValueError:
        pass
    if not isinstance(detail, dict):
        detail = {"message": str(detail)}
    code = f"{detail.get('type', '')} {detail.get('code', '')} {detail.get('status', '')}"
    msg = detail.get("message") or r.text[:300]
    if "payment" in code:
        return ("ElevenLabs blocked the request: your subscription has a failed or unpaid invoice. "
                "Pay it at elevenlabs.io/app/subscription, then press Re-render. (" + msg + ")")
    if "quota" in code or "credits" in code:
        return "ElevenLabs credits are used up for this billing period (elevenlabs.io/app/subscription). (" + msg + ")"
    if "key id" in msg.lower() or "sk_" in msg:
        return ("The ElevenLabs value in Settings is a Key ID, not the API key. Paste the secret key that starts "
                "with sk_ (elevenlabs.io/app/settings/api-keys), then press Re-render.")
    if r.status_code == 401:
        return "ElevenLabs rejected the API key; paste it again on the Settings tab. (" + msg + ")"
    if "voice_not_found" in code or r.status_code == 404:
        return "ElevenLabs could not find that voice ID in your account. (" + msg + ")"
    return f"ElevenLabs {step} failed ({r.status_code}): {msg}"


def _send(method: str, url: str, **kw) -> httpx.Response:
    try:
        return httpx.request(method, url, **kw)
    except httpx.HTTPError as e:
        raise VoiceError(f"Could not reach ElevenLabs ({type(e).__name__}). Check your internet connection.") from e


def transcribe(audio: Path) -> dict:
    """Return {"language": code, "text": str, "words": [[start, end, word], ...]}."""
    with open(audio, "rb") as f:
        r = _send("POST", f"{API}/speech-to-text", headers={"xi-api-key": _key()},
                       data={"model_id": "scribe_v1", "timestamps_granularity": "word"},
                       files={"file": (audio.name, f, "audio/wav")}, timeout=300)
    if r.status_code >= 400:
        raise VoiceError(_explain("speech-to-text", r))
    d = r.json()
    words = [[w.get("start", 0), w.get("end", 0), w.get("text", "")]
             for w in d.get("words", []) if w.get("type", "word") == "word"]
    return {"language": d.get("language_code", ""), "text": d.get("text", ""), "words": words}


def speak(text: str, out_mp3: Path, voice_id: str | None = None, model_id: str | None = None) -> list:
    """Synthesize `text`, write mp3, return word timings [[start, end, word], ...]."""
    voice_id = voice_id or config.get("ELEVENLABS_VOICE_ID")
    model_id = model_id or config.get("ELEVENLABS_MODEL_ID")
    r = _send("POST", f"{API}/text-to-speech/{voice_id}/with-timestamps",
                   params={"output_format": "mp3_44100_128"},
                   headers={"xi-api-key": _key()},
                   json={"text": text, "model_id": model_id}, timeout=300)
    if r.status_code >= 400:
        raise VoiceError(_explain("text-to-speech", r))
    d = r.json()
    out_mp3.write_bytes(base64.b64decode(d["audio_base64"]))
    al = d.get("alignment") or d.get("normalized_alignment") or {}
    return chars_to_words(al.get("characters", []), al.get("character_start_times_seconds", []),
                          al.get("character_end_times_seconds", []))


def chars_to_words(chars, starts, ends) -> list:
    words, cur, s, e = [], "", None, None
    for ch, cs, ce in zip(chars, starts, ends):
        if ch.isspace():
            if cur:
                words.append([s, e, cur])
            cur, s, e = "", None, None
            continue
        if s is None:
            s = cs
        cur += ch
        e = ce
    if cur:
        words.append([s, e, cur])
    return words


def list_voices() -> list[dict]:
    """Voices in the user's ElevenLabs account: [{voice_id, name, preview_url, labels}]."""
    r = _send("GET", f"{API}/voices", headers={"xi-api-key": _key()}, timeout=30)
    if r.status_code >= 400:
        raise VoiceError(_explain("voice list", r))
    out = []
    for v in r.json().get("voices", []):
        lab = v.get("labels") or {}
        out.append({"voice_id": v.get("voice_id"), "name": v.get("name") or "",
                    "preview_url": v.get("preview_url") or "",
                    "labels": " · ".join(str(lab[k]) for k in ("language", "gender", "accent", "age") if lab.get(k))})
    return sorted(out, key=lambda v: v["name"].lower())
