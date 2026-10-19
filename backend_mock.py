"""
backend.py — the CONTRACT between the Telegram bot (your part) and teammates.

The bot only calls these four functions. They return FAKE data now so the bot
can be built and demoed immediately. Each teammate replaces the inside of one
function and keeps the same inputs and outputs.

  Plan step  | Function            | Owner (teammate)
  -----------|---------------------|-------------------------------
  3          | save_photo_record   | Composio + Google Sheets
  4          | describe_item       | Vision model (Kimi)
  7, 8, 9    | find_matches        | Parallel search + checking loop
  10         | save_findings       | Composio + Google Sheets

Shapes:

  description = {
      "item": "bomber jacket",
      "color": "olive",
      "material": "nylon",
      "details": "cropped, ribbed cuffs",
      "summary": "Olive cropped nylon bomber jacket with ribbed cuffs"
  }

  prefs = {"gender": "women" | "men" | "any", "size": "M", "max_price": 50.0}

  listing = {
      "title": "Olive Nylon Bomber Jacket",
      "price": 34.0,
      "site": "ThredUp",
      "url": "https://...",
      "image_url": "https://..." or None,
      "size": "M",
      "why": "Same color and cut, size M, under budget"   # from the check loop
  }
"""

import time
import uuid


def save_photo_record(user_name: str, image_bytes: bytes, focus: str) -> str:
    """Step 3. Log the request; return a record id used later in save_findings."""
    record_id = uuid.uuid4().hex[:8]
    print(f"[mock] record {record_id} for {user_name}: focus='{focus}'")
    return record_id


def describe_item(image_bytes: bytes, focus: str) -> dict:
    """Step 4. Describe ONLY the item named in `focus`. Never describe the person."""
    time.sleep(1)
    return {
        "item": "bomber jacket",
        "color": "olive",
        "material": "nylon",
        "details": "cropped, ribbed cuffs",
        "summary": "Olive cropped nylon bomber jacket with ribbed cuffs",
    }


def find_matches(description: dict, prefs: dict, limit: int = 5) -> list[dict]:
    """Steps 7-9. Search, check each result against description + prefs, best first."""
    time.sleep(2)
    color, item = description.get("color", ""), description.get("item", "item")
    size, budget = prefs.get("size", "M"), prefs.get("max_price") or 999
    fake = [
        {"title": f"{color.title()} {item.title()}, like new", "price": 31.0, "site": "ThredUp"},
        {"title": f"Vintage {color} {item}", "price": 38.0, "site": "eBay"},
        {"title": f"{color.title()} cropped {item}", "price": 45.0, "site": "eBay"},
        {"title": f"Designer {color} {item}", "price": 120.0, "site": "Google Shopping"},
    ]
    out = []
    for i, r in enumerate(fake):
        if r["price"] > budget:
            continue
        r.update(url=f"https://example.com/listing/{i}", image_url=None, size=size,
                 why=f"Same {color} color and style, size {size}, under ${budget:.0f}")
        out.append(r)
    return out[:limit]


def save_findings(user_name: str, record_id: str, listings: list[dict],
                  favorite: bool = False) -> bool:
    """Step 10. Save results (or one favorite) to the spreadsheet."""
    tag = "FAVORITE" if favorite else f"{len(listings)} results"
    print(f"[mock] saved {tag} for record {record_id} ({user_name})")
    return True
