"""
hubspot.py — HubSpot call fetching + categorization logic.

Extracted from cold-calling-stats/main.py for standalone use.
"""

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

import requests

PACIFIC = ZoneInfo("America/Los_Angeles")
HUBSPOT_API_BASE = "https://api.hubapi.com"
ADAM_OWNER_ID = "87407439"

# HubSpot call disposition GUIDs
DISP_CONNECTED = "f240bbac-87c9-4f6e-bf70-924b57d47db7"
DISP_VOICEMAIL = "b2cf5968-551e-4856-9783-52b3da59a7d0"
DISP_LIVE_MSG = "a4c4c377-d246-4b32-a13b-75a56a4cd0ff"
DISP_NO_ANSWER = "73a0d17f-1163-4015-bdd5-ec830791da20"
DISP_BUSY = "9d9162e7-6cf3-4944-bf63-4dff82258764"
DISP_WRONG_NUM = "17b47fee-58de-441e-a44c-c6300d46f273"
DISP_MEETING_BOOKED = "be31a500-6cfd-4e74-8a31-c664d4615224"
DISP_INTERESTED = "63eb96bc-75b7-4676-a109-3e0336f95f60"
DISP_NOT_INTERESTED = "7bad71c2-dd4b-4627-a3f4-947806c71982"
DISP_NO_RAIL = "cc08f8e0-4c3b-4e42-97b3-54ff1fb7e7a1"
DISP_REFERRAL = "d358b45c-2cc2-4d80-84d8-8569829a1248"
DISP_WRONG_PERSON = "896c329d-ec2a-46ed-9c46-6770ed973d95"

MEETING_DISPOSITIONS = {DISP_MEETING_BOOKED}

CATEGORY_MAP = {
    DISP_MEETING_BOOKED: "Meeting Booked",
    DISP_INTERESTED:     "Interested",
    DISP_NOT_INTERESTED: "Not Interested",
    DISP_NO_RAIL:        "No Rail",
    DISP_REFERRAL:       "Referral Given",
    DISP_WRONG_PERSON:   "Wrong Person",
    DISP_WRONG_NUM:      "Wrong Number",
    DISP_VOICEMAIL:      "Left Voicemail",
    DISP_NO_ANSWER:      "No Answer",
    DISP_BUSY:           "No Answer",
    DISP_CONNECTED:      "Interested",
    DISP_LIVE_MSG:       "Left Voicemail",
}

CATEGORY_KEYWORDS = {
    "No Rail": [r"no rail", r"don'?t (ship|use) rail", r"rail in.{0,10}not out", r"no (railcar|carload|freight)"],
    "Wrong Person": [r"wrong person", r"doesn'?t handle", r"not the right", r"call corporate", r"transferred"],
    "Not Interested": [r"not interested", r"no need", r"don'?t need", r"all set", r"no thanks"],
    "Referral Given": [r"referr", r"talk to \w+", r"contact \w+", r"reach out to", r"speak with"],
    "Meeting Booked": [r"meeting", r"demo", r"scheduled", r"booked"],
    "Gatekeeper": [r"gatekeeper", r"receptionist", r"front desk", r"operator", r"not available"],
}

HUMAN_CONTACT_CATS = {
    "Interested", "Meeting Booked", "Referral Given",
    "Not Interested", "No Rail", "Wrong Person", "Gatekeeper",
}

PITCHED_CATS = {"Interested", "Meeting Booked", "Not Interested"}

ALL_CATEGORIES = [
    "Interested", "Meeting Booked", "Referral Given",
    "Not Interested", "No Rail", "Wrong Person", "Wrong Number", "Gatekeeper",
    "Left Voicemail", "No Answer",
]


def strip_html(text: str) -> str:
    """Strip HTML tags and decode entities to plain text."""
    if not text:
        return ""
    from html.parser import HTMLParser
    from io import StringIO

    class _Stripper(HTMLParser):
        def __init__(self):
            super().__init__()
            self._parts = []
        def handle_data(self, d):
            self._parts.append(d)
        def get_text(self):
            return "".join(self._parts).strip()

    s = _Stripper()
    s.feed(text)
    return s.get_text()


