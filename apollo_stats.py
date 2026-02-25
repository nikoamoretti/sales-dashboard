"""
apollo_stats.py — Lightweight Apollo API client for campaign-level email stats.

Uses campaign-level stats only (1 call per sequence) instead of message-level
pagination. Adapted from sales-automator/src/apollo/api_client.py.
"""

import time
from typing import Any, Dict, List, Optional

import requests

APOLLO_BASE_URL = "https://api.apollo.io/api/v1"


def safe_int(val) -> int:
    """Safely convert to int — Apollo sometimes returns 'loading' strings."""
    try:
        return int(val) if val is not None else 0
    except (ValueError, TypeError):
        return 0


def _calc_rate(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round((numerator / denominator) * 100, 1)


def fetch_apollo_stats(api_key: str) -> Dict[str, Any]:
    """Fetch all sequence stats from Apollo using campaign-level endpoints only.

    Returns dict with 'totals' and 'sequences' keys.
    ~5 API calls total (1 per sequence page + 1 per sequence detail).
    """
    session = requests.Session()
    session.headers.update({
        "X-Api-Key": api_key,
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
    })

    sequences: List[Dict] = []
    page = 1

    while True:
        time.sleep(1.2)  # Rate limit: ~50 req/min
        resp = session.post(
            f"{APOLLO_BASE_URL}/emailer_campaigns/search",
            json={"page": page, "per_page": 100},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        campaigns = data.get("emailer_campaigns", [])

        if not campaigns:
            break

        for c in campaigns:
            delivered = safe_int(c.get("unique_delivered", 0))
            bounced = safe_int(c.get("unique_bounced", 0))
            opened = safe_int(c.get("unique_opened_unfiltered", 0))
            replied = safe_int(c.get("unique_replied", 0))
            sent = delivered + bounced

            sequences.append({
                "name": c.get("name", "Unknown"),
                "active": c.get("active", False),
                "emails_sent": sent,
                "delivered": delivered,
                "bounced": bounced,
                "opened": opened,
                "open_rate": _calc_rate(opened, delivered),
                "replied": replied,
                "reply_rate": _calc_rate(replied, delivered),
            })

        pagination = data.get("pagination", {})
        if page >= pagination.get("total_pages", 1):
            break
        page += 1

    # Aggregate totals
    total_sent = sum(s["emails_sent"] for s in sequences)
    total_delivered = sum(s["delivered"] for s in sequences)
    total_opened = sum(s["opened"] for s in sequences)
    total_replied = sum(s["replied"] for s in sequences)

    return {
        "totals": {
            "emails_sent": total_sent,
            "delivered": total_delivered,
            "opened": total_opened,
            "open_rate": _calc_rate(total_opened, total_delivered),
            "replied": total_replied,
            "reply_rate": _calc_rate(total_replied, total_delivered),
        },
        "sequences": sequences,
    }
