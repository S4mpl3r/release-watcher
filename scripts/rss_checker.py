import os
import json
import time
import argparse
from datetime import datetime, timedelta, timezone
from dateutil import parser as date_parser
import feedparser
import requests
from bs4 import BeautifulSoup

CONFIG_FILE = "config/feeds.json"
HISTORY_FILE = "rss_history.json"

def clean_summary(html_content: str, word_limit: int = 50) -> str:
    if not html_content:
        return ""
    soup = BeautifulSoup(html_content, "html.parser")
    text = soup.get_text(separator=" ")
    words = text.split()
    if len(words) > word_limit:
        return " ".join(words[:word_limit]) + "..."
    return " ".join(words)

def send_telegram_message(entry: dict, blog_name: str) -> bool:
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    topic_id = os.environ.get("TELEGRAM_BLOG_TOPIC_ID")

    if not bot_token or not chat_id:
        print("Error: Missing Telegram secrets.")
        return False

    title = entry.get('title', 'No Title')
    link = entry.get('link', '')
    published = entry.get('published', 'Unknown Date')
    
    # Get and clean summary
    raw_summary = entry.get('summary', entry.get('description', ''))
    summary = clean_summary(raw_summary)

    # Format summary as a quote if it exists
    summary_section = ""
    if summary:
        summary_section = f"<blockquote>{summary}</blockquote>\n\n"

    # Construct Message
    message = (
        f"📰 <b>{blog_name}</b>\n\n"
        f"<b>{title}</b>\n\n"
        f"{summary_section}"
        f"📅 {published}\n"
        f"🔗 <a href='{link}'>Read Post</a>"
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

def save_history(history) -> None:
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

        # Logic: If running in "frequent" mode, skip blogs that aren't marked "twice_daily"
        if mode == "frequent" and frequency != "twice_daily":
            continue

        print(f"Checking {name}...")
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            print(f"Failed to parse {url}: {e}")
            continue
        
        # Lookback window (backup safety net)
        hours_lookback = 30 
        time_threshold = now - timedelta(hours=hours_lookback)

        for entry in feed.entries:
            # 1. Get Unique ID (prefer 'id', fallback to 'link')
            post_id = entry.get('id', entry.get('link'))
            
            # 2. Check cache (history) to prevent duplicates
            if post_id in history[name]:
                continue

            # 3. Parse Date
            if 'published' in entry:
                entry_date_str = entry.published
            elif 'updated' in entry:
                entry_date_str = entry.updated
            else:
                continue

            try:
                entry_date = date_parser.parse(entry_date_str)
                if entry_date.tzinfo is None:
                    entry_date = entry_date.replace(tzinfo=timezone.utc)
                else:
                    entry_date = entry_date.astimezone(timezone.utc)
            except Exception:
                continue

            # 4. Check Time Window
            if entry_date > time_threshold:
                print(f"New post found: {entry.get('title')}")
                success = send_telegram_message(entry, name)
                
                if success:
                    history[name].append(post_id)
                    updated_history = True
                    time.sleep(1) # Prevent rate limiting

        # Keep history file small (last 20 posts per blog)
        if len(history[name]) > 20:
            history[name] = history[name][-20:]

    if updated_history:
        save_history(history)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['all', 'frequent'], required=True)
    args = parser.parse_args()
    check_feeds(args.mode)
