import json
import os
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests
from dateutil import parser as date_parser

# Import extractors
from extractors.anthropic import AnthropicExtractor

CONFIG_FILE = "config/crawled_feeds.json"
HISTORY_FILE = "crawl_history.json"
TARGET_TZ = ZoneInfo("Asia/Tehran")

# --- Registry ---

EXTRACTORS = {"anthropic": AnthropicExtractor}

# --- Utils ---


def format_date_for_display(dt_utc: datetime) -> str:
    try:
        dt_local = dt_utc.astimezone(TARGET_TZ)
        return dt_local.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "Unknown Date"


def send_telegram_message(entry: dict, blog_name: str) -> bool:
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    topic_id = os.environ.get("TELEGRAM_BLOG_TOPIC_ID")

    if not bot_token or not chat_id:
        print("Error: Missing Telegram secrets.")
        return False

    title = entry.get("title", "No Title")
    link = entry.get("link", "")
    summary = entry.get("summary", "")
    published_str = entry.get("published_at", "")

    # Parse Date
    published_display = "Unknown Date"
    if published_str:
        try:
            dt = date_parser.parse(published_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            published_display = format_date_for_display(dt)
        except Exception:
            pass

    # Format tags
    tags = entry.get("metadata", {}).get("tags", [])
    tags_str = f"🏷 <i>{', '.join(tags)}</i>\n\n" if tags else ""

    summary_section = f"{summary}\n\n" if summary else ""

    message = (
        f"🕷 <b>{blog_name}</b>\n\n"
        f"<a href='{link}'><b>{title}</b></a>\n\n"
        f"{tags_str}"
        f"{summary_section}"
        f"📅 {published_display}\n"
    )

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "message_thread_id": topic_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }

    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        print(f"Sent notification for: {title}")
        return True
    except Exception as e:
        print(f"Failed to send Telegram message: {e}")
        return False


def load_history() -> dict:
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    return {}


def save_history(history: dict) -> None:
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f)


def check_crawlers() -> None:
    if not os.path.exists(CONFIG_FILE):
        print(f"Error: Config file not found at {CONFIG_FILE}")
        return

    with open(CONFIG_FILE, "r") as f:
        feeds = json.load(f)

    history = load_history()
    updated_history = False

    for feed_config in feeds:
        name = feed_config["name"]
        url = feed_config["url"]
        extractor_key = feed_config.get("extractor")

        if extractor_key not in EXTRACTORS:
            print(f"Unknown extractor '{extractor_key}' for {name}")
            continue

        extractor = EXTRACTORS[extractor_key]

        # Initialization check
        is_first_run = name not in history
        if is_first_run:
            history[name] = []
            
        print(f"Crawling {name} ({url})...")

        try:
            # We mimic a browser just in case
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
            resp = requests.get(url, headers=headers)
            resp.raise_for_status()
            html_content = resp.text
        except Exception as e:
            print(f"Failed to fetch {url}: {e}")
            continue

        try:
            items = extractor.extract(html_content)
        except Exception as e:
            print(f"Extraction failed for {name}: {e}")
            continue

        # First Run Logic:
        # If this is the first run, we want to capture everything as "seen" EXCEPT the very latest item.
        # This ensures the user gets ONE notification (for the newest post) to confirm it works,
        # but doesn't get spammed with the entire history.
        if is_first_run and items:
            print(f"[{name}] First run detected. Marking {len(items)-1} older items as seen. Latest item will trigger notification.")
            # Assuming items[0] is the newest. Add everything else to history.
            for item in items[1:]:
                lnk = item.get("link")
                if lnk:
                    history[name].append(lnk)

        # Reverse to process oldest first (assuming extractor returns newest first)
        for item in reversed(items):
            link = item.get("link")
            if not link:
                continue
            
            # Use link as unique ID
            if link in history[name]:
                continue
            
            print(f"New entry found: {item.get('title')}")
            success = send_telegram_message(item, name)
            if success:
                history[name].append(link)
                updated_history = True
                time.sleep(1)

        # Keep history manageable
        if len(history[name]) > 50:
            history[name] = history[name][-50:]

    if updated_history:
        save_history(history)


if __name__ == "__main__":
    check_crawlers()