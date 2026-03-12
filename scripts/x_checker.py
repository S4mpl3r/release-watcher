import argparse
import html
import json
import os
import time
from typing import Any

import httpx

HISTORY_FILE = "x_history.json"
BEARER_TOKEN = "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
BASE_URL = "https://x.com/i/api/graphql"
USER_BY_SCREEN_NAME = "/Yka-W8dz7RaEuQNkroPkYw/UserByScreenName"
USER_TWEETS = "/E3opETHurmVJflFsUBVuUQ/UserTweets"
TELEGRAM_SEND_DELAY_SECONDS = 1.0
RECENT_IDS_TO_KEEP = 200
FIRST_RUN_LIMIT = 5
MAX_TIMELINE_PAGES = 8
PAGE_SIZE = 40

USER_FEATURES = {
    "hidden_profile_subscriptions_enabled": True,
    "rweb_tipjar_consumption_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "subscriptions_verification_info_is_identity_verified_enabled": True,
    "subscriptions_verification_info_verified_since_enabled": True,
    "highlights_tweets_tab_ui_enabled": True,
    "responsive_web_twitter_article_notes_tab_enabled": True,
    "subscriptions_feature_can_gift_premium": True,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "responsive_web_graphql_timeline_navigation_enabled": True,
}

TIMELINE_FEATURES = {
    "rweb_tipjar_consumption_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "articles_preview_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "creator_subscriptions_quote_tweet_preview_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "rweb_video_timestamps_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
}

COOKIE_KEYS_TO_KEEP = {
    "auth_token",
    "ct0",
    "twid",
    "kdt",
    "guest_id",
    "d_prefs",
    "lang",
    "g_state",
    "_twitter_sess",
    "__cuid",
    "__cf_bm",
}


def load_json_file(path: str, default):
    if os.path.exists(path):
        with open(path, "r") as file:
            return json.load(file)
    return default


def save_json_file(path: str, data) -> None:
    with open(path, "w") as file:
        json.dump(data, file, indent=2, sort_keys=True)


def build_headers(ct0: str | None) -> dict[str, str]:
    headers = {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "authorization": BEARER_TOKEN,
        "content-type": "application/json",
        "dnt": "1",
        "referer": "https://x.com/",
        "user-agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
        ),
        "x-twitter-active-user": "yes",
        "x-twitter-client-language": "en",
    }
    if ct0:
        headers["x-csrf-token"] = ct0
        headers["x-twitter-auth-type"] = "OAuth2Session"
    return headers


def load_history() -> dict:
    history = load_json_file(HISTORY_FILE, {})
    history.setdefault("accounts", {})
    history.setdefault("session", {})
    return history


def save_history(history: dict) -> None:
    save_json_file(HISTORY_FILE, history)


def load_auth_token() -> str:
    auth_token = os.environ.get("X_AUTH_TOKEN")
    if not auth_token:
        raise RuntimeError("Missing X_AUTH_TOKEN secret")
    return auth_token.strip()


def get_cookie(client: httpx.Client, name: str) -> str | None:
    for cookie in client.cookies.jar:
        if cookie.name == name:
            return cookie.value
    return None


def client_cookies(client: httpx.Client) -> dict[str, Any]:
    return {
        cookie.name: cookie.value
        for cookie in client.cookies.jar
        if cookie.name in COOKIE_KEYS_TO_KEEP
    }


def load_session_state(history: dict) -> dict[str, str]:
    session = history.get("session", {})
    session["auth_token"] = load_auth_token()
    return session


def save_session(history: dict, client: httpx.Client) -> None:
    history["session"] = client_cookies(client)
    save_history(history)


def make_x_client(cookies: dict[str, str]) -> httpx.Client:
    client = httpx.Client(
        follow_redirects=True,
        timeout=30.0,
        headers=build_headers(cookies.get("ct0")),
    )
    for name, value in cookies.items():
        client.cookies.set(name, value, domain="x.com")
    return client


