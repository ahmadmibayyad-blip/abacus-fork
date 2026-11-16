"""Unit tests for the Ad Library parsing and Apify error handling (no network).

    python tests/test_sources.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["CLONER_DATA"] = tempfile.mkdtemp(prefix="cloner-unit-")
os.environ["CLONER_SETTINGS"] = os.path.join(os.environ["CLONER_DATA"], "settings.json")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from cloner import config, sources  # noqa: E402

IMG = {"ad_archive_id": "1", "position": 2, "snapshot": {
    "display_format": "IMAGE", "title": "T", "body": {"text": "B"}, "cta_text": "Shop now", "cards": [],
    "images": [{"original_image_url": "https://x/img.jpg", "resized_image_url": "https://x/s.jpg"}],
    "videos": [], "extra_images": [], "extra_videos": []}}
VID = {"ad_archive_id": "2", "position": 1, "snapshot": {
    "display_format": "VIDEO", "title": "T", "body": {"text": "B"}, "cards": [], "images": [],
    "videos": [{"video_hd_url": "https://x/hd.mp4", "video_sd_url": "https://x/sd.mp4"}]}}
CAROUSEL = {"ad_archive_id": "3", "position": 3, "snapshot": {
    "display_format": "DCO", "body": {"text": "{{product.brand}}"}, "images": [], "videos": [],
    "cards": [{"original_image_url": "https://x/card.jpg", "title": "Card", "body": "Card body"}]}}


def fake_post(status, body):
    def _post(*a, **kw):
        return httpx.Response(status, json=body, request=httpx.Request("POST", "https://api.apify.com"))
    return _post


def run():
    config.save({"APIFY_TOKEN": "test-token"})
    url = "https://www.facebook.com/ads/library/?view_all_page_id=1"

    a = sources.normalise(IMG)
    assert a["kind"] == "image" and a["media_url"] == "https://x/img.jpg", a
    v = sources.normalise(VID)
    assert v["kind"] == "video" and v["media_url"] == "https://x/hd.mp4", v
    c = sources.normalise(CAROUSEL)
    assert c["kind"] == "image" and c["media_url"] == "https://x/card.jpg" and c["copy"]["primary_text"] == "{{product.brand}}", c

    httpx.post = fake_post(201, [IMG, VID, CAROUSEL])
    raw = Path(os.environ["CLONER_DATA"]) / "raw.json"
    ads = sources.fetch_ads(url, 2, raw_path=raw)
    assert [x["ad_id"] for x in ads] == ["2", "1"], ads          # sorted by position
    assert raw.exists()

    cases = [
        (201, [{"url": url, "error": "Facebook blocked the request"}], "Facebook blocked the request"),
        (201, [], "an empty result"),
        (201, [{"foo": 1}], "1 item(s) with no ad data"),
        (401, {"error": {"type": "token-not-valid", "message": "bad"}}, "rejected the token"),
        (402, {"error": {"message": "no credit"}}, "no credit left"),
        (400, {"error": {"message": "Input is not valid: count"}}, "Input is not valid"),
    ]
    for status, body, expect in cases:
        httpx.post = fake_post(status, body)
        try:
            sources.fetch_ads(url, 3)
        except sources.SourceError as e:
            assert expect in str(e), (status, str(e))
        else:
            raise AssertionError(f"no error for {status} {body}")
    # link classification
    assert sources.ad_id_from_link("https://www.facebook.com/ads/library/?id=1139014535679515") == "1139014535679515"
    assert sources.ad_id_from_link("1139014535679515") == "1139014535679515"
    assert sources.ad_id_from_link(url) is None
    kinds = sources.classify([" https://www.facebook.com/ads/library/?id=111111111 ", "", url])
    assert [k["type"] for k in kinds] == ["ad", "page"], kinds
    for bad in (["https://example.com/x"], ["", "  "]):
        try:
            sources.classify(bad)
        except sources.SourceError:
            pass
        else:
            raise AssertionError(bad)

    # single ads: search by ID, keep only exact matches
    sent = {}
    def capture(*a, **kw):
        sent.update(kw["json"])
        other = dict(IMG, ad_archive_id="999")
        hit = dict(VID, ad_archive_id="111111111")
        return httpx.Response(201, json=[other, hit], request=httpx.Request("POST", "https://api.apify.com"))
    httpx.post = capture
    found = sources.fetch_single_ads(["111111111", "222222222"])
    assert set(found) == {"111111111"} and found["111111111"]["kind"] == "video", found
    assert "q=111111111" in sent["urls"][0]["url"] and len(sent["urls"]) == 2, sent
    httpx.post = fake_post(201, [])
    assert sources.fetch_single_ads(["333333333"]) == {}   # nothing found is not an exception
    print("PASS")


if __name__ == "__main__":
    run()
