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

CONFIG_FILE = "config/youtube_feeds.json"
HISTORY_FILE = "youtube_history.json"
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
    if "published" in entry:
        date_str = entry.published
    elif "updated" in entry:
        date_str = entry.updated
    else:
        return None

    try:
        dt = date_parser.parse(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
    except Exception:
        return None


def format_date_for_display(dt_utc: datetime) -> str:
    try:
        dt_local = dt_utc.astimezone(TARGET_TZ)
        return dt_local.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "Unknown Date"


def send_telegram_message(entry: dict, channel_name: str, dt_utc: datetime) -> bool:
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    topic_id = os.environ.get("TELEGRAM_YOUTUBE_TOPIC_ID")

    if not bot_token or not chat_id:
        print("Error: Missing Telegram secrets.")
        return False

    title = entry.get("title", "No Title")
    link = entry.get("link", "")

    video_id = entry.get("yt_videoid", "")
    thumbnail_url = ""
    if video_id:
        thumbnail_url = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
    elif hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
        thumbnail_url = entry.media_thumbnail[0]["url"]

    raw_summary = ""
    if hasattr(entry, "media_description"):
        raw_summary = entry.media_description
    else:
        raw_summary = entry.get("summary", entry.get("description", ""))

    summary = clean_summary(raw_summary, word_limit=80)

    summary_section = ""
    if summary:
        summary_section = f"{summary}\n\n"

    if dt_utc:
        published_display = format_date_for_display(dt_utc)
    else:
        published_display = "Unknown Date"

    message = (
        f"🎥 <b>{channel_name}</b>\n\n"
        f"<a href='{link}'><b>{title}</b></a>\n\n"
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


def check_feeds(mode: str) -> None:
    if not os.path.exists(CONFIG_FILE):
        print(f"Error: Config file not found at {CONFIG_FILE}")
        return

    with open(CONFIG_FILE, "r") as f:
        feeds = json.load(f)

    history = load_history()
    now = datetime.now(timezone.utc)
    updated_history = False

    for feed_config in feeds:
        name = feed_config["name"]
        url = feed_config["url"]
        frequency = feed_config["frequency"]

        if name not in history:
            history[name] = []

        if mode == "frequent" and frequency != "twice_daily":
            continue

        print(f"Checking {name}...")
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            print(f"Failed to parse {url}: {e}")
            continue

        hours_lookback = 30
        time_threshold = now - timedelta(hours=hours_lookback)

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
            print(f"New video found: {entry.get('title')}")

            success = send_telegram_message(entry, name, entry_date)

            if success:
                history[name].append(post_id)
                updated_history = True
                time.sleep(1)

        if len(history[name]) > 20:
            history[name] = history[name][-20:]

    if updated_history:
        save_history(history)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["all", "frequent"], required=True)
    args = parser.parse_args()
    check_feeds(args.mode)
