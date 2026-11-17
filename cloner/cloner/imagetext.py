"""Replace overlaid text on a static image ad: paint over each original text box with
the surrounding background, then draw the translated text fitted into the same box."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import fonts


def _erase(a: np.ndarray, x0: int, y0: int, x1: int, y1: int, m: int = 6) -> None:
    """Fill the box from its border pixels. Flat or gradient backgrounds come out clean;
    busy (photo) backgrounds get a blurred patch instead."""
    h, w = a.shape[:2]
    x0, y0 = max(x0, m), max(y0, m)
    x1, y1 = min(x1, w - m), min(y1, h - m)
    if x1 <= x0 or y1 <= y0:
        return
    top = a[y0 - m:y0, x0:x1].mean(0)
    bot = a[y1:y1 + m, x0:x1].mean(0)
    left = a[y0:y1, x0 - m:x0].mean(1)
    right = a[y0:y1, x1:x1 + m].mean(1)
    border = np.concatenate([a[y0 - m:y0, x0:x1].reshape(-1, 3), a[y1:y1 + m, x0:x1].reshape(-1, 3),
                             a[y0:y1, x0 - m:x0].reshape(-1, 3), a[y0:y1, x1:x1 + m].reshape(-1, 3)])
    busy = border.std(0).mean() > 28
    bh, bw = y1 - y0, x1 - x0
    ty = np.linspace(0, 1, bh)[:, None, None]
    tx = np.linspace(0, 1, bw)[None, :, None]
    vert = (1 - ty) * top[None] + ty * bot[None]
    horiz = (1 - tx) * left[:, None] + tx * right[:, None]
    a[y0:y1, x0:x1] = (vert + horiz) / 2
    if busy:  # soften so the patch blends into photo areas
        pad = 4
        patch = Image.fromarray(a[y0 - pad:y1 + pad, x0 - pad:x1 + pad].clip(0, 255).astype("uint8"))
        patch = patch.filter(ImageFilter.GaussianBlur(6))
        a[y0 - pad:y1 + pad, x0 - pad:x1 + pad] = np.asarray(patch, dtype=float)


def _fit_font(draw, text: str, weight: str, box_w: int, box_h: int):
    size = max(int(box_h / max(text.count("\n") + 1, 1) * 0.92), 10)
    while size > 9:
        font = ImageFont.truetype(str(fonts.path(weight)), size)
        l, t, r, b = draw.multiline_textbbox((0, 0), text, font=font, spacing=int(size * 0.12), align="center")
        if r - l <= box_w and b - t <= box_h:
            return font, (r - l, b - t, l, t)
        size -= 2
    font = ImageFont.truetype(str(fonts.path(weight)), 10)
    l, t, r, b = draw.multiline_textbbox((0, 0), text, font=font)
    return font, (r - l, b - t, l, t)


def render(src: Path, dst: Path, blocks: list[dict]) -> Path:
    im = Image.open(src).convert("RGB")
    a = np.asarray(im, dtype=float).copy()
    pad = max(4, int(min(im.size) * 0.012))   # Claude's boxes can be a little tight
    for b in blocks:
        _erase(a, int(b["x0"]) - pad, int(b["y0"]) - pad, int(b["x1"]) + pad, int(b["y1"]) + pad)
    im = Image.fromarray(a.clip(0, 255).astype("uint8"))
    d = ImageDraw.Draw(im)
    for b in blocks:
        text = b["translated"].upper() if b.get("uppercase") else b["translated"]
        x0, y0, x1, y1 = int(b["x0"]), int(b["y0"]), int(b["x1"]), int(b["y1"])
        bw, bh = max(x1 - x0, 10), max(y1 - y0, 10)
        font, (tw, th, ol, ot) = _fit_font(d, text, b.get("weight", "regular"), bw, bh)
        align = b.get("align", "center")
        if align == "left":
            x = x0
        elif align == "right":
            x = x1 - tw
        else:
            x = x0 + (bw - tw) / 2
        y = y0 + (bh - th) / 2
        d.multiline_text((x - ol, y - ot), text, font=font, fill=b.get("color") or "#111111",
                         align=align, spacing=int(font.size * 0.12))
    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst, quality=92)
    return dst
