#!/usr/bin/env python3
"""
LinkedIn Feed Reader & Engagement Bot
- Scrapes LinkedIn feed for high-quality posts
- Scores them via Claude (relevance + quality)
- Sends top posts to Telegram for approval
- On approval: auto-comment (Claude-generated) + optional connection request
"""

import asyncio
import json
import sqlite3
import requests
import re
import time
from datetime import datetime
from pathlib import Path
from dotenv import dotenv_values
from playwright.async_api import async_playwright
import anthropic

config = dotenv_values(Path.home() / ".env")

ANTHROPIC_KEY = config.get("ANTHROPIC_API_KEY")
TELEGRAM_API  = f"https://api.telegram.org/bot{config.get('TELEGRAM_BOT_TOKEN')}"

DB_PATH      = Path(__file__).parent / "applied_jobs.db"
SESSION_FILE = Path(__file__).parent / "linkedin_session.json"

MIN_SCORE    = 7   # Only surface posts scoring 7+/10
MAX_PER_SCAN = 10  # Max posts sent to Telegram per scan


# ── Database ──────────────────────────────────────────────────────────────────

def init_feed_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS feed_posts (
            id           TEXT PRIMARY KEY,
            author_name  TEXT,
            author_url   TEXT,
            post_text    TEXT,
            post_url     TEXT,
            score        INTEGER DEFAULT 0,
            status       TEXT DEFAULT 'pending',
            comment_text TEXT,
            found_at     DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def save_feed_post(post):
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            """INSERT OR IGNORE INTO feed_posts
               (id, author_name, author_url, post_text, post_url, score)
               VALUES (?,?,?,?,?,?)""",
            (post["id"], post["author_name"], post["author_url"],
             post["post_text"], post["post_url"], post.get("score", 0))
        )
        conn.commit()
    except Exception:
        pass
    conn.close()


def already_seen_post(post_id):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT id FROM feed_posts WHERE id=?", (post_id,)).fetchone()
    conn.close()
    return row is not None


def update_post_status(post_id, status, comment_text=None):
    conn = sqlite3.connect(DB_PATH)
    if comment_text:
        conn.execute(
            "UPDATE feed_posts SET status=?, comment_text=? WHERE id=?",
            (status, comment_text, post_id)
        )
    else:
        conn.execute("UPDATE feed_posts SET status=? WHERE id=?", (status, post_id))
    conn.commit()
    conn.close()


def get_post_by_id(post_id):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT id, author_name, author_url, post_text, post_url FROM feed_posts WHERE id=?",
        (post_id,)
    ).fetchone()
    conn.close()
    if row:
        return {"id": row[0], "author_name": row[1], "author_url": row[2],
                "post_text": row[3], "post_url": row[4]}
    return None


# ── Telegram ──────────────────────────────────────────────────────────────────

def send_telegram(text, reply_markup=None, topic="chat"):
    from telegram_topics import TOPICS, GROUP_ID, TOKEN as TG_TOKEN
    payload = {
        "chat_id":           GROUP_ID,
        "text":              text,
        "parse_mode":        "Markdown",
        "message_thread_id": TOPICS.get(topic, TOPICS["chat"]),
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", json=payload)


def send_post_for_approval(post):
    markup = {
        "inline_keyboard": [[
            {"text": "✅ Comment + Connect", "callback_data": f"fc_{post['id']}"},
            {"text": "💬 Comment only",       "callback_data": f"fco_{post['id']}"},
            {"text": "❌ Skip",               "callback_data": f"fs_{post['id']}"},
        ]]
    }
    preview = post["post_text"][:300] + ("..." if len(post["post_text"]) > 300 else "")
    text = (
        f"📰 *LinkedIn Post* — Score: {post.get('score', '?')}/10\n\n"
        f"👤 *{post['author_name']}*\n\n"
        f"_{preview}_\n\n"
        f"[View Post]({post['post_url']})"
    )
    send_telegram(text, reply_markup=markup, topic="chat")


# ── Claude ────────────────────────────────────────────────────────────────────

def score_post_with_claude(post):
    """Score a post 1-10 for quality and relevance to Akshay's interests."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            messages=[{
                "role": "user",
                "content": f"""Score this LinkedIn post 1-10 for a software engineer interested in:
.NET Core, AWS, DevOps, Kubernetes, Kafka, cloud-native, ML/AI, career growth, fintech.

Post by {post['author_name']}:
{post['post_text'][:500]}

Reply with ONLY a number 1-10.
High score = insightful, technical, career-relevant, thought-provoking.
Low score = promotional, generic, off-topic."""
            }]
        )
        return int(response.content[0].text.strip().split()[0])
    except Exception:
        return 5


def generate_comment(post):
    """Generate a thoughtful, relevant comment using Claude."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=150,
        messages=[{
            "role": "user",
            "content": f"""Write a short, genuine LinkedIn comment (2-3 sentences) for this post.
The commenter is Akshay, a software engineer with expertise in .NET Core, AWS, Kafka, and Kubernetes.
Be specific to the post content. Add real value or a relevant insight. Sound human.
Do NOT start with "Great post!" or "Excellent!" — be direct and thoughtful.

Post by {post['author_name']}:
{post['post_text'][:600]}

Return ONLY the comment text."""
        }]
    )
    return response.content[0].text.strip()


