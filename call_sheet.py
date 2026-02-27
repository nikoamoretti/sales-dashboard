#!/usr/bin/env python3
"""Daily call sheet generator → HubSpot tasks.

Reads call history from Supabase, applies cadence rules, and creates
prioritized HubSpot tasks for Adam to work from his task queue.

Usage:
    python3 call_sheet.py              # create today's HubSpot tasks
    python3 call_sheet.py --dry-run    # show what would be created
    python3 call_sheet.py --stats      # show roster stats only

Rules:
    - Max 4 call attempts per contact, spaced 3+ business days apart
    - Max 5 contacts worked per company
    - Terminal outcomes retire a contact permanently
    - Blocked companies (do_not_contact / not_interested / exhausted) are excluded
"""

import argparse
import os
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env.telegraph", override=True)
load_dotenv(ROOT / ".env", override=True)

# ── Config ──────────────────────────────────────────────────────────
MAX_ATTEMPTS = 4
COOLDOWN_DAYS = 3            # business days between calls to same contact
MAX_CONTACTS_PER_COMPANY = 5
DAILY_TARGET = 50            # contacts per day
BLOCKED_COMPANY_STATUSES = {"do_not_contact", "not_interested", "exhausted"}
TERMINAL_CATEGORIES = {"Not Interested", "No Rail", "Wrong Person", "Wrong Number"}
POSITIVE_CATEGORIES = {"Interested", "Meeting Booked", "Referral Given"}
MAX_VM_NO_REPLY = 3          # voicemails with no live answer → retire
MAX_NO_ANSWER = 5            # no-answers → retire
DNT_FILE = Path.home() / "nico_repo/rail-dashboard/dnt_accounts.txt"


def load_dnt_companies() -> set[str]:
    """Load do-not-touch company names (lowercased) from the DNT file."""
    if not DNT_FILE.exists():
        return set()
    return {line.strip().lower() for line in DNT_FILE.read_text().splitlines() if line.strip()}


def add_business_days(start: date, days: int) -> date:
    """Add N business days (Mon-Fri) to a date."""
    current = start
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:
            added += 1
    return current


# ── Supabase client ─────────────────────────────────────────────────

def get_supabase():
    from supabase import create_client
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    return create_client(url, key)


# ── Build contact profiles from call history ────────────────────────

def fetch_call_data(sb) -> tuple[list[dict], dict[str, dict]]:
    """Fetch calls (with company join data) and companies from Supabase."""
    # Fetch all calls with company info
    calls_resp = sb.table("calls").select(
        "contact_name, company_id, category, called_at, hubspot_contact_id, "
        "companies(id, name, hubspot_id, status)"
    ).order("called_at").execute()

    # Fetch blocked companies
    companies_resp = sb.table("companies").select(
        "id, name, hubspot_id, status"
    ).execute()

    companies_by_id = {}
    for co in companies_resp.data:
        companies_by_id[co["id"]] = co

    return calls_resp.data, companies_by_id


