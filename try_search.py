"""
Test the search WITHOUT Telegram.

  python try_search.py "green bomber jacket"
  python try_search.py "black leather boots" --size 8 --budget 80 --gender women
"""
import argparse
import logging
import time

import backend

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

p = argparse.ArgumentParser()
p.add_argument("item", help='e.g. "green bomber jacket"')
p.add_argument("--size", default="M")
p.add_argument("--budget", type=float, default=50)
p.add_argument("--gender", default="any", choices=["women", "men", "any"])
a = p.parse_args()

desc = backend._fallback_description(a.item)
prefs = {"gender": a.gender, "size": a.size, "max_price": a.budget}
print(f"\nSearching for: {desc['summary']} | {prefs}\n")

start = time.time()
results = backend.find_matches(desc, prefs)
print(f"\n{len(results)} match(es) in {time.time() - start:.1f}s\n")
for i, r in enumerate(results, 1):
    print(f"{i}. ${r['price']:.2f}  {r['site']}  {r['title']}")
    print(f"   {r['why']}")
    print(f"   {r['url']}")
    print(f"   image: {r['image_url']}\n")
