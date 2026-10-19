# Outfit Finder Bot

Snap an outfit you love, send it to our Telegram bot, and get the cheapest matching piece in your size and budget from ThredUp, eBay, and Google Shopping.

Built with Cline, Parallel, Composio, and open-source models at the Cline, Parallel & Composio Hackathon (Open Source AI Week 2026).

## Run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add TELEGRAM_BOT_TOKEN from @BotFather
python bot.py
```

See AGENTS.md for the architecture and team contract.

## License

MIT
