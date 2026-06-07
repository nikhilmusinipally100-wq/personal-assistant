#!/usr/bin/env python3
"""
Personal AI Assistant — Telegram bot server.
Runs continuously, responds to messages via Claude, and accepts commands.
"""

import requests
import anthropic
import time
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from dotenv import dotenv_values
from calendar_bot import get_calendar_summary
from linkedin_jobs import get_job_summary
from linkedin_post import post_from_topic
from job_tracker import format_status_report, handle_update_command
import subprocess

# Prevent duplicate instances
PIDFILE = Path("/tmp/akshay_bot.pid")
if PIDFILE.exists():
    old_pid = int(PIDFILE.read_text().strip())
    try:
        os.kill(old_pid, 0)  # Check if process alive
        print(f"Bot already running (PID {old_pid}). Exiting.")
        sys.exit(0)
    except OSError:
        pass  # Process dead, stale PID file — continue
PIDFILE.write_text(str(os.getpid()))

import atexit
atexit.register(lambda: PIDFILE.unlink(missing_ok=True))

config = dotenv_values(Path.home() / ".env")

ANTHROPIC_KEY  = config.get("ANTHROPIC_API_KEY")
TELEGRAM_TOKEN = config.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT  = config.get("TELEGRAM_CHAT_ID")

TELEGRAM_API   = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# Conversation history for context (last 20 messages)
conversation_history = []

SYSTEM_PROMPT = """You are Akshay Mittapally's personal AI assistant. Here's everything you know about him:

PERSONAL:
- Full name: Akshay Mittapally (LinkedIn: Akshay M, He/Him)
- Email: akshayreddy2022@gmail.com | Phone: +1 (913) 940 6869
- Location: United States (California area)
- Education: MS Computer Science, University of Central Missouri (Jan 2023 – May 2024)
- LinkedIn connections: 500+, followers: 1,454

WORK SCHEDULE (Mon-Fri, PST):
- 8:00am: Wake up & morning routine
- 8:30am: Daily standup
- 9:00am–12:00pm: Work
- 12:00–1:00pm: Lunch
- 1:00–5:00pm: Work
- 5:00–5:30pm: Commute home
- 5:30–7:00pm: Gym
- 7:00–8:30pm: Learn / relax
- 8:30–9:15pm: Dinner
- 9:15–10:00pm: Wind down

CURRENT JOB:
- Company: Luxoft USA Inc., California (March 2025 - Present, ~1.4 yrs)
- Role: Software Engineer (hybrid)
- Project: Capital Group's CRD (Charles River Development) platform — portfolio & risk management
- Key work: event-driven microservices with Kafka, Kubernetes (EKS) deployments, Terraform IaC, Harness CI/CD with blue-green deployments, Datadog/Splunk observability, AWS migration of legacy on-prem apps
- Tech: .NET Core, Apache Kafka, Docker, Kubernetes (EKS), Terraform, Harness, Datadog, Splunk, AWS

PREVIOUS EXPERIENCE:
- Elevance Health (Aug 2024 – Feb 2025, contract, 7 mos): Patient management system, ASP.NET Core, Angular/TypeScript, AWS Elastic Beanstalk, RDS, Cognito, Docker, HIPAA compliance
- Delta Air Lines (Feb 2024 – May 2024, internship, 4 mos, remote): Passenger reservation system, React, TypeScript, Amadeus GDS API, Stripe, PayPal, AWS Cognito/OAuth2, ElastiCache, CodePipeline
- University of Central Missouri research (Jan 2023 – May 2024):
  * Financial News Sentiment Analyzer: FinBERT fine-tuned on 15k+ samples, 87% accuracy, FastAPI REST endpoint
  * Patient Readmission Risk Predictor: XGBoost (best AUC-ROC 0.82), SHAP explainability, SMOTE for class imbalance
- Cognizant (Feb 2022 – Dec 2022): ASP.NET MVC, Web API, SQL Server, Agile sprints

TECHNICAL SKILLS:
- Backend: ASP.NET Core, .NET, C#, RESTful APIs, Microservices, FastAPI (Python)
- Frontend: React, Angular, TypeScript
- Cloud: AWS (EC2, RDS, S3, EKS, Lambda, Elastic Beanstalk, Cognito, CodePipeline, CloudFormation)
- DevOps: Docker, Kubernetes, Terraform, Harness CI/CD, IaC, blue-green deployments
- Messaging: Apache Kafka (event-driven, async inter-service communication)
- Monitoring: Datadog, Splunk
- ML/AI: FinBERT, XGBoost, Scikit-learn, SHAP, SMOTE, Hugging Face Transformers, Pandas, NLTK, Matplotlib
- Databases: SQL Server, ElastiCache (Redis), SQLite
- Other: Python, OAuth2, Amadeus GDS API, HIPAA compliance, Agile/Scrum

LINKEDIN ABOUT (his own words):
"I build high-performance, cloud-native systems that handle real-world complexity — from real-time trade processing on financial platforms to HIPAA-compliant patient management and live flight booking engines. My core stack is .NET Core and microservices architecture, backed by AWS, Apache Kafka, Docker, and Kubernetes. I focus on fault-tolerant event streaming, low-latency APIs, infrastructure as code, and observable systems. Open to senior .NET/cloud engineering roles in fintech, healthtech, or AI-integrated platforms."

PROJECTS:
- stockspredictor: Python CLI that monitors S&P 500 stocks for abnormal drops using yfinance + SQLite
- personal-assistant: This bot! Gmail + Calendar + LinkedIn + Telegram + Claude AI

GOALS & INTERESTS:
- Open to senior .NET/cloud/DevOps roles in fintech, healthtech, or AI platforms
- AWS certification pursuit
- Stock market monitoring and automation
- Building personal AI/automation tools
- Career growth to senior/lead cloud-native engineering roles

Be concise, friendly, and helpful. Keep responses short — this is Telegram, not an essay.
Use emojis occasionally. Help with coding, AWS/DevOps advice, career questions, scheduling, and anything else he needs."""


