"""
bot.py — Telegram conversation for the outfit finder (YOUR part).

Conversation stages (stored per chat in context.chat_data["stage"]):

  await_photo  -> user sends photo + caption ("the jacket")        plan step 2
  confirm_desc -> bot shows description: ✅ Looks right / ✏️ Edit   plan step 5
  edit_desc    -> user types a corrected description
  pref_gender  -> buttons: Women / Men / Any                        plan step 6
  pref_size    -> buttons: XS S M L XL
  pref_budget  -> buttons: $25 $50 $100, or type a number
  results      -> top pick with ❤️ Save / ➡️ Next / 🔁 New search   plan step 11
                  user can also type "in green", "under $40"

Run:  python bot.py   (needs TELEGRAM_BOT_TOKEN in .env)
"""

import asyncio
import html
import logging
import os
import re

from dotenv import load_dotenv
from telegram import InlineKeyboardButton as Btn
from telegram import InlineKeyboardMarkup as Keys
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

import backend

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("outfit-bot")

# Used by the "Use my usual" button so the demo skips the questions (plan step 6).
DEFAULT_PREFS = {"gender": "any", "size": "M", "max_price": 50.0}

COLORS = ["black", "white", "grey", "gray", "beige", "cream", "brown", "tan", "red",
          "pink", "orange", "yellow", "green", "olive", "blue", "navy", "purple"]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def find_color(text: str) -> str | None:
    t = text.lower()
    for c in COLORS:
        if re.search(rf"\b{c}\b", t):
            return "grey" if c == "gray" else c
    return None


def find_price(text: str) -> float | None:
    m = re.search(r"\$?\s*(\d+(?:\.\d+)?)", text)
    return float(m.group(1)) if m else None


def recolor(desc: dict, color: str) -> None:
    """Swap the color in the description, keeping the other details."""
    old, summary = desc.get("color", ""), desc.get("summary", desc.get("item", ""))
    if old and re.search(rf"\b{re.escape(old)}\b", summary, re.I):
        summary = re.sub(rf"\b{re.escape(old)}\b", color, summary, count=1, flags=re.I)
    else:
        summary = f"{color} {summary}"
    desc["color"], desc["summary"] = color, summary[0].upper() + summary[1:]


def prefs_text(p: dict) -> str:
    gender = "any gender" if p["gender"] == "any" else p["gender"]
    return f"{gender}, size {p['size']}, under ${p['max_price']:.0f}"


def listing_caption(r: dict, n: int, total: int) -> str:
    return (f"⭐ <b>Pick {n} of {total}: ${r['price']:.2f}</b> on {html.escape(r['site'])}\n"
            f"{html.escape(r['title'])}\n"
            f"<i>{html.escape(r.get('why', ''))}</i>\n"
            f"<a href=\"{html.escape(r['url'], quote=True)}\">View listing</a>")


