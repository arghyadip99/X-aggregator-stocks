"""
storage.py — Supabase read/write for digests, posts, and subscribers.

Requires environment variables:
  SUPABASE_URL         — your project URL (https://xxx.supabase.co)
  SUPABASE_SERVICE_KEY — service role key (NOT anon key — has write access)

SQL schema to run once in Supabase SQL editor:
  See supabase_schema.sql in the project root.
"""

import logging
import os
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


def _get_client():
    """Lazy-init Supabase client to avoid import errors when not configured."""
    try:
        from supabase import create_client
    except ImportError:
        raise RuntimeError("supabase package not installed. Run: pip install supabase")

    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_KEY", "").strip()

    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env "
            "to use Supabase storage."
        )
    return create_client(url, key)


# ---------------------------------------------------------------------------
# Digests
# ---------------------------------------------------------------------------

def save_digest(
    category_id: str,
    category_label: str,
    digest_html: str,
    num_posts: int,
    num_handles: int,
    lookback_hours: int = 24,
) -> None:
    """
    Persist a generated digest to Supabase.
    The frontend reads from this table to display the latest digests.
    """
    try:
        client = _get_client()
        client.table("digests").insert({
            "category":     category_id,
            "label":        category_label,
            "digest_html":  digest_html,
            "num_posts":    num_posts,
            "num_handles":  num_handles,
            "lookback_hours": lookback_hours,
            "run_at":       datetime.now(IST).isoformat(),
        }).execute()
        logger.info(f"[{category_label}] Digest saved to Supabase.")
    except Exception as e:
        logger.error(f"Failed to save digest to Supabase: {e}")
        # Non-fatal — email delivery already happened


def save_posts(posts: list, category_map: dict) -> None:
    """
    Persist individual categorised posts to Supabase.

    Args:
        posts:        All Post objects.
        category_map: Dict mapping post → category_id
                      (built in main.py from categorize_posts output).
    """
    if not posts:
        return

    try:
        client = _get_client()
        rows = []
        for post in posts:
            cat_id = category_map.get(id(post), "analysis")
            rows.append({
                "handle":     post.handle,
                "content":    post.text,
                "category":   cat_id,
                "posted_at":  post.timestamp.isoformat(),
                "fetched_at": datetime.now(IST).isoformat(),
            })

        # Batch insert in chunks of 100
        chunk_size = 100
        for i in range(0, len(rows), chunk_size):
            client.table("posts").insert(rows[i:i + chunk_size]).execute()

        logger.info(f"Saved {len(rows)} posts to Supabase.")
    except Exception as e:
        logger.error(f"Failed to save posts to Supabase: {e}")


# ---------------------------------------------------------------------------
# Subscribers
# ---------------------------------------------------------------------------

def get_subscribers(category_id: str) -> list[str]:
    """
    Fetch confirmed subscriber emails for a given category.
    Used to send digest to all subscribers, not just the owner.
    """
    try:
        client = _get_client()
        response = (
            client.table("subscribers")
            .select("email")
            .eq("confirmed", True)
            .contains("categories", [category_id])
            .execute()
        )
        emails = [row["email"] for row in (response.data or [])]
        logger.info(f"[{category_id}] Found {len(emails)} subscriber(s).")
        return emails
    except Exception as e:
        logger.error(f"Failed to fetch subscribers: {e}")
        return []


def add_subscriber(email: str, categories: list[str] | None = None) -> bool:
    """
    Add a new subscriber (unconfirmed). Returns True on success.
    Confirmation flow is handled via Supabase Edge Function.
    """
    try:
        client = _get_client()
        client.table("subscribers").upsert({
            "email":      email.lower().strip(),
            "confirmed":  False,
            "categories": categories or ["analysis", "company_updates", "quarterly_updates", "macro"],
        }, on_conflict="email").execute()
        logger.info(f"Subscriber added: {email}")
        return True
    except Exception as e:
        logger.error(f"Failed to add subscriber {email}: {e}")
        return False