def safe_int(value, default=0) -> int:
    try:
        return int(float(value or default))
    except (ValueError, TypeError):
        return default


def parse_hs_timestamp(ts_str) -> Optional[datetime]:
    if not ts_str:
        return None
    return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))


def fetch_calls(token: str, start_ms: int, end_ms: int, owner_id: str = None) -> List[Dict]:
    url = f"{HUBSPOT_API_BASE}/crm/v3/objects/calls/search"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    filters = [
        {"propertyName": "hs_timestamp", "operator": "GTE", "value": str(start_ms)},
        {"propertyName": "hs_timestamp", "operator": "LT", "value": str(end_ms)},
    ]
    if owner_id:
        filters.append({"propertyName": "hubspot_owner_id", "operator": "EQ", "value": owner_id})

    all_calls = []
    after = None
    max_pages = 100

    while True:
        payload = {
            "filterGroups": [{"filters": filters}],
            "properties": [
                "hs_timestamp", "hs_call_duration", "hs_call_disposition",
                "hs_call_direction", "hubspot_owner_id", "hs_call_title",
                "hs_call_body", "hs_body_preview", "hs_call_has_transcript",
            ],
            "limit": 100
        }
        if after:
            payload["after"] = after

        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()

        data = response.json()
        results = data.get("results", [])
        all_calls.extend(results)
        print(f"  Fetched {len(results)} calls (total: {len(all_calls)})")

        paging = data.get("paging")
        if not paging or "next" not in paging:
            break

        after = paging["next"]["after"]
        max_pages -= 1
        if max_pages <= 0:
            print("  WARNING: Hit pagination limit")
            break

    return all_calls


def filter_calls_in_range(calls: List[Dict], start_ms: int, end_ms: int) -> List[Dict]:
    result = []
    for call in calls:
        dt = parse_hs_timestamp(call.get("properties", {}).get("hs_timestamp"))
        if not dt:
            continue
        ts_ms = int(dt.timestamp() * 1000)
        if start_ms <= ts_ms < end_ms:
            result.append(call)
    return result


def group_calls_by_week(calls: List[Dict]) -> List[tuple]:
    weeks = defaultdict(list)
    for call in calls:
        dt = parse_hs_timestamp(call.get("properties", {}).get("hs_timestamp"))
        if not dt:
            continue
        dt_utc = dt.astimezone(ZoneInfo("UTC"))
        monday = dt_utc.date() - timedelta(days=dt_utc.weekday())
        weeks[monday].append(call)
    return sorted(weeks.items())


def load_historical_categories() -> Dict[str, str]:
    path = Path(__file__).parent / "historical_categories.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def categorize_from_notes(notes: str) -> Optional[str]:
    if not notes:
        return None
    notes_lower = notes.lower()
    for category, patterns in CATEGORY_KEYWORDS.items():
        for pattern in patterns:
            if re.search(pattern, notes_lower):
                return category
    return None


def categorize_call(call: Dict, historical: Dict[str, str]) -> str:
    call_id = call.get("id", "")
    props = call.get("properties", {})
    disposition = (props.get("hs_call_disposition") or "").strip()
    duration_ms = safe_int(props.get("hs_call_duration"))
    duration_s = duration_ms // 1000
    notes = props.get("hs_call_body") or ""

    if call_id in historical:
        return historical[call_id]

    if disposition and disposition != DISP_CONNECTED:
        return CATEGORY_MAP.get(disposition, "No Answer")

    if disposition == DISP_CONNECTED:
        from_notes = categorize_from_notes(notes)
        if from_notes:
            return from_notes
        return "Interested"

    if duration_s > 120:
        return "Interested"
    return "No Answer"


