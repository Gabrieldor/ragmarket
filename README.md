# Ragnarok Market Watcher

Monitors item listings on the Ragnarok Online LATAM catalog and sends Discord
notifications when price conditions are triggered.

## Data collection method

**Playwright (headless Chrome)**

The catalog site uses Next.js with dynamic content loading and
browser-fingerprinting checks that make plain HTTP requests unreliable.
Playwright runs a real Chromium instance so all JavaScript executes before
scraping begins.  The provider interface (`data_provider.py`) isolates the
scraping logic so switching to an HTTP backend later requires only changing
one line in `main.py`.

---

## Setup

### 1 — Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2 — Configure `config.json`

| Key | Description |
|-----|-------------|
| `discord_token` | Bot token from the Discord Developer Portal |
| `channel_id` | ID of the channel where notifications will be posted |
| `user_mention` | Discord mention string, e.g. `<@987654321>` |
| `poll_interval` | Seconds between checks (default `60`) |
| `variance_percent` | Price tolerance percentage (default `1.0`) |
| `store_type` | `"BUY"` or `"SELL"` (default `"BUY"`) |
| `server_type` | Server name (default `"FREYA"`) |
| `max_pages` | Result pages to scrape per check (default `1`) |
| `headless` | `true` to run Chrome without a visible window |
| `browser_timeout` | Max milliseconds per page load (default `30000`) |

#### How to get your channel ID and user mention

**Channel ID**

1. Open Discord → go to **User Settings → Advanced** and turn on **Developer Mode**
2. Right-click the channel you want notifications in → **Copy Channel ID**
3. Paste the number as the `channel_id` value in `config.json`

**User mention**

1. With Developer Mode enabled, right-click your own username anywhere in Discord → **Copy User ID**
2. Wrap the number in `<@...>` and paste it as the `user_mention` value

```json
{
  "channel_id": "1234567890123456789",
  "user_mention": "<@987654321098765432>"
}
```

> The mention must use the numeric ID wrapped in `<@...>`, **not** your username or tag.
> Discord will turn it into a real ping when the bot posts a message.

### 3 — Add watch rules

```bash
python main.py add "Elunium > 30000"
python main.py add "Oridecon < 15000"
python main.py add "Mastela Fruit > 50000"
```

### 4 — Run

```bash
python main.py run
```

Press **Ctrl+C** to stop.

---

## Rule format

```
<Item Name> > <Price>
<Item Name> < <Price>
```

Operators are treated as `>=` / `<=` internally.  Variance is also applied:

| Rule | Variance 1% | Condition becomes TRUE when |
|------|-------------|----------------------------|
| `Elunium > 30000` | ±300 | any price **≥ 29 700** |
| `Elunium < 30000` | ±300 | any price **≤ 30 300** |

---

## CLI commands

| Command | Description |
|---------|-------------|
| `python main.py run` | Start the monitor |
| `python main.py add "<rule>"` | Add a watch rule |
| `python main.py remove "<rule>"` | Remove a watch rule |
| `python main.py list` | List all watch rules |

---

## Discord notifications

### Condition triggered (FALSE → TRUE)
```
<@user>

🚨 Elunium condition triggered.

Condition:
Elunium >= 30.000

Matching price:
35.000
```

### Condition cleared (TRUE → FALSE)
```
<@user>

✅ Elunium condition is no longer true.

Condition:
Elunium >= 30.000
```

### Price changed (TRUE → TRUE, price moved)
```
<@user>

📈 Elunium price changed.

Previous:
35.000

Current:
42.000
```

---

## Project structure

```
project/
├── main.py                 Entry point & CLI
├── monitor.py              Monitoring orchestration (one asyncio task per rule)
├── parser.py               Rule parsing & price text conversion
├── data_provider.py        Abstract provider interface
├── http_provider.py        HTTP stub (not active — see file for details)
├── playwright_provider.py  Active Playwright implementation + all CSS selectors
├── discord_notifier.py     Discord bot integration
├── config.json             Runtime configuration
├── watches.json            Persisted watch rules
├── requirements.txt
├── README.md
└── logs/
    └── ragwatch.log
```

## Updating selectors

If the site redesigns its HTML, edit only the `SELECTORS` block at the top of
`playwright_provider.py`.  No other file needs to change.
