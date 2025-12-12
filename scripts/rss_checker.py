import os
import json
import time
import argparse
from zoneinfo import ZoneInfo 
from datetime import datetime, timedelta, timezone
from dateutil import parser as date_parser
import feedparser
import requests
from bs4 import BeautifulSoup

CONFIG_FILE = "config/feeds.json"
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
    if 'published' in entry:
        date_str = entry.published
    elif 'updated' in entry:
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
        return dt_local.strftime('%Y-%m-%d %H:%M')
    except Exception:
        return "Unknown Date"

def send_telegram_message(entry: dict, blog_name: str, dt_utc: datetime) -> bool:
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    topic_id = os.environ.get("TELEGRAM_BLOG_TOPIC_ID")

    if not bot_token or not chat_id:
        print("Error: Missing Telegram secrets.")
        return False

    title = entry.get('title', 'No Title')
    link = entry.get('link', '')
    
    # Get clean summary
    raw_summary = entry.get('summary', entry.get('description', ''))
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
    message = (
        f"📰 <a href='{link}'><b>{blog_name}</b></a>\n\n"
        f"<b>{title}</b>\n\n"
        f"{summary_section}"
        f"📅 {published_display}\n"
    )

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "message_thread_id": topic_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
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
        with open(HISTORY_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_history(history: dict) -> None:
    with open(HISTORY_FILE, 'w') as f:
        json.dump(history, f)

def check_feeds(mode: str) -> None:
    if not os.path.exists(CONFIG_FILE):
        print(f"Error: Config file not found at {CONFIG_FILE}")
        return

    with open(CONFIG_FILE, 'r') as f:
        feeds = json.load(f)
    
    history = load_history()
    now = datetime.now(timezone.utc)
    updated_history = False

    for feed_config in feeds:
        name = feed_config['name']
        url = feed_config['url']
        frequency = feed_config['frequency']

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

        for entry in feed.entries:
            post_id = entry.get('id', entry.get('link'))
            
            if post_id in history[name]:
                continue

            # Parse the date using helper
            entry_date = get_entry_date(entry)
            
            if not entry_date:
                continue

            # Check logic using UTC
            if entry_date > time_threshold:
                print(f"New post found: {entry.get('title')}")
                
                # Pass the date object to the sender for formatting
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
    parser.add_argument('--mode', choices=['all', 'frequent'], required=True)
    args = parser.parse_args()
    check_feeds(args.mode)
