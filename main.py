"""
main.py — Orchestrator for the Stock Research Aggregator.

Run this script directly to generate and send all 4 category digests:
    python main.py

Or with options:
    python main.py --dry-run                     # Print digests, no email
    python main.py --category analysis           # Run only one category
    python main.py --config /path/to/config.yaml
    python main.py --hours 48                    # Override lookback window

Flags:
  --dry-run   : Fetch & summarise but print the digest to stdout instead of emailing.
  --config    : Path to the YAML config file (default: config.yaml in same dir).
  --hours     : Override fetch_hours from config (e.g. --hours 48 for last 2 days).
  --category  : Run only a single category (analysis|company_updates|quarterly_updates|macro).
"""

import argparse
import logging
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Make sure 'src' is importable when running from project root
sys.path.insert(0, str(Path(__file__).parent))

from src.fetcher import fetch_all_handles
from src.summarizer import summarize, CATEGORIES
from src.notifier import send_digest

# ---------------------------------------------------------------------------
# Logging Setup
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config Loader
# ---------------------------------------------------------------------------

def load_config(config_path: Path) -> dict:
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def get_env(key: str, fallback: str = "") -> str:
    """Read from environment (set via .env file or GitHub Actions Secrets)."""
    val = os.getenv(key, fallback).strip()
    if not val:
        logger.error(
            f"Missing required environment variable: {key}. "
            f"Copy .env.example to .env and fill in your credentials."
        )
        sys.exit(1)
    return val


# ---------------------------------------------------------------------------
# CLI Argument Parsing
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="Stock Research Aggregator — Multi-Category Digest")
    p.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).parent / "config.yaml",
        help="Path to config.yaml (default: config.yaml next to main.py)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print digest to stdout instead of sending email",
    )
    p.add_argument(
        "--hours",
        type=int,
        default=None,
        help="Override fetch_hours from config",
    )
    p.add_argument(
        "--category",
        type=str,
        default=None,
        choices=list(CATEGORIES.keys()),
        help="Run only a single category instead of all four",
    )
    return p.parse_args()


# ---------------------------------------------------------------------------
# Process a single category
# ---------------------------------------------------------------------------

def process_category(
    category: str,
    handles: list,
    settings: dict,
    lookback_hours: int,
    groq_key: str,
    sender_email: str,
    app_password: str,
    recipient_email: str,
    dry_run: bool,
) -> bool:
    """
    Fetch posts, generate digest, and optionally email for one category.
    Returns True if digest was generated, False if skipped (no handles / no posts).
    """
    cat_label = CATEGORIES[category]["label"]

    if not handles:
        logger.info(f"[{cat_label}] No handles configured — skipping.")
        return False

    nitter_instances = settings.get("nitter_instances", ["https://nitter.net"])
    min_length = settings.get("min_post_length", 30)
    delay = settings.get("fetch_delay_seconds", 1.0)
    model_name = settings.get("groq_model", "llama-3.3-70b-versatile")

    logger.info("=" * 60)
    logger.info(f"CATEGORY: {cat_label} ({len(handles)} handle(s))")
    logger.info("=" * 60)

    # Step 1: Fetch
    posts = fetch_all_handles(
        handles=handles,
        nitter_instances=nitter_instances,
        lookback_hours=lookback_hours,
        min_length=min_length,
        delay=delay,
    )

    if not posts:
        logger.warning(f"[{cat_label}] No posts collected — skipping digest.")
        return False

    logger.info(f"[{cat_label}] {len(posts)} post(s) collected.")

    # Step 2: Summarise
    digest_html = summarize(
        posts=posts,
        api_key=groq_key,
        model_name=model_name,
        lookback_hours=lookback_hours,
        category=category,
    )

    # Step 3: Deliver
    if dry_run:
        print(f"\n{'=' * 60}")
        print(f"DRY RUN — {cat_label} DIGEST")
        print("=" * 60)
        print(digest_html)
        print("=" * 60)
        logger.info(f"[{cat_label}] Dry run complete. No email sent.")
    else:
        send_digest(
            digest_html=digest_html,
            sender_email=sender_email,
            app_password=app_password,
            recipient_email=recipient_email,
            num_handles=len(set(p.handle for p in posts)),
            num_posts=len(posts),
            lookback_hours=lookback_hours,
            category=category,
        )

    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = parse_args()

    # 1. Load .env file if present
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        load_dotenv(env_file)
        logger.info(f"Loaded environment from {env_file}")
    else:
        logger.info("No .env file found — expecting environment variables to be set externally.")

    # 2. Load YAML config
    if not args.config.exists():
        logger.error(f"Config file not found: {args.config}")
        sys.exit(1)

    config = load_config(args.config)
    settings = config.get("settings", {})
    handles_config = config.get("handles", {})

    # 3. Resolve lookback window
    lookback_hours = args.hours or settings.get("fetch_hours", 24)

    # 4. Load credentials
    groq_key = get_env("GROQ_API_KEY")
    sender_email = app_password = recipient_email = ""
    if not args.dry_run:
        sender_email = get_env("GMAIL_SENDER")
        app_password = get_env("GMAIL_APP_PASSWORD")
        recipient_email = get_env("RECIPIENT_EMAIL")

    # 5. Determine which categories to run
    if args.category:
        categories_to_run = [args.category]
        logger.info(f"Running single category: {args.category}")
    else:
        categories_to_run = list(CATEGORIES.keys())
        logger.info(f"Running all {len(categories_to_run)} categories.")

    # 6. Process each category
    results = {}
    for category in categories_to_run:
        handles = [
            h.strip().lstrip("@")
            for h in (handles_config.get(category) or [])
        ]
        success = process_category(
            category=category,
            handles=handles,
            settings=settings,
            lookback_hours=lookback_hours,
            groq_key=groq_key,
            sender_email=sender_email,
            app_password=app_password,
            recipient_email=recipient_email,
            dry_run=args.dry_run,
        )
        results[category] = success

    # 7. Summary
    logger.info("=" * 60)
    logger.info("RUN SUMMARY")
    logger.info("=" * 60)
    for cat, ok in results.items():
        label = CATEGORIES[cat]["label"]
        status = "✅ Sent" if ok and not args.dry_run else ("📄 Dry run" if ok else "⏭️  Skipped")
        logger.info(f"  {label:<28} {status}")
    logger.info("✅ All done!")


if __name__ == "__main__":
    main()
