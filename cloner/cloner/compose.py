"""Build and render the HyperFrames composition for a video clone:
muted source footage, a blurred strip over the burned-in captions, new captions timed
to the new voiceover, and a closing offer card."""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from . import fonts
from .config import ROOT

HF_VERSION = "0.9.32"


class ComposeError(RuntimeError):
    pass


def _norm(t: str) -> str:
    return re.sub(r"[^\w]", "", t.lower())


def _chunks(words: list, maxw: int, maxc: int) -> list[list]:
    out, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= maxw or len(" ".join(c[2] for c in cur)) >= maxc or re.search(r"[.,!?:;]$", w[2]):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def _clean(w: str) -> str:
    return re.sub(r"[.,:;\"“”'’]+$", "", w).strip("\"'“”‘’")


def build(project: Path, *, src_video: Path, last_jpg: Path, vo_audio: Path, words: list,
          probe: dict, plan: dict, lang_code: str = "da") -> dict:
    """Write project/index.html (+ assets). `words` are [[start, end, word]] relative to
    the start of vo_audio. Returns timing info."""
    project.mkdir(parents=True, exist_ok=True)
    assets = project / "assets"
    assets.mkdir(exist_ok=True)
    shutil.copy(src_video, assets / "src.mp4")
    shutil.copy(last_jpg, assets / "last.jpg")
    shutil.copy(vo_audio, assets / ("vo" + vo_audio.suffix))
    for w in ("extrabold", "black", "medium"):
        shutil.copy(fonts.path(w), assets / fonts.path(w).name)

    W = 1080
    H = int(round(W * probe["height"] / max(probe["width"], 1) / 2) * 2) or 1920
    dur = probe["duration"]
    cap = plan["captions"]
    style = cap.get("style", "bold_upper")
    hl = cap.get("highlight_color") or "#ff8bc3"
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", hl) or hl.lower() in ("#ffffff", "#fff"):
        hl = "#ff8bc3"

    if cap.get("present"):
        bx = int(W * cap["x_pct"] / 100) - 10
        by = int(H * cap["y_pct"] / 100) - 10
        bw = int(W * cap["w_pct"] / 100) + 20
        bh = int(H * cap["h_pct"] / 100) + 20
        bx, by = max(bx, 0), max(by, 0)
        bw, bh = min(bw, W - bx), min(bh, H - by)
        cy = by + bh // 2
    else:
        bx = by = bw = bh = 0
        cy = int(H * 0.62)

    off = 0.15
    vo_end = (words[-1][1] if words else 0) + off
    end_t = round(vo_end + 0.25, 2)
    total = round(end_t + 2.8, 2)
    a_end = round(min(dur, end_t), 2)

    upper = style == "bold_upper"
    groups = _chunks(words, 3 if upper else 4, 16 if upper else 24)
    caps, anim = [], []
    for i, g in enumerate(groups):
        st = g[0][0] + off
        en = min((groups[i + 1][0][0] + off) if i + 1 < len(groups) else g[-1][1] + off + 0.4, end_t)
        if en <= st:
            continue
        ws = [html.escape(_clean(x[2])) for x in g]
        ws = [w for w in ws if w]
        if not ws:
            continue
        if upper:
            ws = [w.upper() for w in ws]
            if len(ws) > 1:
                k = max(range(len(ws)), key=lambda j: len(_norm(ws[j])))
                ws[k] = f'<span class="hl">{ws[k]}</span>'
        cid = f"c{i}"
        caps.append(f'<div id="{cid}" class="clip cap" data-start="{st:.2f}" data-duration="{en - st:.2f}" '
                    f'data-track-index="3"><span class="in">{" ".join(ws)}</span></div>')
        if upper:
            anim.append(f'tl.fromTo("#{cid} .in",{{scale:0.6,opacity:0}},{{scale:1,opacity:1,duration:0.14,ease:"back.out(2.5)"}},{st:.2f});')
        else:
            anim.append(f'tl.fromTo("#{cid} .in",{{y:14,opacity:0}},{{y:0,opacity:1,duration:0.18,ease:"power2.out"}},{st:.2f});')

    # end card
    lines = [l for l in (plan.get("end_card_lines") or []) if l.strip()][:4]
    end_divs = []
    for i, line in enumerate(lines):
        base = [170, 120, 70, 54][i]
        size = int(min(base, (W - 140) / (0.66 * max(len(line), 1))))
        color = hl if i == 1 else "#ffffff"
        end_divs.append(f'<div class="el" style="font-size:{size}px;color:{color}">{html.escape(line)}</div>')
    if plan.get("end_card_cta"):
        end_divs.append(f'<div class="cta">{html.escape(plan["end_card_cta"])}</div>')

    hold = ""
    band_hold = ""
    if dur < end_t - 0.05:
        hold = (f'<img id="hold" class="clip full" src="assets/last.jpg" data-start="{a_end}" '
                f'data-duration="{end_t - a_end:.2f}" data-track-index="0" />')
        band_hold = (f'<img id="band-h" src="assets/last.jpg" data-start="{a_end}" '
                     f'data-duration="{end_t - a_end:.2f}" data-track-index="2" />')

    if upper:
        capstyle = (".cap .in{font-family:'PopX';font-weight:800;font-size:%dpx;line-height:1.05;color:#fff;"
                    "text-transform:uppercase;text-shadow:0 0 6px #000,4px 4px 0 #000,-4px -4px 0 #000,4px -4px 0 #000,"
                    "-4px 4px 0 #000,0 5px 0 #000,0 -5px 0 #000,5px 0 0 #000,-5px 0 0 #000;}"
                    ".cap .hl{color:%s}") % (int(W * 0.07), hl)
    else:
        capstyle = (".cap .in{font-family:'PopM';font-weight:500;font-size:%dpx;color:#fff;"
                    "text-shadow:0 2px 8px rgba(0,0,0,.65),0 0 2px rgba(0,0,0,.8);}") % int(W * 0.054)

    band_html = ""
    band_css = ""
    if bw and bh:
        band_css = (f"#band{{position:absolute;left:{bx}px;top:{by}px;width:{bw}px;height:{bh}px;overflow:hidden;border-radius:28px}}\n"
                    f"#band video,#band img{{position:absolute;left:{-bx}px;top:{-by}px;width:{W}px;height:{H}px;object-fit:cover;"
                    f"filter:blur(26px) saturate(1.05);transform:scale(1.04);transform-origin:{bx + bw / 2}px {by + bh / 2}px}}")
        band_html = (f'<div id="band"><video id="band-v" src="assets/src.mp4" muted playsinline data-start="0" '
                     f'data-duration="{a_end}" data-track-index="2"></video>{band_hold}</div>')

    doc = f"""<!doctype html>
<html lang="{html.escape(lang_code)}">
<head><meta charset="UTF-8" /><meta name="viewport" content="width={W}, height={H}" />
<script src="https://cdn.jsdelivr.net/npm/gsap@3.15.0/dist/gsap.min.js"></script>
<style>
@font-face{{font-family:'PopX';src:url(assets/Poppins-ExtraBold.ttf);font-weight:800}}
@font-face{{font-family:'PopB';src:url(assets/Poppins-Black.ttf);font-weight:900}}
@font-face{{font-family:'PopM';src:url(assets/Poppins-Medium.ttf);font-weight:500}}
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:{W}px;height:{H}px;overflow:hidden;background:#000}}
.clip{{position:absolute;inset:0}}
.full{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}}
{band_css}
.cap{{display:flex;align-items:center;justify-content:center;text-align:center;inset:auto;left:60px;width:{W - 120}px;top:{cy - 160}px;height:320px;z-index:5}}
.cap .in{{display:inline-block;max-width:{W - 120}px}}
{capstyle}
#endbg{{filter:blur(18px) brightness(.5);transform:scale(1.08)}}
#end{{display:flex;flex-direction:column;align-items:center;justify-content:center;z-index:6;color:#fff;font-family:'PopB';text-align:center;padding:0 60px}}
#end .el{{line-height:1.05;margin:6px 0}}
#end .cta{{margin-top:70px;background:#fff;color:#111;font-size:56px;padding:26px 80px;border-radius:999px}}
</style></head>
<body>
<div id="root" data-composition-id="main" data-start="0" data-duration="{total}" data-width="{W}" data-height="{H}">
  <video id="a-roll" class="clip full" src="assets/src.mp4" muted playsinline data-start="0" data-duration="{a_end}" data-track-index="0"></video>
  {hold}
  <img id="endbg" class="clip full" src="assets/last.jpg" data-start="{end_t}" data-duration="{total - end_t:.2f}" data-track-index="1" />
  {band_html}
  {''.join(caps)}
  <div id="end" class="clip" data-start="{end_t}" data-duration="{total - end_t:.2f}" data-track-index="4">{''.join(end_divs)}</div>
  <audio id="vo" src="assets/vo{vo_audio.suffix}" data-start="{off}" data-duration="{vo_end - off:.2f}" data-volume="1"></audio>
</div>
<script>
window.__timelines = window.__timelines || {{}};
const tl = gsap.timeline({{ paused: true }});
{chr(10).join(anim)}
tl.fromTo("#endbg",{{opacity:0}},{{opacity:1,duration:0.35}},{end_t});
tl.from("#end > div",{{y:60,opacity:0,scale:0.85,duration:0.4,stagger:0.12,ease:"back.out(2)"}},{end_t + 0.1:.2f});
tl.to("#end .cta",{{scale:1.08,duration:0.35,yoyo:true,repeat:3,ease:"sine.inOut"}},{end_t + 1.0:.2f});
window.__timelines["main"] = tl;
</script>
</body></html>"""
    (project / "index.html").write_text(doc, encoding="utf-8")
    (project / "hyperframes.json").write_text(json.dumps({
        "$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
        "paths": {"blocks": "compositions", "components": "compositions/components", "assets": "assets"},
        "media": {"autoProxy": True}}, indent=2))
    (project / "meta.json").write_text(json.dumps({"id": project.name, "name": project.name}), encoding="utf-8")
    return {"width": W, "height": H, "total": total, "end_t": end_t, "captions": len(caps)}


