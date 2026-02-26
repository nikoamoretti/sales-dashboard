#!/usr/bin/env python3
"""
sync_deals.py — Sync HubSpot deals into Supabase.

Fetches all deals owned by Nico (owner_id=83627643), maps stages to labels,
resolves company associations, and upserts into the `deals` table.

Usage:
    python3 sync_deals.py              # sync all Nico's deals
    python3 sync_deals.py --dry-run    # show what would sync
    python3 sync_deals.py --create-table  # create the deals table first
"""

import argparse
import os
import sys
from datetime import datetime, timezone
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

HUBSPOT_API_BASE = "https://api.hubapi.com"
NICO_OWNER_ID = "83627643"

# Stage ID -> human label
STAGE_MAP = {
    "appointmentscheduled": "Introductory Call",
    "decisionmakerboughtin": "Demo",
    "contractsent": "Pilot",
    "30701462": "Nurture",
    "32931384": "Backlog",
    "32383652": "Qualified",
    "167386809": "Proposal",
    "26949515": "Closed Won",
    "closedlost": "Blocked / Stale",
}

# Display order (lower = earlier in pipeline)
STAGE_ORDER = [
    "Demo", "Introductory Call", "Qualified", "Pilot",
    "Proposal", "Nurture", "Backlog", "Closed Won", "Blocked / Stale",
]


# ---------------------------------------------------------------------------
# Supabase helpers
# ---------------------------------------------------------------------------

def get_supabase():
    from supabase import create_client
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])


def create_deals_table():
    """Create the deals table via Supabase SQL (psycopg2)."""
    import psycopg2

    conn_str = (
        "host=db.giptkpwwhwhtrrrmdfqt.supabase.co "
        "port=5432 "
        "user=postgres "
        "password=NINTOEMF2w2Uwxbn "
        "dbname=postgres "
        "sslmode=require"
    )
    conn = psycopg2.connect(conn_str)
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS deals (
            id SERIAL PRIMARY KEY,
            hubspot_deal_id BIGINT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            amount NUMERIC,
            stage TEXT,
            stage_label TEXT,
            close_date DATE,
            company_id INTEGER REFERENCES companies(id),
            company_name TEXT,
            source TEXT DEFAULT 'hubspot',
            owner_id BIGINT,
            pipeline TEXT,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        );
    """)

    # Index for common queries
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_deals_stage ON deals(stage);
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_deals_owner ON deals(owner_id);
    """)

    print("deals table created (or already exists).")
    cur.close()
    conn.close()


# ---------------------------------------------------------------------------
# HubSpot API
# ---------------------------------------------------------------------------