def try_refresh_from_auth_token(auth_token: str) -> httpx.Client | None:
    client = httpx.Client(
        follow_redirects=True,
        timeout=30.0,
        headers=build_headers(None),
    )
    client.cookies.set("auth_token", auth_token, domain="x.com")
    try:
        response = client.get("https://x.com")
        if response.status_code not in {200, 401, 403}:
            response.raise_for_status()
        ct0 = get_cookie(client, "ct0")
        if not ct0:
            return None
        client.headers.update(build_headers(ct0))
        return client
    except Exception:
        return None


def refresh_x_client(history: dict, previous_client: httpx.Client) -> httpx.Client:
    auth_token = get_cookie(previous_client, "auth_token") or load_auth_token()
    refreshed = try_refresh_from_auth_token(auth_token)
    if not refreshed:
        raise RuntimeError("Unable to refresh X session from auth token")
    save_session(history, refreshed)
    return refreshed


def gql_get(
    client: httpx.Client,
    endpoint: str,
    variables: dict,
    features: dict,
    extra_params: dict | None = None,
) -> dict:
    params = {
        "variables": json.dumps(variables, separators=(",", ":")),
        "features": json.dumps(features, separators=(",", ":")),
    }
    if extra_params:
        params.update(extra_params)

    response = client.get(f"{BASE_URL}{endpoint}", params=params)
    if response.status_code in {401, 403}:
        raise PermissionError(f"X returned {response.status_code}")
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise RuntimeError(f"X API returned errors: {payload['errors']}")
    return payload


def user_identity(tweet: dict) -> tuple[str | None, str | None]:
    user_result = (
        tweet.get("core", {}).get("user_result", {}).get("result")
        or tweet.get("core", {}).get("user_results", {}).get("result")
        or {}
    )
    user_legacy = user_result.get("legacy", {})
    user_core = user_result.get("core", {})
    return user_core.get("name") or user_legacy.get("name"), user_core.get(
        "screen_name"
    ) or user_legacy.get("screen_name")


def clean_text(legacy: dict, media: list[dict]) -> tuple[str, list[str]]:
    text = legacy.get("full_text") or legacy.get("text") or ""
    note_tweet = legacy.get("note_text")
    if note_tweet:
        text = note_tweet

    media_urls = {item.get("url") for item in media if item.get("url")}
    expanded_links = []
    for entity in legacy.get("entities", {}).get("urls", []):
        short_url = entity.get("url")
        expanded_url = (
            entity.get("expanded_url") or entity.get("display_url") or short_url
        )
        if short_url and short_url not in media_urls and expanded_url:
            text = text.replace(short_url, expanded_url)
            expanded_links.append(expanded_url)

    for media_url in media_urls:
        if media_url:
            text = text.replace(media_url, "")

    lines = [line.strip() for line in text.splitlines()]
    text = "\n".join(line for line in lines if line)
    return text.strip(), list(dict.fromkeys(expanded_links))


def best_video_variant(media: dict) -> str | None:
    variants = media.get("video_info", {}).get("variants", [])
    mp4_variants = [
        variant
        for variant in variants
        if variant.get("content_type") == "video/mp4" and variant.get("url")
    ]
    if not mp4_variants:
        return None
    return max(mp4_variants, key=lambda variant: variant.get("bitrate", 0))["url"]


def media_items(tweet: dict) -> list[dict[str, str]]:
    media = tweet.get("legacy", {}).get("extended_entities", {}).get("media") or []
    items = []
    for item in media:
        item_type = item.get("type")
        if item_type == "photo" and item.get("media_url_https"):
            items.append(
                {"type": "photo", "url": f"{item['media_url_https']}?name=orig"}
            )
        elif item_type in {"video", "animated_gif"}:
            video_url = best_video_variant(item)
            if video_url:
                items.append({"type": "video", "url": video_url})
    return items


