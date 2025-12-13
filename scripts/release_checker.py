import json
import os
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests
from dateutil import parser as date_parser

CONFIG_FILE = "config/release_repos.json"
HISTORY_FILE = "release_history.json"
TARGET_TZ = ZoneInfo("Asia/Tehran")


def format_date_for_display(dt_utc: datetime) -> str:
    try:
        dt_local = dt_utc.astimezone(TARGET_TZ)
        return dt_local.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "Unknown Date"


def send_telegram_message(
    repo: str, tag: str, html_url: str, published_at: str
) -> bool:
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    topic_id = os.environ.get("TELEGRAM_RELEASE_TOPIC_ID")

    if not bot_token or not chat_id:
        print("Error: Missing Telegram secrets.")
        return False

    published_display = "Unknown Date"
    if published_at:
        try:
            dt = date_parser.parse(published_at)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            published_display = format_date_for_display(dt)
        except Exception:
            pass

    message = (
        f"📦 New release for <b>{repo}</b>\n\n"
        f"<b>Tag:</b> <code>{tag}</code>\n"
        f"📅 {published_display}\n\n"
        f"🔗 <a href='{html_url}'>View Release</a>"
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
        print(f"Sent notification for: {repo} - {tag}")
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


def check_releases() -> None:
    if not os.path.exists(CONFIG_FILE):
        print(f"Error: Config file not found at {CONFIG_FILE}")
        return

    with open(CONFIG_FILE, "r") as f:
        repos = json.load(f)

    history = load_history()
    updated_history = False

    for repo_config in repos:
        repo = repo_config["repo"]
        print(f"Checking {repo}...")

        api_url = f"https://api.github.com/repos/{repo}/releases/latest"

        try:
            response = requests.get(api_url)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            print(f"Failed to fetch release for {repo}: {e}")
            continue

        tag = data.get("tag_name")
        html_url = data.get("html_url")
        published_at = data.get("published_at", "")

        if not tag:
            print(f"No releases for {repo}")
            continue

        last_seen = history.get(repo)

        if tag != last_seen:
            print(f"NEW RELEASE for {repo}: {tag}")

            success = send_telegram_message(repo, tag, html_url, published_at)

            if success:
                history[repo] = tag
                updated_history = True
                time.sleep(1)
        else:
            print(f"No new release for {repo}")

    if updated_history:
        save_history(history)


if __name__ == "__main__":
    check_releases()
