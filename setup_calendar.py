#!/usr/bin/env python3
"""
Sets up recurring weekly work schedule on Google Calendar.
"""

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/calendar"]  # write access needed
BASE   = Path(__file__).parent

def get_service():
    creds = Credentials.from_authorized_user_file(BASE / "token.json", SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(BASE / "token.json", "w") as f:
            f.write(creds.to_json())
    return build("calendar", "v3", credentials=creds)


# Recurring Mon-Fri rule
WEEKDAYS = "RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"
TZ       = "America/Los_Angeles"

# Start from next Monday June 8, 2026
events = [
    {
        "summary": "☀️ Morning Routine",
        "description": "Wake up & freshen up",
        "start": {"dateTime": "2026-06-08T08:00:00", "timeZone": TZ},
        "end":   {"dateTime": "2026-06-08T08:30:00", "timeZone": TZ},
        "recurrence": [WEEKDAYS],
    },
    {
        "summary": "📋 Daily Standup",
        "description": "Team standup meeting",
        "start": {"dateTime": "2026-06-08T08:30:00", "timeZone": TZ},
        "end":   {"dateTime": "2026-06-08T09:00:00", "timeZone": TZ},
        "recurrence": [WEEKDAYS],
    },
    {
        "summary": "💻 Work — Irvine",
        "description": "Software development work",
        "location": "Irvine, CA",
        "start": {"dateTime": "2026-06-08T09:00:00", "timeZone": TZ},
        "end":   {"dateTime": "2026-06-08T12:00:00", "timeZone": TZ},
        "recurrence": [WEEKDAYS],
    },
    {
        "summary": "🥗 Lunch Break",
        "start": {"dateTime": "2026-06-08T12:00:00", "timeZone": TZ},
        "end":   {"dateTime": "2026-06-08T13:00:00", "timeZone": TZ},
        "recurrence": [WEEKDAYS],
    },
    {
        "summary": "💻 Work — Irvine",
        "description": "Software development work",
        "location": "Irvine, CA",
        "start": {"dateTime": "2026-06-08T13:00:00", "timeZone": TZ},
        "end":   {"dateTime": "2026-06-08T17:00:00", "timeZone": TZ},
        "recurrence": [WEEKDAYS],
    },
    {
        "summary": "🌙 Personal Time",
        "description": "Free time — available until 10pm or midnight",
        "start": {"dateTime": "2026-06-08T17:00:00", "timeZone": TZ},
        "end":   {"dateTime": "2026-06-08T22:00:00", "timeZone": TZ},
        "recurrence": [WEEKDAYS],
    },
]


def main():
    service = get_service()
    print("Creating recurring events...\n")
    for e in events:
        result = service.events().insert(calendarId="primary", body=e).execute()
        print(f"✅ Created: {e['summary']} — {result.get('htmlLink')}")
    print("\nAll done! Your weekly schedule is set.")


if __name__ == "__main__":
    main()
