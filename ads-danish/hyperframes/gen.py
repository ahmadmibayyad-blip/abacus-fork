"""Generate the HyperFrames compositions (adN/index.html) for the Danish ad clones.

Usage:  python3 gen.py 2   (or 3)
Inputs per ad folder: script.txt (Danish VO text), words.json (word timestamps of the VO,
from Whisper), assets/ (src.mp4, vo.wav, last.jpg, Poppins-*.ttf; not committed).
"""
import json, re, difflib, sys, html


def norm(t): return re.sub(r"[^a-zæøå0-9]", "", t.lower())


def align(script, words, off):
    """Map each word of the correct script onto the Whisper timestamps."""
    toks = script.split(); a = [norm(t) for t in toks]; b = [norm(w[2]) for w in words]
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False); T = [None] * len(toks)
    for blk in sm.get_matching_blocks():
        for k in range(blk.size): T[blk.a + k] = words[blk.b + k][:2]
    for i in range(len(toks)):
        if T[i] is None:
            p = next((T[j] for j in range(i - 1, -1, -1) if T[j]), [0, 0])
            n = next((T[j] for j in range(i + 1, len(toks)) if T[j]), [p[1] + .4, p[1] + .4])
            T[i] = [p[1], (p[1] + n[0]) / 2 if n[0] > p[1] else p[1] + .2]
    return [(t[0] + off, t[1] + off, tok) for t, tok in zip(T, toks)]


def chunks(items, maxw, maxc):
    out = []; cur = []
    for it in items:
        cur.append(it)
        if len(cur) >= maxw or len(" ".join(c[2] for c in cur)) >= maxc or re.search(r"[.,!?:]$", it[2]):
            out.append(cur); cur = []
    if cur: out.append(cur)
    return out


def clean(w): return re.sub(r"[.,:']+$", "", w).strip("'")


C = {
    # band = (x, y, w, h) of the blurred strip that hides the burned-in French captions (1080x1920 space)
    "2": dict(off=0.10, maxw=3, maxc=16, upper=True, band=(170, 1140, 740, 240), cy=1260,
              end_t=43.3, total=46.6, src_dur=43.53,
              end_html='<div class="e1">KØB 1</div><div class="e2">FÅ 1 GRATIS</div><div class="e3">Gratis fragt · 30 dages returret</div><div class="cta">SHOP NU</div>'),
    "3": dict(off=0.30, maxw=3, maxc=22, upper=False, band=(60, 880, 960, 170), cy=963,
              end_t=38.9, total=41.8, src_dur=39.63,
              end_html='<div class="e0">BLACK FRIDAY</div><div class="e1">-50%</div><div class="e2b">+ KØB 1, FÅ 1 GRATIS</div><div class="cta">SHOP NU</div>'),
}

n = sys.argv[1]; c = C[n]
items = align(open(f"ad{n}/script.txt").read(), json.load(open(f"ad{n}/words.json")), c["off"])
ch = chunks(items, c["maxw"], c["maxc"])
vo_end = items[-1][1] + 0.3
caps = []; anim = []
for i, g in enumerate(ch):
    st = g[0][0]; en = min(ch[i + 1][0][0] if i + 1 < len(ch) else g[-1][1] + 0.5, c["end_t"])
    if en <= st: continue
    ws = [html.escape(clean(x[2])) for x in g]
    if c["upper"]:
        ws = [w.upper() for w in ws]
        if len(ws) > 1:
            k = max(range(len(ws)), key=lambda j: len(norm(ws[j]))); ws[k] = f'<span class="hl">{ws[k]}</span>'
    txt = " ".join(ws)
    cid = f"c{i}"
    caps.append(f'<div id="{cid}" class="clip cap" data-start="{st:.2f}" data-duration="{en-st:.2f}" data-track-index="3"><span class="in">{txt}</span></div>')
    if c["upper"]:
        anim.append(f'tl.fromTo("#{cid} .in",{{scale:0.6,opacity:0}},{{scale:1,opacity:1,duration:0.14,ease:"back.out(2.5)"}},{st:.2f});')
    else:
        anim.append(f'tl.fromTo("#{cid} .in",{{y:14,opacity:0}},{{y:0,opacity:1,duration:0.18,ease:"power2.out"}},{st:.2f});')

