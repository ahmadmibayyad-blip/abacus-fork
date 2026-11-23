# Cloner

A local web app that clones a page's top Meta ads into another language. It runs at **http://127.0.0.1:8765/**.

You paste one or more Ad Library links, choose the target language, and press **Clone ads**. Use **＋ Add another link** to add more links (up to 10). You can also paste several links at once and each becomes its own row. Each link can be:

- **A single ad**, like `https://www.facebook.com/ads/library/?id=1139014535679515`. You can also paste just the number. Cloner looks it up by its Library ID.
- **A page view**, like a page's ads sorted by impressions (`…&view_all_page_id=…`). Cloner takes the top N ads, using **Ads per page link**.

A job can mix both kinds, up to 20 ads in total. A single ad that can't be found is marked on its card, and the other ads still run. For each ad:

| Ad type | What happens |
|---|---|
| **Video** | ElevenLabs transcribes the original voiceover. **Claude Opus** watches frames of the ad and writes a localized script, the post copy and an end card, and finds where the burned-in captions sit. ElevenLabs records the new voiceover with word timings. **HyperFrames** renders the clone: original footage, the old captions blurred out, new captions timed to the voice, and an offer card at the end. |
| **Image** | Claude finds every overlaid text block and translates it. Cloner paints over the old text and draws the new text in the same place, in Poppins. |

Every ad also gets localized post copy (primary text, headline, description, button). Claude lists each change it made, such as removing the competitor's brand name or softening claims Meta would reject.

In the **Jobs** tab you can edit the script, end card, copy or image text, then **re-render**. **Download all (.zip)** gives you the files plus `ad_copy.md`.

You can also skip the Ad Library and **upload** your own ad images or videos.

## Generate new ad

The fourth mode makes an original ad with all-new footage of your product. Nothing is copied from another advertiser, and there is no blurred text.

1. Upload 1-4 product photos and say what the product is.
2. Optionally paste a script, for example the script of an ad you cloned. Leave it empty and Claude writes one.
3. Choose how many ads you want (1-5). Each gets a different script and angle.
4. Press **Generate ad**. Cloner then:
   - has Claude write the script and record it with ElevenLabs,
   - has Claude plan one shot for every spoken line,
   - renders the first frame of each shot with an image model, using your product photos as reference,
   - animates each frame with a Higgsfield video model,
   - cuts the shots to the voiceover and adds captions and an end card.

On the job page you can edit a shot's description or tick **Redo** to make that shot again; the other shots and the voiceover are kept. **Another voice take** and **New script, new ad** work as in Build from my clips.

**What it needs (Settings tab)**

- **Higgsfield API key ID and secret**, from console.higgsfield.ai. Costs are charged in dollars to your Higgsfield Console balance. This is separate from the credits of the Higgsfield web app.
- Optional: a **Gemini API key** if you set the image provider to Gemini (Nano Banana). By default Higgsfield makes the images too, so one key is enough.

**Defaults**

| Setting | Default |
|---|---|
| Image provider | Higgsfield |
| Higgsfield image model | `xai/grok-imagine-image-2.0` (accepts product reference images) |
| Higgsfield video model | `xai/grok-imagine-video/v1.5/reference-to-video` |
| Gemini image model | `gemini-nano-banana-2.1` |
| Max cost per ad | $5. Before generating, Cloner asks Higgsfield for a price estimate and stops if it is above this. |

To use another Higgsfield model, paste its API path from its page on docs.higgsfield.ai and adjust the JSON settings to that model's parameters.

## Build from my clips

The third mode on **New clone** makes a new ad from your own raw product videos, so nothing in it is someone else's footage.

1. Upload around 5 product videos (up to 12) and say what the product is.
2. Optionally paste a script. It can be in any language, for example the script of an ad you cloned. Leave it empty and Claude writes one.
3. Press **Build ad**. Cloner then:
   - cuts every video into scenes (up to 60 clips),
   - has Claude look at each clip and note what it shows, and skip unusable ones,
   - writes or translates the script and records the voiceover,
   - has Claude pick the best clip for every spoken line,
   - cuts the montage in 9:16 and renders it with captions and an end card.

Captions that are already burned into your source videos are blurred out, so only the new captions show.

On the job page you can:

- **See your clip library.** Clips used in the ad are outlined.
- **Swap a clip.** Under "Which clip plays on which line", press **Swap** on a line and pick another clip, then **Save & rebuild**. The voiceover is kept.
- **Change the caption style**: bold pop, clean, or no captions.
- **Edit the script** and press **Save & rebuild**. The voiceover is recorded again only when the script changed.
- **Another voice take**: records the same script again.
- **New script, new ad**: Claude writes a different hook and angle and builds another ad from the same clips, without analysing them again.

On the **New clone** tab, the voice list shows the voices in your ElevenLabs account, with a preview button.

## Requirements

- Python 3.10+
- Node.js 22+ (for HyperFrames)
- ffmpeg
- Google Chrome (HyperFrames renders with it)
- API keys (Anthropic and ElevenLabs for every mode; the others only for the modes named):
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
  gen.py        Higgsfield and Gemini requests for the Generate new ad mode
  builder.py    build an ad from your own clips: scenes, cut list, montage
  imagetext.py  replaces text on image ads
  media.py      ffmpeg helpers
  static/index.html  the web UI
data/jobs/<id>/      everything a job produced (sources, plans, renders, HyperFrames projects)
tests/               offline tests (paid APIs stubbed, real ffmpeg and HyperFrames render)
```

## Before you run the ads

- **The footage belongs to the original advertiser.** Video clones reuse it. Only run the clones if you have rights to it; otherwise re-shoot, put your file in `data/jobs/<id>/adN/source.mp4`, and re-render.
- **Check the offer.** Make sure the shipping, guarantee, discount and buy-one-get-one terms match your store, or set **Your offer** when you start the job.
- **Read "Changes from the original"** on each ad before publishing.
