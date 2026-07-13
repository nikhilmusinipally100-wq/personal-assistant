# Personal AI Assistant

A Telegram bot that acts as a personal assistant — powered by Claude AI. Handles Gmail, Google Calendar, LinkedIn job search, stock alerts, and more.

## Features

| Command | What it does |
|---|---|
| `/findjobs` | Searches LinkedIn Easy Apply for matching jobs, sends each to Telegram for approval |
| `/applyjobs` | Auto-applies to approved jobs (tailors resume via Claude + messages recruiter) |
| `/mystatus` | Shows full job application pipeline |
| `/update <id> <stage>` | Updates application stage (applied → phone_screen → interview → offer) |
| `/schedule` | Today's Google Calendar summary |
| `/emails` | Last 2 hours of Gmail summarized by Claude |
| `/stocks` | Checks your stock watchlist for abnormal drops |
| `/post <topic>` | Generates and posts to LinkedIn |
| Chat | Talk to Claude AI with full context about you |

## Architecture

```
bot_server.py          — Main Telegram bot loop, handles all commands
telegram_topics.py     — Routes messages to correct Telegram group topics
email_bot.py           — Gmail IMAP reader + Claude summarizer
smart_email_alert.py   — Priority email watcher (runs every 15 min via cron)
calendar_bot.py        — Google Calendar API integration
morning_briefing.py    — Daily morning summary (runs at 8am via cron)
linkedin_apply.py      — LinkedIn Easy Apply automation via Playwright
linkedin_jobs.py       — LinkedIn job alert email parser
linkedin_post.py       — LinkedIn post generator via Claude
job_tracker.py         — SQLite job application tracker
resume_tailor.py       — Claude-powered resume tailoring per job
```

## Setup

### 1. Install dependencies

```bash
pip3 install -r requirements.txt
playwright install chromium
```

### 2. Configure credentials

```bash
cp .env.example ~/.env
chmod 600 ~/.env
# Edit ~/.env and fill in all values
```

You need:
- **Anthropic API key** — [console.anthropic.com](https://console.anthropic.com)
- **Telegram bot token** — create via [@BotFather](https://t.me/BotFather), then `/newbot`
- **Telegram group** — create a group, enable Topics (forum mode), add your bot, disable privacy mode via BotFather → `/setprivacy` → Disable
- **Gmail App Password** — [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
- **Google Calendar OAuth** — see [Calendar Setup](#google-calendar-setup) below

### 3. Customize for yourself

Edit `bot_server.py` and update the `SYSTEM_PROMPT` with your own:
- Name, email, location
- Work experience and tech stack
- Daily schedule
- Career goals

Also update the `RESUME` constant in `resume_tailor.py` with your actual resume.

### 4. Get your Telegram IDs

```bash
# Get your personal chat ID — message @userinfobot on Telegram
# Get your group ID and topic thread IDs:
python3 get_topic_ids.py
```

Add the IDs to `~/.env`.

### 5. Run the bot

```bash
python3 bot_server.py
```

### Google Calendar Setup

```bash
# Download credentials.json from Google Cloud Console
# (APIs & Services → Credentials → OAuth 2.0 → Desktop app)
# Place it in this directory, then:
python3 setup_calendar.py
# Follow the browser prompt to authorize — saves token.json
```

## Auto-start on macOS (runs 24/7, survives screen lock)

```bash
# Copy and edit the plist template
cp com.nikhil.assistant.plist.example ~/Library/LaunchAgents/com.nikhil.assistant.plist
# Edit paths inside the plist to match your username
launchctl load ~/Library/LaunchAgents/com.nikhil.assistant.plist
```

## Telegram Group Structure

The bot routes messages to 5 topic threads in a Telegram group:

| Topic | Content |
|---|---|
| Chat | AI conversation responses |
| Emails | Gmail summaries and priority alerts |
| Jobs | Job search results, apply buttons, tracker |
| Stocks | Stock drop alerts |
| Daily | Morning briefings and evening summaries |

## Cron jobs (optional)

```
# Morning briefing at 8am weekdays
0 8 * * 1-5 cd ~/email_assistant && python3 morning_briefing.py

# Priority email alerts every 15 min
*/15 * * * * cd ~/email_assistant && python3 smart_email_alert.py

# Daily job application summary at 6pm weekdays
0 18 * * 1-5 cd ~/email_assistant && python3 -c "from job_tracker import send_daily_summary; send_daily_summary()"

# Stock check at market open (9:30am ET = 6:30am PT) weekdays
30 6 * * 1-5 python3 ~/Nikhil/stockspredictor/stock_alerts.py
```

Add these with `crontab -e`.
