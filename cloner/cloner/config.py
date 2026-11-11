"""Paths and settings. Keys come from the environment, a .env file, or settings.json
(written by the Settings tab). Nothing here leaves the machine."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # cloner/ project dir
DATA = Path(os.environ.get("CLONER_DATA", ROOT / "data"))
JOBS_DIR = DATA / "jobs"
FONTS_DIR = ROOT / "assets" / "fonts"
SETTINGS_FILE = ROOT / "settings.json"
STATIC = Path(__file__).resolve().parent / "static"

JOBS_DIR.mkdir(parents=True, exist_ok=True)
FONTS_DIR.mkdir(parents=True, exist_ok=True)

KEYS = ["ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY", "APIFY_TOKEN",
        "ELEVENLABS_VOICE_ID", "ELEVENLABS_MODEL_ID", "CLAUDE_MODEL"]
SECRET_KEYS = {"ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY", "APIFY_TOKEN"}

DEFAULTS = {
    "ELEVENLABS_VOICE_ID": "jL9zCPolQd2Uh8OUGEk3",
    "ELEVENLABS_MODEL_ID": "eleven_multilingual_v2",
    "CLAUDE_MODEL": "claude-opus-5-5",
}


def _dotenv() -> dict:
    out = {}
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _saved() -> dict:
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def get(key: str) -> str:
    """settings.json > environment > .env > default."""
    for src in (_saved(), os.environ, _dotenv()):
        v = src.get(key)
        if v:
            return v
    return DEFAULTS.get(key, "")


def save(values: dict) -> None:
    cur = _saved()
    for k, v in values.items():
        if k in KEYS and v is not None:
            if v == "":
                cur.pop(k, None)
            else:
                cur[k] = v
    SETTINGS_FILE.write_text(json.dumps(cur, indent=2))
    try:
        os.chmod(SETTINGS_FILE, 0o600)
    except OSError:
        pass


def public_view() -> dict:
    """What the UI may see: secrets only as set/unset."""
    out = {}
    for k in KEYS:
        v = get(k)
        out[k] = ("set" if v else "") if k in SECRET_KEYS else v
    return out
