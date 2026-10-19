"""
backend.py — the real backend behind the Telegram bot.

Same contract as before (bot.py doesn't change):

  save_photo_record(user_name, image_bytes, focus) -> record_id
  describe_item(image_bytes, focus)                 -> description dict
  find_matches(description, prefs, limit=5)         -> list of listings, best first
  save_findings(user_name, record_id, listings, favorite=False) -> bool

What's real now:
  * find_matches   -> Parallel Search on ThredUp, eBay and Google, then a checking
                      loop (price, item, color, size). Parallel Image Search adds photos.
  * describe_item  -> any OpenAI-compatible vision model (Kimi, etc.) if configured
                      in .env; otherwise a simple description from the caption that
                      the user can edit in the chat.
  * save_findings  -> saves to findings.csv locally (swap for Composio + Sheets later).

The old fake version is kept in backend_mock.py for offline demos.

.env:
  PARALLEL_API_KEY=...
  VISION_BASE_URL=...   # OpenAI-compatible endpoint (optional)
  VISION_API_KEY=...    # optional
  VISION_MODEL=...      # optional
"""

import base64
import csv
import json
import logging
import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger("backend")

PARALLEL_SEARCH_URL = "https://api.parallel.ai/v1/search"
PARALLEL_IMAGE_URL = "https://api.parallel.ai/v1/images/search"
FINDINGS_CSV = Path(__file__).parent / "findings.csv"

COLORS = ["black", "white", "grey", "gray", "beige", "cream", "brown", "tan", "red",
          "pink", "orange", "yellow", "green", "olive", "blue", "navy", "purple"]

SITES = {"ThredUp": "thredup", "eBay": "ebay", "Google": None}


# ===========================================================================
# Step 3: log the request (no photo is stored, for privacy)
# ===========================================================================
def save_photo_record(user_name: str, image_bytes: bytes, focus: str) -> str:
    record_id = uuid.uuid4().hex[:8]
    log.info("new request %s from %s, focus=%r (photo not stored)", record_id, user_name, focus)
    return record_id


# ===========================================================================
# Step 4: describe the item
# ===========================================================================
VISION_PROMPT = """Look ONLY at the clothing item described as: "{focus}".
Ignore the person completely. Do not describe their face, body, age, or identity.
Reply with ONLY a JSON object, no other text:
{{"item": "short item name, e.g. bomber jacket",
  "color": "main color, one word",
  "material": "material if visible, else empty",
  "details": "2-5 words of key style details",
  "summary": "one short phrase combining color, details, material and item"}}"""


def _fallback_description(focus: str) -> dict:
    """No vision model available: build a description from the caption."""
    words = re.sub(r"^(the|this|that|my)\s+", "", focus.strip().lower())
    color = next((c for c in COLORS if re.search(rf"\b{c}\b", words)), "")
    item = re.sub(rf"\b{color}\b", "", words).strip() if color else words
    item = item or "clothing item"
    summary = f"{color} {item}".strip()
    return {"item": item, "color": color, "material": "", "details": "",
            "summary": summary[:1].upper() + summary[1:]}


def describe_item(image_bytes: bytes, focus: str) -> dict:
    base, key, model = (os.getenv("VISION_BASE_URL"), os.getenv("VISION_API_KEY"),
                        os.getenv("VISION_MODEL"))
    if not (base and key and model):
        log.info("no vision model configured, using caption fallback")
        return _fallback_description(focus)

    image_b64 = base64.b64encode(image_bytes).decode()
    body = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": VISION_PROMPT.format(focus=focus)},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
        ]}],
        "temperature": 0.2,
    }
    try:
        r = requests.post(f"{base.rstrip('/')}/chat/completions",
                          headers={"Authorization": f"Bearer {key}"}, json=body, timeout=60)
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"]
        desc = json.loads(text[text.find("{"): text.rfind("}") + 1])
        desc = {k: str(desc.get(k, "")).strip() for k in
                ("item", "color", "material", "details", "summary")}
        if not desc["item"]:
            raise ValueError("model returned no item")
        desc["color"] = desc["color"].lower()
        desc["summary"] = desc["summary"] or f"{desc['color']} {desc['item']}".strip()
        return desc
    except Exception as e:
        log.warning("vision model failed (%s), using caption fallback", e)
        return _fallback_description(focus)


# ===========================================================================
# Steps 7-9: search with Parallel, then check results match
# ===========================================================================
def _parallel_post(url: str, body: dict) -> dict:
    key = os.getenv("PARALLEL_API_KEY")
    if not key:
        raise RuntimeError("PARALLEL_API_KEY missing in .env")
    r = requests.post(url, headers={"x-api-key": key, "Content-Type": "application/json"},
                      json=body, timeout=45)
    if r.status_code >= 400:
        raise RuntimeError(f"Parallel {r.status_code}: {r.text[:300]}")
    return r.json()


def _gender_word(prefs: dict) -> str:
    return {"women": "women's", "men": "men's"}.get(prefs.get("gender", "any"), "")


def _search_site(site_name: str, desc: dict, prefs: dict, strict_color: bool) -> list[dict]:
    """One Parallel search for one site. Returns raw results tagged with the site."""
    item = desc.get("item", "")
    color = desc.get("color", "") if strict_color else ""
    size, budget = prefs.get("size", ""), prefs.get("max_price") or 100
    who = _gender_word(prefs)
    core = " ".join(x for x in (color, desc.get("details", ""), item) if x)
    domain = SITES[site_name]

    if domain:
        queries = [f"{core} {who} size {size} {domain}", f"{color} {item} {domain}".strip()]
        where = f"on {domain}.com product listing pages"
    else:
        queries = [f"buy {core} {who} size {size} under ${budget:.0f}", f"{core} {who} on sale"]
        where = "on online stores (Google Shopping style product pages)"

    objective = (f"Find individual product listings currently for sale {where} for: "
                 f"{desc.get('summary', core)}. {who} size {size}, priced under ${budget:.0f}. "
                 f"Prefer pages that show the item's price.")
    data = _parallel_post(PARALLEL_SEARCH_URL,
                          {"objective": objective, "search_queries": queries, "mode": "fast"})
    results = data.get("results", [])
    for r in results:
        r["_site"] = site_name
    return results