def quoted_tweet_data(tweet: dict) -> dict[str, str] | None:
    quoted = tweet.get("quoted_status_result", {}).get("result") or tweet.get(
        "quoted_status_result", {}
    )
    if quoted.get("tweet"):
        quoted = quoted["tweet"]
    legacy = quoted.get("legacy")
    if not legacy:
        return None

    note_tweet = (
        quoted.get("note_tweet", {}).get("note_tweet_results", {}).get("result", {})
    )
    if note_tweet.get("text"):
        legacy = {**legacy, "note_text": note_tweet["text"]}

    _name, handle = user_identity(quoted)
    tweet_id = quoted.get("rest_id") or legacy.get("id_str")
    text, _links = clean_text(
        legacy, legacy.get("extended_entities", {}).get("media") or []
    )
    if not handle and not text:
        return None
    return {
        "handle": handle or "unknown",
        "text": text,
        "url": f"https://x.com/{handle or 'i'}/status/{tweet_id}" if tweet_id else "",
    }


def normalize_tweet(tweet_result: dict) -> dict | None:
    tweet = tweet_result.get("tweet") or tweet_result
    legacy = tweet.get("legacy")
    if not legacy:
        return None

    name, screen_name = user_identity(tweet)
    note_tweet = (
        tweet.get("note_tweet", {}).get("note_tweet_results", {}).get("result", {})
    )
    if note_tweet.get("text"):
        legacy = {**legacy, "note_text": note_tweet["text"]}

    text, _links = clean_text(
        legacy, tweet.get("legacy", {}).get("extended_entities", {}).get("media") or []
    )
    tweet_id = tweet.get("rest_id") or legacy.get("id_str")
    media = media_items(tweet)
    retweet = (
        tweet.get("legacy", {})
        .get("retweeted_status_result", {})
        .get("result", {})
        .get("legacy")
    )
    return {
        "id": str(tweet_id),
        "author_name": name,
        "author_handle": screen_name,
        "text": text,
        "url": f"https://x.com/{screen_name}/status/{tweet_id}",
        "is_retweet": bool(retweet),
        "is_reply": bool(legacy.get("in_reply_to_status_id_str")),
        "reply_to_handle": legacy.get("in_reply_to_screen_name"),
        "media": media,
        "quoted_tweet": quoted_tweet_data(tweet),
    }


def extract_entries_and_cursor(payload: dict) -> tuple[list[dict], str | None]:
    user_result = payload.get("data", {}).get("user", {}).get("result", {})
    timeline = (
        user_result.get("timeline", {}).get("timeline")
        or user_result.get("timeline", {}).get("timeline_v2")
        or user_result.get("timeline_v2", {}).get("timeline")
        or {}
    )
    entries = []
    cursor = None
    for instruction in timeline.get("instructions", []):
        if instruction.get("type") == "TimelineAddEntries":
            for entry in instruction.get("entries", []):
                entries.append(entry)
                if entry.get("entryId", "").startswith("cursor-bottom-"):
                    cursor = entry.get("content", {}).get("value") or cursor
        elif instruction.get("type") == "TimelineReplaceEntry":
            entry = instruction.get("entry", {})
            if entry.get("entryId", "").startswith("cursor-bottom-"):
                cursor = entry.get("content", {}).get("value") or cursor
    return entries, cursor


def resolve_user(client: httpx.Client, screen_name: str) -> dict[str, str]:
    payload = gql_get(
        client,
        USER_BY_SCREEN_NAME,
        {"screen_name": screen_name, "withSafetyModeUserFields": True},
        USER_FEATURES,
        {"fieldToggles": json.dumps({"withAuxiliaryUserLabels": False})},
    )
    result = payload.get("data", {}).get("user", {}).get("result", {})
    legacy = result.get("legacy", {})
    rest_id = result.get("rest_id")
    if not rest_id:
        raise RuntimeError(f"Could not resolve X account: {screen_name}")
    return {
        "rest_id": rest_id,
        "name": legacy.get("name") or screen_name,
        "screen_name": legacy.get("screen_name") or screen_name,
    }


