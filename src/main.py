#!/usr/bin/env python3
"""Ragnarok Market Watcher — entry point.

Usage
─────
  python main.py run               Start monitoring all configured rules
  python main.py add <rule>        Add a watch rule
  python main.py remove <rule>     Remove a watch rule
  python main.py list              List all configured rules

Rule format
───────────
  <Item Name> > <Price>   — alert when any listing price  >=  target (minus variance)
  <Item Name> < <Price>   — alert when any listing price  <=  target (plus  variance)

Examples
────────
  python main.py add "Elunium > 30000"
  python main.py add "Oridecon < 15000"
  python main.py add "Mastela Fruit > 50000"
  python main.py run
"""

import asyncio
import json
import logging
import signal
import sys
from pathlib import Path

from discord_notifier import DiscordNotifier
from monitor import Monitor
from parser import WatchRule, parse_rule
from playwright_provider import PlaywrightProvider
from sound_notifier import SoundNotifier

# ── File paths ────────────────────────────────────────────────────────────────
SRC_DIR = Path(__file__).parent          # .../Rag/src/
ROOT_DIR = SRC_DIR.parent                # .../Rag/
CONFIG_PATH = ROOT_DIR / "config.json"  # kept in root alongside the bat
WATCHES_PATH = ROOT_DIR / "watches.json"
LOG_DIR = SRC_DIR / "logs"

# ── Default configuration ─────────────────────────────────────────────────────
DEFAULT_CONFIG: dict = {
    "base_url": "https://ro.gnjoylatam.com/pt/intro/shop-search/trading",
    "discord_token": "",
    "channel_id": "",
    "user_mention": "",
    "poll_interval": 60,
    "variance_percent": 1.0,
    "store_type": "BUY",
    "server_type": "FREYA",
    "max_pages": 1,
    "headless": True,
    "browser_timeout": 30000,
    "local_sound": False,
}


def setup_logging() -> None:
    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(LOG_DIR / "ragwatch.log", encoding="utf-8"),
        ],
    )


# ── Config / watches I/O ──────────────────────────────────────────────────────

def load_config() -> dict:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")
        print(f"Created default config at {CONFIG_PATH}")
        print("Please fill in 'discord_token' and 'channel_id' before running.")
        sys.exit(0)
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def load_watches() -> list[str]:
    if not WATCHES_PATH.exists():
        WATCHES_PATH.write_text(json.dumps([], indent=2), encoding="utf-8")
        return []
    return json.loads(WATCHES_PATH.read_text(encoding="utf-8"))


def save_watches(watches: list[str]) -> None:
    WATCHES_PATH.write_text(json.dumps(watches, indent=2), encoding="utf-8")


def build_rules() -> list[WatchRule]:
    """Load watches.json and parse it into rules, skipping invalid lines.

    Called fresh at the start of every monitor loop so edits made to
    watches.json while the bot is running take effect on the next cycle.
    """
    rules: list[WatchRule] = []
    for raw in load_watches():
        try:
            rules.append(parse_rule(raw))
        except ValueError as exc:
            print(f"Skipping invalid rule '{raw}': {exc}")
    return rules


# ── Sub-commands ──────────────────────────────────────────────────────────────

def cmd_add(args: list[str]) -> None:
    rule_str = " ".join(args)
    try:
        rule = parse_rule(rule_str)
    except ValueError as exc:
        print(f"Error: {exc}")
        sys.exit(1)

    watches = load_watches()
    if rule_str in watches:
        print(f"Rule already exists: {rule_str}")
        return

    watches.append(rule_str)
    save_watches(watches)
    print(f"Added: {rule.raw}")


def cmd_remove(args: list[str]) -> None:
    rule_str = " ".join(args)
    watches = load_watches()
    if rule_str not in watches:
        print(f"Rule not found: {rule_str!r}")
        sys.exit(1)

    watches.remove(rule_str)
    save_watches(watches)
    print(f"Removed: {rule_str}")


def cmd_list() -> None:
    watches = load_watches()
    if not watches:
        print("No watch rules configured.")
        return
    print(f"Active watch rules ({len(watches)}):")
    for i, w in enumerate(watches, 1):
        print(f"  {i}. {w}")


# ── Monitor runner ────────────────────────────────────────────────────────────

async def run_monitor(config: dict, load_rules) -> None:
    provider = PlaywrightProvider(
        headless=bool(config.get("headless", True)),
        timeout=int(config.get("browser_timeout", 30_000)),
        page_delay=float(config.get("page_delay", 3.0)),
    )
    if config.get("local_sound", False):
        notifier = SoundNotifier(user_mention=config.get("user_mention", ""))
    else:
        notifier = DiscordNotifier(
            token=config["discord_token"],
            channel_id=int(config["channel_id"]),
            user_mention=config.get("user_mention", ""),
        )
    monitor = Monitor(provider=provider, notifier=notifier, config=config)

    await provider.setup()
    await notifier.start()

    loop = asyncio.get_running_loop()

    def _shutdown(sig_name: str) -> None:
        logging.getLogger(__name__).info("Shutdown signal received (%s)", sig_name)
        for task in asyncio.all_tasks(loop):
            task.cancel()

    # Signal handlers — not supported on Windows; fall back to KeyboardInterrupt
    try:
        loop.add_signal_handler(signal.SIGINT, _shutdown, "SIGINT")
        loop.add_signal_handler(signal.SIGTERM, _shutdown, "SIGTERM")
    except (NotImplementedError, AttributeError):
        pass  # Windows: Ctrl-C raises KeyboardInterrupt which cancels the gather

    try:
        await monitor.run(load_rules)
    except (asyncio.CancelledError, KeyboardInterrupt):
        logging.getLogger(__name__).info("Monitor stopped.")
    finally:
        await provider.teardown()
        await notifier.close()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    args = sys.argv[1:]
    setup_logging()

    config = load_config()

    if not args or args[0] == "run":
        rules = build_rules()
        if not rules:
            print("No watch rules found.")
            print("Add one with:  python main.py add \"Elunium > 30000\"")
            sys.exit(0)

        if not config.get("local_sound", False):
            if not config.get("discord_token"):
                print("Error: 'discord_token' is empty in config.json")
                sys.exit(1)
            if not config.get("channel_id"):
                print("Error: 'channel_id' is empty in config.json")
                sys.exit(1)

        print(f"Starting monitor with {len(rules)} rule(s). Press Ctrl+C to stop.")
        print("watches.json is re-read at the start of every cycle — edit it anytime.")
        try:
            asyncio.run(run_monitor(config, build_rules))
        except KeyboardInterrupt:
            print("\nStopped.")

    elif args[0] == "add":
        cmd_add(args[1:])

    elif args[0] == "remove":
        cmd_remove(args[1:])

    elif args[0] == "list":
        cmd_list()

    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