# ── LinkedIn Playwright ───────────────────────────────────────────────────────

async def load_session(context):
    if SESSION_FILE.exists():
        try:
            cookies = json.loads(SESSION_FILE.read_text())
            await context.add_cookies(cookies)
            return True
        except Exception:
            pass
    return False


async def scrape_feed_posts(page):
    """Scroll through LinkedIn feed and extract posts."""
    await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)

    # Scroll to load more posts
    for _ in range(4):
        await page.evaluate("window.scrollBy(0, 800)")
        await page.wait_for_timeout(1500)

    posts     = []
    seen_ids  = set()

    # Find all post containers (try both old and new LinkedIn markup)
    containers = await page.query_selector_all(
        "div.feed-shared-update-v2, div[data-urn*='activity']"
    )

    for container in containers[:40]:
        try:
            # Extract activity ID from data-urn or a permalink link
            urn   = await container.get_attribute("data-urn") or ""
            match = re.search(r'activity:(\d+)', urn)

            if not match:
                permalink = await container.query_selector("a[href*='feed/update/urn']")
                if permalink:
                    href  = await permalink.get_attribute("href") or ""
                    match = re.search(r'activity:(\d+)', href)

            if not match:
                continue

            post_id = match.group(1)
            if post_id in seen_ids or already_seen_post(post_id):
                continue
            seen_ids.add(post_id)

            # Post text (try multiple selectors for resilience)
            text_el = (
                await container.query_selector(".feed-shared-update-v2__description .break-words") or
                await container.query_selector(".update-components-text .break-words")            or
                await container.query_selector(".feed-shared-update-v2__description")             or
                await container.query_selector(".update-components-text")
            )
            post_text = (await text_el.inner_text()).strip() if text_el else ""
            if not post_text or len(post_text) < 50:
                continue

            # Author name + profile URL
            author_link = (
                await container.query_selector(".update-components-actor__meta-link") or
                await container.query_selector("a.update-components-actor__name")     or
                await container.query_selector(".feed-shared-actor__name-link")
            )
            author_name = "Unknown"
            author_url  = ""
            if author_link:
                author_name = (await author_link.inner_text()).strip().split("\n")[0]
                href        = await author_link.get_attribute("href") or ""
                if href.startswith("/"):
                    href = f"https://www.linkedin.com{href}"
                author_url = href.split("?")[0]

            posts.append({
                "id":          post_id,
                "author_name": author_name,
                "author_url":  author_url,
                "post_text":   post_text,
                "post_url":    f"https://www.linkedin.com/feed/update/urn:li:activity:{post_id}/",
            })

        except Exception:
            continue

    return posts