def send_message(text, parse_mode="Markdown", thread_id=None):
    """Send a message to the group chat topic."""
    from telegram_topics import GROUP_ID, TOPICS
    payload = {
        "chat_id":    GROUP_ID,
        "text":       text,
        "parse_mode": parse_mode,
        "message_thread_id": thread_id if thread_id else TOPICS["chat"],
    }
    resp = requests.post(f"{TELEGRAM_API}/sendMessage", json=payload)
    return resp.ok


def get_updates(offset=None):
    """Poll Telegram for new messages and callback queries."""
    params = {"timeout": 30, "allowed_updates": ["message", "callback_query"]}
    if offset:
        params["offset"] = offset
    resp = requests.get(f"{TELEGRAM_API}/getUpdates", params=params, timeout=35)
    return resp.json() if resp.ok else {"result": []}


def is_authorized(msg):
    """Accept messages from the group or the personal chat."""
    chat = msg.get("chat", {})
    chat_id   = str(chat.get("id", ""))
    chat_type = chat.get("type", "")
    from telegram_topics import GROUP_ID
    return chat_id == TELEGRAM_CHAT or chat_id == str(GROUP_ID) or chat_type in ("group", "supergroup")


def ask_claude(user_message):
    """Send message to Claude and get a response."""
    global conversation_history

    conversation_history.append({"role": "user", "content": user_message})

    # Keep last 20 messages for context
    if len(conversation_history) > 20:
        conversation_history = conversation_history[-20:]

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=conversation_history
    )

    reply = response.content[0].text
    conversation_history.append({"role": "assistant", "content": reply})
    return reply