def build_contact_profiles(
    calls: list[dict],
    companies_by_id: dict[str, dict],
) -> list[dict]:
    """Build contact profiles from call history, applying cadence rules.

    Returns a list of callable contacts sorted by priority.
    """
    today = date.today()

    # Blocked company IDs (from Supabase status)
    blocked_company_ids = {
        cid for cid, co in companies_by_id.items()
        if co.get("status") in BLOCKED_COMPANY_STATUSES
    }

    # DNT list (from rail-dashboard file)
    dnt_companies = load_dnt_companies()

    # DNT company IDs — match by name (case-insensitive)
    dnt_company_ids = set()
    for cid, co in companies_by_id.items():
        co_name = (co.get("name") or "").lower()
        if co_name and co_name in dnt_companies:
            dnt_company_ids.add(cid)

    # Group calls by contact (name + company_id)
    profiles: dict[str, dict] = {}

    for c in calls:
        name = (c.get("contact_name") or "").strip()
        company_id = c.get("company_id")
        if not name or not company_id:
            continue

        co = c.get("companies") or companies_by_id.get(company_id, {})
        company_name = co.get("name", "") if isinstance(co, dict) else ""
        hubspot_company_id = co.get("hubspot_id", "") if isinstance(co, dict) else ""

        key = f"{name}|||{company_id}"
        if key not in profiles:
            profiles[key] = {
                "name": name,
                "company_name": company_name,
                "company_id": company_id,
                "hubspot_company_id": hubspot_company_id,
                "hubspot_contact_id": c.get("hubspot_contact_id") or "",
                "attempt_count": 0,
                "last_called_at": None,
                "best_outcome": None,
                "categories": [],
                "status": "active",
                "retired_reason": None,
            }

        p = profiles[key]
        cat = c.get("category", "")
        called_at = (c.get("called_at") or "")[:10]

        p["attempt_count"] += 1
        p["categories"].append(cat)
        if called_at:
            p["last_called_at"] = called_at

        # Keep most recent hubspot_contact_id
        hcid = c.get("hubspot_contact_id")
        if hcid:
            p["hubspot_contact_id"] = hcid

        # Track best outcome
        if cat in POSITIVE_CATEGORIES:
            p["best_outcome"] = cat
        elif cat in TERMINAL_CATEGORIES and not p["best_outcome"]:
            p["best_outcome"] = cat

    # Determine status for each contact
    for key, p in profiles.items():
        cats = p["categories"]

        # Blocked company (Supabase status)
        if p["company_id"] in blocked_company_ids:
            p["status"] = "blocked"
            p["retired_reason"] = "Company blocked"
            continue

        # DNT list (rail-dashboard)
        if p["company_id"] in dnt_company_ids:
            p["status"] = "blocked"
            p["retired_reason"] = "DNT list"
            continue

        # Meeting booked — in pipeline (check before terminal so it takes precedence)
        if "Meeting Booked" in cats:
            p["status"] = "retired"
            p["retired_reason"] = "Meeting booked"
            continue

        # Interested — hand off to Nico for email/meeting follow-up
        if "Interested" in cats:
            p["status"] = "retired"
            p["retired_reason"] = "Interested — follow up via email"
            continue

        # Terminal outcome
        terminal = [c for c in cats if c in TERMINAL_CATEGORIES]
        if terminal:
            p["status"] = "retired"
            p["retired_reason"] = f"Outcome: {terminal[-1]}"
            continue

        # Max attempts
        if p["attempt_count"] >= MAX_ATTEMPTS:
            p["status"] = "retired"
            p["retired_reason"] = f"Max attempts ({p['attempt_count']})"
            continue

        # VM exhaustion: N+ voicemails and never reached a live person
        vm_count = cats.count("Left Voicemail")
        ever_answered = any(c not in ("Left Voicemail", "No Answer") for c in cats)
        if vm_count >= MAX_VM_NO_REPLY and not ever_answered:
            p["status"] = "retired"
            p["retired_reason"] = f"{vm_count} voicemails, never answered"
            continue

        # No-answer exhaustion
        na_count = cats.count("No Answer")
        if na_count >= MAX_NO_ANSWER:
            p["status"] = "retired"
            p["retired_reason"] = f"{na_count} no-answers"
            continue

        # Cooldown check
        if p["last_called_at"]:
            last = date.fromisoformat(p["last_called_at"])
            next_callable = add_business_days(last, COOLDOWN_DAYS)
            if next_callable > today:
                p["status"] = "cooling"
                continue

    return list(profiles.values())


def select_callable_contacts(profiles: list[dict]) -> list[dict]:
    """Apply cadence rules and return up to DAILY_TARGET callable contacts."""
    today = date.today()

    # Filter to callable contacts
    callable_contacts = [
        p for p in profiles
        if p["status"] == "active"
    ]

    # Sort by priority: warm leads first, then fewest attempts, then oldest
    def sort_key(p):
        warm = 0 if p.get("best_outcome") in {"Interested", "Referral Given"} else 1
        return (warm, p["attempt_count"], p.get("last_called_at") or "")

    callable_contacts.sort(key=sort_key)

    # Enforce company-level limits
    company_total_worked = defaultdict(int)
    for p in profiles:
        if p["status"] in ("active", "cooling"):
            company_total_worked[p["company_id"]] += 1

    company_slots_today = defaultdict(int)
    call_sheet = []

    for p in callable_contacts:
        cid = p["company_id"]

        # Max contacts worked per company overall
        if company_total_worked.get(cid, 0) > MAX_CONTACTS_PER_COMPANY:
            continue

        # Max 3 per company per day
        if company_slots_today[cid] >= 3:
            continue

        company_slots_today[cid] += 1

        # Determine HubSpot task priority
        if p.get("best_outcome") in {"Interested", "Referral Given"}:
            priority = "HIGH"
        elif p["attempt_count"] > 0:
            priority = "MEDIUM"
        else:
            priority = "LOW"

        call_sheet.append({
            "name": p["name"],
            "company": p["company_name"],
            "company_id": p["company_id"],
            "hubspot_company_id": p["hubspot_company_id"],
            "hubspot_contact_id": p["hubspot_contact_id"],
            "attempt": p["attempt_count"] + 1,
            "last_called": p.get("last_called_at") or "—",
            "prior_best": p.get("best_outcome") or "—",
            "priority": priority,
        })

        if len(call_sheet) >= DAILY_TARGET:
            break

    return call_sheet


