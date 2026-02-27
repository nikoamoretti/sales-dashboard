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
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent
RAW_FILE = BASE_DIR / "inmail_raw.json"
INMAIL_DATA = BASE_DIR / "inmail_data.json"

# Classifier uses mixed case; DB uses lowercase
SENTIMENT_MAP = {
    "Interested": "interested",
    "Not Interested": "not_interested",
    "Neutral": "neutral",
    "OOO": "ooo",
}


def sync_to_supabase() -> None:
    """Upsert inmail_data.json into the Supabase inmails table."""
    if not INMAIL_DATA.exists():
        print("No inmail_data.json found, skipping Supabase sync.")
        return

    from supabase import create_client

    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
    data = json.loads(INMAIL_DATA.read_text())
    inmails = data.get("inmails", [])

    if not inmails:
        print("No inmails to sync.")
        return

    # Resolve company IDs by name
    companies_result = sb.table("companies").select("id, name").execute()
    name_to_id = {r["name"].lower(): r["id"] for r in (companies_result.data or [])}

    records = []
    for im in inmails:
        co_name = (im.get("company") or "").strip()
        sentiment = im.get("sentiment")
        db_sentiment = SENTIMENT_MAP.get(sentiment) if sentiment else None
        if sentiment and db_sentiment is None:
            print(f"  WARN: unknown sentiment '{sentiment}' for {im.get('recipient_name')}")

        records.append({
            "contact_name": im.get("recipient_name") or None,
            "contact_title": im.get("recipient_title") or None,
            "company_name": co_name,
            "company_id": name_to_id.get(co_name.lower()) if co_name else None,
            "sent_date": im.get("date_sent"),
            "replied": im.get("replied", False),
            "reply_sentiment": db_sentiment,
            "reply_text": im.get("reply_text") or None,
            "week_num": im.get("week_num"),
        })

    # No unique constraint on inmails (no natural key), so delete + re-insert.
    # Not atomic (Supabase REST has no transactions), but inmail_data.json is
    # the source of truth — a failed run just re-syncs next time.
    print(f"Syncing {len(records)} inmails to Supabase...")
    sb.table("inmails").delete().neq("id", 0).execute()

    new_count = 0
    for i in range(0, len(records), 200):
        chunk = records[i:i + 200]
        result = sb.table("inmails").insert(chunk).execute()
        new_count += len(result.data or [])

    print(f"  Synced {new_count} inmails to Supabase")


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

    # Step 3: Sync to Supabase
    if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_KEY"):
        sync_to_supabase()
    else:
        print("Skipping Supabase sync (SUPABASE_URL/SUPABASE_SERVICE_KEY not set)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
