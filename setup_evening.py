#!/usr/bin/env python3
"""
Sets up recurring evening routine on Google Calendar (Mon-Fri).
"""

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/calendar"]
BASE   = Path(__file__).parent

def get_service():
    creds = Credentials.from_authorized_user_file(BASE / "token.json", SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(BASE / "token.json", "w") as f:
            f.write(creds.to_json())
    return build("calendar", "v3", credentials=creds)


WEEKDAYS = "RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"
TZ       = "America/Los_Angeles"

events = [
    {
        "summary": "🚗 Commute Home",
        "start": {"dateTime": "2026-06-08T17:00:00", "timeZone": TZ},
        "end":   {"dateTime": "2026-06-08T17:30:00", "timeZone": TZ},
        "recurrence": [WEEKDAYS],
    },
    {
        "summary": "🏋️ Gym / Workout",
        "start": {"dateTime": "2026-06-08T17:30:00", "timeZone": TZ},
        "end":   {"dateTime": "2026-06-08T19:00:00", "timeZone": TZ},
        "recurrence": [WEEKDAYS],
    },
    {
        "summary": "🚿 Shower & Freshen Up",
        "start": {"dateTime": "2026-06-08T19:00:00", "timeZone": TZ},
        "end":   {"dateTime": "2026-06-08T19:30:00", "timeZone": TZ},
        "recurrence": [WEEKDAYS],
    },
    {
        "summary": "📖 Learn / Side Project / Relax",
        "description": "Personal development, side projects, or just relax",
        "start": {"dateTime": "2026-06-08T19:30:00", "timeZone": TZ},
        "end":   {"dateTime": "2026-06-08T20:30:00", "timeZone": TZ},
        "recurrence": [WEEKDAYS],
    },
    {
        "summary": "🍽️ Dinner",
        "start": {"dateTime": "2026-06-08T20:30:00", "timeZone": TZ},
        "end":   {"dateTime": "2026-06-08T21:15:00", "timeZone": TZ},
        "recurrence": [WEEKDAYS],
    },
    {
        "summary": "🌙 Wind Down",
        "description": "Read, plan next day, prep for tomorrow",
        "start": {"dateTime": "2026-06-08T21:15:00", "timeZone": TZ},
        "end":   {"dateTime": "2026-06-08T22:00:00", "timeZone": TZ},
        "recurrence": [WEEKDAYS],
    },
]


def main():
    service = get_service()
    print("Adding evening routine...\n")
    for e in events:
        result = service.events().insert(calendarId="primary", body=e).execute()
        print(f"✅ {e['summary']}")
    print("\nEvening routine added to your calendar!")


if __name__ == "__main__":
    main()
