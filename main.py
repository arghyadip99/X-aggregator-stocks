"""
main.py — Orchestrator for the Stock Research Aggregator.

Pipeline:
  1. Fetch posts from all handles via Nitter RSS
  2. AI categorizes each post (Groq)
  3. Generate per-category HTML digest (Groq)
  4. Send digest emails to recipients
  5. Store digests + posts in Supabase (if configured)

Usage:
  python main.py                         # Full run
  python main.py --dry-run               # No email, no Supabase — print only
  python main.py --category analysis     # Run only one category
  python main.py --hours 6              # Override lookback window
  python main.py --config /path/to.yaml  # Custom config
"""

import argparse
import logging
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))

from src.fetcher import fetch_all_handles
from src.categorizer import categorize_posts
from src.summarizer import summarize
from src.notifier import send_digest

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_config(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def get_env(key: str) -> str:
    val = os.getenv(key, "").strip()
    if not val:
        logger.error(f"Missing env var: {key}. Set it in .env or GitHub Secrets.")
        sys.exit(1)
    return val


# ---------------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="Stock Research Aggregator")
    p.add_argument("--config", type=Path,
                   default=Path(__file__).parent / "config.yaml")
    p.add_argument("--dry-run", action="store_true",
                   help="Print digests to stdout, skip email and Supabase")
    p.add_argument("--hours", type=int, default=None,
                   help="Override fetch_hours from config")
    p.add_argument("--category", type=str, default=None,
                   help="Run only a single category ID")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = parse_args()

    # 1. Load environment
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        load_dotenv(env_file)
        logger.info(f"Loaded environment from {env_file}")

    # 2. Load config
    if not args.config.exists():
        logger.error(f"Config not found: {args.config}")
        sys.exit(1)

    config = load_config(args.config)
    settings = config.get("settings", {})
    handles = [h.strip().lstrip("@") for h in (config.get("handles") or [])]
    categories = [c for c in (config.get("categories") or []) if c.get("enabled", True)]

    if not handles:
        logger.error("No handles configured in config.yaml")
        sys.exit(1)

    if not categories:
        logger.error("No enabled categories in config.yaml")
        sys.exit(1)

    # Filter to single category if requested
    if args.category:
        categories = [c for c in categories if c["id"] == args.category]
        if not categories:
            logger.error(f"Category '{args.category}' not found or not enabled.")
            sys.exit(1)
        logger.info(f"Running single category: {args.category}")
    else:
        logger.info(f"Running {len(categories)} categories: {[c['id'] for c in categories]}")

    # 3. Settings
    lookback_hours = args.hours or settings.get("fetch_hours", 24)
    nitter_instances = settings.get("nitter_instances", ["https://nitter.net"])
    min_length = settings.get("min_post_length", 30)
    delay = settings.get("fetch_delay_seconds", 1.0)
    model_name = settings.get("groq_model", "llama-3.3-70b-versatile")
    retries = settings.get("groq_retries", 2)
    retry_delay = float(settings.get("groq_retry_delay_seconds", 10))
    use_supabase = settings.get("use_supabase", False) and not args.dry_run

    # 4. Credentials
    groq_key = get_env("GROQ_API_KEY")
    sender_email = app_password = recipient_email = ""
    if not args.dry_run:
        sender_email = get_env("GMAIL_SENDER")
        app_password = get_env("GMAIL_APP_PASSWORD")
        recipient_email = get_env("RECIPIENT_EMAIL")

    # =========================================================================
    # STEP 1 — Fetch all posts
    # =========================================================================
    logger.info("=" * 60)
    logger.info(f"STEP 1 — Fetching {len(handles)} handle(s) over last {lookback_hours}h")
    logger.info("=" * 60)

    all_posts = fetch_all_handles(
        handles=handles,
        nitter_instances=nitter_instances,
        lookback_hours=lookback_hours,
        min_length=min_length,
        delay=delay,
    )

    if not all_posts:
        logger.warning("No posts collected. Exiting.")
        sys.exit(0)

    logger.info(f"Total posts collected: {len(all_posts)}")

    # =========================================================================
    # STEP 2 — AI categorize all posts
    # =========================================================================
    logger.info("=" * 60)
    logger.info("STEP 2 — AI categorizing posts")
    logger.info("=" * 60)

    categorized = categorize_posts(
        posts=all_posts,
        categories=categories,
        api_key=groq_key,
        model_name=model_name,
        retries=retries,
        retry_delay=retry_delay,
    )

    # Build a post→category_id lookup for Supabase storage
    post_category_map = {}
    for cat_id, posts in categorized.items():
        for post in posts:
            post_category_map[id(post)] = cat_id

    # =========================================================================
    # STEP 3 — Store raw posts in Supabase
    # =========================================================================
    if use_supabase:
        logger.info("=" * 60)
        logger.info("STEP 3 — Saving posts to Supabase")
        logger.info("=" * 60)
        try:
            from src.storage import save_posts
            save_posts(all_posts, post_category_map)
        except Exception as e:
            logger.error(f"Supabase post storage failed (non-fatal): {e}")

    # =========================================================================
    # STEP 4-5 — Summarize + Email + Store digests
    # =========================================================================
    results = {}
    for cat in categories:
        cat_id = cat["id"]
        cat_label = cat.get("label", cat_id)
        cat_color = cat.get("color", "#0f3460")
        prompt_focus = cat.get("prompt_focus", "")

        posts = categorized.get(cat_id, [])

        logger.info("=" * 60)
        logger.info(f"CATEGORY: {cat_label} — {len(posts)} post(s)")
        logger.info("=" * 60)

        if not posts:
            logger.info(f"[{cat_label}] No posts — skipping.")
            results[cat_id] = "skipped"
            continue

        # Summarize
        try:
            digest_html = summarize(
                posts=posts,
                api_key=groq_key,
                model_name=model_name,
                lookback_hours=lookback_hours,
                category=cat_id,
                category_label=cat_label,
                prompt_focus=prompt_focus,
                retries=retries,
                retry_delay=retry_delay,
            )
        except Exception as e:
            logger.error(f"[{cat_label}] Summarization failed: {e}")
            results[cat_id] = "error"
            continue

        num_handles = len(set(p.handle for p in posts))

        # Deliver
        if args.dry_run:
            print(f"\n{'=' * 60}")
            print(f"DRY RUN — {cat_label}")
            print("=" * 60)
            print(digest_html)
            print("=" * 60)
            results[cat_id] = "dry_run"
        else:
            try:
                send_digest(
                    digest_html=digest_html,
                    sender_email=sender_email,
                    app_password=app_password,
                    recipient_email=recipient_email,
                    num_handles=num_handles,
                    num_posts=len(posts),
                    lookback_hours=lookback_hours,
                    category=cat_id,
                    category_label=cat_label,
                    category_color=cat_color,
                )
                results[cat_id] = "sent"
            except Exception as e:
                logger.error(f"[{cat_label}] Email failed: {e}")
                results[cat_id] = "email_error"

        # Store digest in Supabase
        if use_supabase:
            try:
                from src.storage import save_digest
                save_digest(
                    category_id=cat_id,
                    category_label=cat_label,
                    digest_html=digest_html,
                    num_posts=len(posts),
                    num_handles=num_handles,
                    lookback_hours=lookback_hours,
                )
            except Exception as e:
                logger.error(f"[{cat_label}] Supabase digest storage failed (non-fatal): {e}")

    # =========================================================================
    # Summary
    # =========================================================================
    logger.info("=" * 60)
    logger.info("RUN SUMMARY")
    logger.info("=" * 60)
    status_icons = {
        "sent": "✅ Sent", "dry_run": "📄 Dry run",
        "skipped": "⏭️  Skipped (no posts)", "error": "❌ Error",
        "email_error": "⚠️  Email failed",
    }
    for cat in categories:
        cid = cat["id"]
        status = status_icons.get(results.get(cid, "skipped"), "❓")
        logger.info(f"  {cat.get('label', cid):<28} {status}")
    logger.info("✅ All done!")


if __name__ == "__main__":
    main()
