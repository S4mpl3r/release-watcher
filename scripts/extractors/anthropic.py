import json
import re
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup


class AnthropicExtractor:
    BASE_URL = "https://www.anthropic.com"

    @staticmethod
    def _standardize_output(
        title: Optional[str],
        published_at: Optional[str],
        link: Optional[str],
        summary: Optional[str],
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "title": title,
            "published_at": published_at,
            "link": link,
            "summary": summary,
            "metadata": metadata,
        }

    @classmethod
    def extract(cls, html_content: str) -> List[Dict[str, Any]]:
        """
        Parses Next.js hydration data using non-greedy Regex to isolate specific chunks.
        Adapted to work with BeautifulSoup instead of justhtml.
        """
        soup = BeautifulSoup(html_content, "html.parser")
        scripts = soup.find_all("script")

        target_articles = []

        # Regex to capture the JSON payload inside self.__next_f.push(...)
        pattern = re.compile(
            r"self\.__next_f\.push\(\[\s*1\s*,\s*\"(.*?)\"\s*\]\s*\)", re.DOTALL
        )

        for script in scripts:
            if not script.string:
                continue

            text = script.string

            # Optimization check
            if (
                "articles" not in text
                and "publicationList" not in text
                and "posts" not in text
            ):
                continue

            matches = pattern.findall(text)

            for raw_payload in matches:
                # We are looking for either "articles" (Engineering) or "posts" (Research)
                if "articles" not in raw_payload and "posts" not in raw_payload:
                    continue

                try:
                    # 1. Decode Level 1: JavaScript String -> Valid JSON String
                    unescaped_str = json.loads(f'"{raw_payload}"', strict=False)

                    # 2. Remove Chunk ID
                    if ":" not in unescaped_str:
                        continue

                    _, json_str = unescaped_str.split(":", 1)

                    # 3. Decode Level 2: JSON String -> Python Dict/List
                    data = json.loads(json_str)

                    # 4. Navigate Next.js Data Structure
                    # Expected: ["$", "RefID", null, {"page": ...}]
                    if (
                        isinstance(data, list)
                        and len(data) > 3
                        and isinstance(data[3], dict)
                    ):
                        page_data = data[3].get("page", {})
                        sections = page_data.get("sections", [])

                        for section in sections:
                            # Engineering page uses 'articleList' -> 'articles'
                            if section.get("_type") == "articleList":
                                target_articles = section.get("articles", [])
                                break

                            # Research page uses 'publicationList' -> 'posts'
                            if section.get("_type") == "publicationList":
                                target_articles = section.get("posts", [])
                                break

                    if target_articles:
                        break

                except (json.JSONDecodeError, ValueError, IndexError, AttributeError):
                    continue

            if target_articles:
                break

        # Standardize Output
        results = []
        for art in target_articles:
            if not isinstance(art, dict):
                continue

            title = art.get("title")
            published_at = art.get("publishedOn")
            summary = art.get("summary")

            # Link Construction
            slug_obj = art.get("slug")
            slug = slug_obj.get("current") if isinstance(slug_obj, dict) else None
            art_type = art.get("_type", "")

            if slug:
                if "engineering" in str(art_type).lower():
                    base = "/engineering/"
                elif "research" in str(art_type).lower():
                    base = "/research/"
                elif art.get("_type") == "post":
                    base = "/research/"
                else:
                    base = "/engineering/"

                link = f"{cls.BASE_URL}{base}{slug}"
            else:
                link = None

            # Collect Tags
            subjects_list = art.get("subjects")
            subjects = []
            if isinstance(subjects_list, list):
                for t in subjects_list:
                    if isinstance(t, dict):
                        label = t.get("label")
                        if label:
                            subjects.append(label)

            # Image URL
            card_image = art.get("cardImage")
            card_photo = art.get("cardPhoto")
            image_url = None
            if isinstance(card_image, dict):
                image_url = card_image.get("url")
            if not image_url and isinstance(card_photo, dict):
                image_url = card_photo.get("url")

            metadata = {
                "tags": subjects,
                "image_url": image_url,
            }

            results.append(
                cls._standardize_output(title, published_at, link, summary, metadata)
            )

        return results
