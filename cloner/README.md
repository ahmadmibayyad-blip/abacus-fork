# Cloner

A local web app that clones a page's top Meta ads into another language. It runs at **http://127.0.0.1:8765/**.

You paste an Ad Library link (for example a page's ads sorted by impressions), choose how many ads and the target language, and press **Clone ads**. For each ad:

| Ad type | What happens |
|---|---|
| **Video** | ElevenLabs transcribes the original voiceover. **Claude Opus** watches frames of the ad and writes a localized script, the post copy and an end card, and finds where the burned-in captions sit. ElevenLabs records the new voiceover with word timings. **HyperFrames** renders the clone: original footage, the old captions blurred out, new captions timed to the voice, and an offer card at the end. |
| **Image** | Claude finds every overlaid text block and translates it. Cloner paints over the old text and draws the new text in the same place, in Poppins. |

Every ad also gets localized post copy (primary text, headline, description, button). Claude lists each change it made, such as removing the competitor's brand name or softening claims Meta would reject.

In the **Jobs** tab you can edit the script, end card, copy or image text, then **re-render**. **Download all (.zip)** gives you the files plus `ad_copy.md`.

You can also skip the Ad Library and **upload** your own ad images or videos.

## Requirements

- Python 3.10+
- Node.js 22+ (for HyperFrames)
- ffmpeg
- Google Chrome (HyperFrames renders with it)
- API keys:
  - **Anthropic**: Claude Opus writes the clones (`claude-opus-5-5`)
  - **ElevenLabs**: speech-to-text and voiceover
  - **Apify**: reads the Ad Library through the `curious_coder/facebook-ads-library-scraper` actor. Not needed for uploads.

## Run

macOS / Linux:

```bash
./run.sh
```

Windows:

```bat
run.bat
```

Then open http://127.0.0.1:8765/ and add your keys on the **Settings** tab. You can also put them in a `.env` file; see `.env.example`.

The first run installs the Python packages into `.venv` and HyperFrames plus the Poppins font into `node_modules`.

## Costs per ad (roughly)

- **Claude Opus 5.5:** one request per ad, with 6 frames for a video or the image for an image ad, at effort `high`. A few cents.
- **ElevenLabs:** speech-to-text of the original, plus text-to-speech of the new script (about 40 s ≈ 600–900 characters).
- **Apify:** about $0.00075 per ad fetched.

Requests use server-side refusal fallbacks (`fallbacks: "default"`). If Opus declines a request, the API retries it on a fallback model automatically.

## Settings

| Setting | Default |
|---|---|
| Claude model | `claude-opus-5-5` |
| ElevenLabs voice | `jL9zCPolQd2Uh8OUGEk3` ("Dråbefri DK – UGC female"); change it per job or in Settings |
| ElevenLabs model | `eleven_multilingual_v2` |
| Languages | Danish, Swedish, Norwegian, Finnish, German, Dutch, English, French, Spanish, Italian, Portuguese, Polish |

Keys are saved only on your computer, in `settings.json`. The server listens on `127.0.0.1` only. Set `CLONER_HOST` / `CLONER_PORT` to change that.

## Files

```
cloner/
  app.py        FastAPI server and API
  jobs.py       job queue and the clone pipeline
  sources.py    Ad Library fetch (Apify) and media download
  ai.py         Claude Opus: video and image clone plans (structured outputs)
  voice.py      ElevenLabs speech-to-text and text-to-speech with timings
  compose.py    HyperFrames composition and render
  imagetext.py  replaces text on image ads
  media.py      ffmpeg helpers
  static/index.html  the web UI
data/jobs/<id>/      everything a job produced (sources, plans, renders, HyperFrames projects)
tests/smoke_test.py  offline end-to-end test (paid APIs stubbed, real ffmpeg and HyperFrames render)
```

## Before you run the ads

- **The footage belongs to the original advertiser.** Video clones reuse it. Only run the clones if you have rights to it; otherwise re-shoot, put your file in `data/jobs/<id>/adN/source.mp4`, and re-render.
- **Check the offer.** Make sure the shipping, guarantee, discount and buy-one-get-one terms match your store, or set **Your offer** when you start the job.
- **Read "Changes from the original"** on each ad before publishing.