def fetch_latest_tweets(
    client: httpx.Client, rest_id: str, stop_after_id: str | None
) -> list[dict]:
    tweets = []
    seen_ids = set()
    cursor = None

    for _ in range(MAX_TIMELINE_PAGES):
        variables = {
            "userId": rest_id,
            "count": PAGE_SIZE,
            "includePromotedContent": True,
            "withQuickPromoteEligibilityTweetFields": True,
            "withVoice": True,
            "withV2Timeline": True,
        }
        if cursor:
            variables["cursor"] = cursor

        payload = gql_get(client, USER_TWEETS, variables, TIMELINE_FEATURES)
        entries, cursor = extract_entries_and_cursor(payload)
        reached_known = False

        for entry in entries:
            entry_id = entry.get("entryId", "")
            if not (
                entry_id.startswith("tweet-")
                or entry_id.startswith("profile-grid-0-tweet-")
            ):
                continue
            content = entry.get("content") or entry.get("item") or {}
            tweet_result = content.get("content", {}).get("tweetResult", {}).get(
                "result"
            ) or content.get("itemContent", {}).get("tweet_results", {}).get("result")
            if not tweet_result:
                continue
            tweet = normalize_tweet(tweet_result)
            if not tweet or tweet["is_retweet"]:
                continue
            tweet_id = tweet["id"]
            if tweet_id in seen_ids:
                continue
            seen_ids.add(tweet_id)
            tweets.append(tweet)
            if stop_after_id and int(tweet_id) <= int(stop_after_id):
                reached_known = True

        if reached_known or not cursor:
            break

    return tweets


def account_state(history: dict, key: str) -> dict:
    value = history.get("accounts", {}).get(key, {})
    if isinstance(value, str):
        return {"last_seen_id": value, "recent_ids": [value], "initialized": True}
    return {
        "last_seen_id": value.get("last_seen_id"),
        "recent_ids": list(value.get("recent_ids", [])),
        "initialized": value.get("initialized", False),
    }


def save_account_state(history: dict, key: str, state: dict) -> None:
    history.setdefault("accounts", {})
    history["accounts"][key] = {
        "last_seen_id": state.get("last_seen_id"),
        "recent_ids": list(dict.fromkeys(state.get("recent_ids", [])))[
            -RECENT_IDS_TO_KEEP:
        ],
        "initialized": state.get("initialized", False),
    }
    save_history(history)


def truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)].rstrip() + "..."


def telegram_html(tweet: dict) -> str:
    parts = [f"<code>@{html.escape(tweet['author_handle'] or '')}</code>"]
    if tweet["is_reply"] and tweet.get("reply_to_handle"):
        parts.append(f"Replying to <b>@{html.escape(tweet['reply_to_handle'])}</b>")
    if tweet["text"]:
        parts.append(html.escape(tweet["text"]))
    if tweet.get("quoted_tweet"):
        quoted = tweet["quoted_tweet"]
        quote_handle = f"@{quoted['handle']}"
        quote_link = (
            f'<a href="{html.escape(quoted["url"], quote=True)}">{html.escape(quote_handle)}</a>'
            if quoted.get("url")
            else f"<code>{html.escape(quote_handle)}</code>"
        )
        quote_parts = []
        if quoted.get("text"):
            quote_parts.append(html.escape(quoted["text"]))
        quote_parts.append(quote_link)
        quote_block = "\n".join(part for part in quote_parts if part)
        if len(parts) > 1 and not parts[-1].startswith("Replying to"):
            parts[-1] = f"{parts[-1]}\n<blockquote>{quote_block}</blockquote>"
        else:
            parts.append(f"<blockquote>{quote_block}</blockquote>")
    parts.append(f'<a href="{html.escape(tweet["url"], quote=True)}">View on X</a>')
    return "\n\n".join(part for part in parts if part)


def telegram_caption(tweet: dict) -> str:
    parts = [f"<code>@{html.escape(tweet['author_handle'] or '')}</code>"]
    if tweet["is_reply"] and tweet.get("reply_to_handle"):
        parts.append(f"Replying to <b>@{html.escape(tweet['reply_to_handle'])}</b>")
    if tweet["text"]:
        parts.append(html.escape(truncate_text(tweet["text"], 700)))
    if tweet.get("quoted_tweet"):
        quoted = tweet["quoted_tweet"]
        quote_handle = f"@{quoted['handle']}"
        quote_link = (
            f'<a href="{html.escape(quoted["url"], quote=True)}">{html.escape(quote_handle)}</a>'
            if quoted.get("url")
            else f"<code>{html.escape(quote_handle)}</code>"
        )
        if quoted.get("text"):
            quote_block = (
                f"{html.escape(truncate_text(quoted['text'], 220))}\n{quote_link}"
            )
            if len(parts) > 1 and not parts[-1].startswith("Replying to"):
                parts[-1] = f"{parts[-1]}\n<blockquote>{quote_block}</blockquote>"
            else:
                parts.append(f"<blockquote>{quote_block}</blockquote>")
        else:
            parts.append(f"<blockquote>{quote_link}</blockquote>")
    parts.append(f'<a href="{html.escape(tweet["url"], quote=True)}">View on X</a>')
    return truncate_text("\n\n".join(part for part in parts if part), 1024)


