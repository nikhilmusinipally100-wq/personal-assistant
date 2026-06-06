#!/usr/bin/env python3
"""
Google Calendar fetcher — gets today's and upcoming events.
"""

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from datetime import datetime, timezone, timedelta
from pathlib import Path

SCOPES  = ["https://www.googleapis.com/auth/calendar"]
BASE    = Path(__file__).parent
TOKEN   = BASE / "token.json"
CREDS_F = BASE / "credentials.json"


def get_calendar_service():
    creds = Credentials.from_authorized_user_file(TOKEN, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN, "w") as f:
            f.write(creds.to_json())
    return build("calendar", "v3", credentials=creds)


def fetch_todays_events():
    service = get_calendar_service()

    now = datetime.now(timezone.utc)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day   = now.replace(hour=23, minute=59, second=59, microsecond=0)

    events_result = service.events().list(
        calendarId="primary",
        timeMin=start_of_day.isoformat(),
        timeMax=end_of_day.isoformat(),
        singleEvents=True,
        orderBy="startTime"
    ).execute()

    return events_result.get("items", [])


def fetch_upcoming_events(days=3):
    service = get_calendar_service()

    now = datetime.now(timezone.utc)
    until = now + timedelta(days=days)

    events_result = service.events().list(
        calendarId="primary",
        timeMin=now.isoformat(),
        timeMax=until.isoformat(),
        singleEvents=True,
        orderBy="startTime"
    ).execute()

    return events_result.get("items", [])


def format_event(event):
    summary = event.get("summary", "No title")
    start   = event["start"].get("dateTime", event["start"].get("date", ""))
    location = event.get("location", "")

    try:
        dt = datetime.fromisoformat(start)
        time_str = dt.strftime("%I:%M %p")
        date_str = dt.strftime("%b %d")
    except Exception:
        time_str = start
        date_str = ""

    loc = f" @ {location}" if location else ""
    return f"• {date_str} {time_str} — {summary}{loc}"


def get_calendar_summary():
    today_events    = fetch_todays_events()
    upcoming_events = fetch_upcoming_events(days=3)

    today = datetime.now().strftime("%A, %b %d")
    lines = [f"📅 *Calendar — {today}*\n"]

    if today_events:
        lines.append("*Today:*")
        for e in today_events:
            lines.append(format_event(e))
    else:
        lines.append("*Today:* No events scheduled")

    # Upcoming (exclude today's events)
    today_ids = {e["id"] for e in today_events}
    upcoming  = [e for e in upcoming_events if e["id"] not in today_ids]

    if upcoming:
        lines.append("\n*Coming up:*")
        for e in upcoming:
            lines.append(format_event(e))

    return "\n".join(lines)


if __name__ == "__main__":
    print(get_calendar_summary())
