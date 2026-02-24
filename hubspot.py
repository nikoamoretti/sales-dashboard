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
                "hs_call_body", "hs_body_preview",
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