# ── Stats ────────────────────────────────────────────────────────────

def show_stats(profiles: list[dict]):
    today = date.today()
    total = len(profiles)

    status_counts = defaultdict(int)
    for p in profiles:
        status_counts[p["status"]] += 1

    print(f"\n{'=' * 55}")
    print(f"  CONTACT ROSTER — {today}")
    print(f"{'=' * 55}")
    print(f"  Total contacts: {total}")
    print()
    for status in ["active", "cooling", "retired", "blocked"]:
        count = status_counts.get(status, 0)
        pct = count / total * 100 if total else 0
        bar = "#" * int(pct / 2)
        print(f"  {status:12s}  {count:4d}  ({pct:4.1f}%)  {bar}")

    # Retired breakdown
    retired_reasons = defaultdict(int)
    for p in profiles:
        if p["status"] == "retired" and p.get("retired_reason"):
            retired_reasons[p["retired_reason"]] += 1

    if retired_reasons:
        print(f"\n  Retired breakdown:")
        for reason, count in sorted(retired_reasons.items(), key=lambda x: -x[1]):
            print(f"    {count:3d}  {reason}")

    # Company saturation
    company_stats = defaultdict(lambda: {"active": 0, "retired": 0, "total": 0})
    for p in profiles:
        co = p["company_name"]
        company_stats[co]["total"] += 1
        if p["status"] == "active":
            company_stats[co]["active"] += 1
        elif p["status"] == "retired":
            company_stats[co]["retired"] += 1

    saturated = [(co, s) for co, s in company_stats.items() if s["total"] >= 5]
    if saturated:
        saturated.sort(key=lambda x: -x[1]["total"])
        print(f"\n  Most-worked companies (5+ contacts):")
        print(f"  {'Company':35s}  Active  Retired  Total")
        for co, s in saturated[:15]:
            flag = " <- saturated" if s["active"] == 0 else ""
            print(f"  {co:35s}  {s['active']:5d}  {s['retired']:6d}  {s['total']:5d}{flag}")


# ── Output ───────────────────────────────────────────────────────────

def print_call_sheet(call_sheet: list[dict]):
    """Print call sheet summary to terminal."""
    today = date.today()

    print(f"\n{'=' * 80}")
    print(f"  DAILY CALL SHEET — {today.strftime('%A %b %d, %Y')}")
    print(f"  {len(call_sheet)} contacts (target: {DAILY_TARGET})")
    print(f"{'=' * 80}")

    if not call_sheet:
        print("\n  No contacts available. Add new prospects to Supabase.")
        return

    # Priority breakdown
    by_priority = defaultdict(int)
    for c in call_sheet:
        by_priority[c["priority"]] += 1

    print(f"\n  Priority: HIGH={by_priority.get('HIGH', 0)}  "
          f"MEDIUM={by_priority.get('MEDIUM', 0)}  "
          f"LOW={by_priority.get('LOW', 0)}")

    # Group by type
    warm = [c for c in call_sheet if c["priority"] == "HIGH"]
    retry = [c for c in call_sheet if c["priority"] == "MEDIUM"]
    fresh = [c for c in call_sheet if c["priority"] == "LOW"]

    if warm:
        print(f"\n  WARM LEADS — prior positive signal ({len(warm)})")
        print(f"  {'#':>3s}  {'Contact':30s}  {'Company':30s}  {'Att':>3s}  Prior Best")
        print(f"  {'─' * 3}  {'─' * 30}  {'─' * 30}  {'─' * 3}  {'─' * 15}")
        for i, c in enumerate(warm, 1):
            print(f"  {i:3d}  {c['name']:30s}  {c['company']:30s}  {c['attempt']:3d}  {c['prior_best']}")

    if retry:
        n = len(warm) + 1
        print(f"\n  RETRIES — follow-up calls ({len(retry)})")
        print(f"  {'#':>3s}  {'Contact':30s}  {'Company':30s}  {'Att':>3s}  Last Called")
        print(f"  {'─' * 3}  {'─' * 30}  {'─' * 30}  {'─' * 3}  {'─' * 12}")
        for i, c in enumerate(retry, n):
            print(f"  {i:3d}  {c['name']:30s}  {c['company']:30s}  {c['attempt']:3d}  {c['last_called']}")

    if fresh:
        n = len(warm) + len(retry) + 1
        print(f"\n  FRESH CONTACTS — first call ({len(fresh)})")
        print(f"  {'#':>3s}  {'Contact':30s}  {'Company':30s}")
        print(f"  {'─' * 3}  {'─' * 30}  {'─' * 30}")
        for i, c in enumerate(fresh, n):
            print(f"  {i:3d}  {c['name']:30s}  {c['company']:30s}")

    # Company distribution
    cos = defaultdict(int)
    for c in call_sheet:
        cos[c["company"]] += 1
    print(f"\n  Across {len(cos)} companies", end="")
    multi = {k: v for k, v in cos.items() if v > 1}
    if multi:
        print(f" ({len(multi)} with 2+ contacts):")
        for co, cnt in sorted(multi.items(), key=lambda x: -x[1])[:10]:
            print(f"    {co}: {cnt}")
    else:
        print()


