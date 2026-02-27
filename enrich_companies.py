#!/usr/bin/env python3
"""
enrich_companies.py — Aggregate call_intel data up to company level.

Reads call_intel records from Supabase and populates CRM fields on
the companies table: current_provider, commodities, next_action,
contact_name, contact_role.

Usage:
    python3 enrich_companies.py
    python3 enrich_companies.py --dry-run
"""

import argparse
import os
import sys
from collections import Counter, defaultdict

from dotenv import load_dotenv

load_dotenv()


def _sb():
    from supabase import create_client
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_KEY"],
    )


def _check_columns(sb) -> bool:
    """Verify CRM columns exist on companies table."""
    try:
        sb.table("companies").select("current_provider").limit(0).execute()
        return True
    except Exception:
        return False


def enrich(dry_run: bool = False) -> int:
    sb = _sb()

    if not _check_columns(sb):
        print("ERROR: CRM columns not found on companies table.")
        print("Run the migration first:")
        print("  migrations/001_companies_crm.sql")
        print("  https://supabase.com/dashboard/project/giptkpwwhwhtrrrmdfqt/sql/new")
        return 1

    # Fetch all call_intel with company data
    print("Fetching call_intel records...")
    result = sb.table("call_intel").select(
        "company_id, competitor, commodities, next_action, objection, "
        "referral_name, referral_role, interest_level, qualified, "
        "extracted_at"
    ).not_.is_("company_id", "null").order("extracted_at").execute()

    intel_records = result.data or []
    print(f"  {len(intel_records)} call_intel records with company_id")

    if not intel_records:
        print("  Nothing to enrich.")
        return 0

    # Fetch existing companies
    companies_result = sb.table("companies").select("id, name, status, notes").execute()
    companies = {c["id"]: c for c in (companies_result.data or [])}

    # Aggregate intel by company
    by_company = defaultdict(list)
    for rec in intel_records:
        by_company[rec["company_id"]].append(rec)

    updates = []
    for company_id, records in by_company.items():
        if company_id not in companies:
            continue

        # Most recent record takes priority for single-value fields
        latest = records[-1]

        # Competitor: most frequently mentioned → current_provider
        competitors = [r["competitor"] for r in records if r.get("competitor")]
        current_provider = None
        if competitors:
            current_provider = Counter(competitors).most_common(1)[0][0]

        # Commodities: union of all mentioned
        all_commodities = set()
        for r in records:
            if r.get("commodities"):
                # Split on commas if it's a comma-separated string
                for c in r["commodities"].split(","):
                    c = c.strip()
                    if c:
                        all_commodities.add(c)
        commodities = ", ".join(sorted(all_commodities)) if all_commodities else None

        # Next action: from most recent intel
        next_action = latest.get("next_action")

        # Contact: from most recent referral info
        contact_name = None
        contact_role = None
        for r in reversed(records):
            if r.get("referral_name"):
                contact_name = r["referral_name"]
                contact_role = r.get("referral_role")
                break

        # Objection: extract normalized category from "category: detail" format
        objection_category = None
        for r in reversed(records):
            obj = r.get("objection")
            if obj and ":" in obj:
                objection_category = obj.split(":")[0].strip()
                break
            elif obj:
                objection_category = obj  # legacy free-text fallback
                break

        # Status upgrade based on interest
        current_status = companies[company_id].get("status", "prospect")
        new_status = current_status
        interest_levels = [r["interest_level"] for r in records if r.get("interest_level")]
        has_qualified = any(r.get("qualified") for r in records)
        if interest_levels:
            best = interest_levels[-1]  # most recent
            if best == "high" and current_status in ("prospect", "contacted"):
                new_status = "interested"
            elif best in ("medium", "low") and current_status == "prospect":
                new_status = "contacted"

        update = {"id": company_id}
        changed = False

        if current_provider:
            update["current_provider"] = current_provider
            changed = True
        if commodities:
            update["commodities"] = commodities
            changed = True
        if next_action:
            update["next_action"] = next_action
            changed = True
        if contact_name:
            update["contact_name"] = contact_name
            changed = True
        if contact_role:
            update["contact_role"] = contact_role
            changed = True
        if new_status != current_status:
            update["status"] = new_status
            changed = True
        if objection_category:
            existing_notes = companies[company_id].get("notes") or ""
            # Only set if no manual notes (preserve user-entered notes)
            if not existing_notes or existing_notes.startswith("objection:"):
                update["notes"] = f"objection: {objection_category}"
                changed = True

        if changed:
            updates.append(update)

    if dry_run:
        print(f"\n  [dry-run] Would update {len(updates)} companies:")
        for u in updates[:20]:
            name = companies.get(u["id"], {}).get("name", "?")
            fields = [f"{k}={v}" for k, v in u.items() if k != "id"]
            print(f"    {name}: {', '.join(fields)}")
        if len(updates) > 20:
            print(f"    ... and {len(updates) - 20} more")
        return 0

    # Apply updates
    print(f"  Updating {len(updates)} companies...")
    for update in updates:
        company_id = update.pop("id")
        sb.table("companies").update(update).eq("id", company_id).execute()

    print(f"  Enriched {len(updates)} companies from call_intel data")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Enrich companies from call_intel")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    required = ["SUPABASE_URL", "SUPABASE_SERVICE_KEY"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"ERROR: Missing: {', '.join(missing)}", file=sys.stderr)
        return 1

    return enrich(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
