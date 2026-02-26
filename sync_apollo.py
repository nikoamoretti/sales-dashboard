#!/usr/bin/env python3
"""
sync_apollo.py — Sync Apollo email sequence stats into Supabase.

Fetches all sequences via Apollo API and upserts into email_sequences table.

Usage:
    python3 sync_apollo.py
    python3 sync_apollo.py --dry-run
"""

import argparse
import os
import sys
from datetime import date

from dotenv import load_dotenv

load_dotenv()

from apollo_stats import fetch_apollo_stats


def _sb():
    from supabase import create_client
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_KEY"],
    )


def sync(dry_run: bool = False) -> int:
    api_key = os.environ.get("APOLLO_API_KEY")
    if not api_key:
        print("ERROR: APOLLO_API_KEY not set", file=sys.stderr)
        return 1

    print("Fetching Apollo sequence stats...")
    data = fetch_apollo_stats(api_key)
    sequences = data["sequences"]
    totals = data["totals"]

    print(f"  {len(sequences)} sequences, {totals['emails_sent']} total sent, "
          f"{totals['reply_rate']}% reply rate")

    if not sequences:
        print("  No sequences found.")
        return 0

    today = date.today().isoformat()
    records = []
    for seq in sequences:
        records.append({
            "sequence_name": seq["name"],
            "apollo_id": seq["id"],
            "status": "active" if seq["active"] else "paused",
            "sent": seq["emails_sent"],
            "delivered": seq["delivered"],
            "opened": seq["opened"],
            "replied": seq["replied"],
            "clicked": seq["clicked"],
            "open_rate": seq["open_rate"],
            "reply_rate": seq["reply_rate"],
            "click_rate": seq["click_rate"],
            "snapshot_date": today,
        })

    if dry_run:
        print(f"\n  [dry-run] Would upsert {len(records)} sequences:")
        for r in records:
            print(f"    {r['sequence_name']}: {r['sent']} sent, "
                  f"{r['reply_rate']}% RR ({r['status']})")
        return 0

    sb = _sb()

    # Delete today's existing snapshots and insert fresh
    sb.table("email_sequences").delete().eq("snapshot_date", today).execute()
    sb.table("email_sequences").insert(records).execute()
    print(f"  Upserted {len(records)} sequences for {today}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync Apollo stats to Supabase")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    required = ["APOLLO_API_KEY", "SUPABASE_URL", "SUPABASE_SERVICE_KEY"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"ERROR: Missing: {', '.join(missing)}", file=sys.stderr)
        return 1

    return sync(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
