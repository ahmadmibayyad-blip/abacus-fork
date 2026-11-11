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


def transcribe(audio: Path) -> dict:
    """Return {"language": code, "text": str, "words": [[start, end, word], ...]}."""
    with open(audio, "rb") as f:
        r = httpx.post(f"{API}/speech-to-text", headers={"xi-api-key": _key()},
                       data={"model_id": "scribe_v1", "timestamps_granularity": "word"},
                       files={"file": (audio.name, f, "audio/wav")}, timeout=300)
    if r.status_code >= 400:
        raise VoiceError(f"ElevenLabs speech-to-text failed ({r.status_code}): {r.text[:300]}")
    d = r.json()
    words = [[w.get("start", 0), w.get("end", 0), w.get("text", "")]
             for w in d.get("words", []) if w.get("type", "word") == "word"]
    return {"language": d.get("language_code", ""), "text": d.get("text", ""), "words": words}


def speak(text: str, out_mp3: Path, voice_id: str | None = None, model_id: str | None = None) -> list:
    """Synthesize `text`, write mp3, return word timings [[start, end, word], ...]."""
    voice_id = voice_id or config.get("ELEVENLABS_VOICE_ID")
    model_id = model_id or config.get("ELEVENLABS_MODEL_ID")
    r = httpx.post(f"{API}/text-to-speech/{voice_id}/with-timestamps",
                   params={"output_format": "mp3_44100_128"},
                   headers={"xi-api-key": _key()},
                   json={"text": text, "model_id": model_id}, timeout=300)
    if r.status_code >= 400:
        raise VoiceError(f"ElevenLabs text-to-speech failed ({r.status_code}): {r.text[:300]}")
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