def calculate_category_stats(calls: List[Dict], historical: Dict[str, str]) -> Dict:
    categories: Counter = Counter()
    for call in calls:
        cat = categorize_call(call, historical)
        categories[cat] += 1

    total = sum(categories.values())
    human_contact = sum(categories.get(c, 0) for c in HUMAN_CONTACT_CATS)
    pitched = sum(categories.get(c, 0) for c in PITCHED_CATS)

    return {
        "total_dials": total,
        "categories": dict(categories),
        "human_contact": human_contact,
        "human_contact_rate": round(human_contact / total * 100, 1) if total else 0,
        "pitch_rate": round(pitched / total * 100, 1) if total else 0,
        "meetings_booked": categories.get("Meeting Booked", 0),
    }


def fetch_meeting_details_for_categorized(token: str, calls: List[Dict], historical: Dict[str, str]) -> List[Dict]:
    """Fetch contact + company details for all calls categorized as Meeting Booked."""
    headers = {"Authorization": f"Bearer {token}"}
    meeting_calls = [c for c in calls if categorize_call(c, historical) == "Meeting Booked"]

    details = []
    for call in meeting_calls:
        ts = parse_hs_timestamp(call.get("properties", {}).get("hs_timestamp"))
        date_str = ts.astimezone(PACIFIC).strftime("%b %d") if ts else "Unknown"

        assoc = requests.get(
            f"{HUBSPOT_API_BASE}/crm/v3/objects/calls/{call['id']}/associations/contacts",
            headers=headers, timeout=15
        ).json().get("results", [])

        if not assoc:
            details.append({"date": date_str, "name": "Unknown", "company": "Unknown"})
            continue

        contact_id = assoc[0]["id"]
        contact = requests.get(
            f"{HUBSPOT_API_BASE}/crm/v3/objects/contacts/{contact_id}?properties=firstname,lastname,company",
            headers=headers, timeout=15
        ).json().get("properties", {})
        name = f"{contact.get('firstname', '')} {contact.get('lastname', '')}".strip() or "Unknown"

        comp_assoc = requests.get(
            f"{HUBSPOT_API_BASE}/crm/v3/objects/contacts/{contact_id}/associations/companies",
            headers=headers, timeout=15
        ).json().get("results", [])
        company = contact.get("company", "Unknown")
        if comp_assoc:
            comp = requests.get(
                f"{HUBSPOT_API_BASE}/crm/v3/objects/companies/{comp_assoc[0]['id']}?properties=name",
                headers=headers, timeout=15
            ).json().get("properties", {})
            company = comp.get("name", company)

        details.append({"date": date_str, "name": name, "company": company})

    return details


def batch_fetch_associations(token: str, from_type: str, to_type: str,
                             from_ids: List[str], batch_size: int = 100) -> Dict[str, List[str]]:
    """Batch fetch associations using HubSpot v4 API.

    Returns dict mapping from_id -> [to_id, ...].
    """
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    result: Dict[str, List[str]] = {}

    for i in range(0, len(from_ids), batch_size):
        batch = from_ids[i:i + batch_size]
        payload = {"inputs": [{"id": str(fid)} for fid in batch]}
        try:
            resp = requests.post(
                f"{HUBSPOT_API_BASE}/crm/v4/associations/{from_type}/{to_type}/batch/read",
                json=payload, headers=headers, timeout=30,
            )
            resp.raise_for_status()
            for item in resp.json().get("results", []):
                from_id = str(item["from"]["id"])
                to_ids = [str(t.get("toObjectId", t.get("id", "")))
                          for t in item.get("to", []) if t.get("toObjectId") or t.get("id")]
                result[from_id] = to_ids
        except requests.RequestException as e:
            print(f"  Warning: batch assoc {from_type}->{to_type} page {i//batch_size}: {e}")
            continue

    return result


def batch_fetch_objects(token: str, object_type: str, object_ids: List[str],
                        properties: List[str], batch_size: int = 100) -> Dict[str, Dict]:
    """Batch fetch CRM objects by ID. Returns dict mapping id -> properties."""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    result: Dict[str, Dict] = {}
    unique_ids = list({str(oid) for oid in object_ids if oid})

    for i in range(0, len(unique_ids), batch_size):
        batch = unique_ids[i:i + batch_size]
        payload = {"inputs": [{"id": oid} for oid in batch], "properties": properties}
        try:
            resp = requests.post(
                f"{HUBSPOT_API_BASE}/crm/v3/objects/{object_type}/batch/read",
                json=payload, headers=headers, timeout=30,
            )
            resp.raise_for_status()
            for item in resp.json().get("results", []):
                result[str(item["id"])] = item.get("properties", {})
        except requests.RequestException as e:
            print(f"  Warning: batch fetch {object_type} page {i//batch_size}: {e}")
            continue

    return result


