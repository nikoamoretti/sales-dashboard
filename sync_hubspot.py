#!/usr/bin/env python3
"""
sync_hubspot.py — Sync HubSpot calls into Supabase.

Fetches calls for a date range, enriches with associations, categorizes,
upserts companies + calls, runs AI intel extraction on new calls, and
builds weekly_snapshots for the calls channel.

Usage:
    python3 sync_hubspot.py                    # sync last 7 days
    python3 sync_hubspot.py --since 2026-01-01 # sync since date
    python3 sync_hubspot.py --skip-intel       # skip AI intel extraction
    python3 sync_hubspot.py --dry-run          # show what would sync
"""

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent

# Campaign week numbering: Wk 1 = Jan 19, 2026
CAMPAIGN_START = date(2026, 1, 19)  # Monday of Week 1


def campaign_week_num(d: date) -> int:
    """Convert a date to campaign week number (1-based, Mon start)."""
    monday = d - timedelta(days=d.weekday())
    return ((monday - CAMPAIGN_START).days // 7) + 1


# ---------------------------------------------------------------------------
# Imports from project modules
# ---------------------------------------------------------------------------

from hubspot import (
    ADAM_OWNER_ID,
    CATEGORY_MAP,
    HUMAN_CONTACT_CATS,
    PACIFIC,
    categorize_call,
    enrich_calls_with_associations,
    fetch_calls,
    group_calls_by_week,
    load_historical_categories,
    parse_hs_timestamp,
    safe_int,
    strip_summary_html,
)
from call_intel import (
    EXTRACTABLE_CATEGORIES,
    GeminiBackend,
    build_text_block,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CALLS_CHANNEL = "calls"

# Company status precedence (higher index = higher status)
STATUS_PRECEDENCE = [
    "prospect", "contacted", "interested",
    "meeting_booked", "opportunity", "closed", "disqualified",
]

_STATUS_RANK = {s: i for i, s in enumerate(STATUS_PRECEDENCE)}


def _derive_status(category: str) -> str:
    """Map a call category to the best matching company status."""
    if category == "Meeting Booked":
        return "meeting_booked"
    if category == "Interested":
        return "interested"
    if category in {"Not Interested", "No Rail", "Wrong Person",
                    "Referral Given", "Gatekeeper"}:
        return "contacted"
    return "prospect"


# ---------------------------------------------------------------------------
# Supabase helpers
# ---------------------------------------------------------------------------

def get_supabase():
    from supabase import create_client
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    return create_client(url, key)


def fetch_existing_companies(sb) -> dict[str, dict]:
    """Return all companies keyed by name (lowercased) and also by hubspot_id."""
    result = sb.table("companies").select(
        "id, name, hubspot_id, status, channels_touched, total_touches, "
        "last_touch_at, first_touch_at"
    ).execute()

    by_name: dict[str, dict] = {}
    by_hubspot_id: dict[str, dict] = {}

    for row in result.data:
        by_name[row["name"].lower()] = row
        if row.get("hubspot_id"):
            by_hubspot_id[row["hubspot_id"]] = row

    return by_name, by_hubspot_id


def fetch_existing_call_ids(sb) -> set[str]:
    """Fetch all hubspot_call_ids already in the calls table."""
    result = sb.table("calls").select("hubspot_call_id").execute()
    return {r["hubspot_call_id"] for r in result.data if r.get("hubspot_call_id")}


def fetch_intel_call_ids(sb) -> set[int]:
    """Fetch call.id values that already have a call_intel record."""
    result = sb.table("call_intel").select("call_id").execute()
    return {r["call_id"] for r in result.data if r.get("call_id")}


# ---------------------------------------------------------------------------
# Company upsert logic
# ---------------------------------------------------------------------------

def upsert_companies(
    sb,
    calls: list[dict],
    enrichment: dict[str, dict],
    historical: dict[str, str],
    dry_run: bool = False,
) -> dict[str, int]:
    """
    Upsert companies from this batch of calls.

    - Matches by hubspot_id first, then by name (case-insensitive).
    - Adds 'calls' to channels_touched if missing.
    - Increments total_touches.
    - Updates last_touch_at / first_touch_at.
    - Updates hubspot_id on name-matched records that don't have one yet.

    Returns: mapping of hubspot_company_id -> supabase company id.
    """
    by_name, by_hubspot_id = fetch_existing_companies(sb)

    # Aggregate per-company data from this call batch
    company_data: dict[str, dict] = {}  # keyed by hubspot_company_id

    for call in calls:
        call_id = str(call.get("id", ""))
        enrich = enrichment.get(call_id, {})
        hs_company_id = enrich.get("company_id", "")
        company_name = (enrich.get("company_name") or "").strip()

        if not company_name and not hs_company_id:
            continue

        key = hs_company_id or company_name.lower()
        if key not in company_data:
            category = categorize_call(call, historical)
            ts = parse_hs_timestamp(
                call.get("properties", {}).get("hs_timestamp")
            )
            ts_iso = ts.isoformat() if ts else None

            company_data[key] = {
                "hs_company_id": hs_company_id,
                "name": company_name,
                "touches": 0,
                "best_category": category,
                "first_ts": ts_iso,
                "last_ts": ts_iso,
            }
        entry = company_data[key]
        entry["touches"] += 1

        # Track best category (highest status rank)
        this_category = categorize_call(call, historical)
        current_status = _derive_status(entry["best_category"])
        new_status = _derive_status(this_category)
        if _STATUS_RANK.get(new_status, 0) > _STATUS_RANK.get(current_status, 0):
            entry["best_category"] = this_category

        # Track timestamps
        ts = parse_hs_timestamp(
            call.get("properties", {}).get("hs_timestamp")
        )
        ts_iso = ts.isoformat() if ts else None
        if ts_iso:
            if not entry["first_ts"] or ts_iso < entry["first_ts"]:
                entry["first_ts"] = ts_iso
            if not entry["last_ts"] or ts_iso > entry["last_ts"]:
                entry["last_ts"] = ts_iso

    # Resolve each company to existing row or new insert
    to_insert: list[dict] = []
    to_update: list[dict] = []

    for key, cd in company_data.items():
        hs_id = cd["hs_company_id"]
        name = cd["name"]
        new_status = _derive_status(cd["best_category"])
        touches = cd["touches"]

        # Find existing record
        existing = None
        matched_by = None

        if hs_id and hs_id in by_hubspot_id:
            existing = by_hubspot_id[hs_id]
            matched_by = "hubspot_id"
        elif name and name.lower() in by_name:
            existing = by_name[name.lower()]
            matched_by = "name"

        if existing:
            # Build update payload
            channels = list(existing.get("channels_touched") or [])
            if CALLS_CHANNEL not in channels:
                channels.append(CALLS_CHANNEL)

            current_rank = _STATUS_RANK.get(existing.get("status", "prospect"), 0)
            new_rank = _STATUS_RANK.get(new_status, 0)
            status = (
                STATUS_PRECEDENCE[max(current_rank, new_rank)]
            )

            update: dict = {
                "channels_touched": channels,
                "total_touches": (existing.get("total_touches") or 0) + touches,
                "last_touch_at": cd["last_ts"],
                "status": status,
            }

            # Set first_touch_at only if not already set or our first is earlier
            existing_first = existing.get("first_touch_at")
            if cd["first_ts"] and (
                not existing_first or cd["first_ts"] < existing_first
            ):
                update["first_touch_at"] = cd["first_ts"]

            # Backfill hubspot_id if we matched by name and it was missing
            if matched_by == "name" and not existing.get("hubspot_id") and hs_id:
                update["hubspot_id"] = hs_id

            to_update.append({"id": existing["id"], **update})
        else:
            # New company
            to_insert.append({
                "name": name or f"Unknown (HS:{hs_id})",
                "hubspot_id": hs_id or None,
                "status": new_status,
                "channels_touched": [CALLS_CHANNEL],
                "total_touches": touches,
                "first_touch_at": cd["first_ts"],
                "last_touch_at": cd["last_ts"],
            })

    if dry_run:
        print(f"  [dry-run] Would insert {len(to_insert)} new companies")
        print(f"  [dry-run] Would update {len(to_update)} existing companies")
        # Build a fake hs_id -> supabase_id map from existing records only
        result_map: dict[str, int] = {}
        for cd in company_data.values():
            hs_id = cd["hs_company_id"]
            name = cd["name"]
            existing = (
                by_hubspot_id.get(hs_id) if hs_id else None
            ) or by_name.get((name or "").lower())
            if existing:
                result_map[hs_id or name.lower()] = existing["id"]
        return result_map

    # Execute inserts
    inserted_ids: dict[str, int] = {}
    if to_insert:
        resp = sb.table("companies").insert(to_insert).execute()
        for row in resp.data:
            hs = row.get("hubspot_id") or ""
            nm = row.get("name", "").lower()
            if hs:
                inserted_ids[hs] = row["id"]
            inserted_ids[nm] = row["id"]
        print(f"  Inserted {len(to_insert)} new companies")

    # Execute updates (row by row — Supabase client doesn't support bulk update)
    if to_update:
        for upd in to_update:
            row_id = upd.pop("id")
            sb.table("companies").update(upd).eq("id", row_id).execute()
        print(f"  Updated {len(to_update)} existing companies")

    # Rebuild lookup after mutations
    # Re-fetch to get final state (needed for FK resolution in calls)
    by_name_new, by_hubspot_id_new = fetch_existing_companies(sb)

    result_map: dict[str, int] = {}
    for cd in company_data.values():
        hs_id = cd["hs_company_id"]
        name = cd["name"]
        existing = (
            by_hubspot_id_new.get(hs_id) if hs_id else None
        ) or by_name_new.get((name or "").lower())
        if existing:
            result_map[hs_id or name.lower()] = existing["id"]

    return result_map


# ---------------------------------------------------------------------------
# Call upsert
# ---------------------------------------------------------------------------

def build_call_record(
    call: dict,
    enrichment: dict[str, dict],
    historical: dict[str, str],
    company_id_map: dict[str, int],
) -> Optional[dict]:
    """Build a Supabase calls row dict from a HubSpot call object."""
    call_id = str(call.get("id", ""))
    props = call.get("properties", {})
    enrich = enrichment.get(call_id, {})

    ts = parse_hs_timestamp(props.get("hs_timestamp"))
    if not ts:
        return None

    category = categorize_call(call, historical)
    duration_ms = safe_int(props.get("hs_call_duration"))
    summary_raw = props.get("hs_call_summary") or props.get("hs_body_preview") or ""
    notes_raw = props.get("hs_call_body") or ""

    # Resolve company FK
    hs_company_id = enrich.get("company_id", "")
    company_name = (enrich.get("company_name") or "").strip()
    supabase_company_id = (
        company_id_map.get(hs_company_id)
        or company_id_map.get(company_name.lower())
    )

    # Campaign week number (Wk 1 = Jan 19, 2026)
    week_num = campaign_week_num(ts.date())

    return {
        "hubspot_call_id": call_id,
        "company_id": supabase_company_id,
        "contact_name": enrich.get("contact_name") or "Unknown",
        "category": category,
        "duration_s": duration_ms // 1000,
        "notes": notes_raw,
        "summary": strip_summary_html(summary_raw),
        "recording_url": props.get("hs_call_recording_url") or "",
        "has_transcript": (props.get("hs_call_has_transcript") or "").lower() == "true",
        "called_at": ts.isoformat(),
        "week_num": week_num,
    }


def upsert_calls(
    sb,
    calls: list[dict],
    enrichment: dict[str, dict],
    historical: dict[str, str],
    company_id_map: dict[str, int],
    existing_call_ids: set[str],
    dry_run: bool = False,
) -> tuple[list[dict], list[int]]:
    """
    Upsert calls by hubspot_call_id.

    Returns: (all_records, new_call_supabase_ids)
    """
    records = []
    for call in calls:
        rec = build_call_record(call, enrichment, historical, company_id_map)
        if rec:
            records.append(rec)

    new_records = [r for r in records if r["hubspot_call_id"] not in existing_call_ids]
    existing_records = [r for r in records if r["hubspot_call_id"] in existing_call_ids]

    if dry_run:
        print(f"  [dry-run] Would insert {len(new_records)} new calls")
        print(f"  [dry-run] Would upsert {len(existing_records)} existing calls")
        return records, []

    # Upsert all (insert new, update existing)
    new_supabase_ids: list[int] = []
    if records:
        resp = sb.table("calls").upsert(
            records, on_conflict="hubspot_call_id"
        ).execute()
        # Collect IDs of newly inserted calls for intel extraction
        inserted_hs_ids = {r["hubspot_call_id"] for r in new_records}
        for row in resp.data:
            if row.get("hubspot_call_id") in inserted_hs_ids:
                new_supabase_ids.append(row["id"])

    print(f"  Upserted {len(records)} calls ({len(new_records)} new, "
          f"{len(existing_records)} updated)")
    return records, new_supabase_ids


# ---------------------------------------------------------------------------
# Call intel extraction
# ---------------------------------------------------------------------------

def run_intel_extraction(
    sb,
    calls: list[dict],
    enrichment: dict[str, dict],
    historical: dict[str, str],
    new_supabase_ids: list[int],
    dry_run: bool = False,
) -> int:
    """
    Extract call intel for new calls that are in EXTRACTABLE_CATEGORIES
    and don't already have a call_intel record.

    Returns: number of records extracted.
    """
    # Fetch current call_intel call_ids to avoid duplicates
    existing_intel_call_ids = fetch_intel_call_ids(sb)

    # Fetch call rows for the new IDs we just inserted
    if not new_supabase_ids:
        print("  No new calls requiring intel extraction")
        return 0

    # Fetch call records from Supabase (we need id + hubspot_call_id + company_id)
    result = sb.table("calls").select(
        "id, hubspot_call_id, company_id, contact_name, category, duration_s, notes, summary"
    ).in_("id", new_supabase_ids).execute()

    call_rows = {r["hubspot_call_id"]: r for r in result.data}

    # Build the candidate list for extraction
    to_extract: list[tuple[dict, dict]] = []  # (hs_call_raw, sb_call_row)

    for call in calls:
        call_id = str(call.get("id", ""))
        sb_row = call_rows.get(call_id)
        if not sb_row:
            continue  # not a new call
        if sb_row["id"] in existing_intel_call_ids:
            continue  # already has intel
        if sb_row.get("category") not in EXTRACTABLE_CATEGORIES:
            continue

        enrich = enrichment.get(call_id, {})
        # Build a call dict in the format call_intel.py expects
        call_for_intel = {
            "id": call_id,
            "contact_name": sb_row.get("contact_name") or enrich.get("contact_name") or "Unknown",
            "company_name": enrich.get("company_name") or "",
            "category": sb_row["category"],
            "duration_s": sb_row.get("duration_s", 0),
            "summary": sb_row.get("summary") or "",
            "notes": sb_row.get("notes") or "",
            "engagement_notes": enrich.get("engagement_notes") or [],
        }

        text = build_text_block(call_for_intel)
        if not text.strip():
            continue

        to_extract.append((call_for_intel, sb_row))

    if not to_extract:
        print("  No calls requiring intel extraction")
        return 0

    if dry_run:
        print(f"  [dry-run] Would extract intel for {len(to_extract)} calls:")
        for call_for_intel, _ in to_extract[:5]:
            print(f"    {call_for_intel['contact_name']:30s} "
                  f"{call_for_intel['company_name']:25s} "
                  f"[{call_for_intel['category']}]")
        if len(to_extract) > 5:
            print(f"    ... and {len(to_extract) - 5} more")
        return 0

    print(f"  Extracting intel for {len(to_extract)} calls via Gemini...")
    try:
        backend = GeminiBackend()
    except ValueError as exc:
        print(f"  WARNING: Cannot init Gemini — {exc}. Skipping intel.")
        return 0

    extracted = 0
    errors = 0
    intel_records: list[dict] = []

    for i, (call_for_intel, sb_row) in enumerate(to_extract, 1):
        name = call_for_intel["contact_name"]
        company = call_for_intel["company_name"]
        print(f"  [{i}/{len(to_extract)}] {name} ({company})...", end=" ", flush=True)

        try:
            intel = backend.extract(call_for_intel)
        except Exception as exc:
            print(f"ERROR: {exc}")
            errors += 1
            if errors > 5:
                print("  Too many errors, stopping intel extraction.")
                break
            time.sleep(2)
            continue

        if not intel:
            print("SKIP (no parseable result)")
            continue

        level = intel.get("interest_level", "?")
        action = (intel.get("next_action") or "")[:60]
        print(f"[{level}] {action}")

        intel_records.append({
            "call_id": sb_row["id"],
            "company_id": sb_row.get("company_id"),
            "interest_level": intel.get("interest_level"),
            "qualified": bool(intel.get("qualified", False)),
            "next_action": intel.get("next_action"),
            "objection": intel.get("objection"),
            "competitor": intel.get("competitor"),
            "commodities": intel.get("commodities"),
            "referral_name": intel.get("referral_name"),
            "referral_role": intel.get("referral_role"),
            "key_quote": intel.get("key_quote"),
        })
        extracted += 1

        # Gemini free tier: ~15 RPM — pace to 4.2s per request
        time.sleep(4.2)

    # Batch insert intel records
    if intel_records:
        sb.table("call_intel").insert(intel_records).execute()
        print(f"  Inserted {len(intel_records)} call_intel records")

    return extracted


# ---------------------------------------------------------------------------
# Weekly snapshots
# ---------------------------------------------------------------------------

def upsert_weekly_snapshots(
    sb,
    calls: list[dict],
    historical: dict[str, str],
    dry_run: bool = False,
) -> int:
    """
    Build and upsert weekly_snapshots rows for the calls channel.

    Only processes weeks present in the current call batch.
    Returns: number of snapshots upserted.
    """
    # Group calls by ISO week
    week_calls: dict[date, list[dict]] = defaultdict(list)
    for call in calls:
        ts = parse_hs_timestamp(call.get("properties", {}).get("hs_timestamp"))
        if not ts:
            continue
        monday = ts.date() - timedelta(days=ts.weekday())
        week_calls[monday].append(call)

    if not week_calls:
        return 0

    # Fetch existing snapshots to avoid overwriting complete weeks with partial data
    today = date.today()
    current_monday = today - timedelta(days=today.weekday())
    existing_snaps: dict[int, int] = {}  # week_num -> existing dials count
    if not dry_run:
        existing = sb.table("weekly_snapshots").select(
            "week_num, dials"
        ).eq("channel", CALLS_CHANNEL).execute()
        existing_snaps = {r["week_num"]: r["dials"] or 0 for r in existing.data}

    records: list[dict] = []
    for monday, wk_calls in sorted(week_calls.items()):
        categories: Counter = Counter()
        human_contacts = 0
        meetings_booked = 0

        for call in wk_calls:
            cat = categorize_call(call, historical)
            categories[cat] += 1
            if cat in HUMAN_CONTACT_CATS:
                human_contacts += 1
            if cat == "Meeting Booked":
                meetings_booked += 1

        total = sum(categories.values())
        hcr = round(human_contacts / total * 100, 1) if total else 0.0
        week_num = campaign_week_num(monday)

        # Skip past weeks where we have MORE data already (partial sync would corrupt)
        if monday < current_monday:
            existing_count = existing_snaps.get(week_num, 0)
            if total < existing_count:
                print(f"  Skipping Wk {week_num} ({monday}): sync has {total} dials but DB has {existing_count}")
                continue

        records.append({
            "week_num": week_num,
            "monday": monday.isoformat(),
            "channel": CALLS_CHANNEL,
            "dials": total,
            "human_contacts": human_contacts,
            "human_contact_rate": hcr,
            "meetings_booked": meetings_booked,
            "categories": json.dumps(dict(categories)),
        })

    if dry_run:
        print(f"  [dry-run] Would upsert {len(records)} weekly_snapshots")
        for r in records:
            print(f"    Week {r['week_num']} ({r['monday']}): "
                  f"{r['dials']} dials, {r['human_contacts']} HC, "
                  f"{r['meetings_booked']} mtg")
        return len(records)

    sb.table("weekly_snapshots").upsert(
        records, on_conflict="week_num,channel"
    ).execute()
    print(f"  Upserted {len(records)} weekly_snapshots for calls channel")
    return len(records)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def sync(
    since: Optional[date] = None,
    skip_intel: bool = False,
    dry_run: bool = False,
) -> None:
    token = os.environ.get("HUBSPOT_TOKEN")
    if not token:
        print("ERROR: HUBSPOT_TOKEN not set in environment.")
        sys.exit(1)

    # Determine date range
    now_utc = datetime.now(timezone.utc)
    if since:
        start_dt = datetime(since.year, since.month, since.day, tzinfo=timezone.utc)
    else:
        start_dt = now_utc - timedelta(days=7)

    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(now_utc.timestamp() * 1000)

    print(f"\n{'='*60}")
    print(f"HubSpot -> Supabase Sync")
    print(f"{'='*60}")
    print(f"Range : {start_dt.date().isoformat()} -> {now_utc.date().isoformat()}")
    if dry_run:
        print("Mode  : DRY RUN (no writes)")
    if skip_intel:
        print("Intel : SKIPPED")
    print()

    # Step 1: Fetch calls from HubSpot
    print("Step 1: Fetching calls from HubSpot...")
    calls = fetch_calls(token, start_ms, end_ms, owner_id=ADAM_OWNER_ID)
    print(f"  Total calls fetched: {len(calls)}")

    if not calls:
        print("No calls in range. Nothing to sync.")
        return

    # Step 2: Enrich with associations
    print("\nStep 2: Enriching with associations...")
    enrichment = enrich_calls_with_associations(token, calls)

    # Step 3: Load historical categories
    historical = load_historical_categories()

    # Connect to Supabase (needed for reads even in dry-run)
    sb = get_supabase()

    # Step 4: Upsert companies
    print("\nStep 3: Upserting companies...")
    company_id_map = upsert_companies(sb, calls, enrichment, historical, dry_run=dry_run)

    # Step 5: Upsert calls
    print("\nStep 4: Upserting calls...")
    existing_call_ids = fetch_existing_call_ids(sb)

    call_records, new_supabase_ids = upsert_calls(
        sb, calls, enrichment, historical, company_id_map,
        existing_call_ids, dry_run=dry_run,
    )

    # Step 6: Intel extraction
    if not skip_intel:
        print("\nStep 5: Running call intel extraction...")
        if not dry_run:
            intel_count = run_intel_extraction(
                sb, calls, enrichment, historical, new_supabase_ids, dry_run=False
            )
        else:
            intel_count = run_intel_extraction(
                sb, calls, enrichment, historical,
                # For dry-run, pretend all calls are new using fake IDs
                list(range(len(calls))),
                dry_run=True,
            )
    else:
        intel_count = 0

    # Step 7: Weekly snapshots
    print("\nStep 6: Building weekly snapshots...")
    snapshot_count = upsert_weekly_snapshots(sb, calls, historical, dry_run=dry_run)

    # Summary
    print(f"\n{'='*60}")
    print("Sync Summary")
    print(f"{'='*60}")
    print(f"  Calls fetched       : {len(calls)}")
    print(f"  Calls upserted      : {len(call_records)}")
    print(f"  New calls           : {len(new_supabase_ids) if not dry_run else '(dry-run)'}")
    print(f"  Intel extracted     : {intel_count if not skip_intel else 'skipped'}")
    print(f"  Weekly snapshots    : {snapshot_count}")

    # Category breakdown
    categories: Counter = Counter()
    for call in calls:
        categories[categorize_call(call, historical)] += 1

    print(f"\n  Category breakdown:")
    for cat, count in categories.most_common():
        marker = " *" if cat in HUMAN_CONTACT_CATS else ""
        print(f"    {cat:<20s} {count:>4d}{marker}")

    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync HubSpot calls into Supabase",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--since",
        metavar="YYYY-MM-DD",
        help="Sync calls since this date (default: last 7 days)",
    )
    parser.add_argument(
        "--skip-intel",
        action="store_true",
        help="Skip AI call intel extraction",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be synced without writing to Supabase",
    )
    args = parser.parse_args()

    since: Optional[date] = None
    if args.since:
        try:
            since = date.fromisoformat(args.since)
        except ValueError:
            print(f"ERROR: Invalid date format '{args.since}'. Use YYYY-MM-DD.")
            return 1

    sync(since=since, skip_intel=args.skip_intel, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