async def comment_on_post(page, post, comment_text):
    """Navigate to post and submit a comment."""
    try:
        await page.goto(post["post_url"], wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        # Click Comment button
        comment_btn = (
            await page.query_selector("button[aria-label*='Comment']") or
            await page.query_selector(".comment-button")
        )
        if not comment_btn:
            print(f"  No comment button for post {post['id']}")
            return False

        await comment_btn.click()
        await page.wait_for_timeout(2000)

        # LinkedIn uses Quill editor for comments
        editor = (
            await page.query_selector(".comments-comment-box__text-editor .ql-editor") or
            await page.query_selector(".ql-editor")
        )
        if not editor:
            print(f"  No comment editor found for post {post['id']}")
            return False

        await editor.click()
        await page.wait_for_timeout(500)
        await editor.type(comment_text, delay=30)
        await page.wait_for_timeout(1000)

        # Submit comment
        submit_btn = (
            await page.query_selector("button.comments-comment-box__submit-button")        or
            await page.query_selector("button[aria-label*='post your comment']")            or
            await page.query_selector("button[class*='submit'][class*='comment']")
        )
        if not submit_btn:
            print(f"  No submit button found for post {post['id']}")
            return False

        await submit_btn.click()
        await page.wait_for_timeout(2000)
        print(f"  ✅ Commented on post by {post['author_name']}")
        return True

    except Exception as e:
        print(f"  ❌ Comment error: {e}")
        return False


async def connect_with_author(page, post):
    """Navigate to author profile and send a connection request."""
    if not post.get("author_url") or "/in/" not in post["author_url"]:
        return False
    try:
        await page.goto(post["author_url"], wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        # Find Connect button (direct or inside More dropdown)
        connect_btn = await page.query_selector("button[aria-label*='Connect']")
        if not connect_btn:
            more_btn = await page.query_selector("button[aria-label*='More actions']")
            if more_btn:
                await more_btn.click()
                await page.wait_for_timeout(1000)
                connect_btn = await page.query_selector("div[aria-label*='Connect']")

        if not connect_btn:
            print(f"  No Connect button for {post['author_name']} — already connected or not available")
            return False

        await connect_btn.click()
        await page.wait_for_timeout(1500)

        # Add a personalized note
        note_btn = await page.query_selector("button[aria-label='Add a note']")
        if note_btn:
            await note_btn.click()
            await page.wait_for_timeout(1000)
            note_field = await page.query_selector("textarea#custom-message")
            if note_field:
                first_name = post["author_name"].split()[0]
                note = (
                    f"Hi {first_name}, I came across your recent post and found it really insightful. "
                    f"I'm a software engineer working with .NET Core, AWS, and cloud-native systems. "
                    f"Would love to connect!"
                )
                await note_field.fill(note[:300])

        send_btn = (
            await page.query_selector("button[aria-label='Send now']") or
            await page.query_selector("button[aria-label='Send invitation']")
        )
        if send_btn:
            await send_btn.click()
            await page.wait_for_timeout(1500)
            print(f"  ✅ Connection sent to {post['author_name']}")
            return True

        # Dismiss modal if send failed
        close = await page.query_selector("button[aria-label='Dismiss']")
        if close:
            await close.click()
        return False

    except Exception as e:
        print(f"  ❌ Connect error: {e}")
        return False


# ── Action Handler (called from bot_server callback) ─────────────────────────

async def handle_feed_action(post_id, action):
    """Execute comment + optional connect after Telegram approval."""
    post = get_post_by_id(post_id)
    if not post:
        send_telegram(f"⚠️ Post `{post_id}` not found.", topic="chat")
        return

    send_telegram(f"✍️ Generating comment for *{post['author_name']}'s* post...", topic="chat")
    comment_text = generate_comment(post)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = await context.new_page()
        await load_session(context)

        # Step 1 — Comment
        commented = await comment_on_post(page, post, comment_text)
        if commented:
            update_post_status(post_id, "commented", comment_text)
            send_telegram(
                f"💬 *Commented on {post['author_name']}'s post:*\n\n_{comment_text}_",
                topic="chat"
            )
        else:
            send_telegram(
                "⚠️ Couldn't post comment — LinkedIn form may have changed. Try manually.",
                topic="chat"
            )

        # Step 2 — Connect (only if requested)
        if action == "comment_connect" and post.get("author_url"):
            await asyncio.sleep(3)
            connected = await connect_with_author(page, post)
            if connected:
                update_post_status(post_id, "connected", comment_text)
                send_telegram(
                    f"🤝 Connection request sent to *{post['author_name']}*",
                    topic="chat"
                )
            else:
                send_telegram(
                    f"ℹ️ Could not connect with *{post['author_name']}* — may already be connected.",
                    topic="chat"
                )

        await browser.close()


def handle_feed_callback(update):
    """Route fc_/fco_/fs_ callback queries from bot_server."""
    callback = update.get("callback_query", {})
    data     = callback.get("data", "")
    msg_id   = callback.get("id")

    requests.post(f"{TELEGRAM_API}/answerCallbackQuery", json={"callback_query_id": msg_id})

    if data.startswith("fc_"):
        post_id = data[3:]
        asyncio.run(handle_feed_action(post_id, "comment_connect"))

    elif data.startswith("fco_"):
        post_id = data[4:]
        asyncio.run(handle_feed_action(post_id, "comment_only"))

    elif data.startswith("fs_"):
        post_id = data[3:]
        update_post_status(post_id, "skipped")
        send_telegram(f"⏭️ Skipped.", topic="chat")


# ── Entry point ───────────────────────────────────────────────────────────────

async def scan_feed():
    """Scrape feed → score with Claude → send top posts to Telegram."""
    init_feed_db()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = await context.new_page()
        await load_session(context)

        await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)

        if "login" in page.url or "authwall" in page.url:
            send_telegram("⚠️ LinkedIn session expired — re-login needed.", topic="chat")
            await browser.close()
            return

        print("Scraping LinkedIn feed...")
        posts = await scrape_feed_posts(page)
        await browser.close()

    if not posts:
        send_telegram("📰 *LinkedIn Feed*\nNo new posts found.", topic="chat")
        return

    print(f"Scoring {len(posts)} posts with Claude...")
    scored = []
    for post in posts:
        score = score_post_with_claude(post)
        post["score"] = score
        if score >= MIN_SCORE:
            scored.append(post)
            save_feed_post(post)

    scored.sort(key=lambda x: x["score"], reverse=True)
    top = scored[:MAX_PER_SCAN]

    if not top:
        send_telegram(
            f"📰 *LinkedIn Feed*\nScanned {len(posts)} posts — none scored {MIN_SCORE}+/10 today.",
            topic="chat"
        )
        return

    send_telegram(
        f"📰 *LinkedIn Feed Scan Complete*\n"
        f"Found *{len(top)} quality posts* (score {MIN_SCORE}+) out of {len(posts)} scanned.\n"
        f"Tap ✅ to comment + connect, 💬 to comment only, ❌ to skip. 👇",
        topic="chat"
    )

    for post in top:
        send_post_for_approval(post)
        time.sleep(1)


if __name__ == "__main__":
    asyncio.run(scan_feed())