# ── Main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Daily call sheet → HubSpot tasks")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print call sheet without creating HubSpot tasks")
    parser.add_argument("--stats", action="store_true",
                        help="Show roster stats only")
    args = parser.parse_args()

    # Fetch data from Supabase
    print("Fetching call data from Supabase...")
    sb = get_supabase()
    calls, companies_by_id = fetch_call_data(sb)
    print(f"  {len(calls)} calls, {len(companies_by_id)} companies")

    # Build contact profiles in memory
    profiles = build_contact_profiles(calls, companies_by_id)
    print(f"  {len(profiles)} unique contacts")

    if args.stats:
        show_stats(profiles)
        return

    # Generate call sheet
    call_sheet = select_callable_contacts(profiles)
    print_call_sheet(call_sheet)

    if not call_sheet:
        return

    # ── Validate before touching HubSpot ──
    from validate_call_sheet import validate

    result = validate(call_sheet, profiles)
    result.print_report()

    if not result.passed:
        print(f"  Aborting — fix {len(result.violations)} violation(s) before creating tasks.")
        sys.exit(1)

    if args.dry_run:
        print(f"\n  [dry-run] Would create {len(call_sheet)} HubSpot tasks for Adam")
        return

    # ── HubSpot task management ──
    token = os.environ.get("HUBSPOT_TOKEN")
    if not token:
        print("ERROR: HUBSPOT_TOKEN not set. Cannot create tasks.")
        sys.exit(1)

    from hubspot_tasks import (
        search_call_sheet_tasks,
        complete_tasks,
        create_call_tasks,
    )

    # Step 1: Find existing call sheet tasks (stale + today)
    print(f"\nChecking existing call sheet tasks...")
    existing = search_call_sheet_tasks(token)

    # Guard: don't create duplicates if today's tasks already exist
    if existing["today"]:
        print(f"  Found {len(existing['today'])} tasks already created for today.")
        print(f"  Aborting — run once per day. To recreate, complete today's tasks first.")
        return

    # Step 2: Complete stale tasks from previous days
    if existing["stale"]:
        stale_ids = [t["id"] for t in existing["stale"]]
        completed = complete_tasks(token, stale_ids)
        print(f"  Completed {completed} stale tasks from previous days")
    else:
        print(f"  No stale tasks found")

    # Step 3: Create today's tasks
    print(f"\nCreating {len(call_sheet)} HubSpot tasks for Adam...")
    created = create_call_tasks(token, call_sheet)

    # Priority breakdown
    by_priority = defaultdict(int)
    for c in call_sheet:
        by_priority[c["priority"]] += 1

    print(f"\n{'=' * 50}")
    print(f"  Created {created} tasks")
    print(f"  HIGH={by_priority.get('HIGH', 0)}  "
          f"MEDIUM={by_priority.get('MEDIUM', 0)}  "
          f"LOW={by_priority.get('LOW', 0)}")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
