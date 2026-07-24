"""
fetcher.py — Fetches posts from X (Twitter) handles via Nitter RSS feeds.

Nitter is an open-source alternative frontend to Twitter that exposes RSS feeds
for public profiles without requiring an API key.

Strategy:
  - Tries each Nitter instance in order until one succeeds.
  - Filters posts to only those within the lookback window.
  - Strips HTML from post text.
  - Returns a flat list of Post dataclass objects.
"""

import re
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

import feedparser
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data Model
# ---------------------------------------------------------------------------

@dataclass
class Post:
    handle: str          # Twitter handle (without @)
    author_name: str     # Display name from feed
    text: str            # Cleaned post text
    url: str             # Link to original post
    timestamp: datetime  # UTC-aware datetime


# ---------------------------------------------------------------------------
# RSS Fetching
# ---------------------------------------------------------------------------

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; StockResearchAggregator/1.0; "
        "+https://github.com/your-repo)"
    )
}


def _clean_html(raw: str) -> str:
    """Strip HTML tags and normalise whitespace from a raw feed entry."""
    soup = BeautifulSoup(raw, "lxml")
    text = soup.get_text(separator=" ")
    # Collapse multiple spaces/newlines
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_published(entry) -> Optional[datetime]:
    """Parse the published time from a feedparser entry into a UTC datetime."""
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
    return None


def fetch_handle(
    handle: str,
    nitter_instances: list[str],
    lookback_hours: int,
    min_length: int,
    delay: float,
) -> list[Post]:
    """
    Fetch posts for a single X handle from Nitter RSS.

    Tries each Nitter instance in order; returns on the first success.
    Returns an empty list if all instances fail.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    posts: list[Post] = []

    for instance in nitter_instances:
        rss_url = f"{instance.rstrip('/')}/{handle}/rss"
        try:
            resp = httpx.get(rss_url, headers=_HEADERS, timeout=20, follow_redirects=True)
            if resp.status_code != 200:
                logger.debug(f"[{handle}] {instance} returned HTTP {resp.status_code}")
                continue

            feed = feedparser.parse(resp.text)

            if feed.bozo and not feed.entries:
                # feedparser bozo flag means parse error AND no entries — skip instance
                logger.debug(f"[{handle}] Feed parse error at {instance}")
                continue

            for entry in feed.entries:
                pub_time = _parse_published(entry)

                # Skip posts older than the lookback window
                if pub_time and pub_time < cutoff:
                    continue

                raw_text = entry.get("summary", entry.get("title", ""))
                text = _clean_html(raw_text)

                # Skip very short posts (likely noise or retweet stubs)
                if len(text) < min_length:
                    continue

                posts.append(
                    Post(
                        handle=handle,
                        author_name=feed.feed.get("title", handle),
                        text=text,
                        url=entry.get("link", ""),
                        timestamp=pub_time or datetime.now(timezone.utc),
                    )
                )

            logger.info(f"  ✓ @{handle}: {len(posts)} post(s) via {instance}")
            return posts  # Success — no need to try further instances

        except httpx.TimeoutException:
            logger.warning(f"[{handle}] Timeout on {instance}")
        except Exception as e:
            logger.warning(f"[{handle}] Error on {instance}: {e}")

        time.sleep(0.3)  # Small pause before trying next instance

    logger.error(f"  ✗ @{handle}: All Nitter instances failed — skipping")
    return []


def fetch_all_handles(
    handles: list[str],
    nitter_instances: list[str],
    lookback_hours: int = 24,
    min_length: int = 30,
    delay: float = 1.0,
) -> list[Post]:
    """
    Fetch posts from all handles and return a combined, chronologically sorted list.

    Args:
        handles:          List of Twitter handles (without @)
        nitter_instances: Ordered list of Nitter base URLs to try
        lookback_hours:   Only include posts within this many hours
        min_length:       Minimum text length to include a post
        delay:            Seconds to wait between handles (be polite to servers)

    Returns:
        Flat list of Post objects sorted newest-first.
    """
    all_posts: list[Post] = []

    logger.info(f"Fetching {len(handles)} handle(s) over last {lookback_hours}h …")

    for i, handle in enumerate(handles, 1):
        logger.info(f"[{i}/{len(handles)}] Fetching @{handle} …")
        posts = fetch_handle(handle, nitter_instances, lookback_hours, min_length, delay)
        all_posts.extend(posts)

        if i < len(handles):
            time.sleep(delay)

    # Sort newest-first
    all_posts.sort(key=lambda p: p.timestamp, reverse=True)

    logger.info(f"Total posts collected: {len(all_posts)}")
    return all_posts