async def typing(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    await context.bot.send_chat_action(chat_id, ChatAction.TYPING)


# ---------------------------------------------------------------------------
# Each stage's message
# ---------------------------------------------------------------------------
async def show_description(context, chat_id: int) -> None:
    """Plan step 5: share the description so the user can approve or edit it."""
    context.chat_data["stage"] = "confirm_desc"
    desc = context.chat_data["description"]
    await context.bot.send_message(
        chat_id,
        f"Here's what I see:\n\n👕 <b>{html.escape(desc['summary'])}</b>\n\nIs that right?",
        parse_mode=ParseMode.HTML,
        reply_markup=Keys([[Btn("✅ Looks right", callback_data="desc_ok"),
                            Btn("✏️ Edit", callback_data="desc_edit")]]))


async def ask_gender(context, chat_id: int) -> None:
    """Plan step 6: preferences, with a one-tap shortcut for the demo."""
    context.chat_data["stage"] = "pref_gender"
    await context.bot.send_message(
        chat_id, "Who's it for?",
        reply_markup=Keys([
            [Btn("Women", callback_data="g:women"), Btn("Men", callback_data="g:men"),
             Btn("Any", callback_data="g:any")],
            [Btn(f"⚡ Use my usual ({prefs_text(DEFAULT_PREFS)})", callback_data="usual")]]))


async def ask_size(context, chat_id: int) -> None:
    context.chat_data["stage"] = "pref_size"
    sizes = ["XS", "S", "M", "L", "XL"]
    await context.bot.send_message(
        chat_id, "What size?",
        reply_markup=Keys([[Btn(s, callback_data=f"s:{s}") for s in sizes]]))


async def ask_budget(context, chat_id: int) -> None:
    context.chat_data["stage"] = "pref_budget"
    await context.bot.send_message(
        chat_id, "Max price? Tap one or type a number.",
        reply_markup=Keys([[Btn(f"${b}", callback_data=f"b:{b}") for b in (25, 50, 100)]]))


async def run_search(context, chat_id: int) -> None:
    """Plan steps 7-11: search, save findings, then show the top pick."""
    data = context.chat_data
    data["stage"] = "results"
    await context.bot.send_message(
        chat_id, f"🔎 Searching ThredUp, eBay and Google for {prefs_text(data['prefs'])}…")
    await typing(context, chat_id)
    try:
        listings = await asyncio.to_thread(backend.find_matches, data["description"], data["prefs"])
    except Exception:
        log.exception("search failed")
        await context.bot.send_message(chat_id, "😕 Search hit a snag. Tap 🔁 or send the photo again.")
        return

    data["listings"], data["index"] = listings, 0
    if listings:
        asyncio.create_task(asyncio.to_thread(  # plan step 10, in the background
            backend.save_findings, data["user"], data["record_id"], listings))
    await show_pick(context, chat_id)


async def show_pick(context, chat_id: int) -> None:
    data = context.chat_data
    listings, i = data.get("listings", []), data.get("index", 0)
    if not listings:
        await context.bot.send_message(
            chat_id, "No matches in that size and budget. Try “under $80” or “in black”.",
            reply_markup=Keys([[Btn("🔁 New search", callback_data="restart")]]))
        return

    r = listings[i]
    buttons = [Btn("❤️ Save", callback_data=f"save:{i}")]
    if i + 1 < len(listings):
        buttons.append(Btn("➡️ Next", callback_data="next"))
    buttons.append(Btn("🔁 New search", callback_data="restart"))
    caption = listing_caption(r, i + 1, len(listings))

    if r.get("image_url"):
        try:
            await context.bot.send_photo(chat_id, r["image_url"], caption=caption,
                                         parse_mode=ParseMode.HTML, reply_markup=Keys([buttons]))
            return
        except Exception:
            log.warning("image failed, sending text instead")
    await context.bot.send_message(chat_id, caption, parse_mode=ParseMode.HTML,
                                   disable_web_page_preview=True, reply_markup=Keys([buttons]))


# ---------------------------------------------------------------------------
# Handlers: photo, text, buttons
# ---------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.chat_data.clear()
    context.chat_data["stage"] = "await_photo"
    await update.message.reply_text(
        "👋 Send me a photo of an outfit and tell me which piece you like "
        "(for example, caption it “the jacket”).\n\n"
        "I only look at the clothing, never the person.")


async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Plan steps 2-4: receive photo, log it, describe the item."""
    chat_id, data = update.effective_chat.id, context.chat_data
    focus = (update.message.caption or "the main clothing item").strip()
    data.clear()
    data.update(user=update.effective_user.first_name or "user", focus=focus)

    await update.message.reply_text(f"👀 Got it, looking at {focus}…")
    await typing(context, chat_id)
    image_bytes = bytes(await (await update.message.photo[-1].get_file()).download_as_bytearray())

    try:
        data["record_id"] = await asyncio.to_thread(
            backend.save_photo_record, data["user"], image_bytes, focus)
        data["description"] = await asyncio.to_thread(backend.describe_item, image_bytes, focus)
    except Exception:
        log.exception("describe failed")
        await update.message.reply_text("😕 I couldn't read that photo. Try a clearer one?")
        data["stage"] = "await_photo"
        return
    await show_description(context, chat_id)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id, data, text = update.effective_chat.id, context.chat_data, update.message.text
    stage = data.get("stage", "await_photo")

    if stage == "edit_desc":
        desc = data["description"]
        desc["summary"] = text.strip()[:1].upper() + text.strip()[1:]
        color = find_color(text)
        if color:
            desc["color"] = color
        await show_description(context, chat_id)

    elif stage == "pref_budget":
        price = find_price(text)
        if price is None:
            await update.message.reply_text("Just a number please, like 40.")
            return
        data["prefs"]["max_price"] = price
        await run_search(context, chat_id)

    elif stage == "results":
        color, price = find_color(text), None
        if re.search(r"under|below|max|\$|cheaper", text.lower()):
            price = find_price(text) or round(data["prefs"]["max_price"] * 0.7, 2)
        if not color and price is None:
            await update.message.reply_text("Try “in green”, “under $40”, or “cheaper”.")
            return
        if color:
            recolor(data["description"], color)
        if price is not None:
            data["prefs"]["max_price"] = price
        await run_search(context, chat_id)

    elif stage in ("confirm_desc", "pref_gender", "pref_size"):
        await update.message.reply_text("👆 Tap one of the buttons above.")
    else:
        await update.message.reply_text("📸 Send me a photo of an outfit to start!")


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    chat_id, data, choice = update.effective_chat.id, context.chat_data, query.data

    if choice == "restart" or "description" not in data:
        data.clear()
        data["stage"] = "await_photo"
        await context.bot.send_message(chat_id, "📸 Send a new photo whenever you're ready.")
        return

    if choice == "desc_ok":
        await ask_gender(context, chat_id)
    elif choice == "desc_edit":
        data["stage"] = "edit_desc"
        await context.bot.send_message(chat_id, "Type the corrected description, e.g. “green cropped bomber jacket”.")
    elif choice == "usual":
        data["prefs"] = dict(DEFAULT_PREFS)
        await run_search(context, chat_id)
    elif choice.startswith("g:"):
        data["prefs"] = {"gender": choice[2:], "size": "M", "max_price": 50.0}
        await ask_size(context, chat_id)
    elif choice.startswith("s:"):
        data["prefs"]["size"] = choice[2:]
        await ask_budget(context, chat_id)
    elif choice.startswith("b:"):
        data["prefs"]["max_price"] = float(choice[2:])
        await run_search(context, chat_id)
    elif choice == "next":
        data["index"] = min(data.get("index", 0) + 1, len(data.get("listings", [])) - 1)
        await show_pick(context, chat_id)
    elif choice.startswith("save:"):
        listing = data["listings"][int(choice[5:])]
        ok = await asyncio.to_thread(backend.save_findings, data["user"],
                                     data["record_id"], [listing], True)
        await context.bot.send_message(chat_id, "❤️ Saved to your favorites!" if ok else "😕 Couldn't save.")


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Missing TELEGRAM_BOT_TOKEN in .env (get one from @BotFather).")
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler(["start", "help"], start))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(CallbackQueryHandler(on_button))
    log.info("Bot running. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
