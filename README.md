# Release & Content Watcher

An automated monitoring system powered by GitHub Actions that tracks software releases, blog posts, and YouTube videos, delivering formatted notifications to a Telegram group.

## Features

*   **GitHub Releases:** Tracks new tags/releases for specified repositories.
*   **RSS Blogs:** Monitors blog feeds with intelligent scheduling (daily vs. frequent checks).
*   **YouTube:** Tracks new video uploads.
*   **Crawled Feeds:** Custom scrapers for blogs that lack RSS feeds (e.g., Anthropic).
*   **State Management:** Uses GitHub Actions Cache to prevent duplicate notifications.
*   **Topic Support:** Routes different types of content to specific Telegram Topics.

## Configuration & Workflows

The system is divided into four main workflows. To add new content, you primarily modify the JSON files in the `config/` directory.

### 1. GitHub Release Checker
*   **Workflow:** `.github/workflows/release-checker.yml`
*   **Script:** `scripts/release_checker.py`
*   **Schedule:** Every 6 hours.
*   **How to Expand:**
    Add a repository to `config/release_repos.json`:
    ```json
    {
      "repo": "owner/repository-name"
    }
    ```

### 2. RSS Blog Checker
*   **Workflow:** `.github/workflows/blog-checker.yml`
*   **Script:** `scripts/rss_checker.py`
*   **Schedule:** Every 4 hours (approx).
*   **How to Expand:**
    Add a feed to `config/blog_feeds.json`:
    ```json
    {
      "name": "Blog Name",
      "url": "https://example.com/feed.xml",
      "check_hours": 24
    }
    ```
    *Note: Feeds with `check_hours: 24` are only checked during the "Morning Run" (5 AM - 7 AM).*

### 3. YouTube Checker
*   **Workflow:** `.github/workflows/youtube-checker.yml`
*   **Script:** `scripts/youtube_checker.py`
*   **Schedule:** Every 6 hours.
*   **How to Expand:**
    Add a channel to `config/youtube_feeds.json`:
    ```json
    {
      "name": "Channel Name",
      "url": "https://www.youtube.com/feeds/videos.xml?channel_id=CHANNEL_ID"
    }
    ```

### 4. Crawled Feeds (Custom Scrapers)
Designed for sites without RSS feeds.
*   **Workflow:** `.github/workflows/crawl-checker.yml`
*   **Script:** `scripts/crawl_checker.py`
*   **Schedule:** 06:00 AM & 06:00 PM.
*   **How to Expand (Existing Extractor):**
    If the site is supported (e.g., Anthropic), add it to `config/crawled_feeds.json`:
    ```json
    {
      "name": "Anthropic Research",
      "url": "https://www.anthropic.com/research",
      "extractor": "anthropic"
    }
    ```
*   **How to Add a NEW Website Type:**
    1.  Create a new extractor class in `scripts/extractors/your_site.py`.
    2.  Implement an `extract(html_content)` method that returns a list of dictionaries.
    3.  Import and register it in `scripts/crawl_checker.py` under the `EXTRACTORS` dictionary.

## Setup & Secrets

To run this in your own repository, set the following **Repository Secrets** in GitHub:

| Secret Name | Description |
| :--- | :--- |
| `TELEGRAM_BOT_TOKEN` | Token from @BotFather |
| `TELEGRAM_CHAT_ID` | The ID of the Group/Channel |
| `TELEGRAM_RELEASE_TOPIC_ID` | Topic ID for Release notifications |
| `TELEGRAM_BLOG_TOPIC_ID` | Topic ID for Blog/RSS notifications |
| `TELEGRAM_YOUTUBE_TOPIC_ID` | Topic ID for YouTube notifications |

## Local Development

1.  **Install Dependencies:**
    ```bash
    pip install -r scripts/requirements.txt
    # OR using uv
    uv pip install -r scripts/requirements.txt
    ```

2.  **Run Scripts:**
    Set your environment variables (e.g., in a `.env` file) and run:
    ```bash
    python scripts/crawl_checker.py
    ```

## Instant View Support

The RSS checker supports Telegram's **Instant View** for a cleaner reading experience.

1.  Create a template at [instantview.telegram.org](https://instantview.telegram.org/).
2.  Obtain your `rhash` from the "View in Telegram" link.
3.  Add the `rhash` to the feed's entry in `config/blog_feeds.json`:
    ```json
    {
      "name": "Simon Willison",
      "url": "...",
      "rhash": "..."
    }
    ```
    *The title link remains pointing to the original website, while the preview button triggers the Instant View.*

## Spam Prevention

*   **RSS/YouTube:** Filters posts by time (looking back only X hours).
*   **Crawlers:** Includes a "First Run Silent Mode". If a feed has no history, it populates the database and only sends the latest entry.
