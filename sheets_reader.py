"""
sheets_reader.py — Read LinkedIn stats from the shared Google Sheet.

Reads from the same sheet that linkedin-tracker writes to:
- "Cumulative Sequences Performance" tab, cols G (requests sent) and H (connected)
- "Weekly Sequences Scorecard" tab, rows 6-7 (weekly LI requests/connected)
"""

import json
import os
from typing import Any, Dict, List, Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

# The sequence name that linkedin-tracker uses
LI_SEQUENCE_NAME = "Sequence Q126 - Energy, Chemicals & Mining - Chemicals - Mid-Management"


def _build_sheets_service(credentials_json: str):
    """Build authenticated Sheets API service from JSON credentials string."""
    creds_dict = json.loads(credentials_json)
    credentials = service_account.Credentials.from_service_account_info(
        creds_dict, scopes=SCOPES
    )
    return build("sheets", "v4", credentials=credentials)


def _safe_int(val) -> int:
    """Safely convert cell value to int."""
    try:
        return int(float(str(val).replace(",", ""))) if val else 0
    except (ValueError, TypeError):
        return 0


def fetch_linkedin_stats(sheet_id: str, credentials_json: str) -> Dict[str, Any]:
    """Read LinkedIn stats from the shared Google Sheet.

    Returns dict with requests_sent, connected, pending, accept_rate.
    """
    service = _build_sheets_service(credentials_json)
    sheets = service.spreadsheets().values()

    # Read cumulative data from "Cumulative Sequences Performance" tab
    # Find the row matching our sequence name, then read cols G and H
    cumulative_range = "'Cumulative Sequences Performance'!A:H"
    result = sheets.get(spreadsheetId=sheet_id, range=cumulative_range).execute()
    rows = result.get("values", [])

    requests_sent = 0
    connected = 0

    for row in rows:
        if len(row) >= 2 and LI_SEQUENCE_NAME in str(row[1] if len(row) > 1 else ""):
            # Col G = index 6, Col H = index 7
            requests_sent = _safe_int(row[6]) if len(row) > 6 else 0
            connected = _safe_int(row[7]) if len(row) > 7 else 0
            break

    # Also try weekly data from "Weekly Sequences Scorecard" rows 6-7
    weekly_range = "'Weekly Sequences Scorecard'!A6:L7"
    try:
        weekly_result = sheets.get(spreadsheetId=sheet_id, range=weekly_range).execute()
        weekly_rows = weekly_result.get("values", [])

        # Sum all weekly values for rows 6 and 7 (skipping col A label)
        if weekly_rows and len(weekly_rows) >= 1 and weekly_rows[0]:
            weekly_requests = sum(_safe_int(v) for v in weekly_rows[0][1:] if v)
            if requests_sent == 0:
                requests_sent = weekly_requests

        if weekly_rows and len(weekly_rows) >= 2 and weekly_rows[1]:
            weekly_connected = sum(_safe_int(v) for v in weekly_rows[1][1:] if v)
            if connected == 0:
                connected = weekly_connected
    except Exception:
        pass  # Weekly data is supplementary

    pending = max(0, requests_sent - connected)
    accept_rate = round(connected / requests_sent * 100, 1) if requests_sent > 0 else 0.0

    return {
        "requests_sent": requests_sent,
        "connected": connected,
        "pending": pending,
        "accept_rate": accept_rate,
    }
