import hashlib
import json
import os

import requests

HISTORY_FILE = "upstream_constants_history.json"
RAW_URL = "https://raw.githubusercontent.com/DIYgod/RSSHub/master/lib/routes/twitter/api/web-api/constants.ts"
BLOB_URL = "https://github.com/DIYgod/RSSHub/blob/master/lib/routes/twitter/api/web-api/constants.ts"
SOURCE_NAME = "RSSHub X constants.ts"


def load_history() -> dict:
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as file:
            return json.load(file)
    return {}


def save_history(history: dict) -> None:
    with open(HISTORY_FILE, "w") as file:
        json.dump(history, file, indent=2, sort_keys=True)


def fetch_file() -> tuple[str, str]:
    response = requests.get(RAW_URL, timeout=60)
    response.raise_for_status()
    content = response.text
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return content, digest


def send_telegram_message(old_hash: str | None, new_hash: str, size: int) -> bool:
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    topic_id = os.environ.get("TELEGRAM_RELEASE_TOPIC_ID")

    if not bot_token or not chat_id or not topic_id:
        print("Error: Missing Telegram secrets.")
        return False

    old_display = old_hash[:12] if old_hash else "first-seen"
    new_display = new_hash[:12]
    message = (
        f"🔧 <b>Upstream file changed</b>\n\n"
        f"<b>{SOURCE_NAME}</b>\n"
        f"<code>lib/routes/twitter/api/web-api/constants.ts</code>\n\n"
        f"<b>Hash:</b> <code>{old_display}</code> → <code>{new_display}</code>\n"
        f"<b>Size:</b> <code>{size}</code> bytes\n\n"
        f'<a href="{BLOB_URL}">View on GitHub</a>'
    )

    payload = {
        "chat_id": chat_id,
        "message_thread_id": topic_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        print(f"Sent change notification for {SOURCE_NAME}")
        return True
    except Exception as exc:
        print(f"Failed to send Telegram message: {exc}")
        return False


def main() -> int:
    try:
        history = load_history()
        content, digest = fetch_file()
        previous_digest = history.get("sha256")

        if previous_digest == digest:
            print("No change detected.")
            return 0

        if previous_digest:
            if not send_telegram_message(
                previous_digest, digest, len(content.encode("utf-8"))
            ):
                return 1
        else:
            print("First run: recording current hash without sending notification.")

        history["sha256"] = digest
        save_history(history)
        return 0
    except Exception as exc:
        print(f"Error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
