#!/usr/bin/env python3
"""
Resume Auto-Tailor
- Fetches job description from LinkedIn
- Uses Claude to rewrite resume bullets to match the role
- Returns tailored resume text to send via Telegram
"""

import anthropic
import requests
from pathlib import Path
from dotenv import dotenv_values
from playwright.async_api import async_playwright
import asyncio

config        = dotenv_values(Path.home() / ".env")
ANTHROPIC_KEY = config.get("ANTHROPIC_API_KEY")

RESUME = """
Nikhil Musinipally | nikhil.musinipally.100@gmail.com | +44 7448863585 | London, UK

PROFILE
Aspiring Data Analyst with an MSc in Management with Data Analytics (in progress) and a
B-Tech in Electrical & Electronics Engineering. Skilled in SQL, Python, Excel, and BI tools
(Power BI, Tableau) for cleaning, analysing, and visualising data. Strong numerical accuracy
and communication developed through customer-facing retail and hospitality roles. Seeking
Data Analyst / Business Analyst roles (also open to software development).

EDUCATION
MSc Management with Data Analytics — BPP University, London (2025–2027)
B-Tech Electrical & Electronics Engineering — TKR College of Engineering & Technology, Hyderabad (2018–2022)

TECHNICAL SKILLS
Data: SQL, Python (Pandas, NumPy), advanced Excel, data cleaning, statistics
Visualization / BI: Power BI, Tableau, dashboards & reporting
Concepts: exploratory data analysis, KPI reporting, foundations of machine learning

EXPERIENCE
Sales Assistant & Post Office Clerk — Morrisons, UK (Jun 2025 – Present)
• Handled high volumes of cash/card transactions and balanced tills daily with full accuracy
• Processed postal, parcel, and bill-payment services efficiently, reducing customer wait times
Store Assistant — Reliance Retail, India (2022)
• Monitored stock levels and organised inventory/deliveries; flagged reorder needs proactively

CERTIFICATES
Food Safety & Hygiene for Catering (Level 2) | IELTS 6.5 | GRE 316

# TODO: Replace/expand this with your full professional data CV and any data projects when ready.
"""


async def fetch_job_description(url, session_file):
    """Scrape job description from LinkedIn job page."""
    try:
        import json
        cookies = json.loads(Path(session_file).read_text()) if Path(session_file).exists() else []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            if cookies:
                cookie_list = cookies["cookies"] if isinstance(cookies, dict) and "cookies" in cookies else cookies
                await context.add_cookies(cookie_list)
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            # Try to expand "Show more" for full description
            try:
                btn = await page.query_selector("button[aria-label*='more']")
                if btn:
                    await btn.click()
                    await page.wait_for_timeout(1000)
            except Exception:
                pass

            desc_el = (
                await page.query_selector(".jobs-description__content") or
                await page.query_selector(".job-details-jobs-unified-top-card__job-insight") or
                await page.query_selector("#job-details") or
                await page.query_selector(".description__text")
            )
            desc = (await desc_el.inner_text()).strip() if desc_el else ""
            await browser.close()
            return desc[:3000]  # cap at 3k chars for Claude
    except Exception as e:
        print(f"Could not fetch job description: {e}")
        return ""


def tailor_resume_with_claude(job_title, company, job_description):
    """Ask Claude to rewrite resume bullets to match the job."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    prompt = f"""You are a professional resume writer. Tailor Nikhil's resume for this specific job.

JOB: {job_title} at {company}

JOB DESCRIPTION:
{job_description if job_description else "No description available — tailor based on job title."}

NIKHIL'S CURRENT RESUME:
{RESUME}

INSTRUCTIONS:
1. Keep the same structure and all real experience — do NOT invent anything
2. Rewrite bullet points to use keywords from the job description
3. Reorder skills to put the most relevant ones first
4. Adjust the summary/profile emphasis to match what this company wants
5. Keep it concise — max 1 page worth of content

Return ONLY the tailored resume text, no commentary."""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text


def tailor_for_job(job, session_file):
    """Full pipeline: fetch JD → tailor → return text."""
    print(f"Tailoring resume for {job['title']} @ {job['company']}...")
    jd = asyncio.run(fetch_job_description(job["url"], session_file))
    tailored = tailor_resume_with_claude(job["title"], job["company"], jd)
    return tailored


if __name__ == "__main__":
    import sys
    # Quick test
    job = {
        "title": sys.argv[1] if len(sys.argv) > 1 else "Data Analyst",
        "company": sys.argv[2] if len(sys.argv) > 2 else "Test Company",
        "url": sys.argv[3] if len(sys.argv) > 3 else ""
    }
    session = Path(__file__).parent / "linkedin_session.json"
    result = tailor_for_job(job, str(session))
    print(result)
