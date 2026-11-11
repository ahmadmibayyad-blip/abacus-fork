"""Fetch ads from the Meta Ad Library (via the Apify Facebook Ad Library scraper) and
download their media."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

from . import config

ACTOR = "curious_coder~facebook-ads-library-scraper"


class SourceError(RuntimeError):
    pass


def fetch_ads(library_url: str, count: int) -> list[dict]:
    """Return the first `count` ads of an Ad Library URL, in the URL's own sort order
    (e.g. sort_data[mode]=total_impressions), normalised to Cloner's ad dict."""
    token = config.get("APIFY_TOKEN")
    if not token:
        raise SourceError("APIFY_TOKEN is not set (Settings tab).")
    if "facebook.com/ads/library" not in library_url:
        raise SourceError("That does not look like a Meta Ad Library URL.")
    payload = {
        "urls": [{"url": library_url}],
        "count": max(count, 1),
        "limitPerSource": max(count, 1),
        "scrapeAdDetails": False,
    }
    url = f"https://api.apify.com/v2/acts/{ACTOR}/run-sync-get-dataset-items"
    try:
        r = httpx.post(url, params={"token": token}, json=payload, timeout=300)
    except httpx.HTTPError as e:
        raise SourceError(f"Apify request failed: {e}") from e
    if r.status_code >= 400:
        raise SourceError(f"Apify returned {r.status_code}: {r.text[:300]}")
    items = r.json()
    if not isinstance(items, list) or not items:
        raise SourceError("No ads came back for that URL (is it public and active?).")
    items.sort(key=lambda it: it.get("position") or 10**9)
    return [normalise(it) for it in items[:count]]


def normalise(it: dict) -> dict:
    snap = it.get("snapshot") or {}
    cards = snap.get("cards") or []
    first_card = cards[0] if cards else {}
    images = [i.get("original_image_url") or i.get("resized_image_url") for i in (snap.get("images") or [])]
    videos = snap.get("videos") or []
    video_url = None
    if videos:
        video_url = videos[0].get("video_hd_url") or videos[0].get("video_sd_url")
    elif first_card.get("video_hd_url") or first_card.get("video_sd_url"):
        video_url = first_card.get("video_hd_url") or first_card.get("video_sd_url")
    if not images and first_card.get("original_image_url"):
        images = [first_card.get("original_image_url")]
    body = (snap.get("body") or {}).get("text") or first_card.get("body") or ""
    kind = "video" if video_url else ("image" if images else "unknown")
    return {
        "ad_id": str(it.get("ad_archive_id") or it.get("ad_id") or ""),
        "page_name": snap.get("page_name") or it.get("page_name") or "",
        "start_date": it.get("start_date_formatted") or "",
        "kind": kind,
        "media_url": video_url or (images[0] if images else None),
        "copy": {
            "primary_text": body,
            "headline": snap.get("title") or first_card.get("title") or "",
            "description": snap.get("link_description") or first_card.get("link_description") or "",
            "cta": snap.get("cta_text") or "",
            "link_url": snap.get("link_url") or first_card.get("link_url") or "",
        },
        "library_url": f"https://www.facebook.com/ads/library/?id={it.get('ad_archive_id')}",
    }


def page_id_from_url(library_url: str) -> str:
    q = parse_qs(urlparse(library_url).query)
    return (q.get("view_all_page_id") or [""])[0]


def download(url: str, dest: Path) -> Path:
    with httpx.stream("GET", url, timeout=120, follow_redirects=True) as r:
        if r.status_code >= 400:
            raise SourceError(f"Media download failed ({r.status_code}).")
        with open(dest, "wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    if dest.stat().st_size == 0:
        raise SourceError("Media download was empty.")
    return dest
