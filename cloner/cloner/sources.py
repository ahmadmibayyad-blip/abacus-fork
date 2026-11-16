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


def ad_id_from_link(link: str) -> str | None:
    """The Library ID if `link` points at one ad (…/ads/library/?id=123) or is a bare ID."""
    link = link.strip()
    if link.isdigit() and len(link) >= 8:
        return link
    q = parse_qs(urlparse(link).query)
    ad_id = (q.get("id") or [""])[0]
    if ad_id.isdigit() and not q.get("view_all_page_id") and not q.get("q"):
        return ad_id
    return None


def classify(links: list[str]) -> list[dict]:
    """[{"type": "ad", "id": ...} | {"type": "page", "url": ...}] in input order."""
    out = []
    for link in links:
        link = link.strip()
        if not link:
            continue
        ad_id = ad_id_from_link(link)
        if ad_id:
            out.append({"type": "ad", "id": ad_id, "link": link})
        elif "facebook.com/ads/library" in link:
            out.append({"type": "page", "url": link, "link": link})
        else:
            raise SourceError(f"Not a Meta Ad Library link: {link[:120]}")
    if not out:
        raise SourceError("Add at least one Ad Library link.")
    return out


def _search_url(ad_id: str) -> str:
    # the scraper ignores ?id= links, but the Library's keyword search finds an ad by its ID
    return ("https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country=ALL"
            f"&is_targeted_country=false&media_type=all&q={ad_id}&search_type=keyword_unordered")


def fetch_single_ads(ad_ids: list[str], raw_path: Path | None = None) -> dict[str, dict]:
    """Look up specific ads by Library ID (one Apify run). Returns {id: ad}; IDs that
    were not found are missing from the dict."""
    items = _run([_search_url(i) for i in ad_ids], 10, raw_path, require_ads=False)
    found = {}
    for it in items:
        aid = str(it.get("ad_archive_id") or "")
        if aid in ad_ids and aid not in found and it.get("snapshot"):
            found[aid] = normalise(it)
    return found


def fetch_ads(library_url: str, count: int, raw_path: Path | None = None) -> list[dict]:
    """Return the first `count` ads of an Ad Library URL, in the URL's own sort order
    (e.g. sort_data[mode]=total_impressions), normalised to Cloner's ad dict.
    The raw Apify response is saved to raw_path for debugging."""
    if "facebook.com/ads/library" not in library_url:
        raise SourceError("That does not look like a Meta Ad Library URL.")
    # ask for at least 10: the scraper works in pages and small limits can return nothing
    ads = _run([library_url], max(count, 10), raw_path, require_ads=True)
    ads.sort(key=lambda it: it.get("position") or 10**9)
    return [normalise(it) for it in ads[:count]]


def _run(urls: list[str], per_url: int, raw_path: Path | None, require_ads: bool) -> list[dict]:
    """One synchronous Apify run of the Ad Library scraper; returns the ad items."""
    token = config.get("APIFY_TOKEN").strip()
    if not token:
        raise SourceError("APIFY_TOKEN is not set (Settings tab).")
    payload = {
        "urls": [{"url": u} for u in urls],
        "count": per_url * len(urls),
        "limitPerSource": per_url,
        "scrapeAdDetails": False,
    }
    url = f"https://api.apify.com/v2/acts/{ACTOR}/run-sync-get-dataset-items"
    try:
        r = httpx.post(url, params={"token": token}, json=payload, timeout=320)
    except httpx.HTTPError as e:
        raise SourceError(f"Apify request failed: {e}") from e
    if raw_path:
        raw_path.write_text(r.text, encoding="utf-8")
    if r.status_code == 401:
        raise SourceError("Apify rejected the token. Copy it again from console.apify.com → Settings → API & Integrations.")
    if r.status_code == 402:
        raise SourceError("Apify says the account has no credit left for this scraper (console.apify.com → Billing).")
    if r.status_code == 408:
        raise SourceError("Apify took longer than 5 minutes; try again.")
    if r.status_code >= 400:
        raise SourceError(f"Apify returned {r.status_code}: {_apify_msg(r)}")
    try:
        items = r.json()
    except ValueError as e:
        raise SourceError(f"Apify sent something unexpected: {r.text[:300]}") from e
    if isinstance(items, dict):
        raise SourceError(f"Apify error: {_apify_msg(r)}")
    ads = [it for it in items if isinstance(it, dict) and it.get("snapshot")]
    if not ads and require_ads:
        errs = [str(it.get("error") or it.get("errorMessage") or it.get("message") or "")
                for it in items if isinstance(it, dict)]
        errs = [e for e in errs if e]
        detail = errs[0][:300] if errs else (
            f"{len(items)} item(s) with no ad data" if items else "an empty result")
        raise SourceError(f"The Ad Library scraper returned no ads ({detail}). Check the URL opens in a browser, "
                          "shows active ads, and that your Apify account can run "
                          "curious_coder/facebook-ads-library-scraper.")
    return ads


def _apify_msg(r: httpx.Response) -> str:
    try:
        d = r.json()
        if isinstance(d, dict):
            e = d.get("error") or {}
            return (e.get("message") if isinstance(e, dict) else str(e)) or r.text[:300]
    except ValueError:
        pass
    return r.text[:300]


def normalise(it: dict) -> dict:
    snap = it.get("snapshot") or {}
    cards = snap.get("cards") or []
    first_card = cards[0] if cards else {}
    images = [i.get("original_image_url") or i.get("resized_image_url")
              for i in (snap.get("images") or []) + (snap.get("extra_images") or [])]
    images = [u for u in images if u]
    videos = [v for v in (snap.get("videos") or []) + (snap.get("extra_videos") or [])
              if v.get("video_hd_url") or v.get("video_sd_url")]
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