PRICE_RE = re.compile(r"(?:US\s?)?\$\s?(\d{1,4}(?:,\d{3})?(?:\.\d{2})?)")
NOT_LISTING = re.compile(r"/search|[?&](?:_nkw|q)=|/sch/|/b/|/category|/collections?/", re.I)


def _find_price(text: str) -> float | None:
    for m in PRICE_RE.finditer(text):
        value = float(m.group(1).replace(",", ""))
        if 3 <= value <= 2000:
            return value
    return None


def _site_label(url: str, fallback: str) -> str:
    host = urlparse(url).netloc.lower()
    if "thredup" in host:
        return "ThredUp"
    if "ebay" in host:
        return "eBay"
    name = host.replace("www.", "").split(".")[0]
    return name.title() if name else fallback


def _check(result: dict, desc: dict, prefs: dict, strict_color: bool) -> dict | None:
    """The 'does this match?' check. Returns a listing, or None if it fails."""
    url, title = result.get("url", ""), (result.get("title") or "").strip()
    excerpts = " ".join(result.get("excerpts") or [])
    text = f"{title} {excerpts}".lower()
    if not url or NOT_LISTING.search(url):
        return None

    price = _find_price(f"{title} {excerpts}")
    budget = prefs.get("max_price") or 100
    if price is None or price > budget:
        return None

    item_word = (desc.get("item", "").split() or [""])[-1].lower()  # "bomber jacket" -> "jacket"
    if item_word and item_word.rstrip("s") not in text:
        return None

    color = desc.get("color", "").lower()
    color_ok = bool(color) and color in text
    if strict_color and color and not color_ok:
        return None

    size = str(prefs.get("size", "")).lower()
    size_ok = bool(size) and bool(re.search(rf"\bsize\s*{re.escape(size)}\b", text))

    why = []
    if color:
        why.append(f"{color} ✓" if color_ok else "color may differ")
    if item_word:
        why.append(f"{item_word} ✓")
    if size:
        why.append(f"size {prefs['size']} ✓" if size_ok else f"check size {prefs['size']}")
    why.append(f"${price:.2f} ≤ ${budget:.0f}")

    return {
        "title": title or "Listing",
        "price": price,
        "site": _site_label(url, result.get("_site", "Web")),
        "url": url,
        "image_url": None,
        "size": prefs.get("size", ""),
        "why": " · ".join(why),
        "_score": 2 * color_ok + size_ok,
    }


def _add_image(listing: dict) -> None:
    """Parallel Image Search: find a photo for a listing (best effort)."""
    try:
        data = _parallel_post(PARALLEL_IMAGE_URL, {
            "objective": f"Product photo of: {listing['title']}",
            "search_queries": [listing["title"]],
            "mode": "fast",
        })
        results = data.get("results", [])
        host = urlparse(listing["url"]).netloc
        same_page = [i for i in results if i.get("source_page_url") == listing["url"]]
        same_site = [i for i in results if urlparse(i.get("source_page_url", "")).netloc == host]
        pick = (same_page or same_site or [{}])[0]  # never show a photo from another store
        listing["image_url"] = pick.get("image_url")
    except Exception as e:
        log.info("image search skipped: %s", e)


def find_matches(description: dict, prefs: dict, limit: int = 5) -> list[dict]:
    """
    The checking loop:
      pass 1: strict  - price within budget, item type matches, color matches
      pass 2: relaxed - same, but color may differ (only if pass 1 found nothing)
    """
    matches = []
    for strict_color in (True, False):
        raw = []
        with ThreadPoolExecutor(max_workers=len(SITES)) as pool:
            jobs = [pool.submit(_search_site, s, description, prefs, strict_color) for s in SITES]
            for job in jobs:
                try:
                    raw.extend(job.result())
                except Exception as e:
                    log.warning("search failed for one site: %s", e)

        seen, matches = set(), []
        for r in raw:
            listing = _check(r, description, prefs, strict_color)
            if listing and listing["url"] not in seen:
                seen.add(listing["url"])
                matches.append(listing)

        log.info("pass %s: %d raw results, %d matched",
                 "strict" if strict_color else "relaxed", len(raw), len(matches))
        if matches or not description.get("color"):
            break

    matches.sort(key=lambda m: (-m["_score"], m["price"]))
    top = matches[:limit]
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(_add_image, top[:3]))
    for m in top:
        m.pop("_score", None)
    return top


# ===========================================================================
# Step 10: save findings (local CSV now; Composio + Google Sheets later)
# ===========================================================================
def save_findings(user_name: str, record_id: str, listings: list[dict],
                  favorite: bool = False) -> bool:
    try:
        new_file = not FINDINGS_CSV.exists()
        with FINDINGS_CSV.open("a", newline="") as f:
            w = csv.writer(f)
            if new_file:
                w.writerow(["time", "user", "record_id", "favorite", "title", "price", "site", "url"])
            for item in listings:
                w.writerow([datetime.now().isoformat(timespec="seconds"), user_name, record_id,
                            "yes" if favorite else "", item["title"], item["price"],
                            item["site"], item["url"]])
        return True
    except Exception as e:
        log.warning("save failed: %s", e)
        return False
