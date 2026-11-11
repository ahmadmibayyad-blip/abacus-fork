"""Poppins (SIL Open Font License) is used for image text and video captions.
Taken from the npm package @expo-google-fonts/poppins (installed by `npm install`),
falling back to a one-time download from the Google Fonts GitHub repo."""
from __future__ import annotations

import shutil
from pathlib import Path

import httpx

from .config import FONTS_DIR, ROOT

WEIGHTS = {"regular": ("Regular", "400Regular"), "medium": ("Medium", "500Medium"), "bold": ("Bold", "700Bold"),
           "extrabold": ("ExtraBold", "800ExtraBold"), "black": ("Black", "900Black")}
NPM_DIR = ROOT / "node_modules" / "@expo-google-fonts" / "poppins"
GH = "https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-{}.ttf"


class FontError(RuntimeError):
    pass


def path(weight: str) -> Path:
    name, npm = WEIGHTS.get(weight, WEIGHTS["regular"])
    dest = FONTS_DIR / f"Poppins-{name}.ttf"
    if dest.exists() and dest.stat().st_size > 10000:
        return dest
    npm_file = NPM_DIR / npm / f"Poppins_{npm}.ttf"
    if npm_file.exists():
        shutil.copy(npm_file, dest)
        return dest
    try:
        r = httpx.get(GH.format(name), follow_redirects=True, timeout=60)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise FontError("Poppins font missing: run `npm install` in the cloner folder.") from e
    dest.write_bytes(r.content)
    return dest