def enrich_calls_with_associations(token: str, calls: List[Dict]) -> Dict[str, Dict]:
    """Resolve call->contact->company and call->note associations in bulk.

    Returns dict mapping call_id -> {contact_name, company_name, company_id, engagement_notes}.
    """
    call_ids = [str(c.get("id", "")) for c in calls if c.get("id")]
    if not call_ids:
        return {}

    print(f"  Enriching {len(call_ids)} calls with associations...")

    # Call -> Contact
    print("  Fetching call->contact associations...")
    call_contacts = batch_fetch_associations(token, "call", "contact", call_ids)

    # Call -> Note
    print("  Fetching call->note associations...")
    call_notes_map = batch_fetch_associations(token, "call", "note", call_ids)

    # Unique contact IDs
    all_contact_ids: set = set()
    for cids in call_contacts.values():
        all_contact_ids.update(cids)

    # Batch fetch contacts
    contacts: Dict[str, Dict] = {}
    if all_contact_ids:
        print(f"  Fetching {len(all_contact_ids)} contacts...")
        contacts = batch_fetch_objects(
            token, "contacts", list(all_contact_ids),
            ["firstname", "lastname", "company"],
        )

    # Contact -> Company
    contact_companies: Dict[str, List[str]] = {}
    if all_contact_ids:
        print("  Fetching contact->company associations...")
        contact_companies = batch_fetch_associations(
            token, "contact", "company", list(all_contact_ids),
        )

    # Unique company IDs
    all_company_ids: set = set()
    for cids in contact_companies.values():
        all_company_ids.update(cids)

    # Batch fetch companies
    companies: Dict[str, Dict] = {}
    if all_company_ids:
        print(f"  Fetching {len(all_company_ids)} companies...")
        companies = batch_fetch_objects(
            token, "companies", list(all_company_ids),
            ["name", "domain", "industry", "city", "state"],
        )

    # Unique note IDs
    all_note_ids: set = set()
    for nids in call_notes_map.values():
        all_note_ids.update(nids)

    # Batch fetch notes
    notes: Dict[str, Dict] = {}
    if all_note_ids:
        print(f"  Fetching {len(all_note_ids)} notes...")
        notes = batch_fetch_objects(
            token, "notes", list(all_note_ids),
            ["hs_note_body", "hs_timestamp"],
        )

    # Build enrichment map
    enrichment: Dict[str, Dict] = {}
    for call_id in call_ids:
        contact_name = ""
        company_name = ""
        company_id = ""

        cid_list = call_contacts.get(call_id, [])
        if cid_list:
            cid = cid_list[0]
            cp = contacts.get(cid, {})
            first = cp.get("firstname", "")
            last = cp.get("lastname", "")
            contact_name = f"{first} {last}".strip()
            company_name = cp.get("company", "")

            comp_ids = contact_companies.get(cid, [])
            if comp_ids:
                comp_p = companies.get(comp_ids[0], {})
                resolved = comp_p.get("name", "")
                if resolved:
                    company_name = resolved
                company_id = comp_ids[0]

        note_ids = call_notes_map.get(call_id, [])
        engagement_notes = []
        for nid in note_ids:
            np = notes.get(nid, {})
            body = np.get("hs_note_body", "")
            if body:
                engagement_notes.append(strip_html(body))

        enrichment[call_id] = {
            "contact_name": contact_name,
            "company_name": company_name,
            "company_id": company_id,
            "engagement_notes": engagement_notes,
        }

    with_co = sum(1 for e in enrichment.values() if e["company_name"])
    with_notes = sum(1 for e in enrichment.values() if e["engagement_notes"])
    print(f"  Enrichment done: {with_co} with company, {with_notes} with notes")

    return enrichment
