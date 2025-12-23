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


def parse_date_safe(date_str: str) -> datetime:
    """
    Parses a date string into a timezone-aware datetime object.
    Defaults to epoch if parsing fails, to ensure sortability.
    """
    if not date_str:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    try:
        dt = date_parser.parse(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
    except Exception:
        return datetime.fromtimestamp(0, tz=timezone.utc)


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
            dt = parse_date_safe(published_str)
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
        "link_preview_options": {"url": link},
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

        if name not in history:
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

        if not items:
            continue

        # 1. Sort by Date (Newest First)
        # We try to trust published_at, but fall back to existing order if needed.
        items.sort(key=lambda x: parse_date_safe(x.get("published_at")), reverse=True)

        # 2. Identify New Items
        new_items = []
        for item in items:
            link = item.get("link")
            if not link:
                continue
            if link not in history[name]:
                new_items.append(item)

        if not new_items:
            print(f"[{name}] No new items found.")
            continue

        print(f"[{name}] Found {len(new_items)} new items.")

        # 3. Spam Protection Strategy
        # If we see too many new items (> 3), it's likely a First Run, a Recovery, or a Reset.
        # We only notify for the LATEST one, and mark the rest as seen silently.
        to_send = []
        
        if len(new_items) > 3:
            print(f"[{name}] ⚠️ Spam Protection Triggered! {len(new_items)} items is > 3.")
            print(f"[{name}] Marking older {len(new_items)-1} items as seen silently.")
            
            # The newest item is index 0 (because we sorted Newest First)
            to_send = [new_items[0]]
            
            # Add the rest to history immediately
            for item in new_items[1:]:
                history[name].append(item.get("link"))
            updated_history = True # Mark dirty so we save even if send fails
        else:
            to_send = new_items

        # 4. Send Notifications (Oldest -> Newest)
        # to_send is currently [Newest, ..., Oldest] (subset of sorted items)
        # We want to send chronologically.
        for item in reversed(to_send):
            print(f"New entry found: {item.get('title')}")
            success = send_telegram_message(item, name)
            
            if success:
                history[name].append(item.get("link"))
                updated_history = True
                time.sleep(1)
        
        # Keep history manageable
        if len(history[name]) > 50:
            history[name] = history[name][-50:]

    if updated_history:
        save_history(history)


if __name__ == "__main__":
    check_crawlers()