#!/usr/bin/env python3
"""
Personal AI Assistant — Telegram bot server.
Runs continuously, responds to messages via Claude, and accepts commands.
"""

import requests
import anthropic
import time
import json
from datetime import datetime
from pathlib import Path
from dotenv import dotenv_values
from calendar_bot import get_calendar_summary

config = dotenv_values(Path.home() / ".env")

ANTHROPIC_KEY  = config.get("ANTHROPIC_API_KEY")
TELEGRAM_TOKEN = config.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT  = config.get("TELEGRAM_CHAT_ID")

TELEGRAM_API   = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# Conversation history for context (last 20 messages)
conversation_history = []

SYSTEM_PROMPT = """You are Akshay's personal AI assistant. Here's what you know about him:
- He is a software developer working in Irvine, CA
- Works Mon-Fri, 8:30am standup, 9am-5pm work hours (PST)
- Evening routine: gym 5:30-7pm, dinner at 8:30pm, winds down at 10pm
- Email: akshayreddy2022@gmail.com
- Interests: AWS, DevOps, Python, stock market monitoring
- Has a stock monitoring app (stockspredictor) that tracks S&P 500 drops

Be concise, friendly, and helpful. You can help with:
- Answering questions about his schedule
- General knowledge and coding questions
- AWS/DevOps advice
- Stock market questions
- Daily planning and reminders

Keep responses short and conversational — this is a Telegram chat, not an essay.
Use emojis occasionally to keep it friendly."""


def send_message(text, parse_mode="Markdown"):
    """Send a message to Telegram."""
    resp = requests.post(f"{TELEGRAM_API}/sendMessage", json={
        "chat_id": TELEGRAM_CHAT,
        "text": text,
        "parse_mode": parse_mode
    })
    return resp.ok


def get_updates(offset=None):
    """Poll Telegram for new messages."""
    params = {"timeout": 30, "allowed_updates": ["message"]}
    if offset:
        params["offset"] = offset
    resp = requests.get(f"{TELEGRAM_API}/getUpdates", params=params, timeout=35)
    return resp.json() if resp.ok else {"result": []}


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

    if cmd == "/help":
        return ("🤖 *Available Commands:*\n\n"
                "/schedule — today's calendar\n"
                "/emails — last 2hrs email summary\n"
                "/start — welcome message\n\n"
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
                msg = update.get("message", {})
                text = msg.get("text", "").strip()
                chat_id = str(msg.get("chat", {}).get("id", ""))

                # Only respond to your own chat
                if not text or chat_id != TELEGRAM_CHAT:
                    continue

                print(f"[{datetime.now().strftime('%H:%M')}] Message: {text}")

                # Check for commands first
                if text.startswith("/"):
                    reply = handle_command(text.split()[0])
                    if reply:
                        send_message(reply)
                        continue

                # Otherwise send to Claude
                try:
                    reply = ask_claude(text)
                    send_message(reply)
                except Exception as e:
                    send_message(f"⚠️ Error: {e}")

        except KeyboardInterrupt:
            print("Bot stopped.")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)
            continue


if __name__ == "__main__":
    run()
