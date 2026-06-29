#!/usr/bin/env python3
"""Boot-time script: reads Discord settings from DB, fetches the new public IP
from EC2 instance metadata, and posts a notification to the Discord channel.
Also clears the rate-limit backoff so the collector retries immediately."""
import asyncio
import sqlite3
import sys
import urllib.request
from pathlib import Path

DB_PATH = Path(__file__).parent / "market_intel.db"
IMDS = "http://169.254.169.254/latest"


def imds_get(path: str) -> str:
    tok_req = urllib.request.Request(
        f"{IMDS}/api/token",
        method="PUT",
        headers={"X-aws-ec2-metadata-token-ttl-seconds": "21600"},
    )
    with urllib.request.urlopen(tok_req, timeout=5) as r:
        token = r.read().decode()
    req = urllib.request.Request(
        f"{IMDS}/meta-data/{path}",
        headers={"X-aws-ec2-metadata-token": token},
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.read().decode()


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "SELECT discord_token, channel_id, user_mention "
            "FROM notification_settings WHERE id = 1"
        ).fetchone()

        # Clear rate-limit backoff so collector retries immediately on the new IP.
        # Sets retry_requested in case the collector is already sleeping;
        # zeroes consecutive_rate_limits so it won't backoff on next startup.
        conn.execute(
            "UPDATE collector_status SET consecutive_rate_limits = 0, retry_requested = 1"
        )
        conn.commit()
    finally:
        conn.close()

    if not row or not row[0] or not row[1]:
        print("No Discord token/channel configured — skipping notification.")
        sys.exit(0)

    discord_token, channel_id, user_mention = row
    public_ip = imds_get("public-ipv4")

    mention = f"{user_mention} " if user_mention else ""
    content = (
        f"{mention}**[Market Intel]** Instance restarted with new IP: `{public_ip}`\n"
        f"Frontend: http://{public_ip}:3000"
    )

    import discord

    async def _send() -> None:
        intents = discord.Intents.none()
        client = discord.Client(intents=intents)

        @client.event
        async def on_ready() -> None:
            try:
                ch = await client.fetch_channel(int(channel_id))
                await ch.send(content)
                print(f"Sent to channel {channel_id}: {content!r}")
            finally:
                await client.close()

        await client.start(discord_token)

    asyncio.run(_send())


if __name__ == "__main__":
    main()