def _hf_cmd() -> list[str]:
    local = ROOT / "node_modules" / ".bin" / ("hyperframes.cmd" if os.name == "nt" else "hyperframes")
    if local.exists():
        return [str(local)]
    npx = shutil.which("npx")
    if not npx:
        raise ComposeError("Node.js/npx not found. Install Node 22+ and run `npm install` in the cloner folder.")
    return [npx, "--yes", f"hyperframes@{HF_VERSION}"]


def render(project: Path, out: Path, on_progress: Callable[[float], None] | None = None) -> Path:
    env = dict(os.environ, DO_NOT_TRACK="1", HYPERFRAMES_SKIP_SKILLS="1", CI="1")
    cmd = _hf_cmd() + ["render", "-o", str(out.resolve())]
    p = subprocess.Popen(cmd, cwd=project, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", env=env)
    tail = []
    for line in p.stdout:
        tail = (tail + [line])[-40:]
        if line.startswith("@hf-progress") and on_progress:
            try:
                on_progress(float(json.loads(line.split(" ", 1)[1]).get("pct", 0)))
            except (ValueError, json.JSONDecodeError):
                pass
    p.wait()
    if p.returncode != 0 or not out.exists():
        raise ComposeError("HyperFrames render failed:\n" + "".join(tail)[-1500:])
    return out
