"""Claude (Opus) does the creative work: reads the source ad (transcript, frames, image)
and writes the localized clone plan as structured output."""
from __future__ import annotations

import base64
from pathlib import Path
from typing import List, Literal

import anthropic
from pydantic import BaseModel

from . import config

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AIError(RuntimeError):
    pass


# ---------- structured output schemas ----------

class AdCopy(BaseModel):
    primary_text: str
    headline: str
    description: str
    cta: str


class CaptionBox(BaseModel):
    present: bool          # are there burned-in captions/subtitles to cover?
    x_pct: float           # left edge, % of frame width
    y_pct: float           # top edge, % of frame height
    w_pct: float
    h_pct: float
    style: Literal["bold_upper", "clean"]
    highlight_color: str   # hex, e.g. "#ff8bc3"


class VideoPlan(BaseModel):
    source_language: str
    voiceover: str
    ad_copy: AdCopy
    captions: CaptionBox
    end_card_lines: List[str]
    end_card_cta: str
    changes: List[str]


class TextBlock(BaseModel):
    original: str
    translated: str
    x0: int
    y0: int
    x1: int
    y1: int
    color: str
    weight: Literal["regular", "medium", "bold", "black"]
    align: Literal["left", "center", "right"]
    uppercase: bool


class ImagePlan(BaseModel):
    blocks: List[TextBlock]
    ad_copy: AdCopy
    changes: List[str]


# ---------- prompts ----------

def _rules(opts: dict) -> str:
    lang = opts.get("language", "Danish")
    brand = (opts.get("brand") or "").strip()
    offer = (opts.get("offer") or "").strip()
    if opts.get("mode") == "build":
        lines = [f"You are a direct-response creative strategist and video editor making Meta ads in {lang} "
                 "from a seller's own raw product footage.",
                 f"Write natively in {lang}: natural, spoken, persuasive."
                 + (f' The brand is "{brand}".' if brand else "")]
        if offer:
            lines.append(f"The seller's offer is: {offer}. Do not invent other prices, discounts, guarantees or shipping terms.")
        else:
            lines.append("No offer was given: do not invent prices, discounts, guarantees or shipping terms.")
        if opts.get("safe_claims", True):
            lines.append("Avoid claims a regulator or Meta's ad review would reject: unverifiable numbers, medical or "
                         "health cures, guaranteed results, before/after promises. Phrase benefits as appearance or feel.")
        return "\n".join(lines)
    lines = [
        f"You localize a competitor's winning Meta ad into {lang} for a different seller who sells a similar product.",
        f"Write natively in {lang} for that market: natural, spoken, persuasive, same structure, hook, pacing, angle and offer mechanics as the source. Do not translate word for word.",
        "Never mention the source brand, its website, or its product name. "
        + (f"Use the brand name \"{brand}\" where the source names its brand." if brand else
           "Where the source names its brand, use a neutral description of the product instead."),
    ]
    if offer:
        lines.append(f"The seller's real offer is: {offer}. Use it instead of the source offer wherever the source states an offer, price, discount, guarantee or shipping terms.")
    else:
        lines.append("Keep the source's offer mechanics (e.g. buy one get one, discount, shipping, guarantee); the seller will verify them.")
    if opts.get("safe_claims", True):
        lines.append("Drop or soften claims a regulator or Meta's ad review would reject: unverifiable numbers, medical/health cures, 'patented'/'world first', guaranteed results, weight-loss or calorie claims, before/after promises. Keep the benefit, phrase it as appearance or feel. List each change you made in `changes`.")
    lines.append("List in `changes` every brand removal, offer swap or claim edit, in English, one short line each.")
    return "\n".join(lines)


def _client() -> anthropic.Anthropic:
    key = config.get("ANTHROPIC_API_KEY")
    if not key:
        raise AIError("ANTHROPIC_API_KEY is not set (Settings tab).")
    return anthropic.Anthropic(api_key=key)


def _img_block(path: Path, media_type: str = "image/jpeg") -> dict:
    data = base64.standard_b64encode(path.read_bytes()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}