bx, by, bw, bh = c["band"]; T = c["total"]; E = c["end_t"]; sd = c["src_dur"]
capstyle = """.cap .in{font-family:'PopX';font-weight:800;font-size:76px;line-height:1.05;color:#fff;text-transform:uppercase;
  -webkit-text-stroke:0;text-shadow:0 0 6px #000,4px 4px 0 #000,-4px -4px 0 #000,4px -4px 0 #000,-4px 4px 0 #000,0 5px 0 #000,0 -5px 0 #000,5px 0 0 #000,-5px 0 0 #000;}
 .cap .hl{color:#ff8bc3}""" if c["upper"] else """.cap .in{font-family:'PopM';font-weight:500;font-size:58px;color:#fff;text-shadow:0 2px 8px rgba(0,0,0,.65),0 0 2px rgba(0,0,0,.8);}"""
doc = f"""<!doctype html>
<html lang="da" data-resolution="portrait">
<head><meta charset="UTF-8" /><meta name="viewport" content="width=1080, height=1920" />
<script src="https://cdn.jsdelivr.net/npm/gsap@3.15.0/dist/gsap.min.js"></script>
<style>
@font-face{{font-family:'PopX';src:url(assets/Poppins-ExtraBold.ttf);font-weight:800}}
@font-face{{font-family:'PopB';src:url(assets/Poppins-Black.ttf);font-weight:900}}
@font-face{{font-family:'PopM';src:url(assets/Poppins-Medium.ttf);font-weight:500}}
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:1080px;height:1920px;overflow:hidden;background:#000}}
.clip{{position:absolute;inset:0}}
.full{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}}
#band{{position:absolute;left:{bx}px;top:{by}px;width:{bw}px;height:{bh}px;overflow:hidden;border-radius:28px}}
#band video{{position:absolute;left:{-bx}px;top:{-by}px;width:1080px;height:1920px;object-fit:cover;filter:blur(26px) saturate(1.05);transform:scale(1.04);transform-origin:{bx+bw/2}px {by+bh/2}px}}
.cap{{display:flex;align-items:center;justify-content:center;text-align:center;inset:auto;left:90px;width:900px;top:{c['cy']-150}px;height:300px;z-index:5}}
.cap .in{{display:inline-block;max-width:900px}}
{capstyle}
#endbg{{filter:blur(18px) brightness(.55);transform:scale(1.08)}}
#end{{display:flex;flex-direction:column;align-items:center;justify-content:center;z-index:6;color:#fff;font-family:'PopB';text-align:center}}
#end .e0{{font-size:84px;letter-spacing:4px}}
#end .e1{{font-size:190px;line-height:1}}
#end .e2{{font-size:118px;line-height:1.05;color:#ff8bc3}}
#end .e2b{{font-size:66px;color:#ff8bc3;margin-top:10px}}
#end .e3{{font-family:'PopM';font-size:42px;margin-top:34px;opacity:.95}}
#end .cta{{margin-top:70px;background:#fff;color:#111;font-size:56px;padding:26px 80px;border-radius:999px}}
</style></head>
<body>
<div id="root" data-composition-id="main" data-start="0" data-duration="{T}" data-width="1080" data-height="1920">
  <video id="a-roll" class="clip full" src="assets/src.mp4" muted playsinline data-start="0" data-duration="{sd}" data-track-index="0"></video>
  <img id="endbg" class="clip full" src="assets/last.jpg" data-start="{E}" data-duration="{T-E:.2f}" data-track-index="1" />
  <div id="band">
    <video id="band-v" src="assets/src.mp4" muted playsinline data-start="0" data-duration="{min(sd,E):.2f}" data-track-index="2"></video>
  </div>
  {''.join(caps)}
  <div id="end" class="clip" data-start="{E}" data-duration="{T-E:.2f}" data-track-index="4">{c['end_html']}</div>
  <audio id="vo" src="assets/vo.wav" data-start="{c['off']}" data-duration="{vo_end-c['off']:.2f}" data-volume="1"></audio>
</div>
<script>
window.__timelines = window.__timelines || {{}};
const tl = gsap.timeline({{ paused: true }});
{chr(10).join(anim)}
tl.fromTo("#endbg",{{opacity:0}},{{opacity:1,duration:0.35}},{E});
tl.from("#end > div",{{y:60,opacity:0,scale:0.85,duration:0.4,stagger:0.12,ease:"back.out(2)"}},{E+0.1:.2f});
tl.to("#end .cta",{{scale:1.08,duration:0.35,yoyo:true,repeat:3,ease:"sine.inOut"}},{E+1.0:.2f});
window.__timelines["main"] = tl;
</script>
</body></html>"""
open(f"ad{n}/index.html", "w").write(doc); print(n, len(caps), "caps; vo_end", round(vo_end, 2))
