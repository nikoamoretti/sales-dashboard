"""
hubspot_tasks.py — Fetch Adam's open HubSpot tasks for the task queue monitor.

Uses POST /crm/v3/objects/tasks/search to find open tasks.
Alert thresholds: green (>50 remaining), yellow (20-50), red (<20).
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import requests

HUBSPOT_API_BASE = "https://api.hubapi.com"
ADAM_OWNER_ID = "87407439"


def fetch_open_tasks(token: str, owner_id: str = ADAM_OWNER_ID) -> Dict:
    """Fetch all open tasks assigned to owner_id and return summary stats."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # Only fetch tasks created since Monday of current week (UTC)
    now_utc = datetime.now(timezone.utc)
    monday = now_utc - timedelta(days=now_utc.weekday())
    week_start = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start_ms = str(int(week_start.timestamp() * 1000))

    all_tasks: List[Dict] = []
    after = None

    while True:
        payload = {
            "filterGroups": [{
                "filters": [
                    {"propertyName": "hubspot_owner_id", "operator": "EQ", "value": owner_id},
                    {"propertyName": "hs_task_status", "operator": "NEQ", "value": "COMPLETED"},
                    {"propertyName": "hs_createdate", "operator": "GTE", "value": week_start_ms},
                ]
            }],
            "properties": [
                "hs_task_subject", "hs_task_status", "hs_timestamp",
                "hs_task_priority", "hs_task_type",
            ],
            "limit": 100,
        }
        if after:
            payload["after"] = after

        resp = requests.post(
            f"{HUBSPOT_API_BASE}/crm/v3/objects/tasks/search",
            json=payload, headers=headers, timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        all_tasks.extend(results)

        paging = data.get("paging")
        if not paging or "next" not in paging:
            break
        after = paging["next"]["after"]

    return _summarize_tasks(all_tasks)


def _summarize_tasks(tasks: List[Dict]) -> Dict:
    """Build summary from raw task list, excluding auto-generated follow-ups."""
    # Filter out HubSpot auto-generated follow-up tasks
    tasks = [t for t in tasks
             if "follow up" not in (t.get("properties", {}).get("hs_task_subject") or "").lower()]

    by_priority = {"HIGH": 0, "MEDIUM": 0, "LOW": 0, "NONE": 0}
    oldest_ts: Optional[datetime] = None
    task_list = []

    for task in tasks:
        props = task.get("properties", {})
        priority = (props.get("hs_task_priority") or "NONE").upper()
        if priority not in by_priority:
            priority = "NONE"
        by_priority[priority] += 1

        # Track oldest task
        ts_str = props.get("hs_timestamp")
        if ts_str:
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if oldest_ts is None or ts < oldest_ts:
                    oldest_ts = ts
            except (ValueError, TypeError):
                pass

        task_list.append({
            "subject": props.get("hs_task_subject", "Untitled"),
            "priority": priority,
            "status": props.get("hs_task_status", ""),
        })

    total = len(tasks)
    oldest_days = 0
    if oldest_ts:
        oldest_days = (datetime.now(timezone.utc) - oldest_ts).days

    # Alert: green >50, yellow 20-50, red <20
    if total > 50:
        alert_level = "ok"
    elif total >= 20:
        alert_level = "warning"
    else:
        alert_level = "critical"

    display_priority = {k: v for k, v in by_priority.items() if v > 0}

    return {
        "total_open": total,
        "by_priority": display_priority,
        "alert_level": alert_level,
        "oldest_task_days": oldest_days,
        "tasks": sorted(task_list, key=lambda t: {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "NONE": 3}.get(t["priority"], 3)),
    }