def _parse(content: list, schema, opts: dict):
    client = _client()
    try:
        resp = client.beta.messages.parse(
            model=config.get("CLAUDE_MODEL"),
            max_tokens=16000,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            output_config={"effort": "high"},
            system=_rules(opts),
            messages=[{"role": "user", "content": content}],
            output_format=schema,
        )
    except anthropic.AuthenticationError as e:
        raise AIError("Anthropic API key was rejected.") from e
    except anthropic.RateLimitError as e:
        raise AIError("Anthropic rate limit hit; try again in a minute.") from e
    except anthropic.APIStatusError as e:
        raise AIError(f"Anthropic API error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise AIError("Could not reach the Anthropic API.") from e
    if resp.stop_reason == "refusal":
        raise AIError("Claude declined this ad.")
    if resp.stop_reason == "max_tokens" or resp.parsed_output is None:
        raise AIError("Claude's answer was cut off; try again.")
    return resp.parsed_output


def plan_video(transcript: str, frames: list[Path], src_copy: dict, duration: float, opts: dict) -> VideoPlan:
    words = len(transcript.split())
    content = [_img_block(p) for p in frames]
    content.append({"type": "text", "text": f"""These are {len(frames)} evenly spaced frames of a {duration:.1f}s vertical video ad (in order).

Spoken voiceover transcript (auto-transcribed, may contain errors):
<transcript>
{transcript or "(no speech detected)"}
</transcript>

Ad post copy:
<copy>
primary text: {src_copy.get('primary_text', '')}
headline: {src_copy.get('headline', '')}
description: {src_copy.get('description', '')}
call to action: {src_copy.get('cta', '')}
</copy>

Produce the clone plan:
- voiceover: the full localized voiceover script, roughly {max(words, 20)} words so it fits the same {duration:.0f} seconds when read at a natural, energetic pace. Plain text only, no stage directions or emojis.
- ad_copy: localized post copy (primary text keeps the source's line breaks and emoji style; cta is the button label in the target language).
- captions: where the burned-in captions/subtitles sit in the frames. Give the box that covers every caption position you see, as percentages of frame width/height, with a little margin. style "bold_upper" if they are bold uppercase/stroked, else "clean". highlight_color: the accent colour used on captions (or "#ffffff"). If there are no burned-in captions, present=false.
- end_card_lines: 2-4 short lines for a closing offer card (largest first), end_card_cta: short button text.
- source_language: language of the source ad."""})
    return _parse(content, VideoPlan, opts)


def plan_image(image: Path, width: int, height: int, src_copy: dict, opts: dict) -> ImagePlan:
    media = "image/png" if image.suffix.lower() == ".png" else "image/jpeg"
    content = [_img_block(image, media), {"type": "text", "text": f"""This is a static image ad, exactly {width}x{height} pixels.

Ad post copy:
<copy>
primary text: {src_copy.get('primary_text', '')}
headline: {src_copy.get('headline', '')}
description: {src_copy.get('description', '')}
call to action: {src_copy.get('cta', '')}
</copy>

1. blocks: every piece of overlaid marketing text in the image (headlines, benefit labels, offer badges, prices). Not text that is printed on the product or packaging itself. One block per visually separate text group (a 2-line label is one block, lines joined with "\\n").
   For each: original text, translated text (keep line breaks; similar length, shorter is better), and a tight pixel bounding box x0,y0,x1,y1 in this {width}x{height} image that covers all of the original glyphs. color = text colour hex, weight, align, uppercase as in the original.
   Text that is just the source brand name: translate to the seller's brand, or a short product descriptor.
2. ad_copy: localized post copy.
3. changes: as instructed."""}]
    return _parse(content, ImagePlan, opts)


# ---------- build an ad from the user's own clips ----------

class ClipInfo(BaseModel):
    id: int
    description: str       # what is visible, one short sentence
    shows: Literal["product_closeup", "product_in_use", "person_talking", "result", "unboxing", "lifestyle", "other"]
    has_burned_text: bool  # captions/logos/watermarks baked into the footage
    usable: bool           # false for blurry, black, or irrelevant footage


class ClipLibrary(BaseModel):
    product_summary: str
    clips: List[ClipInfo]


class BuildScript(BaseModel):
    voiceover: str
    ad_copy: AdCopy
    end_card_lines: List[str]
    end_card_cta: str
    changes: List[str]


class Assignment(BaseModel):
    segment: int
    clip_ids: List[int]


class Matching(BaseModel):
    assignments: List[Assignment]


def describe_clips(clips: list[dict], thumbs_dir: Path, product: str, opts: dict) -> ClipLibrary:
    content = []
    for c in clips:
        content.append({"type": "text", "text": f"Clip {c['id']} ({c['dur']:.1f}s, from {c['file']}):"})
        content.append(_img_block(thumbs_dir / c["thumb"]))
    content.append({"type": "text", "text": f"""Above is one frame from each of {len(clips)} clips cut from a seller's raw product videos.
Product notes from the seller: {product or "(none given)"}

For every clip id, say what is visible (in English, one short concrete sentence an editor could match to a script line), classify it, flag burned-in text, and mark unusable footage. Then summarise the product in one or two sentences: what it is and what it does, judging from the footage and the notes. Return every clip id exactly once."""})
    return _parse(content, ClipLibrary, opts)


def write_build_script(library: dict, product: str, script: str, previous: list[str], opts: dict) -> BuildScript:
    lang = opts.get("language", "Danish")
    clip_lines = "\n".join(f"- {c['description']} ({c['shows']})" for c in library["clips"] if c.get("usable", True))
    if script.strip():
        task = f"""The seller supplied this script. Use it as the voiceover: keep its content and order, translate it into {lang} if it is in another language, and only fix what the rules require.
<script>
{script.strip()}
</script>"""
    else:
        task = f"""Write the voiceover for a 25-35 second vertical UGC-style ad in {lang}: a scroll-stopping hook in the first sentence, the problem, how the product solves it, 2-3 concrete benefits that the footage can show, the offer if one is given, and a short call to action. Short spoken sentences. Plain text, no stage directions or emojis. Only claim what the footage and notes support."""
        if previous:
            task += "\nEarlier scripts for this product (write a clearly different hook and angle):\n" + "\n".join(f"<earlier>{p}</earlier>" for p in previous[-3:])
    content = [{"type": "text", "text": f"""Product: {library.get('product_summary', '')}
Seller's notes: {product or "(none)"}

Footage available (the ad will be cut from these clips, so write lines that these shots can illustrate):
{clip_lines}

{task}

Also return: ad_copy for the Meta post in {lang} (primary text, headline, description, button label), end_card_lines (2-4 short lines for the closing offer card, largest first), end_card_cta (short button text), and changes (anything you altered or left out because of the rules; empty if nothing)."""}]
    return _parse(content, BuildScript, opts)


def match_clips(segs: list[dict], clips: list[dict], opts: dict) -> Matching:
    seg_lines = "\n".join(f"{s['i']}: ({s['dur']:.1f}s) {s['text']}" for s in segs)
    clip_lines = "\n".join(f"{c['id']}: ({c['dur']:.1f}s, {c.get('shows', 'other')}"
                           f"{', has burned-in text' if c.get('has_burned_text') else ''}) {c.get('description', '')}"
                           for c in clips if c.get("usable", True))
    content = [{"type": "text", "text": f"""You are editing a short vertical product ad. Pick footage for each voiceover beat.

Voiceover beats (index: duration, text):
{seg_lines}

Clips (id: duration, type, what it shows):
{clip_lines}

For every beat return clip_ids: the clip that best illustrates what is being said, plus more clips if one is shorter than the beat (their durations should add up to at least the beat's duration). Rules: the first beat gets the most eye-catching clip; show the product in use when a benefit is described; do not reuse a clip unless you run out; prefer clips without burned-in text; keep variety by not putting look-alike clips back to back. Return every beat index exactly once."""}]
    return _parse(content, Matching, opts)