def fetch_deals(token: str, owner_id: str) -> list[dict]:
    """Fetch all deals for an owner from HubSpot CRM."""
    url = f"{HUBSPOT_API_BASE}/crm/v3/objects/deals/search"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    all_deals = []
    after = None

    while True:
        body = {
            "filterGroups": [{
                "filters": [{
                    "propertyName": "hubspot_owner_id",
                    "operator": "EQ",
                    "value": owner_id,
                }]
            }],
            "properties": [
                "dealname", "amount", "dealstage", "closedate",
                "pipeline", "hubspot_owner_id", "createdate",
                "hs_lastmodifieddate",
            ],
            "limit": 100,
        }
        if after:
            body["after"] = after

        resp = requests.post(url, headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()

        results = data.get("results", [])
        all_deals.extend(results)

        paging = data.get("paging", {})
        next_page = paging.get("next", {})
        after = next_page.get("after")
        if not after:
            break

    return all_deals


def fetch_deal_company_associations(token: str, deal_ids: list[str]) -> dict[str, str]:
    """Batch fetch company associations for deals. Returns deal_id -> company_id."""
    if not deal_ids:
        return {}

    url = f"{HUBSPOT_API_BASE}/crm/v4/associations/deals/companies/batch/read"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    deal_to_company: dict[str, str] = {}

    # Batch in chunks of 100
    for i in range(0, len(deal_ids), 100):
        chunk = deal_ids[i:i + 100]
        body = {"inputs": [{"id": did} for did in chunk]}

        resp = requests.post(url, headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()

        for result in data.get("results", []):
            from_id = str(result.get("from", {}).get("id", ""))
            to_list = result.get("to", [])
            if to_list:
                deal_to_company[from_id] = str(to_list[0].get("toObjectId", ""))

    return deal_to_company


def fetch_company_names(token: str, company_ids: list[str]) -> dict[str, str]:
    """Fetch company names by HubSpot company ID (individual GET calls).

    Uses HUBSPOT_API_KEY if available (has company read scope), falls back to token.
    """
    if not company_ids:
        return {}

    # HUBSPOT_API_KEY has broader scopes (company read)
    api_key = os.environ.get("HUBSPOT_API_KEY") or token
    headers = {"Authorization": f"Bearer {api_key}"}
    id_to_name: dict[str, str] = {}

    for cid in company_ids:
        try:
            resp = requests.get(
                f"{HUBSPOT_API_BASE}/crm/v3/objects/companies/{cid}",
                headers=headers,
                params={"properties": "name"},
                timeout=15,
            )
            resp.raise_for_status()
            name = resp.json().get("properties", {}).get("name", "")
            if name:
                id_to_name[cid] = name
        except requests.RequestException as e:
            print(f"  Warning: could not fetch company {cid}: {e}")
            continue

    return id_to_name


# ---------------------------------------------------------------------------
# Sync logic
# ---------------------------------------------------------------------------

def sync_deals(dry_run: bool = False) -> None:
    token = os.environ.get("HUBSPOT_TOKEN")
    if not token:
        print("ERROR: HUBSPOT_TOKEN not set.")
        sys.exit(1)

    print(f"\n{'=' * 60}")
    print("HubSpot Deals -> Supabase Sync")
    print(f"{'=' * 60}")
    if dry_run:
        print("Mode: DRY RUN\n")

    # 1. Fetch deals
    print("Step 1: Fetching deals from HubSpot...")
    deals = fetch_deals(token, NICO_OWNER_ID)
    print(f"  {len(deals)} deals fetched")

    if not deals:
        print("No deals found.")
        return

    # 2. Fetch company associations
    print("\nStep 2: Resolving company associations...")
    deal_ids = [str(d["id"]) for d in deals]
    deal_to_company = fetch_deal_company_associations(token, deal_ids)
    print(f"  {len(deal_to_company)} deals have company associations")

    # 3. Fetch company names
    unique_company_ids = list(set(deal_to_company.values()))
    company_names = fetch_company_names(token, unique_company_ids)
    print(f"  {len(company_names)} company names resolved")

    # 4. Resolve Supabase company IDs (match by hubspot_id or name)
    sb = get_supabase()
    sb_companies = sb.table("companies").select("id, name, hubspot_id").execute()
    sb_by_hubspot_id: dict[str, int] = {}
    sb_by_name: dict[str, int] = {}
    for row in sb_companies.data:
        if row.get("hubspot_id"):
            sb_by_hubspot_id[row["hubspot_id"]] = row["id"]
        sb_by_name[row["name"].lower()] = row["id"]

    # 5. Build records
    print("\nStep 3: Building deal records...")
    records = []
    stage_counts = {}

    for deal in deals:
        props = deal.get("properties", {})
        deal_id = str(deal["id"])
        name = props.get("dealname", "Untitled")
        amount_raw = props.get("amount")
        stage = props.get("dealstage", "")
        stage_label = STAGE_MAP.get(stage, stage)
        close_date = props.get("closedate")
        pipeline = props.get("pipeline", "")
        owner = props.get("hubspot_owner_id", "")

        # Parse amount
        amount = None
        if amount_raw:
            try:
                amount = float(amount_raw)
            except (ValueError, TypeError):
                pass

        # Parse close date
        close_dt = None
        if close_date:
            try:
                close_dt = close_date[:10]  # YYYY-MM-DD
            except (TypeError, IndexError):
                pass

        # Resolve company
        hs_company_id = deal_to_company.get(deal_id, "")
        company_name = company_names.get(hs_company_id, "")
        sb_company_id = None
        if hs_company_id:
            sb_company_id = sb_by_hubspot_id.get(hs_company_id)
        if not sb_company_id and company_name:
            sb_company_id = sb_by_name.get(company_name.lower())

        # Track stage counts
        stage_counts[stage_label] = stage_counts.get(stage_label, 0) + 1

        records.append({
            "hubspot_deal_id": int(deal_id),
            "name": name,
            "amount": amount,
            "stage": stage,
            "stage_label": stage_label,
            "close_date": close_dt,
            "company_id": sb_company_id,
            "company_name": company_name or name,
            "source": "hubspot",
            "owner_id": int(owner) if owner else None,
            "pipeline": pipeline,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })

    # Summary
    print(f"\n  Stage breakdown:")
    for stage_label in STAGE_ORDER:
        count = stage_counts.get(stage_label, 0)
        if count:
            total_amount = sum(
                r["amount"] or 0 for r in records if r["stage_label"] == stage_label
            )
            print(f"    {stage_label:<20s} {count:>3d} deals  ${total_amount:>12,.0f}")

    total_value = sum(r["amount"] or 0 for r in records)
    print(f"\n  Total pipeline: {len(records)} deals, ${total_value:,.0f}")

    if dry_run:
        print("\n  [dry-run] Would upsert all records. Exiting.")
        return

    # 6. Upsert to Supabase
    print("\nStep 4: Upserting to Supabase...")
    resp = sb.table("deals").upsert(records, on_conflict="hubspot_deal_id").execute()
    print(f"  Upserted {len(resp.data)} deal records")

    print(f"\n{'=' * 60}")
    print("Done.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Sync HubSpot deals into Supabase")
    parser.add_argument("--dry-run", action="store_true", help="Show what would sync")
    parser.add_argument("--create-table", action="store_true", help="Create the deals table")
    args = parser.parse_args()

    if args.create_table:
        create_deals_table()
        if not args.dry_run:
            return 0

    sync_deals(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
