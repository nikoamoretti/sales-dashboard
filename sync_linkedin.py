#!/usr/bin/env python3
"""
sync_linkedin.py — Build weekly_snapshots for LinkedIn from raw inmails table.

Reads all inmails from Supabase, aggregates by week_num, and upserts
into weekly_snapshots with channel='linkedin'.

Usage:
    python3 sync_linkedin.py
    python3 sync_linkedin.py --dry-run
"""

import argparse
import os
import sys
from collections import defaultdict
from datetime import date, timedelta

from dotenv import load_dotenv

load_dotenv()

CAMPAIGN_START = date(2026, 1, 19)


def week_monday(week_num: int) -> str:
    return (CAMPAIGN_START + timedelta(weeks=week_num - 1)).isoformat()


def _sb():
    from supabase import create_client
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_KEY"],
    )


def sync(dry_run: bool = False) -> int:
    sb = _sb()

    print("Fetching inmails from Supabase...")
    result = sb.table("inmails").select(
        "week_num, replied, reply_sentiment"
    ).execute()
    inmails = result.data or []
    print(f"  {len(inmails)} raw inmails")

    if not inmails:
        print("  No inmails to aggregate.")
        return 0

    # Aggregate by week
    by_week = defaultdict(lambda: {"sent": 0, "replied": 0, "interested": 0})
    for im in inmails:
        wk = im.get("week_num")
        if not wk:
            continue
        by_week[wk]["sent"] += 1
        if im.get("replied"):
            by_week[wk]["replied"] += 1
        if im.get("reply_sentiment") == "interested":
            by_week[wk]["interested"] += 1

    records = []
    for wk in sorted(by_week.keys()):
        d = by_week[wk]
        rr = round(d["replied"] / d["sent"] * 100, 1) if d["sent"] else 0.0
        records.append({
            "week_num": wk,
            "monday": week_monday(wk),
            "channel": "linkedin",
            "inmails_sent": d["sent"],
            "inmails_replied": d["replied"],
            "inmail_reply_rate": rr,
            "interested_count": d["interested"],
        })

    if dry_run:
        print(f"\n  [dry-run] Would upsert {len(records)} linkedin snapshots:")
        for r in records:
            print(f"    Wk {r['week_num']}: sent={r['inmails_sent']}, "
                  f"replied={r['inmails_replied']}, rr={r['inmail_reply_rate']}%, "
                  f"interested={r['interested_count']}")
        return 0

    sb.table("weekly_snapshots").upsert(
        records, on_conflict="week_num,channel"
    ).execute()
    print(f"  Upserted {len(records)} linkedin weekly_snapshots")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync LinkedIn snapshots to Supabase")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    required = ["SUPABASE_URL", "SUPABASE_SERVICE_KEY"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"ERROR: Missing: {', '.join(missing)}", file=sys.stderr)
        return 1

    return sync(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