def telegram_request(client: httpx.Client, method: str, data: dict) -> dict:
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN secret")

    last_error = None
    for attempt in range(3):
        try:
            response = client.post(
                f"https://api.telegram.org/bot{bot_token}/{method}", data=data
            )
            payload = response.json()
            if payload.get("ok"):
                return payload
            retry_after = payload.get("parameters", {}).get("retry_after")
            if response.status_code == 429 and retry_after:
                time.sleep(max(int(retry_after), 1))
                continue
            if response.status_code >= 500 and attempt < 2:
                time.sleep(2**attempt)
                continue
            raise RuntimeError(f"Telegram API error for {method}: {payload}")
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2**attempt)
                continue
            raise RuntimeError(f"Telegram request failed for {method}: {exc}") from exc
    raise RuntimeError(f"Telegram request failed for {method}: {last_error}")


def send_media(client: httpx.Client, topic_id: str, tweet: dict) -> None:
    media = tweet["media"][:10]
    caption = telegram_caption(tweet)
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not chat_id:
        raise RuntimeError("Missing TELEGRAM_CHAT_ID secret")

    if len(media) == 1:
        item = media[0]
        payload = {
            "chat_id": chat_id,
            "message_thread_id": topic_id,
            "caption": caption,
            "parse_mode": "HTML",
        }
        if item["type"] == "photo":
            payload["photo"] = item["url"]
            telegram_request(client, "sendPhoto", payload)
        else:
            payload["video"] = item["url"]
            payload["supports_streaming"] = "true"
            telegram_request(client, "sendVideo", payload)
        return

    payload = []
    for index, item in enumerate(media):
        media_item = {
            "type": "photo" if item["type"] == "photo" else "video",
            "media": item["url"],
        }
        if media_item["type"] == "video":
            media_item["supports_streaming"] = True
        if index == 0:
            media_item["caption"] = caption
            media_item["parse_mode"] = "HTML"
        payload.append(media_item)

    telegram_request(
        client,
        "sendMediaGroup",
        {
            "chat_id": chat_id,
            "message_thread_id": topic_id,
            "media": json.dumps(payload),
        },
    )


def send_error(
    client: httpx.Client, topic_id: str, tweet_url: str, error: Exception
) -> None:
    """Send an error message to Telegram for a failed tweet."""
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not chat_id:
        return  # Can't send without chat_id, silently skip

    text = (
        f"Failed to forward tweet\n\n"
        f"<code>{html.escape(tweet_url)}</code>\n\n"
        f"<pre>{html.escape(str(error)[:500])}</pre>"
    )
    payload = {
        "chat_id": chat_id,
        "message_thread_id": topic_id,
        "text": text,
        "parse_mode": "HTML",
    }
    try:
        telegram_request(client, "sendMessage", payload)
        time.sleep(TELEGRAM_SEND_DELAY_SECONDS)
    except Exception:
        pass  # Don't crash if error reporting fails


def send_text(client: httpx.Client, topic_id: str, tweet: dict) -> None:
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not chat_id:
        raise RuntimeError("Missing TELEGRAM_CHAT_ID secret")

    payload = {
        "chat_id": chat_id,
        "message_thread_id": topic_id,
        "text": telegram_html(tweet),
        "parse_mode": "HTML",
    }
    if tweet.get("quoted_tweet"):
        payload["link_preview_options"] = json.dumps({"is_disabled": True})
    else:
        payload["link_preview_options"] = json.dumps(
            {
                "url": tweet["url"],
                "prefer_large_media": True,
                "show_above_text": False,
            }
        )
    telegram_request(client, "sendMessage", payload)


