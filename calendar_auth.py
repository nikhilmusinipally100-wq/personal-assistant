#!/usr/bin/env python3
"""
One-time Google Calendar OAuth authentication.
Run this once to generate token.json, then the bot uses it automatically.
"""

from google_auth_oauthlib.flow import InstalledAppFlow
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/calendar"]
BASE   = Path(__file__).parent

flow = InstalledAppFlow.from_client_secrets_file(BASE / "credentials.json", SCOPES)
creds = flow.run_local_server(port=0)

with open(BASE / "token.json", "w") as f:
    f.write(creds.to_json())

print("✅ Authentication successful! token.json saved.")
