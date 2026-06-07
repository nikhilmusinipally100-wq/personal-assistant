#!/usr/bin/env python3
"""
LinkedIn Easy Apply Bot
- Finds Easy Apply jobs matching Akshay's profile
- Sends job details to Telegram for approval
- Applies to approved jobs automatically
"""

import asyncio
import json
import sqlite3
import requests
import time
from datetime import datetime
from pathlib import Path
from dotenv import dotenv_values
from playwright.async_api import async_playwright

config = dotenv_values(Path.home() / ".env")

TELEGRAM_TOKEN = config.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT  = config.get("TELEGRAM_CHAT_ID")
TELEGRAM_API   = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# Job search keywords matching Akshay's profile
JOB_KEYWORDS = [
    "Software Developer .NET",
    "ASP.NET Core Developer",
    "Full Stack Developer .NET",
    "Software Engineer AWS",
    ".NET Developer AWS",
]

LINKEDIN_EMAIL    = config.get("LINKEDIN_EMAIL")
LINKEDIN_PASSWORD = config.get("LINKEDIN_PASSWORD")

LOCATION     = "Irvine, CA"
DB_PATH      = Path(__file__).parent / "applied_jobs.db"
SESSION_FILE = Path(__file__).parent / "linkedin_session.json"


# ── Database ──────────────────────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id              TEXT PRIMARY KEY,
            title           TEXT,
            company         TEXT,
            location        TEXT,
            url             TEXT,
            status          TEXT DEFAULT 'pending',
            stage           TEXT DEFAULT 'pending',
            notes           TEXT,
            tailored_resume TEXT,
            recruiter       TEXT,
            found_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
            applied_at      DATETIME
        )
    """)
    # Add columns if upgrading from older schema
    for col, definition in [
        ("stage",           "TEXT DEFAULT 'pending'"),
        ("notes",           "TEXT"),
        ("tailored_resume", "TEXT"),
        ("recruiter",       "TEXT"),
    ]:
        try:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {definition}")
        except Exception:
            pass
    conn.commit()
    conn.close()


def save_job(job):
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO jobs (id, title, company, location, url) VALUES (?,?,?,?,?)",
            (job["id"], job["title"], job["company"], job["location"], job["url"])
        )
        conn.commit()
    except Exception:
        pass
    conn.close()


def update_job_status(job_id, status):
    conn = sqlite3.connect(DB_PATH)
    # Only advance stage to 'applied' on confirmed success
    # For failed/skipped/approved, keep stage as-is so tracker stays clean
    if status == "applied":
        conn.execute(
            "UPDATE jobs SET status=?, stage=?, applied_at=? WHERE id=?",
            (status, "applied", datetime.now().isoformat(), job_id)
        )
    else:
        conn.execute(
            "UPDATE jobs SET status=?, applied_at=? WHERE id=?",
            (status, datetime.now().isoformat(), job_id)
        )
    conn.commit()
    conn.close()


def get_pending_jobs():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, title, company, location, url FROM jobs WHERE status='approved'"
    ).fetchall()
    conn.close()
    return [{"id": r[0], "title": r[1], "company": r[2], "location": r[3], "url": r[4]} for r in rows]


def already_seen(job_id):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT id FROM jobs WHERE id=?", (job_id,)).fetchone()
    conn.close()
    return row is not None


# ── Telegram ──────────────────────────────────────────────────────────────────

def send_telegram(text, reply_markup=None):
    from telegram_topics import TOPICS, GROUP_ID, TOKEN as TG_TOKEN
    payload = {
        "chat_id": GROUP_ID,
        "text": text,
        "parse_mode": "Markdown",
        "message_thread_id": TOPICS["jobs"],
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", json=payload)


def send_job_for_approval(job):
    markup = {
        "inline_keyboard": [[
            {"text": "✅ Apply", "callback_data": f"apply_{job['id']}"},
            {"text": "❌ Skip",  "callback_data": f"skip_{job['id']}"}
        ]]
    }
    text = (
        f"💼 *New Job Found*\n\n"
        f"*{job['title']}*\n"
        f"🏢 {job['company']}\n"
        f"📍 {job['location']}\n\n"
        f"[View Job]({job['url']})"
    )
    send_telegram(text, reply_markup=markup)


def handle_callback(update):
    callback = update.get("callback_query", {})
    data     = callback.get("data", "")
    msg_id   = callback.get("id")

    # Answer callback to remove loading state
    requests.post(f"{TELEGRAM_API}/answerCallbackQuery", json={"callback_query_id": msg_id})

    if data.startswith("apply_"):
        job_id = data[6:]
        update_job_status(job_id, "approved")
        send_telegram(f"✅ Marked for apply: `{job_id}`")

    elif data.startswith("skip_"):
        job_id = data[5:]
        update_job_status(job_id, "skipped")
        send_telegram(f"❌ Skipped: `{job_id}`")


# ── LinkedIn Playwright ───────────────────────────────────────────────────────

async def save_session(page):
    cookies = await page.context.cookies()
    SESSION_FILE.write_text(json.dumps(cookies))


async def load_session(context):
    if SESSION_FILE.exists():
        cookies = json.loads(SESSION_FILE.read_text())
        await context.add_cookies(cookies)
        return True
    return False


async def login_linkedin_visible():
    """Open a visible browser, auto-fill credentials, and save session."""
    send_telegram("🔐 LinkedIn session expired — opening browser to re-login automatically...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        try:
            await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            # Index 1 is the visible form (index 0 is a hidden duplicate)
            email_field = page.locator("input[type='email']").nth(1)
            pwd_field   = page.locator("input[type='password']").nth(1)
            await email_field.click(timeout=10000)
            await email_field.type(LINKEDIN_EMAIL, delay=50)
            await page.wait_for_timeout(500)

            await pwd_field.click(timeout=10000)
            await pwd_field.type(LINKEDIN_PASSWORD, delay=50)
            await page.wait_for_timeout(1000)

            # Click Sign in by text — button type changes after form fill
            signin_btn = page.get_by_role("button", name="Sign in").last
            await signin_btn.click(timeout=10000)
            await page.wait_for_timeout(3000)

            # Wait for feed — notify user if CAPTCHA appears
            try:
                await page.wait_for_url("**/feed/**", timeout=30000)
            except Exception:
                send_telegram("⚠️ LinkedIn login needs manual help — please complete CAPTCHA in the browser window that just opened.")
                await page.wait_for_url("**/feed/**", timeout=120000)

            await save_session(page)
            send_telegram("✅ LinkedIn re-logged in! Job search is ready.")
            print("✅ Session refreshed.")
        finally:
            await browser.close()


async def search_jobs(page, keyword):
    """Search Easy Apply jobs and return list of job cards."""
    url = (
        f"https://www.linkedin.com/jobs/search/?"
        f"keywords={keyword.replace(' ', '%20')}"
        f"&location={LOCATION.replace(' ', '%20').replace(',', '%2C')}"
        f"&f_AL=true"
        f"&sortBy=DD"
    )
    await page.goto(url, wait_until="domcontentloaded")
    # Wait for job cards to render (up to 10s), then scroll to load more
    try:
        await page.wait_for_selector("a[href*='/jobs/view/']", timeout=10000)
    except Exception:
        pass
    await page.wait_for_timeout(3000)
    await page.evaluate("window.scrollBy(0, 600)")
    await page.wait_for_timeout(2000)

    jobs = []
    seen_ids = set()

    links = await page.query_selector_all("a[href*='/jobs/view/']")

    for link in links[:20]:
        try:
            href  = await link.get_attribute("href") or ""
            title = (await link.inner_text()).strip()

            if not href or not title or len(title) < 3:
                continue

            # Extract numeric job ID from slug URL
            slug  = href.split("/jobs/view/")[1].split("?")[0].split("/")[0]
            # Last segment is the numeric ID: "dotnet-developer-at-tranzeal-4414123"
            parts  = slug.rsplit("-", 1)
            job_id = parts[-1] if parts[-1].isdigit() else slug

            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            # Get company + location from parent li
            parent = await link.evaluate_handle("el => el.closest('li')")
            parent_el = parent.as_element() if parent else None

            company  = "Unknown Company"
            location = ""
            if parent_el:
                # Authenticated (logged-in) LinkedIn SPA selectors
                company_el = (
                    await parent_el.query_selector(".artdeco-entity-lockup__subtitle") or
                    await parent_el.query_selector("div[class*='subtitle']") or
                    await parent_el.query_selector(".job-card-container__primary-description") or
                    await parent_el.query_selector(".base-search-card__subtitle")
                )
                if company_el:
                    company = (await company_el.inner_text()).strip()

                location_el = (
                    await parent_el.query_selector(".job-card-container__metadata-wrapper") or
                    await parent_el.query_selector(".job-search-card__location") or
                    await parent_el.query_selector(".base-search-card__metadata")
                )
                if location_el:
                    location = (await location_el.inner_text()).strip().split("\n")[0]

            full_url = f"https://www.linkedin.com{href}" if href.startswith("/") else href

            jobs.append({
                "id":       job_id,
                "title":    title,
                "company":  company,
                "location": location,
                "url":      full_url.split("?")[0],
            })

        except Exception:
            continue

    return jobs


async def apply_to_job(page, job):
    """Apply to a single Easy Apply job."""
    try:
        await page.goto(job["url"])
        await page.wait_for_timeout(2000)

        # Click Easy Apply button
        apply_btn = await page.query_selector("button.jobs-apply-button")
        if not apply_btn:
            print(f"  No Easy Apply button for {job['title']}")
            return False

        await apply_btn.click()
        await page.wait_for_timeout(2000)

        # Go through application steps (next/submit)
        for _ in range(10):
            # Check for Submit button
            submit = await page.query_selector("button[aria-label*='Submit application']")
            if submit:
                await submit.click()
                await page.wait_for_timeout(2000)
                print(f"  ✅ Applied to {job['title']} at {job['company']}")
                return True

            # Click Next
            nxt = await page.query_selector("button[aria-label*='Continue to next step']")
            if nxt:
                await nxt.click()
                await page.wait_for_timeout(1500)
                continue

            # Review button
            review = await page.query_selector("button[aria-label*='Review your application']")
            if review:
                await review.click()
                await page.wait_for_timeout(1500)
                continue

            break

        return False

    except Exception as e:
        print(f"  ❌ Error applying to {job['title']}: {e}")
        return False


async def find_and_connect_recruiter(page, job):
    """Search for recruiter/hiring manager at the company and send a connection request."""
    try:
        company_slug = job["company"].lower().replace(" ", "%20")
        search_url = (
            f"https://www.linkedin.com/search/results/people/?"
            f"keywords=recruiter+{company_slug}&origin=GLOBAL_SEARCH_HEADER"
        )
        await page.goto(search_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        # Find first person result with Connect button
        cards = await page.query_selector_all(".reusable-search__result-container")
        for card in cards[:5]:
            try:
                connect_btn = await card.query_selector("button[aria-label*='Connect']")
                name_el     = await card.query_selector(".entity-result__title-text")
                if not connect_btn or not name_el:
                    continue

                name = (await name_el.inner_text()).strip().split("\n")[0]
                await connect_btn.click()
                await page.wait_for_timeout(1500)

                # Add a note
                note_btn = await page.query_selector("button[aria-label='Add a note']")
                if note_btn:
                    await note_btn.click()
                    await page.wait_for_timeout(1000)
                    note_field = await page.query_selector("textarea#custom-message")
                    if note_field:
                        note_text = (
                            f"Hi {name.split()[0]}, I recently applied for the "
                            f"{job['title']} role at {job['company']}. "
                            f"I'm a software developer with experience in .NET Core, AWS, and DevOps. "
                            f"Would love to connect!"
                        )
                        await note_field.fill(note_text[:300])

                send_btn = await page.query_selector("button[aria-label='Send now']")
                if send_btn:
                    await send_btn.click()
                    await page.wait_for_timeout(1000)
                    return name

                # Close modal if send failed
                close = await page.query_selector("button[aria-label='Dismiss']")
                if close:
                    await close.click()

            except Exception:
                continue

        return None
    except Exception as e:
        print(f"  Recruiter search error: {e}")
        return None


# ── Main ──────────────────────────────────────────────────────────────────────

async def find_jobs():
    """Find new Easy Apply jobs and send to Telegram for approval."""
    init_db()
    new_jobs = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = await context.new_page()

        session_loaded = await load_session(context)
        if not session_loaded:
            await browser.close()
            await login_linkedin_visible()
            # Re-open headless browser with fresh session
            browser  = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"])
            context  = await browser.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36", viewport={"width": 1280, "height": 800})
            await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            page = await context.new_page()
            await load_session(context)
        else:
            await page.goto("https://www.linkedin.com/feed")
            await page.wait_for_timeout(2000)
            if "login" in page.url or "authwall" in page.url:
                print("Session expired, re-logging in...")
                await browser.close()
                await login_linkedin_visible()
                browser  = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"])
                context  = await browser.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36", viewport={"width": 1280, "height": 800})
                await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
                page = await context.new_page()
                await load_session(context)

        for keyword in JOB_KEYWORDS:
            print(f"Searching: {keyword}...")
            jobs = await search_jobs(page, keyword)
            for job in jobs:
                if not already_seen(job["id"]):
                    save_job(job)
                    send_job_for_approval(job)
                    new_jobs += 1
                    await asyncio.sleep(1)

        await browser.close()

    if new_jobs == 0:
        send_telegram("💼 *Job Search Complete*\nNo new Easy Apply jobs found matching your profile.")
    else:
        send_telegram(f"💼 Found *{new_jobs} new jobs*! Review above and tap ✅ Apply or ❌ Skip.")


async def apply_approved():
    """Apply to all Telegram-approved jobs."""
    init_db()
    approved = get_pending_jobs()

    if not approved:
        send_telegram("📋 No approved jobs to apply to yet. Use /findjobs first, then tap ✅ on jobs you want.")
        return

    send_telegram(f"🚀 Applying to *{len(approved)} approved jobs*...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = await context.new_page()

        await load_session(context)
        await page.goto("https://www.linkedin.com/feed")
        await page.wait_for_timeout(2000)

        applied = 0
        for job in approved:
            # 1. Tailor resume before applying
            try:
                from resume_tailor import tailor_for_job
                tailored = tailor_for_job(job, str(SESSION_FILE))
                if tailored:
                    # Save to DB
                    conn = sqlite3.connect(DB_PATH)
                    conn.execute("UPDATE jobs SET tailored_resume=? WHERE id=?", (tailored, job["id"]))
                    conn.commit()
                    conn.close()
                    send_telegram(
                        f"📄 *Tailored Resume for {job['title']} @ {job['company']}*\n\n"
                        f"```\n{tailored[:800]}...\n```\n_(full version saved)_"
                    )
            except Exception as e:
                print(f"  Resume tailor error: {e}")

            # 2. Apply
            success = await apply_to_job(page, job)
            status = "applied" if success else "failed"
            update_job_status(job["id"], status)

            if success:
                applied += 1
                send_telegram(f"✅ Applied: *{job['title']}* at {job['company']}")

                # 3. Recruiter outreach
                try:
                    recruiter = await find_and_connect_recruiter(page, job)
                    if recruiter:
                        conn = sqlite3.connect(DB_PATH)
                        conn.execute(
                            "UPDATE jobs SET recruiter=? WHERE id=?",
                            (recruiter, job["id"])
                        )
                        conn.commit()
                        conn.close()
                        send_telegram(f"🤝 Connection request sent to recruiter at *{job['company']}*")
                except Exception as e:
                    print(f"  Recruiter outreach error: {e}")
            else:
                send_telegram(f"⚠️ Could not apply to *{job['title']}* at {job['company']} — Easy Apply form needs manual review.")

            await asyncio.sleep(5)

        await browser.close()

    send_telegram(f"🎉 Done! Applied to *{applied}/{len(approved)}* jobs.")


def poll_approvals():
    """Poll Telegram for ✅/❌ button taps."""
    offset = None
    print("Polling for approvals (30 seconds)...")
    end = time.time() + 30

    while time.time() < end:
        params = {"timeout": 5, "allowed_updates": ["callback_query"]}
        if offset:
            params["offset"] = offset
        resp = requests.get(f"{TELEGRAM_API}/getUpdates", params=params, timeout=10)
        if resp.ok:
            for update in resp.json().get("result", []):
                offset = update["update_id"] + 1
                handle_callback(update)
        time.sleep(2)


async def do_login():
    """Open visible browser, auto-fill credentials and save session."""
    await login_linkedin_visible()


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "find"

    if cmd == "find":
        asyncio.run(find_jobs())
    elif cmd == "apply":
        asyncio.run(apply_approved())
    elif cmd == "poll":
        poll_approvals()
    elif cmd == "login":
        asyncio.run(do_login())
