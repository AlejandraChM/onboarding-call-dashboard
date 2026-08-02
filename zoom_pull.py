#!/usr/bin/env python3
"""
Pulls onboarding-call attendance (participants, join/leave, duration) from the
Zoom Reports API and writes it to onboarding_data.json in the same format used
by the onboarding attendance dashboard.

Setup:
  pip install requests
  export ZOOM_ACCOUNT_ID=...
  export ZOOM_CLIENT_ID=...
  export ZOOM_CLIENT_SECRET=...

Usage:
  python3 zoom_pull.py --host-email events@op.workada.co --from 2026-07-01 --to 2026-07-31 --topic-filter "Onboarding"

Notes:
  - Requires the Server-to-Server OAuth app to have these scopes:
      report:read:list_meeting_participants:admin (or report:read:admin)
      report:read:user:admin (or report:read:admin) -- to list a user's past meetings
  - Zoom's report API returns participant duration in SECONDS; this script
    converts it to minutes to match the existing dashboard data.
  - This script needs normal internet access to zoom.us / api.zoom.us.
    It will NOT run inside the Cowork sandbox (network is allowlisted and
    blocks those domains) -- run it on your own machine, in a GitHub Action,
    or as a Vercel scheduled function.
"""

import argparse
import base64
import json
import os
import re
import sys
from datetime import datetime

import requests

TOKEN_URL = "https://zoom.us/oauth/token"
API_BASE = "https://api.zoom.us/v2"


def get_access_token(account_id, client_id, client_secret):
    resp = requests.post(
        TOKEN_URL,
        params={"grant_type": "account_credentials", "account_id": account_id},
        auth=(client_id, client_secret),
        timeout=30,
    )
    if not resp.ok:
        print(f"Zoom token request failed: {resp.status_code}")
        print(f"Response body: {resp.text}")
    resp.raise_for_status()
    return resp.json()["access_token"]


