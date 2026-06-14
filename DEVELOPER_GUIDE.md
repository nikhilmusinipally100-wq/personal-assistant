# Developer Guide — Personal AI Assistant (Bunty)

A 24/7 personal Telegram bot powered by Claude AI. Handles Gmail, Google Calendar, LinkedIn Easy Apply, job tracking, stock alerts, and more.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Clone & Install](#2-clone--install)
3. [External Services Setup](#3-external-services-setup)
4. [Environment Variables](#4-environment-variables)
5. [Google Calendar OAuth](#5-google-calendar-oauth)
6. [LaunchAgent (Auto-start on macOS)](#6-launchagent-auto-start-on-macos)
7. [Cron Jobs](#7-cron-jobs)
8. [Running the Bot](#8-running-the-bot)
9. [Slash Commands](#9-slash-commands)
10. [Project Architecture](#10-project-architecture)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| macOS | 12+ | LaunchAgent and `caffeinate` are macOS-specific |
| Python | 3.11 | Install via [python.org](https://www.python.org/downloads/) |
| pip | bundled | Comes with Python 3.11 |
| cron | built-in | Available on macOS via `crontab` |

Verify your Python version:

```bash
python3 --version   # should print Python 3.11.x
```

---

## 2. Clone & Install

```bash
git clone https://github.com/AkshayMittapally/personal-assistant.git email_assistant
cd email_assistant

pip3 install -r requirements.txt

# Install Playwright browsers (needed for LinkedIn automation)
python3 -m playwright install chromium
```

---

## 3. External Services Setup

You need accounts and credentials from four services before the bot will run.

### 3.1 Anthropic (Claude AI)

1. Sign up at [console.anthropic.com](https://console.anthropic.com)
2. Create an API key
3. Save as `ANTHROPIC_API_KEY` in `~/.env`

### 3.2 Telegram Bot

1. Open Telegram and message **@BotFather**
2. Run `/newbot` → choose a name and username → copy the **bot token**
3. Save as `TELEGRAM_BOT_TOKEN` in `~/.env`

**Create a group with topic threads:**

1. Create a new Telegram group (e.g. "My Assistant")
2. Open group Settings → Enable **Topics**
3. Create 5 topics: `Chat`, `Emails`, `Jobs`, `Daily`, `Stocks`
4. Add your bot to the group
5. In BotFather, run `/setprivacy` → select your bot → **Disable** (bot must read all group messages)
6. Get the group ID by forwarding any group message to **@userinfobot** — it starts with `-100...`
7. Save as `TELEGRAM_GROUP_ID` in `~/.env`

**Get topic thread IDs:**

```bash
python3 get_topic_ids.py
```

This script prints all topic IDs. Save them as `TELEGRAM_TOPIC_CHAT`, `TELEGRAM_TOPIC_EMAILS`, etc. in `~/.env`.

**Get your personal chat ID:**

Message your bot directly, then run:

```bash
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates"
```

Look for `"id"` inside the `"chat"` object. Save as `TELEGRAM_CHAT_ID`.

### 3.3 Gmail (IMAP App Password)

1. Go to your Google Account → **Security**
2. Enable **2-Step Verification** if not already on
3. Go to **App Passwords** → create one for "Mail" / "Mac"
4. Save your Gmail address as `GMAIL_ADDRESS` and the 16-character app password as `GMAIL_APP_PASSWORD` in `~/.env`

### 3.4 Google Calendar (OAuth)

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a project → enable **Google Calendar API**
3. Go to **Credentials** → Create **OAuth 2.0 Client ID** → type: Desktop App
4. Download the JSON file and save it as `credentials.json` inside the `email_assistant/` directory
5. Run the one-time auth flow (see [Section 5](#5-google-calendar-oauth))

### 3.5 LinkedIn

No API key needed. The bot uses Playwright to automate the browser with your LinkedIn credentials.

1. Save as `LINKEDIN_EMAIL` and `LINKEDIN_PASSWORD` in `~/.env`

> **Note:** LinkedIn automation logs into your real account. Use with care and in accordance with LinkedIn's terms.

---

## 4. Environment Variables

Create `~/.env` (outside the repo, never commit this file):

```bash
touch ~/.env
chmod 600 ~/.env
```

Paste and fill in all values:

```ini
# Anthropic
ANTHROPIC_API_KEY=sk-ant-...

# Telegram
TELEGRAM_BOT_TOKEN=7xxxxxxxxx:AAF...
TELEGRAM_CHAT_ID=123456789          # your personal DM chat ID with the bot
TELEGRAM_GROUP_ID=-1003xxxxxxxxx    # the group ID (starts with -100)

# Telegram topic thread IDs (from get_topic_ids.py)
TELEGRAM_TOPIC_CHAT=11
TELEGRAM_TOPIC_EMAILS=12
TELEGRAM_TOPIC_JOBS=13
TELEGRAM_TOPIC_DAILY=14
TELEGRAM_TOPIC_STOCKS=15

# Gmail
GMAIL_ADDRESS=you@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx

# LinkedIn
LINKEDIN_EMAIL=you@example.com
LINKEDIN_PASSWORD=yourpassword
```

All scripts load credentials with `dotenv_values(Path.home() / ".env")` — the file must live at `~/.env`.

---

## 5. Google Calendar OAuth

This is a one-time step that generates `token.json`. After that, the bot refreshes the token automatically.

Make sure `credentials.json` is in the project directory, then run:

```bash
cd email_assistant
python3 calendar_auth.py
```

A browser window will open. Log in with your Google account, grant Calendar access, and close the tab. `token.json` will be saved next to `credentials.json`.

> `credentials.json` and `token.json` are gitignored — never commit them.

---

## 6. LaunchAgent (Auto-start on macOS)

The LaunchAgent keeps the bot alive across reboots and screen locks using `caffeinate -i`.

**Step 1 — Create the plist file:**

```bash
cp ~/email_assistant/com.akshay.assistant.plist.example \
   ~/Library/LaunchAgents/com.akshay.assistant.plist
```

**Step 2 — Edit the plist and replace `YOUR_USERNAME` with your macOS username:**

```bash
# Find your username
whoami

# Find your Python path
which python3
```

Open `~/Library/LaunchAgents/com.akshay.assistant.plist` and update:
- `/Users/YOUR_USERNAME/` → your actual home directory path
- Python path → output of `which python3`

**Step 3 — Load the agent:**

```bash
launchctl load ~/Library/LaunchAgents/com.akshay.assistant.plist
```

**Step 4 — Verify it started:**

```bash
ps aux | grep bot_server | grep -v grep
tail -f ~/email_assistant/assistant.log
```

To stop/restart:

```bash
launchctl unload ~/Library/LaunchAgents/com.akshay.assistant.plist
launchctl load   ~/Library/LaunchAgents/com.akshay.assistant.plist
```

---

## 7. Cron Jobs

These run scheduled tasks independently of the bot server. Open the crontab editor:

```bash
crontab -e
```

Add the following (replace `/YOUR_USERNAME/` with your path and update the Python path if needed):

```cron
# Morning briefing — daily 8am
0 8 * * * /path/to/python3 ~/email_assistant/morning_briefing.py >> ~/email_assistant/bot.log 2>&1

# Priority email watcher — every 15 min
*/15 * * * * /path/to/python3 ~/email_assistant/smart_email_alert.py >> ~/email_assistant/bot.log 2>&1

# Full email summary — every 2 hours
0 */2 * * * /path/to/python3 ~/email_assistant/email_bot.py >> ~/email_assistant/bot.log 2>&1

# LinkedIn job alerts — Mon-Fri 9am
0 9 * * 1-5 /path/to/python3 ~/email_assistant/linkedin_jobs.py >> ~/email_assistant/bot.log 2>&1

# LinkedIn auto-apply — Mon-Fri every 2 hours
0 */2 * * 1-5 /path/to/python3 ~/email_assistant/linkedin_apply.py autoapply >> ~/email_assistant/bot.log 2>&1

# Job tracker daily summary — Mon-Fri 6pm
0 18 * * 1-5 /path/to/python3 ~/email_assistant/job_tracker.py >> ~/email_assistant/bot.log 2>&1

# Tech digest — Mon-Fri 8:30am
30 8 * * 1-5 /path/to/python3 ~/email_assistant/tech_digest.py >> ~/email_assistant/bot.log 2>&1
```

Get the correct Python path with: `which python3`

---

## 8. Running the Bot

**Start manually (foreground, for testing):**

```bash
cd ~/email_assistant
python3 bot_server.py
```

**Start in background (production):**

```bash
pkill -f bot_server.py; rm -f /tmp/akshay_bot.pid
cd ~/email_assistant
nohup python3 bot_server.py > assistant.log 2>&1 &
```

**Check status:**

```bash
ps aux | grep bot_server | grep -v grep
tail -f ~/email_assistant/assistant.log
tail -f ~/email_assistant/bot.log
```

**Stop:**

```bash
pkill -f bot_server.py && rm -f /tmp/akshay_bot.pid
```

---

## 9. Slash Commands

Send these in your Telegram group or in DM with the bot:

| Command | Description |
|---|---|
| `/findjobs` | Search LinkedIn Easy Apply jobs matching your profile |
| `/applyjobs` | Auto-apply to approved jobs (tailors resume + messages recruiter) |
| `/mystatus` | Show job application pipeline |
| `/update <id> <stage> [note]` | Update an application stage (`applied`, `phone_screen`, `interview`, `offer`, `rejected`) |
| `/schedule` | Google Calendar summary for today |
| `/emails` | Gmail summary for the last 2 hours |
| `/stocks` | Trigger a stock drop check |
| `/post <topic>` | Generate and post to LinkedIn on a given topic |
| Free-form text | Claude AI responds (in Chat topic only) |

---

## 10. Project Architecture

| File | Role |
|---|---|
| `bot_server.py` | Main bot loop — commands, Claude chat, callback queries |
| `telegram_topics.py` | Central topic router — routes messages to the right thread |
| `linkedin_apply.py` | Playwright Easy Apply automation — search, approve flow, auto-apply |
| `linkedin_auth.py` | LinkedIn session login (saves `linkedin_session.json`) |
| `linkedin_jobs.py` | LinkedIn job alert email parser |
| `linkedin_post.py` | LinkedIn post generator via Claude |
| `job_tracker.py` | SQLite job tracker — stages: applied → phone_screen → interview → offer → rejected |
| `resume_tailor.py` | Claude resume rewriter per job description |
| `email_bot.py` | Gmail IMAP reader + Claude summarizer |
| `smart_email_alert.py` | Priority email watcher (runs via cron every 15 min) |
| `morning_briefing.py` | Daily 8am briefing — calendar + overnight emails |
| `calendar_bot.py` | Google Calendar API v3 — fetch today's events |
| `calendar_auth.py` | One-time OAuth flow to generate `token.json` |
| `tech_digest.py` | Morning tech news digest |
| `get_topic_ids.py` | Utility to print Telegram topic thread IDs |

**Databases (SQLite, auto-created on first run):**

| File | Contents |
|---|---|
| `applied_jobs.db` | Job application pipeline tracked by `job_tracker.py` |

**Gitignored files (you must create locally):**

| File | Description |
|---|---|
| `~/.env` | All secrets and credentials |
| `credentials.json` | Google OAuth client secrets |
| `token.json` | Google OAuth access token (generated by `calendar_auth.py`) |
| `linkedin_session.json` | LinkedIn Playwright session (auto-generated on first login) |

---

## 11. Troubleshooting

**Bot won't start — "already running"**

```bash
rm -f /tmp/akshay_bot.pid
python3 bot_server.py
```

**409 Conflict from Telegram**

Two instances are polling simultaneously. Kill all and restart cleanly:

```bash
pkill -f bot_server.py
rm -f /tmp/akshay_bot.pid
sleep 5
nohup python3 bot_server.py > assistant.log 2>&1 &
```

**Google Calendar errors**

`token.json` is expired or missing. Re-run the auth flow:

```bash
rm -f token.json
python3 calendar_auth.py
```

**LinkedIn login fails**

Delete the stale session and let the bot re-authenticate:

```bash
rm -f linkedin_session.json
python3 linkedin_auth.py
```

**Gmail connection refused**

- Verify 2-Step Verification is enabled on your Google account
- Re-generate the App Password at myaccount.google.com → Security → App Passwords
- Update `GMAIL_APP_PASSWORD` in `~/.env`

**No messages reaching the bot in the group**

- Confirm bot privacy mode is OFF: message @BotFather → `/setprivacy` → select your bot → Disable
- Confirm the bot is a member of the group with admin or member permissions