def forward_tweet(client: httpx.Client, topic_id: str, tweet: dict) -> None:
    if tweet["media"]:
        send_media(client, topic_id, tweet)
    else:
        send_text(client, topic_id, tweet)
    time.sleep(TELEGRAM_SEND_DELAY_SECONDS)


def account_key(account: str) -> str:
    return account.lower()


def normalized_chat_id() -> str:
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not chat_id:
        raise RuntimeError("Missing TELEGRAM_CHAT_ID secret")
    if chat_id.isdigit():
        return f"-100{chat_id}"
    return chat_id


def process_account(
    x_client: httpx.Client,
    tg_client: httpx.Client,
    history: dict,
    account_config: dict,
    topic_id: str,
) -> httpx.Client:
    account = account_config["account"]
    print(f"Checking @{account}...")

    try:
        user = resolve_user(x_client, account)
    except PermissionError:
        x_client = refresh_x_client(history, x_client)
        user = resolve_user(x_client, account)

    state = account_state(history, account_key(account))
    try:
        tweets = fetch_latest_tweets(
            x_client, user["rest_id"], state.get("last_seen_id")
        )
    except PermissionError:
        x_client = refresh_x_client(history, x_client)
        user = resolve_user(x_client, account)
        tweets = fetch_latest_tweets(
            x_client, user["rest_id"], state.get("last_seen_id")
        )
    save_session(history, x_client)

    recent_ids = {str(item) for item in state.get("recent_ids", [])}
    new_posts = []
    for tweet in tweets:
        tweet_id = tweet["id"]
        if tweet_id in recent_ids:
            continue
        if state.get("last_seen_id") and int(tweet_id) <= int(state["last_seen_id"]):
            continue
        new_posts.append(tweet)

    new_posts.sort(key=lambda item: int(item["id"]))

    if not state.get("initialized") and len(new_posts) > FIRST_RUN_LIMIT:
        new_posts = new_posts[-FIRST_RUN_LIMIT:]

    if not new_posts:
        print(f"No new posts for @{user['screen_name']}")
        state["initialized"] = True
        save_account_state(history, account_key(account), state)
        return x_client

    # Save state before sending to prevent duplicates on failure
    if new_posts:
        state["last_seen_id"] = new_posts[-1]["id"]
        state.setdefault("recent_ids", []).extend(t["id"] for t in new_posts)
        state["recent_ids"] = list(dict.fromkeys(state["recent_ids"]))[
            -RECENT_IDS_TO_KEEP:
        ]
        state["initialized"] = True
        save_account_state(history, account_key(account), state)

    for tweet in new_posts:
        try:
            forward_tweet(tg_client, topic_id, tweet)
            print(f"Forwarded {tweet['url']}")
        except Exception as exc:
            print(f"Failed to forward {tweet['url']}: {exc}")
            send_error(tg_client, topic_id, tweet["url"], exc)

    return x_client


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch X posts and forward new ones to Telegram."
    )
    parser.add_argument("--account", help="Optional X account override")
    return parser.parse_args()


def main() -> int:
    try:
        args = parse_args()
        history = load_history()
        configured_account = args.account or os.environ.get("X_ACCOUNT")
        if not configured_account:
            raise RuntimeError("Missing X_ACCOUNT secret")
        accounts = [{"account": configured_account.strip()}]

        topic_id = os.environ.get("TELEGRAM_X_TOPIC_ID")
        if not topic_id:
            raise RuntimeError("Missing TELEGRAM_X_TOPIC_ID secret")

        os.environ["TELEGRAM_CHAT_ID"] = normalized_chat_id()

        x_client = make_x_client(load_session_state(history))
        tg_client = httpx.Client(timeout=60.0)

        print(f"Loaded {len(accounts)} X accounts")

        for account_config in accounts:
            x_client = process_account(
                x_client, tg_client, history, account_config, topic_id
            )

        return 0
    except KeyboardInterrupt:
        print("Stopped.")
        return 0
    except Exception as exc:
        print(f"Error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
