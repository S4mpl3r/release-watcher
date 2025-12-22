import argparse
import json
import os
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import feedparser
import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

CONFIG_FILE = "config/blog_feeds.json"
HISTORY_FILE = "rss_history.json"
TARGET_TZ = ZoneInfo("Asia/Tehran")


def clean_summary(html_content: str, word_limit: int = 50) -> str:
    if not html_content:
        return ""
    soup = BeautifulSoup(html_content, "html.parser")
    text = soup.get_text(separator=" ")
    words = text.split()
    if len(words) > word_limit:
        return " ".join(words[:word_limit]) + "..."
    return " ".join(words)


def get_entry_date(entry) -> datetime:
    """
    Helper to extract, parse, and normalize the date to UTC.
    Returns a datetime object or None.
    """
    if "published" in entry:
        date_str = entry.published
    elif "updated" in entry:
        date_str = entry.updated
    else:
        return None

    try:
        dt = date_parser.parse(date_str)
        # Ensure it is aware of timezone (UTC)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
    except Exception:
        return None


def format_date_for_display(dt_utc: datetime) -> str:
    """
    Converts UTC datetime object to Target Timezone string.
    """
    try:
        dt_local = dt_utc.astimezone(TARGET_TZ)
        # Format: 2024-05-20 18:30
        return dt_local.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "Unknown Date"


def send_telegram_message(
    entry: dict, blog_name: str, dt_utc: datetime, rhash: str = None
) -> bool:
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    topic_id = os.environ.get("TELEGRAM_BLOG_TOPIC_ID")

    if not bot_token or not chat_id:
        print("Error: Missing Telegram secrets.")
        return False

    title = entry.get("title", "No Title")
    original_link = entry.get("link", "")
    
    # Instant View Logic
    final_link = original_link
    if rhash and original_link:
        # Encode original link if necessary, but usually raw works with Telegram if clean.
        # Ideally we should urllib.parse.quote it, but let's trust requests/telegram to handle basic URLs.
        # Actually, best to be safe with urllib.parse.quote for the query param.
        import urllib.parse
        encoded_url = urllib.parse.quote(original_link)
        final_link = f"https://t.me/iv?url={encoded_url}&rhash={rhash}"

    # Get clean summary
    raw_summary = entry.get("summary", entry.get("description", ""))
    summary = clean_summary(raw_summary)

    # Format summary as quote
    summary_section = ""
    if summary:
        summary_section = f"{summary}\n\n"

    # Format Date to Tehran Time
    if dt_utc:
        published_display = format_date_for_display(dt_utc)
    else:
        published_display = "Unknown Date"

    # Construct Message
    # Note: We use final_link (IV) for the title, so users stay in Telegram.
    message = (
        f"📰 <b>{blog_name}</b>\n\n"
        f"<a href='{final_link}'><b>{title}</b></a>\n\n"
        f"{summary_section}"
        f"📅 {published_display}\n"
    )

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "message_thread_id": topic_id,
        "text": message,
        "parse_mode": "HTML",
        "link_preview_options": {"url": final_link},
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


def check_feeds() -> None:
    if not os.path.exists(CONFIG_FILE):
        print(f"Error: Config file not found at {CONFIG_FILE}")
        return

    with open(CONFIG_FILE, "r") as f:
        feeds = json.load(f)

    history = load_history()
    now_utc = datetime.now(timezone.utc)

    # Get current time in Tehran to decide if we should run daily checks
    now_tehran = datetime.now(TARGET_TZ)
    current_hour_tehran = now_tehran.hour

    # We consider it the "Morning Run" if it is between 5am and 7am Tehran time
    # (Allowing wiggle room for GitHub Action delays)
    is_morning_run = 5 <= current_hour_tehran < 7

    print(
        f"Current Tehran time: {now_tehran.strftime('%H:%M')}. Morning Run: {is_morning_run}"
    )

    updated_history = False

    for feed_config in feeds:
        name = feed_config["name"]
        url = feed_config["url"]
        check_hours = feed_config.get("check_hours", 24)
        rhash = feed_config.get("rhash")

        # LOGIC CHANGE:
        # If the blog is set to check every 24 hours (or more),
        # ONLY check it if we are in the "Morning Run" window.
        if check_hours >= 24 and not is_morning_run:
            print(f"Skipping {name} (Scheduled for 6:00 AM only)")
            continue

        if name not in history:
            history[name] = []

        # SAFETY CHANGE:
        # If we check every 4 hours, looking back exactly 4 hours + 1 is risky.
        # If GitHub delays by 10 mins, you might miss a post.
        # Since we have a history file to prevent duplicates,
        # we can look back further (e.g., 3x the interval) to be safe.
        lookback_hours = check_hours * 3

        print(f"Checking {name} (Lookback window: {lookback_hours}h)...")

        try:
            feed = feedparser.parse(url)
        except Exception as e:
            print(f"Failed to parse {url}: {e}")
            continue

        time_threshold = now_utc - timedelta(hours=lookback_hours)
        entries_to_send = []

        for entry in feed.entries:
            post_id = entry.get("id", entry.get("link"))

            if post_id in history[name]:
                continue

            entry_date = get_entry_date(entry)

            if not entry_date:
                continue

            if entry_date > time_threshold:
                entries_to_send.append((entry_date, entry, post_id))

        entries_to_send.sort(key=lambda x: x[0])

        for entry_date, entry, post_id in entries_to_send:
            print(f"New post found: {entry.get('title')}")

            success = send_telegram_message(entry, name, entry_date, rhash)

            if success:
                history[name].append(post_id)
                updated_history = True
                time.sleep(1)

        # Keep history manageable
        if len(history[name]) > 50:  # Increased buffer slightly
            history[name] = history[name][-50:]

    if updated_history:
        save_history(history)


if __name__ == "__main__":
    check_feeds()
