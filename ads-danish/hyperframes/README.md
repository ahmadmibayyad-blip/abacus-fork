# HyperFrames source: Danish UGC ad clones (ad 2 and ad 3)

These are the [HyperFrames](https://hyperframes.heygen.com) compositions (HTML + GSAP rendered to MP4) behind the Danish video ads in `../AD_COPY_DA.md`.

Each video is built from these layers:

| Layer | What it does |
|---|---|
| `#a-roll` | Original UGC footage, muted |
| `#band` | A blurred copy of the same footage, cropped to a strip, which hides the burned-in French captions |
| `.cap` clips | Danish captions, timed to the Danish voiceover, with a GSAP pop-in |
| `#end` | Danish end card (offer + "SHOP NU") over a blurred last frame |
| `#vo` | Danish voiceover (ElevenLabs, voice "Dråbefri DK – UGC female", model eleven_v4) |

## Rebuild

`assets/` is not committed (source footage and audio). Put these files in each `adN/assets/` folder:

- `src.mp4`: the original ad video (360×640 from the Meta Ad Library)
- `vo.wav`: the Danish voiceover. Leading and trailing silence are trimmed. ad2 is also sped up 1.10× (`atempo=1.10`).
- `last.jpg`: the last frame of `src.mp4` (`ffmpeg -sseof -0.1 -i src.mp4 -frames:v 1 last.jpg`)
- `Poppins-ExtraBold.ttf`, `Poppins-Black.ttf`, `Poppins-Medium.ttf` (Google Fonts, OFL)

Then:

```bash
python3 gen.py 2 && python3 gen.py 3     # writes adN/index.html from script.txt + words.json
```

```bash
cd ad2 && npx --yes hyperframes@0.9.32 check && npx --yes hyperframes@0.9.32 render -o ../DA_ad2.mp4
```

To change the text: edit `adN/script.txt`. If you change the spoken words, regenerate the voiceover and re-run Whisper (Danish, word timestamps) to refresh `words.json`. The end-card text and the position of the blur band are set in the `C` dict in `gen.py`.
