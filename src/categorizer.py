"""
categorizer.py — AI-based post classification using Groq (Llama).

Takes all scraped posts and classifies each one into the best-fit category
defined in config.yaml. Uses a single batch Groq call to classify all posts
at once (minimises API usage).

Returns a dict mapping category_id → list of Posts.
"""

import json
import logging
import time

from groq import Groq

from .fetcher import Post

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert Indian equity market analyst and content classifier.
Your job is to classify social media posts from Indian stock market researchers
into predefined categories.

Rules:
1. Assign each post to EXACTLY ONE category — the best fit.
2. If a post fits multiple categories, pick the PRIMARY theme.
3. If a post doesn't fit any category well (e.g., jokes, off-topic), use the first category as default.
4. Return ONLY valid JSON — no explanation, no markdown, no code fences.
"""

_USER_PROMPT = """\
Classify each of the following {num_posts} posts into one of these categories:

{categories_block}

Posts to classify:
{posts_block}

Return a JSON array with one object per post, in order:
[
  {{"id": 1, "category": "category_id_here"}},
  {{"id": 2, "category": "category_id_here"}},
  ...
]

Only use category IDs from the list above. Return ONLY the JSON array.
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_categories_block(categories: list[dict]) -> str:
    lines = []
    for cat in categories:
        lines.append(f'- id: "{cat["id"]}" → {cat["label"]}: {cat["prompt_focus"].strip()}')
    return "\n".join(lines)


def _build_posts_block(posts: list[Post]) -> str:
    lines = []
    for i, p in enumerate(posts, 1):
        # Truncate very long posts to keep the prompt concise
        text = p.text[:300] + "…" if len(p.text) > 300 else p.text
        lines.append(f'[{i}] @{p.handle}: {text}')
    return "\n".join(lines)


def _parse_response(raw: str, num_posts: int, fallback_id: str) -> list[str]:
    """Parse Groq JSON response into a list of category IDs (one per post)."""
    # Strip any accidental markdown fences
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.rsplit("```", 1)[0].strip()

    try:
        data = json.loads(raw)
        result = [fallback_id] * num_posts
        for item in data:
            idx = int(item.get("id", 0)) - 1
            if 0 <= idx < num_posts:
                result[idx] = item.get("category", fallback_id)
        return result
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.warning(f"Failed to parse categorizer response: {e}. Using fallback category.")
        return [fallback_id] * num_posts


# ---------------------------------------------------------------------------
# Main categorize function
# ---------------------------------------------------------------------------

def categorize_posts(
    posts: list[Post],
    categories: list[dict],
    api_key: str,
    model_name: str = "llama-3.3-70b-versatile",
    retries: int = 2,
    retry_delay: float = 10.0,
) -> dict[str, list[Post]]:
    """
    Classify all posts into categories using a single Groq API call.

    Args:
        posts:       All scraped Post objects (from all handles).
        categories:  List of category dicts from config (id, label, prompt_focus).
        api_key:     Groq API key.
        model_name:  Groq model to use.
        retries:     Number of retry attempts on failure.
        retry_delay: Seconds to wait between retries.

    Returns:
        Dict mapping category_id → list of Post objects.
    """
    # Initialise result buckets for all enabled categories
    enabled = [c for c in categories if c.get("enabled", True)]
    category_ids = [c["id"] for c in enabled]
    result: dict[str, list[Post]] = {cid: [] for cid in category_ids}
    fallback_id = category_ids[0] if category_ids else "analysis"

    if not posts:
        logger.info("No posts to categorize.")
        return result

    if not enabled:
        logger.warning("No enabled categories found — putting all posts in fallback.")
        result[fallback_id] = list(posts)
        return result

    client = Groq(api_key=api_key)
    categories_block = _build_categories_block(enabled)
    posts_block = _build_posts_block(posts)

    prompt = _USER_PROMPT.format(
        num_posts=len(posts),
        categories_block=categories_block,
        posts_block=posts_block,
    )

    logger.info(f"Categorizing {len(posts)} posts across {len(enabled)} categories …")

    for attempt in range(retries + 1):
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,   # Very low — we want deterministic classification
                max_tokens=1024,
            )
            raw = response.choices[0].message.content.strip()
            assigned = _parse_response(raw, len(posts), fallback_id)

            # Distribute posts into buckets
            for post, cat_id in zip(posts, assigned):
                if cat_id in result:
                    result[cat_id].append(post)
                else:
                    logger.warning(f"Unknown category '{cat_id}' assigned — using fallback.")
                    result[fallback_id].append(post)

            # Log distribution
            for cid, bucket in result.items():
                if bucket:
                    logger.info(f"  → {cid}: {len(bucket)} post(s)")

            logger.info("Categorization complete.")
            return result

        except Exception as e:
            if attempt < retries:
                logger.warning(f"Categorizer attempt {attempt + 1} failed: {e}. Retrying in {retry_delay}s …")
                time.sleep(retry_delay)
            else:
                logger.error(f"Categorizer failed after {retries + 1} attempts: {e}. Falling back — all posts → {fallback_id}.")
                result[fallback_id] = list(posts)
                return result
