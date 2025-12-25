import json
import os
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import arxiv
import requests

CONFIG_FILE = "config/arxiv_queries.json"
HISTORY_FILE = "arxiv_history.json"
TARGET_TZ = ZoneInfo("Asia/Tehran")

# --- Constants ---
MAX_HISTORY_SIZE = 100
MAX_NOTIFICATIONS_PER_RUN = 5
ABSTRACT_WORD_LIMIT = 60


def format_date_for_display(dt_utc: datetime) -> str:
    try:
        dt_local = dt_utc.astimezone(TARGET_TZ)
        return dt_local.strftime("%Y-%m-%d %H​:%M")
    except Exception:
        return "Unknown Date"


def clean_abstract(text: str, word_limit: int) -> str:
    if not text:
        return ""
    # Remove newlines and excess spaces
    text = text.replace("\n", " ").strip()
    words = text.split()
    if len(words) > word_limit:
        return " ".join(words[:word_limit]) + "..."
    return " ".join(words)


def send_telegram_message(paper, matched_keywords: list, search_name: str) -> bool:
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    topic_id = os.environ.get("TELEGRAM_ARXIV_TOPIC_ID")

    if not bot_token or not chat_id:
        print("Error: Missing Telegram secrets.")
        return False

    title = paper.title
    # arxiv library returns datetime objects
    published_date = paper.published

    # Format Date
    published_display = format_date_for_display(published_date)

    # Format Keywords
    tags = " ".join([f"#{k.replace(' ', '')}" for k in matched_keywords])

    # Format Abstract
    abstract_excerpt = clean_abstract(paper.summary, ABSTRACT_WORD_LIMIT)

    # Links
    pdf_link = paper.pdf_url
    abs_link = paper.entry_id

    message = (
        f"<b>{title}</b>\n\n"
        f"<i>{abstract_excerpt}</i>\n\n"
        f"🏷 {tags}\n"
        f"📅 {published_display}\n\n"
        f"🔗 <a href='{abs_link}'>Abstract</a> | <a href='{pdf_link}'>PDF</a>"
    )

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "message_thread_id": topic_id,
        "text": message,
        "parse_mode": "HTML",
        "link_preview_options": {"url": abs_link},
    }

    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        print(f"Sent notification for: {title}")
        return True
    except Exception as e:
        print(f"Failed to send Telegram message: {e}")
        return False


def load_history() -> list:
    """Returns a list of paper IDs."""
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            try:
                data = json.load(f)
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                pass
    return []


def save_history(history: list) -> None:
    # Truncate to keep only the last N entries
    if len(history) > MAX_HISTORY_SIZE:
        history = history[-MAX_HISTORY_SIZE:]

    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f)


def check_arxiv() -> None:
    if not os.path.exists(CONFIG_FILE):
        print(f"Error: Config file not found at {CONFIG_FILE}")
        return

    with open(CONFIG_FILE, "r") as f:
        searches = json.load(f)

    history = set(load_history())  # Use set for O(1) lookups
    new_history_items = []

    client = arxiv.Client(page_size=20, delay_seconds=3.0, num_retries=3)

    notifications_sent = 0

    for search_config in searches:
        if notifications_sent >= MAX_NOTIFICATIONS_PER_RUN:
            print("Reached max notifications per run. Stopping.")
            break

        name = search_config.get("name", "ArXiv Search")
        query_str = search_config.get("search_query")
        keywords = search_config.get("keywords", [])

        print(f"Running search: {name} ({query_str})...")

        # Search for recent papers sorted by submission date
        search = arxiv.Search(
            query=query_str,
            max_results=100, # Fetch a larger batch to filter locally and ensure coverage
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending
        )

        try:
            results = list(client.results(search))
            # Reverse results to process Oldest -> Newest
            results.reverse()
        except Exception as e:
            print(f"Failed to fetch arxiv results: {e}")
            continue

        for paper in results:
            if notifications_sent >= MAX_NOTIFICATIONS_PER_RUN:
                break

            paper_id = paper.get_short_id()

            # Skip if seen
            if paper_id in history:
                continue

            # Check for Keyword Matches using regex for word boundaries
            text_to_search = paper.title + " " + paper.summary

            matched = []
            for k in keywords:
                # \b handles word boundaries. re.IGNORECASE for flexibility.
                if re.search(
                    r"\b" + re.escape(k) + r"\b", text_to_search, re.IGNORECASE
                ):
                    matched.append(k)

            # Remove duplicates
            matched = list(set(matched))

            # Logic: Must match at least one keyword?
            if keywords and not matched:
                # Add to history even if not matched to avoid re-processing
                history.add(paper_id)
                new_history_items.append(paper_id)
                continue

            if not keywords:
                # If no keywords defined, assume we want everything (careful!)
                matched = ["All"]

            # It's a match!
            print(f"Match found: {paper.title} [{matched}]")

            success = send_telegram_message(paper, matched, name)

            if success:
                notifications_sent += 1
                history.add(paper_id)
                new_history_items.append(paper_id)
                time.sleep(1)  # Rate limit

    # Save History
    original_history_list = load_history()
    for item in new_history_items:
        if item not in original_history_list:
            original_history_list.append(item)

    save_history(original_history_list)


if __name__ == "__main__":
    check_arxiv()
