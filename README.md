# Release & Content Watcher

An automated monitoring system powered by GitHub Actions that tracks software releases, blog posts, and YouTube videos, delivering formatted notifications to a Telegram group.

## Features

*   **GitHub Releases:** Tracks new tags/releases for specified repositories.
*   **RSS Blogs:** Monitors blog feeds and notifies on new posts.
*   **YouTube:** Tracks new video uploads (filters out Shorts).
*   **Crawled Feeds:** Custom scrapers for blogs that lack RSS feeds (e.g., Anthropic).
*   **ArXiv Research:** Monitors new papers in AI/ML categories with keyword filtering.
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
      "url": "https://example.com/feed.xml"
    }
    ```

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

### 5. ArXiv Paper Watcher
Monitors new research papers in specified categories (e.g., AI, ML).
*   **Workflow:** `.github/workflows/arxiv-checker.yml`
*   **Script:** `scripts/arxiv_checker.py`
*   **Schedule:** 06:30 AM & 06:30 PM.
*   **How to Expand:**
    Add a search query to `config/arxiv_queries.json`:
    ```json
    {
      "name": "Agents Research",
      "search_query": "cat:cs.AI AND abs:Agent",
      "keywords": ["Autonomous", "Reasoning"]
    }
    ```

## Setup & Secrets

To run this in your own repository, set the following **Repository Secrets** in GitHub:

| Secret Name | Description |
| :--- | :--- |
| `TELEGRAM_BOT_TOKEN` | Token from @BotFather |
| `TELEGRAM_CHAT_ID` | The ID of the Group/Channel |
| `TELEGRAM_RELEASE_TOPIC_ID` | Topic ID for Release notifications |
| `TELEGRAM_BLOG_TOPIC_ID` | Topic ID for Blog/RSS notifications |
| `TELEGRAM_YOUTUBE_TOPIC_ID` | Topic ID for YouTube notifications |
| `TELEGRAM_ARXIV_TOPIC_ID` | Topic ID for ArXiv notifications |

## Local Development

1.  **Install Dependencies:**
    ```bash
    pip install -r scripts/requirements.txt
    # OR using uv
    uv pip install -r scripts/requirements.txt
    ```

2. **Run Scripts:**

    Set your environment variables (e.g., in a `.env` file) and run:

    ```bash

    python scripts/crawl_checker.py

    # OR using uv

    uv run scripts/arxiv_checker.py

    ```

## Instant View Support

The RSS and Crawled feed checkers support Telegram's **Instant View** for a cleaner reading experience.

1.  Create a template at [instantview.telegram.org](https://instantview.telegram.org/).
2.  Obtain your `rhash` from the "View in Telegram" link.
3.  Add the `rhash` to the feed's entry in `config/blog_feeds.json` (or `config/crawled_feeds.json`):
    ```json
    {
      "name": "Anthropic Research",
      "url": "...",
      "rhash": "..."
    }
    ```
    *The title link remains pointing to the original website, while the preview button triggers the Instant View.*

## Spam Prevention

*   **RSS/YouTube:** Filters posts by time (looking back 30-48 hours) and checks against a history cache to prevent duplicates.
*   **Crawlers:** Includes a "First Run Silent Mode" for old posts. If a feed is new, it populates the history with all items but only sends notifications for those published in the last 24 hours.
*   **ArXiv:** Tracks history of all processed papers. Limits notifications to 5 per run (drip-feed) to avoid floods, and uses regex word boundaries for precise keyword matching.
*   **Releases:** Tracks the latest tag. Only sends a notification when the tag changes (or on the first run).
*   **State Management:** All workflows use GitHub Actions Cache to persist history between runs.
