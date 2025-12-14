import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import feedparser
import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from google.genai import Client, types

CONFIG_FILE = "config/youtube_feeds.json"
HISTORY_FILE = "youtube_history.json"
TARGET_TZ = ZoneInfo("Asia/Tehran")

# --- Helper Functions ---


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
        return dt_local.strftime("%Y-%m-%d %H\u200b:%M")
    except Exception:
        return "Unknown Date"


def is_youtube_short(entry: dict) -> bool:
    link = entry.get("link", "")
    title = entry.get("title", "")
    if "/shorts/" in link:
        return True
    if "#shorts" in title.lower():
        return True
    return False


def get_video_id_from_entry(entry: dict) -> str:
    # Method 1: yt_videoid extension
    if "yt_videoid" in entry:
        return entry.yt_videoid

    # Method 2: Extract from link
    link = entry.get("link", "")
    match = re.search(r"[?&]v=([^&]+)", link)
    if match:
        return match.group(1)

    return None


# --- AI & Transcript Functions ---


def generate_ai_summary(link: str | None) -> str:
    if not link:
        raise ValueError(f"Invalid link: {link}")
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY is missing.")

    client = Client(api_key=api_key)

    system_prompt = (
        "You are an expert content summarizer. Your task is to summarize the following YouTube video. "
        "Strict Constraints:\n"
        "1. The summary must be in English.\n"
        "2. Maximum length is 2 short paragraphs.\n"
        "3. Be direct. Do NOT start with preamble like 'The video discusses'.\n"
        "4. Do NOT include a conclusion.\n"
        "5. Focus on the core insights and takeaways.\n"
    )

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.7,
            max_output_tokens=8192,
            thinking_config=types.ThinkingConfig(
                include_thoughts=False,
                thinking_budget=4096,
            ),
        ),
        contents=[
            types.Content(
                role="user", parts=[types.Part(file_data=types.FileData(file_uri=link))]
            )
        ],
    )

    if response.text:
        return response.text.strip()
    return ""


# --- Notification Function ---


def send_telegram_message(
    entry: dict, channel_name: str, dt_utc: datetime, summary_text: str
) -> bool:
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    topic_id = os.environ.get("TELEGRAM_YOUTUBE_TOPIC_ID")

    if not bot_token or not chat_id:
        print("Error: Missing Telegram secrets.")
        return False

    title = entry.get("title", "No Title")
    link = entry.get("link", "")

    summary_section = f"{summary_text}\n\n" if summary_text else ""
    published_display = format_date_for_display(dt_utc) if dt_utc else "Unknown Date"

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


# --- Main Logic ---


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
    now = datetime.now(timezone.utc)
    updated_history = False

    for feed_config in feeds:
        name = feed_config["name"]
        url = feed_config["url"]

        if name not in history:
            history[name] = []

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

            if is_youtube_short(entry):
                print(f"Skipping YouTube Short: {entry.get('title')}")
                continue

            if entry_date > time_threshold:
                entries_to_send.append((entry_date, entry, post_id))

        entries_to_send.sort(key=lambda x: x[0])

        for entry_date, entry, post_id in entries_to_send:
            title = entry.get("title")
            print(f"New video found: {title}")

            # --- AI Summary Logic ---
            final_summary = ""
            video_id = get_video_id_from_entry(entry)
            used_fallback = True

            if video_id:
                try:
                    print("Attempting to generate summary...")
                    ai_summary = generate_ai_summary(entry.get("link"))
                    if ai_summary:
                        final_summary = f"✨ <b>AI Summary:</b>\n{ai_summary}"
                        used_fallback = False
                except Exception as e:
                    print(
                        f"AI Summary skipped due to: {e}. Reverting to standard description."
                    )
                    used_fallback = True

            if used_fallback:
                raw_summary = entry.get("summary", entry.get("description", ""))
                final_summary = clean_summary(raw_summary, word_limit=80)

            success = send_telegram_message(entry, name, entry_date, final_summary)

            if success:
                history[name].append(post_id)
                updated_history = True
                time.sleep(1)

        if len(history[name]) > 20:
            history[name] = history[name][-20:]

    if updated_history:
        save_history(history)


if __name__ == "__main__":
    check_feeds()
