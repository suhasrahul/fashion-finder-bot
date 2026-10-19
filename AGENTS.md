# AGENTS.md — Outfit Finder Bot (Telegram part)

Read this fully before writing code. `CLAUDE.md` imports this file.

## 1. The project

A personal agent for fashion in San Francisco. A user sees an outfit on the street, takes a photo, sends it to our Telegram bot with the item they like ("the jacket"), and the agent finds the cheapest matching item in their size and budget on ThredUp, eBay, and Google Shopping, saves findings to a Google Sheet, and shares the top pick. The user can refine ("in green", "under $40").

Built at the Cline, Parallel & Composio Hackathon (Open Source AI Week, SF, Oct 19 2026). Rules: project must be open source (public GitHub repo). Theme: personal agents with Cline, Composio, Parallel, and open-source models. Submissions due 3:15 PM.

## 2. Team plan (agreed steps)

1. User takes a photo (their phone)
2. User sends photo to the bot via Telegram with the item they want → **bot.py**
3. Agent logs the request to the spreadsheet → `save_photo_record` (Composio + Google Sheets)
4. Agent describes the item → `describe_item` (open-source vision model, Kimi)
5. Agent shares the description; user approves or edits → **bot.py**
6. Agent asks gender, size, price (one-tap defaults for demo) → **bot.py**
7–9. Search ThredUp, eBay, Google; loop to check results match the approved terms → `find_matches` (Parallel)
10. Save findings to the spreadsheet → `save_findings` (Composio + Google Sheets)
11. Share the top pick → **bot.py**
12. (Later) learn style and suggest items

## 3. Ownership

- **This developer owns `bot.py`** (the whole Telegram conversation) and integration.
- Teammates own the functions inside `backend.py`. Each replaces the FAKE body of one function with the real version, keeping the exact inputs/outputs.
- Cline is the tool we use to BUILD the project (credit it in the pitch). It is not a runtime step inside the agent.
- Telegram is connected directly with `python-telegram-bot` (long polling). Do NOT route Telegram through Composio. Composio is for Google Sheets.

## 4. The contract (`backend.py`)

```python
save_photo_record(user_name: str, image_bytes: bytes, focus: str) -> str   # record_id
describe_item(image_bytes: bytes, focus: str) -> dict                       # description
find_matches(description: dict, prefs: dict, limit: int = 5) -> list[dict] # listings, best first
save_findings(user_name: str, record_id: str, listings: list[dict], favorite: bool = False) -> bool
```

Shapes:
```python
description = {"item": "bomber jacket", "color": "olive", "material": "nylon",
               "details": "cropped, ribbed cuffs",
               "summary": "Olive cropped nylon bomber jacket with ribbed cuffs"}
prefs = {"gender": "women" | "men" | "any", "size": "M", "max_price": 50.0}
listing = {"title": str, "price": float, "site": str, "url": str,
           "image_url": str | None, "size": str, "why": str}
```

**Never change these signatures or shapes without telling the team.** Adding optional fields is OK.

## 5. Current state (tested)

- `bot.py` works end to end against the fake `backend.py`. A simulated chat covering every stage passed: photo → description → edit → gender → size → typed budget → top pick → next → save → "in black under $100" → restart.
- Conversation stages live in `context.chat_data["stage"]`: `await_photo`, `confirm_desc`, `edit_desc`, `pref_gender`, `pref_size`, `pref_budget`, `results`.
- Slow backend calls run via `asyncio.to_thread` so the bot never freezes. `save_findings` after a search runs in the background.
- Photos are held in memory only, never written to disk by the bot.

## 5b. Backend status (updated)

- `backend.py` is now REAL:
  - `find_matches`: Parallel Search (`POST https://api.parallel.ai/v1/search`, header `x-api-key`, body `objective`, `search_queries`, `mode: "fast"`) once per site (ThredUp, eBay, Google) in parallel threads, then a checking loop: reject search/category pages, price must be found and <= budget, item word must appear, color must match (pass 1 strict; pass 2 relaxes color only if pass 1 found nothing). Sorted by match score then price. Parallel Image Search (`POST /v1/images/search`) adds a photo only from the same website as the listing.
  - `describe_item`: any OpenAI-compatible vision model via VISION_BASE_URL / VISION_API_KEY / VISION_MODEL; falls back to a description from the caption (user can edit it in chat).
  - `save_findings`: appends to `findings.csv` (gitignored). Planned: Composio + Google Sheets.
- `backend_mock.py` = the old fake version, for offline demos (`cp backend_mock.py backend.py` to switch, after backing up).
- `try_search.py "green bomber jacket" --size M --budget 50` tests search without Telegram.
- Parallel response fields used: `results[].url`, `.title`, `.excerpts`; image results: `image_url`, `source_page_url`. If the live API returns different fields, adapt `_check` and `_add_image` only. Docs: https://docs.parallel.ai/llms.txt

## 6. Hard rules

- Python 3.10+. Use a virtual environment in `.venv`.
- `TELEGRAM_BOT_TOKEN` and all keys live in `.env` (gitignored). Never print, log, or commit secrets.
- Privacy: the bot and the vision prompt focus ONLY on clothing, never identify or describe the person. The bot does not save photos to disk. For the demo, use a teammate's outfit with permission.
- Never let the bot crash on stage: every backend call is wrapped in try/except with a friendly message.
- Keep the bot's behavior as is unless asked. Small, focused changes; run and test after each.
- Don't edit a teammate's function body once they've delivered it; ask first.

## 7. Tasks for the coding agent (do in order, report after each)

**T1. Setup.** Create `.venv`, install `requirements.txt`, copy `.env.example` to `.env` if missing. Then stop and ask the human to paste their BotFather token into `.env` (they must do it themselves; never ask them to paste it in chat).

**T2. Offline simulator.** Write `simulate.py` that runs a full fake conversation through `bot.py` handlers with mock Telegram objects (no network) and prints the transcript. It must cover every stage, plus edge cases: text before any photo, photo without caption, tapping old buttons after restart, a budget with no number ("cheap please"), and a backend function raising an exception. Fix any bug it finds in bot.py.

**T3. Backend test harness.** Write `test_backend.py` that calls each of the four contract functions alone with sample inputs (use `sample.jpg` if present, else tiny dummy bytes) and checks the returned shapes match section 4 exactly (types and required keys). Print PASS/FAIL per function. Teammates run this before handing over their code.

**T4. Run the real bot.** `python bot.py`, then guide the human to test on their phone. Help debug anything.

**T5. Integration (when a teammate delivers).** Paste their function into `backend.py`, run `test_backend.py`, then `simulate.py`, then a real phone test. One function at a time. Commit after each.

**T6. Demo polish (only after T1–T5).** Optional ideas, ask before doing: a `/demo` command that runs the flow with default prefs; showing a "checked N listings, kept K" line from find_matches if it provides counts.

## 8. Useful docs

- python-telegram-bot: https://docs.python-telegram-bot.org/ (v21+, async, `Application.builder().token(...).build()`, `run_polling()`)
- Composio (for teammates): https://docs.composio.dev/llms.txt
- Parallel (for teammates): https://docs.parallel.ai/llms.txt (Search, Extract, Image Search)
