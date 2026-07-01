import os
import sys
import time
from typing import List
import requests
from job_finder.interfaces import ParsedAnnouncement

def send_notifications(announcements: List[ParsedAnnouncement]) -> None:
    """
    Sends notifications for a list of parsed announcements to Discord and/or Telegram
    if the respective environment variables are configured.
    """
    if not announcements:
        print("ℹ️ No announcements to notify.")
        return

    discord_webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    telegram_bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not discord_webhook_url and not (telegram_bot_token and telegram_chat_id):
        print("ℹ️ No notification channels configured (Discord/Telegram). Skipping notifications.")
        return

    if discord_webhook_url:
        try:
            _send_to_discord(announcements, discord_webhook_url)
        except Exception as e:
            print(f"⚠️ Error sending to Discord: {e}", file=sys.stderr)

    if telegram_bot_token and telegram_chat_id:
        try:
            _send_to_telegram(announcements, telegram_bot_token, telegram_chat_id)
        except Exception as e:
            print(f"⚠️ Error sending to Telegram: {e}", file=sys.stderr)


def _send_to_discord(announcements: List[ParsedAnnouncement], webhook_url: str) -> None:
    """Sends announcements to a Discord Webhook using Rich Embeds, chunked safely to avoid payload limits."""
    print(f"📢 Sending {len(announcements)} notification(s) to Discord...")
    
    # Reduced chunk size to prevent hitting Discord's total character payload ceiling
    chunk_size = 2
    for i in range(0, len(announcements), chunk_size):
        chunk = announcements[i:i + chunk_size]
        embeds = []
        
        for ann in chunk:
            embed = {
                "title": f"📌 {ann.organism.upper()}"[:256],
                "description": ann.description[:2048],
                "color": 3447003,  # Premium Blue color
                "fields": [
                    {
                        "name": "Source / Location",
                        "value": f"{ann.source} (Page/Item {ann.page_number})",
                        "inline": True
                    },
                    {
                        "name": "Keywords Matched",
                        "value": ", ".join(f"`{k}`" for k in ann.matched_keywords)[:1024] or "None",
                        "inline": True
                    }
                ]
            }
            if ann.url:
                embed["url"] = ann.url
                
            embeds.append(embed)

        payload = {
            "content": "🚀 **New IT Job Opportunities Found!**" if i == 0 else "",
            "embeds": embeds
        }
        
        response = requests.post(webhook_url, json=payload, timeout=10)
        response.raise_for_status()
        time.sleep(0.5)  # Politeness delay


def _send_to_telegram(announcements: List[ParsedAnnouncement], bot_token: str, chat_id: str) -> None:
    """Sends announcements to a Telegram Chat one by one using HTML formatting."""
    print(f"📢 Sending {len(announcements)} notification(s) to Telegram...")
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    for ann in announcements:
        # Formulate HTML content
        # Escape HTML entities for safety
        organism = ann.organism.upper().replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        description = ann.description.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if len(description) > 3000:
            description = description[:3000] + "..."

        keywords = ", ".join(f"<code>{k}</code>" for k in ann.matched_keywords)
        
        message_lines = [
            f"📌 <b>{organism}</b>",
            "",
            description,
            "",
            f"🔑 <b>Keywords:</b> {keywords}",
            f"🌐 <b>Source:</b> {ann.source} (Page/Item {ann.page_number})"
        ]

        if ann.url:
            message_lines.append(f"🔗 <a href='{ann.url}'>Link to announcement</a>")

        payload = {
            "chat_id": chat_id,
            "text": "\n".join(message_lines),
            "parse_mode": "HTML",
            "disable_web_page_preview": False
        }

        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        time.sleep(0.5)  # Avoid rate limiting
