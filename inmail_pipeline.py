#!/usr/bin/env python3
"""
LinkedIn InMail Pipeline.

Orchestrates scraping and classification in one command.

Usage:
    python3 inmail_pipeline.py                   # classify only (use existing raw data)
    python3 inmail_pipeline.py --scrape          # scrape then classify
    python3 inmail_pipeline.py --scrape --visible # scrape with visible browser
    python3 inmail_pipeline.py --login           # login mode (no scrape/classify)
    python3 inmail_pipeline.py --scrape --force  # scrape + re-classify all
"""

import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
RAW_FILE = BASE_DIR / "inmail_raw.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="LinkedIn InMail Pipeline")
    parser.add_argument("--scrape", action="store_true", help="Run scraper before classifying")
    parser.add_argument("--visible", action="store_true", help="Run browser visibly (with --scrape)")
    parser.add_argument("--login", action="store_true", help="Interactive login mode")
    parser.add_argument(
        "--campaign-start",
        default=None,
        help="Override campaign start date (YYYY-MM-DD)",
    )
    parser.add_argument("--force", action="store_true", help="Re-classify all replies")
    args = parser.parse_args()

    # Login mode — just set up the session, nothing else
    if args.login:
        from inmail_scraper import login_interactive
        login_interactive()
        return 0

    # Step 1: Scrape (if requested or raw file is missing)
    if args.scrape or not RAW_FILE.exists():
        if not args.scrape:
            print(f"inmail_raw.json not found — running scraper first.")
        from inmail_scraper import scrape
        records = scrape(headless=not args.visible)
        if not records:
            print("Scrape returned no records. Aborting.")
            return 1

    # Step 2: Classify
    from inmail_classifier import classify, DEFAULT_CAMPAIGN_START
    campaign_start = args.campaign_start or DEFAULT_CAMPAIGN_START
    classify(campaign_start_str=campaign_start, force=args.force)

    return 0


if __name__ == "__main__":
    sys.exit(main())