def handle_command(text):
    """Handle special /commands."""
    cmd = text.lower().strip()

    if cmd == "/start":
        return "👋 Hey Akshay! I'm your personal assistant. Ask me anything or use:\n\n/schedule — today's calendar\n/emails — check recent emails\n/help — show all commands"

    if cmd == "/schedule":
        return get_calendar_summary()

    if cmd == "/emails":
        try:
            from email_bot import fetch_recent_emails, summarize_with_claude
            emails = fetch_recent_emails(hours=2)
            return summarize_with_claude(emails)
        except Exception as e:
            return f"⚠️ Could not fetch emails: {e}"

    if cmd == "/stocks":
        try:
            subprocess.Popen(
                ["/Library/Frameworks/Python.framework/Versions/3.11/bin/python3",
                 "/Users/akshayreddy/Akshay/stockspredictor/stock_alerts.py"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            return "📊 Checking your stocks... results coming shortly!"
        except Exception as e:
            return f"⚠️ Error: {e}"

    if cmd == "/jobs":
        try:
            return get_job_summary()
        except Exception as e:
            return f"⚠️ Could not fetch job alerts: {e}"

    if cmd.startswith("/post"):
        topic = text[5:].strip()
        if not topic:
            return "Usage: `/post your topic here`\nExample: `/post lessons learned from AWS certification`"
        try:
            success, post_text = post_from_topic(topic)
            if success:
                return f"✅ *Posted to LinkedIn!*\n\n{post_text}"
            else:
                return "⚠️ Post failed — check if Share on LinkedIn product is approved in your developer app."
        except Exception as e:
            return f"⚠️ Error: {e}"

    if cmd == "/mystatus":
        try:
            return format_status_report()
        except Exception as e:
            return f"⚠️ Error: {e}"

    if cmd.startswith("/update"):
        try:
            return handle_update_command(text)
        except Exception as e:
            return f"⚠️ Error: {e}"

    if cmd == "/findjobs":
        try:
            subprocess.Popen(
                ["/Library/Frameworks/Python.framework/Versions/3.11/bin/python3",
                 "/Users/akshayreddy/email_assistant/linkedin_apply.py", "find"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            return "🔍 Searching LinkedIn for Easy Apply jobs matching your profile...\nResults will appear below — tap ✅ Apply or ❌ Skip on each one."
        except Exception as e:
            return f"⚠️ Error: {e}"

    if cmd == "/feed":
        try:
            subprocess.Popen(
                ["/Library/Frameworks/Python.framework/Versions/3.11/bin/python3",
                 "/Users/akshayreddy/email_assistant/linkedin_feed.py"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            return "📰 Scanning your LinkedIn feed for quality posts... results coming shortly!"
        except Exception as e:
            return f"⚠️ Error: {e}"

    if cmd == "/applyjobs":
        try:
            subprocess.Popen(
                ["/Library/Frameworks/Python.framework/Versions/3.11/bin/python3",
                 "/Users/akshayreddy/email_assistant/linkedin_apply.py", "apply"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            return "🚀 Applying to all jobs you approved... will update you when done!"
        except Exception as e:
            return f"⚠️ Error: {e}"

    if cmd == "/help":
        return ("🤖 *Available Commands:*\n\n"
                "*Job Search:*\n"
                "/findjobs — search LinkedIn Easy Apply jobs\n"
                "/applyjobs — apply to approved jobs (auto-tailors resume + reaches recruiter)\n"
                "/mystatus — view all applications + pipeline\n"
                "/update [id] [stage] [note] — update application stage\n"
                "  Stages: applied phone\\_screen interview offer rejected\n\n"
                "*Networking:*\n"
                "/feed — scan LinkedIn feed, approve comments + connections\n\n"
                "*Daily:*\n"
                "/schedule — today's calendar\n"
                "/emails — last 2hrs email summary\n"
                "/jobs — LinkedIn job alerts from Gmail\n"
                "/stocks — check stock drops now\n"
                "/post [topic] — post to LinkedIn\n\n"
                "Or just chat with me normally!")

    return None


def run():
    print(f"[{datetime.now().strftime('%H:%M')}] Bot server started. Listening for messages...")
    send_message("🤖 Assistant is online! Type anything to chat, or use /help to see commands.")

    offset = None
    while True:
        try:
            updates = get_updates(offset)
            for update in updates.get("result", []):
                offset = update["update_id"] + 1

                # Handle inline button taps
                if "callback_query" in update:
                    data = update.get("callback_query", {}).get("data", "")
                    try:
                        if data.startswith(("fc_", "fco_", "fs_")):
                            from linkedin_feed import handle_feed_callback
                            handle_feed_callback(update)
                        else:
                            from linkedin_apply import handle_callback
                            handle_callback(update)
                    except Exception as e:
                        print(f"Callback error: {e}")
                    continue

                msg       = update.get("message", {})
                text      = msg.get("text", "").strip()
                thread_id = msg.get("message_thread_id")

                if not text or not is_authorized(msg):
                    continue

                print(f"[{datetime.now().strftime('%H:%M')}] [{thread_id}] Message: {text}")

                # Check for commands first
                if text.startswith("/"):
                    reply = handle_command(text)
                    if reply:
                        send_message(reply, thread_id=thread_id)
                        continue

                # Otherwise send to Claude — only respond in Chat topic or DM
                from telegram_topics import TOPICS
                if thread_id is None or thread_id == TOPICS.get("chat"):
                    try:
                        reply = ask_claude(text)
                        send_message(reply, thread_id=thread_id)
                    except Exception as e:
                        send_message(f"⚠️ Error: {e}", thread_id=thread_id)

        except KeyboardInterrupt:
            print("Bot stopped.")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)
            continue


if __name__ == "__main__":
    run()