def list_past_meetings(token, host_email, date_from, date_to):
    """GET /report/users/{userId}/meetings -- past meetings for a host in a date range."""
    meetings = []
    next_page_token = ""
    while True:
        params = {
            "type": "past",
            "from": date_from,
            "to": date_to,
            "page_size": 300,
        }
        if next_page_token:
            params["next_page_token"] = next_page_token
        resp = requests.get(
            f"{API_BASE}/report/users/{host_email}/meetings",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        meetings.extend(data.get("meetings", []))
        next_page_token = data.get("next_page_token", "")
        if not next_page_token:
            break
    return meetings


def get_participants(token, meeting_uuid):
    """GET /report/meetings/{meetingId}/participants -- attendee list with join/leave/duration (seconds)."""
    # Zoom UUIDs that start with '/' or contain '//' must be double URL-encoded.
    encoded = requests.utils.quote(requests.utils.quote(meeting_uuid, safe="") if (meeting_uuid.startswith("/") or "//" in meeting_uuid) else meeting_uuid, safe="")
    participants = []
    next_page_token = ""
    while True:
        params = {"page_size": 300}
        if next_page_token:
            params["next_page_token"] = next_page_token
        resp = requests.get(
            f"{API_BASE}/report/meetings/{encoded}/participants",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        participants.extend(data.get("participants", []))
        next_page_token = data.get("next_page_token", "")
        if not next_page_token:
            break
    return participants


def build_meeting_record(meeting, raw_participants, host_email):
    by_name = {}
    for p in raw_participants:
        name = p.get("name") or p.get("user_email") or "Unknown"
        entry = by_name.setdefault(name, {
            "name": name,
            "email": p.get("user_email") or None,
            "totalSeconds": 0,
            "sessions": 0,
            "joins": [],
            "leaves": [],
        })
        entry["totalSeconds"] += p.get("duration", 0)
        entry["sessions"] += 1
        if p.get("join_time"):
            entry["joins"].append(p["join_time"])
        if p.get("leave_time"):
            entry["leaves"].append(p["leave_time"])

    participants = []
    for entry in by_name.values():
        first_join = min(entry["joins"]) if entry["joins"] else None
        last_leave = max(entry["leaves"]) if entry["leaves"] else None
        is_host = bool(entry["email"] and entry["email"].lower() == host_email.lower())
        participants.append({
            "name": entry["name"],
            "email": entry["email"],
            "totalMinutes": round(entry["totalSeconds"] / 60),
            "sessions": entry["sessions"],
            "firstJoin": first_join,
            "lastLeave": last_leave,
            "isHost": is_host,
            "guest": "No" if entry["email"] else "Yes",
        })
    participants.sort(key=lambda p: (-p["isHost"], -p["totalMinutes"]))

    meeting_id = str(meeting.get("id", ""))
    formatted_id = " ".join([meeting_id[0:3], meeting_id[3:7], meeting_id[7:11]]) if len(meeting_id) >= 10 else meeting_id

    return {
        "id": formatted_id or meeting_id,
        "idDigits": re.sub(r"\D", "", meeting_id),
        "uuid": meeting.get("uuid"),
        "topic": meeting.get("topic", ""),
        "host": meeting.get("host_id", ""),
        "hostEmail": host_email,
        "start": meeting.get("start_time"),
        "end": meeting.get("end_time"),
        "meetingDurationMin": meeting.get("duration"),
        "participantCount": len(participants),
        "participants": participants,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host-email", required=True, help="Zoom host email whose meetings to pull")
    ap.add_argument("--from", dest="date_from", required=True, help="YYYY-MM-DD")
    ap.add_argument("--to", dest="date_to", required=True, help="YYYY-MM-DD")
    ap.add_argument("--topic-filter", default="", help="Only keep meetings whose topic contains this text")
    ap.add_argument("--out", default="onboarding_data.json")
    args = ap.parse_args()

    account_id = os.environ.get("ZOOM_ACCOUNT_ID")
    client_id = os.environ.get("ZOOM_CLIENT_ID")
    client_secret = os.environ.get("ZOOM_CLIENT_SECRET")
    if not all([account_id, client_id, client_secret]):
        sys.exit("Missing ZOOM_ACCOUNT_ID / ZOOM_CLIENT_ID / ZOOM_CLIENT_SECRET environment variables.")

    token = get_access_token(account_id, client_id, client_secret)
    meetings = list_past_meetings(token, args.host_email, args.date_from, args.date_to)

    if args.topic_filter:
        meetings = [m for m in meetings if args.topic_filter.lower() in m.get("topic", "").lower()]

    print(f"Found {len(meetings)} meetings matching filter.")

    records = []
    for m in meetings:
        try:
            parts = get_participants(token, m["uuid"])
        except requests.HTTPError as e:
            print(f"  skip {m.get('topic')} ({m.get('uuid')}): {e} -- body: {e.response.text if e.response is not None else ''}")
            continue
        records.append(build_meeting_record(m, parts, args.host_email))
        print(f"  {m.get('topic')} -- {len(parts)} participant rows")

    # merge with existing file if present, de-duping by (id, start)
    existing = []
    if os.path.exists(args.out):
        with open(args.out) as f:
            existing = json.load(f)

    seen = {(r["id"], r["start"]) for r in existing}
    added = 0
    for r in records:
        key = (r["id"], r["start"])
        if key not in seen:
            existing.append(r)
            seen.add(key)
            added += 1

    def parse_dt(s):
        try:
            return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            return datetime.min

    existing.sort(key=lambda m: parse_dt(m["start"]) if "T" in str(m.get("start", "")) else datetime.min, reverse=True)

    with open(args.out, "w") as f:
        json.dump(existing, f, indent=2, default=str)

    print(f"Added {added} new meetings. Total meetings in {args.out}: {len(existing)}")


if __name__ == "__main__":
    main()
