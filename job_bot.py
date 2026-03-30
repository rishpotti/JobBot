# =============================================================================
# job_bot.py  —  Module 1: Scraper Engine
# Runs nightly via GitHub Actions. Scrapes job boards, deduplicates, filters
# by master company list, writes results to Supabase, and emails an HTML digest.
# =============================================================================

# FIX: Removed dead commented-out imports at the top of the file. All imports
# are now handled in the safe try/except blocks below, as originally intended.
import sys
import time
import random

print("---------- JOB BOT STARTING ----------", flush=True)

# ── Standard library imports ──────────────────────────────────────────────────
try:
    import os
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    from datetime import date
    print("✅ Standard libraries imported.", flush=True)
except Exception as e:
    print(f"❌ Failed to import standard libraries: {e}", flush=True)
    sys.exit(1)

# ── Pandas ────────────────────────────────────────────────────────────────────
try:
    import pandas as pd
    print("✅ Pandas imported.", flush=True)
except Exception as e:
    print(f"❌ CRITICAL: Pandas failed to import. Check requirements.txt. Error: {e}", flush=True)
    sys.exit(1)

# ── JobSpy ────────────────────────────────────────────────────────────────────
try:
    from jobspy import scrape_jobs
    print("✅ JobSpy imported.", flush=True)
except Exception as e:
    print(f"❌ CRITICAL: JobSpy failed to import. Error: {e}", flush=True)
    sys.exit(1)

# ── Supabase ──────────────────────────────────────────────────────────────────
# FIX: Added Supabase client import. This replaces the CSV write-back approach.
# The scraper now writes directly to the shared database that the Streamlit
# dashboard reads from. Requires `supabase==2.4.0` in requirements.txt.
try:
    from supabase import create_client
    print("✅ Supabase client imported.", flush=True)
except Exception as e:
    # Non-fatal: if Supabase fails, we still send the email and log the error.
    # This prevents a broken Supabase connection from killing the whole nightly run.
    print(f"⚠️ WARNING: Supabase failed to import. Jobs will NOT be written to DB. Error: {e}", flush=True)
    create_client = None

# ── Requests (for Greenhouse & Lever ATS APIs) ────────────────────────────────
try:
    import requests
    print("✅ Requests imported.", flush=True)
except Exception as e:
    print(f"⚠️ WARNING: Requests failed to import. Greenhouse/Lever scraping disabled. Error: {e}", flush=True)
    requests = None


# =============================================================================
# CONFIGURATION
# =============================================================================

KEYWORDS = [
    # --- TIER 1: Standard Data & ML Titles ---
    "Data Science Intern Summer 2026",
    "Data Scientist Intern Summer 2026",
    "Machine Learning Intern Summer 2026",
    "Machine Learning Engineer Intern 2026",
    "Artificial Intelligence Intern 2026",
    "AI Engineer Intern 2026",

    # --- TIER 2: Prestige Tech Titles (Amazon/Microsoft/Nvidia style) ---
    # These often pay 30–50% more than standard "Data Analyst" roles
    "Applied Scientist Intern 2026",
    "Applied Machine Learning Intern 2026",
    "Research Scientist Intern 2026",
    "Research Engineer Intern 2026",
    "Algorithm Engineer Intern 2026",

    # --- TIER 3: Fintech & Quant (High fit for Amex background) ---
    "Quantitative Researcher Intern 2026",
    "Quantitative Analyst Intern 2026",
    "Quant Developer Intern 2026",
    "Financial Engineering Intern 2026",
    "Decision Science Intern 2026",
    "Risk Modeling Intern 2026",

    # --- TIER 4: Emerging Tech (GenAI / LLMs) ---
    "Generative AI Intern 2026",
    "LLM Intern 2026",
    "Large Language Model Intern 2026",
    "Natural Language Processing Intern 2026",
    "Computer Vision Intern 2026",
    "Deep Learning Intern 2026",

    # --- TIER 5: Hidden Engineering Roles ---
    # Often listed as SWE but are 100% ML work
    "Software Engineer Intern Machine Learning",
    "Software Engineer Intern AI",
    "Software Engineer Intern Data",
    "Data Engineer Intern Summer 2026",
    "MLOps Intern 2026",
    "AI Infrastructure Intern 2026",

    # --- TIER 6: Domain Specific (Bio/Health for U-Net project) ---
    "Biomedical Data Science Intern",
    "Computational Biology Intern",
    "Imaging AI Intern",
]

PRIORITY_COMPANIES = [
    # --- TIER 1: BIG TECH & AI ---
    "Google", "Alphabet", "Apple", "Meta", "Facebook", "Amazon", "AWS",
    "Microsoft", "Netflix", "Nvidia", "Tesla", "Adobe", "Salesforce",
    "Oracle", "Intel", "AMD", "Cisco", "IBM", "Intuit", "Uber", "Lyft",
    "Airbnb", "Spotify", "Snap", "Pinterest", "LinkedIn", "Databricks",
    "Snowflake", "Palantir", "OpenAI", "Anthropic", "DeepMind",

    # --- TIER 2: FINTECH & BANKING ---
    "American Express", "JPMorgan", "J.P. Morgan", "Chase", "Goldman Sachs",
    "Morgan Stanley", "Citi", "Citigroup", "Bank of America", "Wells Fargo",
    "Capital One", "Visa", "Mastercard", "PayPal", "Stripe", "Block", "Square",
    "BlackRock", "Two Sigma", "Citadel", "Jane Street", "Fidelity", "Vanguard",
    "Bloomberg", "SoFi", "Chime", "Discover",

    # --- TIER 3: HEALTHCARE & PHARMA ---
    "Pfizer", "Moderna", "Johnson & Johnson", "J&J", "Merck", "AbbVie",
    "Eli Lilly", "UnitedHealth", "Optum", "CVS Health", "Cigna", "Elevance",
    "Humana", "Bristol Myers Squibb", "Amgen", "Gilead", "Regeneron",
    "Thermo Fisher", "Medtronic", "Boston Scientific", "GE HealthCare",

    # --- TIER 4: RETAIL, LOGISTICS & CONSULTING ---
    "Walmart", "Target", "Costco", "Home Depot", "Lowe's", "Nike",
    "Starbucks", "Procter & Gamble", "P&G", "Coca-Cola", "PepsiCo",
    "FedEx", "UPS", "Deloitte", "PwC", "EY", "KPMG", "Accenture",
    "McKinsey", "Bain", "BCG",

    # --- TIER 5: DEFENSE, AUTO & AEROSPACE ---
    "Boeing", "Lockheed Martin", "Northrop Grumman", "Raytheon", "RTX",
    "General Dynamics", "L3Harris", "Anduril", "SpaceX", "Blue Origin",
    "Ford", "General Motors", "GM", "Rivian", "Waymo", "Zoox", "Cruise",
    "Toyota", "Honda", "BMW",
]


# =============================================================================
# ATS CONFIGURATION — Greenhouse, Lever & Ashby
# =============================================================================
# All three ATS platforms expose fully public, unauthenticated JSON APIs.
# Postings appear here 24–48 hours before propagating to LinkedIn/Indeed.
#
# HOW TO VERIFY OR ADD A SLUG:
#   Greenhouse : https://boards.greenhouse.io/{slug}/jobs       → 200 = valid
#   Lever      : https://jobs.lever.co/{slug}                   → 200 = valid
#   Ashby      : https://jobs.ashbyhq.com/{slug}                → loads = valid
#                API: https://api.ashbyhq.com/posting-api/job-board/{slug}
#
# Slugs that returned persistent 404s have been removed. Add them back only
# after manually confirming the correct slug and ATS platform.

GREENHOUSE_COMPANIES = {
    # Company display name   : Greenhouse board slug
    # Verified working as of March 2026
    "Anthropic":              "anthropic",
    "Airbnb":                 "airbnb",
    "Stripe":                 "stripe",
    "Databricks":             "databricks",
    "Pinterest":              "pinterest",
    "Lyft":                   "lyft",
    "Coinbase":               "coinbase",
    "Robinhood":              "robinhood",
    "Duolingo":               "duolingo",
    "Discord":                "discord",
    "Figma":                  "figma",
    "Brex":                   "brex",
    "Scale AI":               "scaleai",
    "Verkada":                "verkada",
    # Corrected slugs (were 404ing under wrong slug / wrong ATS)
    "Waymo":                  "Waymo",             # capital W required
    "Anduril":                "andurilindustries",  # moved from Lever
}

LEVER_COMPANIES = {
    # Company display name   : Lever posting slug
    # Verified working as of March 2026
    "Zoox":                   "zoox",
    # Add verified slugs here as you confirm them
}

# Ashby is the third major ATS, now used by many AI-first companies
# that previously used Greenhouse or Lever.
# API endpoint: GET https://api.ashbyhq.com/posting-api/job-board/{slug}
# Returns: {"jobPostings": [{"title", "location": {"city","region"}, "jobUrl", ...}]}
ASHBY_COMPANIES = {
    # Company display name   : Ashby org slug
    # Verified working as of March 2026
    "OpenAI":                 "openai",
    "Cohere":                 "cohere",
    "Replit":                 "replit",
    "Notion":                 "notion",
    "Perplexity":             "Perplexity",  # case-sensitive slug
}

# ── ATS Title Filtering ───────────────────────────────────────────────────────
# A role must satisfy BOTH conditions to pass:
#   1. Its title contains at least one DOMAIN keyword  (what the role is)
#   2. Its title contains at least one INTERN marker   (confirms it's an internship)
#
# This prevents "Marketing Intern", "Legal Intern", "HR Intern", etc. from
# slipping through just because "intern" appeared in the old flat keyword list.

ATS_DOMAIN_KEYWORDS = [
    # Core DS / ML
    "data science", "data scientist",
    "machine learning", "ml engineer", "ml ",
    "applied scientist", "applied machine learning", "applied ml",
    # AI / Research
    "artificial intelligence", "ai engineer", "ai infrastructure",
    "research scientist", "research engineer", "algorithm engineer",
    # Quant / Finance
    "quantitative", "quant ",
    "decision science", "risk model", "financial engineer",
    # Emerging AI
    "generative ai", "gen ai", "large language model", "llm",
    "natural language processing", "nlp",
    "computer vision", "deep learning",
    # Infra / Eng
    "mlops", "ml ops", "data engineer",
    # Domain-specific (Bio / Health)
    "biomedical", "computational biology", "imaging ai",
]

ATS_INTERN_MARKERS = [
    "intern", "internship", "co-op", "coop", "co op",
    "summer 2026", "summer2026", "2026",
]

# ── US Location Filtering ─────────────────────────────────────────────────────
# Greenhouse and Lever serve global companies. We only want US-based roles.
# Strategy:
#   ACCEPT if location contains a US state abbreviation, a US state name,
#           or a known US-positive term ("remote", "united states", etc.)
#   REJECT  if location contains a known non-US city or country name
#   ACCEPT  if location is blank/unknown (US company, likely US role — don't
#           over-filter; Module 2 lets you review before acting anyway)

US_STATE_ABBREVIATIONS = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
}

US_POSITIVE_TERMS = {
    "remote", "united states", "usa", "u.s.a", "u.s.", " us ",
    "anywhere", "nationwide", "hybrid",
    # Full state names most likely to appear in location strings
    "california", "new york", "texas", "washington", "illinois",
    "massachusetts", "georgia", "colorado", "florida", "virginia",
    "north carolina", "pennsylvania", "utah", "oregon", "arizona",
    "new jersey", "michigan", "ohio", "minnesota", "indiana",
}

# If ANY of these appear in the location string, reject the role outright.
NON_US_TERMS = {
    "canada", "toronto", "vancouver", "montreal", "ottawa",
    "united kingdom", "uk", "england", "london", "manchester", "edinburgh",
    "ireland", "dublin",
    "germany", "berlin", "munich", "hamburg",
    "france", "paris",
    "netherlands", "amsterdam",
    "sweden", "stockholm",
    "india", "bangalore", "bengaluru", "hyderabad", "mumbai", "delhi", "pune",
    "singapore",
    "australia", "sydney", "melbourne",
    "japan", "tokyo",
    "china", "beijing", "shanghai",
    "brazil", "são paulo",
    "mexico", "mexico city",
    "israel", "tel aviv",
    "switzerland", "zurich",
    "spain", "madrid", "barcelona",
    "poland", "warsaw",
    "czech", "prague",
}


# =============================================================================
# HELPERS
# =============================================================================

def load_fortune_1000(filename="fortune1000.csv") -> set:
    """
    Loads Fortune 1000 companies from the CSV committed to the repo root.
    Returns a set of company name strings.
    Falls back gracefully to an empty set if the file can't be read.
    """
    companies = set()
    try:
        try:
            df = pd.read_csv(filename, encoding="utf-8")
        except UnicodeDecodeError:
            print("⚠️ UTF-8 failed for fortune1000.csv, trying Latin-1...", flush=True)
            df = pd.read_csv(filename, encoding="latin1")

        df.columns = [c.lower().strip() for c in df.columns]

        if "company" in df.columns:
            companies.update(df["company"].dropna().astype(str).tolist())
        elif "name" in df.columns:
            companies.update(df["name"].dropna().astype(str).tolist())

        print(f"✅ Loaded {len(companies)} companies from {filename}.", flush=True)
    except Exception as e:
        print(f"⚠️ Could not load {filename}: {e}", flush=True)
        print("   Continuing with PRIORITY_COMPANIES list only.", flush=True)

    return companies


def get_master_company_list() -> list:
    """Merges the hardcoded priority list with the Fortune 1000 CSV."""
    fortune_list = load_fortune_1000()
    master_list = set(PRIORITY_COMPANIES) | fortune_list
    print(f"✅ Master company list ready: {len(master_list)} companies.", flush=True)
    return list(master_list)


def is_high_quality(job_company: str, master_list: list) -> bool:
    """
    Returns True if job_company fuzzy-matches any entry in master_list.
    Catches variants like 'Walmart Global Tech' matching 'Walmart'.
    Also drops rows where company is NaN/None to prevent downstream type errors.
    """
    # FIX: Explicit NaN/None guard. jobspy occasionally returns NaN company names
    # from partially scraped postings. These caused crashes in the original code.
    if not job_company or not isinstance(job_company, str):
        return False

    job_norm = job_company.lower().replace(".", "").replace(",", "").strip()
    if not job_norm:
        return False

    for safe_company in master_list:
        if not isinstance(safe_company, str):
            continue
        safe_norm = safe_company.lower().replace(".", "").replace(",", "").strip()
        if safe_norm and (safe_norm in job_norm or job_norm in safe_norm):
            return True

    return False


# =============================================================================
# SUPABASE WRITER
# =============================================================================

def write_to_supabase(filtered_jobs: list) -> None:
    """
    Upserts filtered jobs into the Supabase pending_jobs table.

    Uses SUPABASE_URL and SUPABASE_SERVICE_KEY from environment variables.
    The service key bypasses Row Level Security so the GitHub Actions runner
    can write without needing user auth.

    Uses upsert with ignore_duplicates=True on the (company, title) unique
    constraint so re-runs don't overwrite a user's status changes from the
    Streamlit dashboard (e.g., a role they already marked as 'targeted').
    """
    if create_client is None:
        print("⚠️ Supabase unavailable — skipping DB write.", flush=True)
        return

    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")

    if not supabase_url or not supabase_key:
        print("⚠️ SUPABASE_URL or SUPABASE_SERVICE_KEY not set — skipping DB write.", flush=True)
        return

    try:
        client = create_client(supabase_url, supabase_key)

        records = []
        today = date.today().isoformat()

        for job in filtered_jobs:
            company = str(job.get("company") or "Unknown").strip()
            is_priority = any(
                p.lower() in company.lower() for p in PRIORITY_COMPANIES
            )

            # Preserve the description field for Module 3's NLP extraction.
            # jobspy returns this when available — we must not drop it.
            description = str(job.get("description") or "").strip()

            records.append({
                "scraped_date": today,
                "title":        str(job.get("title") or "Unknown").strip(),
                "company":      company,
                "location":     str(job.get("location") or "Unknown").strip(),
                "site":         str(job.get("site") or "Unknown").strip(),
                "job_url":      str(job.get("job_url") or job.get("job_url_direct") or "").strip(),
                "description":  description,
                "is_priority":  is_priority,
                "source":       "scraper",
                "status":       "pending",
            })

        if not records:
            print("⚠️ No records to write to Supabase.", flush=True)
            return

        # ignore_duplicates=True: if (company, title) already exists in the table,
        # skip silently. This preserves any status changes the user made in the dashboard.
        client.table("pending_jobs").upsert(
            records,
            on_conflict="company,title",
            ignore_duplicates=True,
        ).execute()

        print(f"✅ Wrote {len(records)} jobs to Supabase pending_jobs table.", flush=True)

    except Exception as e:
        # Non-fatal: a DB write failure should not prevent the email from sending.
        print(f"⚠️ Supabase write failed: {e}", flush=True)


# =============================================================================
# EMAIL SENDER
# =============================================================================

def send_email(jobs: list) -> None:
    """
    Sends an HTML digest email of today's filtered jobs.
    Priority companies are highlighted in gold; Fortune 1000 matches in green.
    Jobs are sorted alphabetically by company name.
    """
    sender_email    = os.environ.get("EMAIL_USER")
    sender_password = os.environ.get("EMAIL_PASS")
    # FIX: Receiver email is now pulled from an environment secret instead of
    # being hardcoded. Falls back to the original address so existing runs
    # don't break if the secret hasn't been added yet.
    receiver_email  = os.environ.get("EMAIL_RECEIVER", "rishpotti@gmail.com")

    if not sender_email or not sender_password:
        print("❌ EMAIL_USER or EMAIL_PASS not set — skipping email.", flush=True)
        return

    today_str = date.today().strftime("%B %d, %Y")
    msg = MIMEMultipart()
    msg["Subject"] = f"🚀 Daily Job Digest ({today_str}): {len(jobs)} Roles Found"
    msg["From"]    = sender_email
    msg["To"]      = receiver_email

    # ── Build HTML table ──────────────────────────────────────────────────────
    html_content = f"""
    <html>
    <body style="font-family: Arial, sans-serif; font-size: 14px; color: #333;">
    <h2>📋 Daily Internship Digest — {today_str}</h2>
    <p>
      <strong>{len(jobs)} unique roles</strong> matched your company list today.
      <span style="color: #856404; font-weight: bold;">🟡 Gold = Priority company.</span>
      <span style="color: #0f5132;">🟢 Green = Fortune 1000 match.</span><br>
      Log into the <strong>Job Hunter Dashboard</strong> to target roles for enrichment.
    </p>
    <table border="1" cellpadding="6" cellspacing="0"
           style="border-collapse: collapse; width: 100%; font-size: 13px;">
      <tr style="background-color: #f2f2f2; text-align: left;">
        <th>Company</th>
        <th>Role</th>
        <th>Location(s)</th>
        <th>Source</th>
        <th>Link</th>
      </tr>
    """

    # Sort alphabetically by company for easy scanning
    jobs_sorted = sorted(jobs, key=lambda x: str(x.get("company", "")).lower())

    for job in jobs_sorted:
        company = str(job.get("company") or "Unknown")

        if any(p.lower() in company.lower() for p in PRIORITY_COMPANIES):
            row_style = "background-color: #fff3cd; font-weight: bold;"   # Gold
        else:
            row_style = "background-color: #e6fffa;"                      # Green

        link = job.get("job_url") or job.get("job_url_direct") or "#"
        apply_cell = f'<a href="{link}">Apply</a>' if link != "#" else "N/A"

        html_content += f"""
      <tr style="{row_style}">
        <td>{company}</td>
        <td>{job.get("title", "Unknown")}</td>
        <td>{job.get("location", "Unknown")}</td>
        <td>{job.get("site", "Unknown")}</td>
        <td>{apply_cell}</td>
      </tr>"""

    html_content += """
    </table>
    </body>
    </html>
    """

    msg.attach(MIMEText(html_content, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, receiver_email, msg.as_string())
        print(f"✅ Email sent to {receiver_email}.", flush=True)
    except Exception as e:
        print(f"❌ Email send failed: {e}", flush=True)


# =============================================================================
# ATS SCRAPERS — Greenhouse & Lever
# =============================================================================

def _title_is_relevant(title: str) -> bool:
    """
    Returns True only if the title satisfies BOTH conditions:
      1. Contains a domain keyword — confirming the role is in DS/ML/Quant/AI
      2. Contains an intern marker — confirming it's an internship, not FTE

    A title like "Machine Learning Intern" passes (domain ✓, intern ✓).
    A title like "Marketing Intern" fails  (no domain ✗).
    A title like "Machine Learning Engineer" fails (no intern marker ✗).
    """
    t = title.lower()
    has_domain = any(kw in t for kw in ATS_DOMAIN_KEYWORDS)
    has_intern = any(m in t for m in ATS_INTERN_MARKERS)
    return has_domain and has_intern


def _is_us_location(location: str) -> bool:
    """
    Returns True if the location string is consistent with a US-based role.

    Logic (checked in order):
      1. Blank / unknown → True  (US company; include and let the dashboard filter)
      2. Contains a non-US term → False
      3. Contains a US state abbreviation as a standalone token → True
      4. Contains a US positive term → True
      5. Default → True  (unknown format; err on the side of inclusion)
    """
    if not location or location.strip().lower() in ("unknown", "none", ""):
        return True

    loc = location.lower()

    # Hard reject on any known non-US geography
    if any(term in loc for term in NON_US_TERMS):
        return False

    # Accept on any US positive indicator
    if any(term in loc for term in US_POSITIVE_TERMS):
        return True

    # Check for state abbreviations as standalone tokens
    # e.g. "San Francisco, CA" → tokens include "CA"
    tokens = {t.strip("(),. ").upper() for t in location.replace(",", " ").split()}
    if tokens & US_STATE_ABBREVIATIONS:
        return True

    # Unknown format — include rather than over-filter
    return True


def scrape_greenhouse(timeout: int = 10) -> list:
    """
    Queries the public Greenhouse job board API for every company in
    GREENHOUSE_COMPANIES and returns matching internship roles as a list
    of normalized job dicts (same shape as jobspy output).

    Greenhouse endpoint (no auth required):
      GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs
      Returns: { "jobs": [ { "id", "title", "location": {"name"}, "absolute_url" } ] }
    """
    if requests is None:
        print("⚠️ Requests not available — skipping Greenhouse scrape.", flush=True)
        return []

    results = []
    print(f"\n🌿 Scraping Greenhouse for {len(GREENHOUSE_COMPANIES)} companies...", flush=True)

    for company_name, slug in GREENHOUSE_COMPANIES.items():
        try:
            url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
            resp = requests.get(url, timeout=timeout)

            if resp.status_code == 404:
                print(f"  ⚠️  {company_name}: slug '{slug}' not found (404) — update GREENHOUSE_COMPANIES.", flush=True)
                continue
            if resp.status_code != 200:
                print(f"  ⚠️  {company_name}: HTTP {resp.status_code}", flush=True)
                continue

            jobs = resp.json().get("jobs", [])
            matched = 0

            for job in jobs:
                title = str(job.get("title", ""))
                if not _title_is_relevant(title):
                    continue

                location = job.get("location", {})
                loc_str = location.get("name", "Unknown") if isinstance(location, dict) else "Unknown"

                if not _is_us_location(loc_str):
                    continue

                results.append({
                    "title":       title,
                    "company":     company_name,
                    "location":    loc_str,
                    "site":        "greenhouse",
                    "job_url":     job.get("absolute_url", ""),
                    "description": "",   # Full description requires a second per-job API call;
                                         # left blank here and fetched by Module 3 during enrichment.
                })
                matched += 1

            if matched:
                print(f"  ✅ {company_name}: {matched} matching role(s).", flush=True)

        except requests.exceptions.Timeout:
            print(f"  ⚠️  {company_name}: request timed out.", flush=True)
        except Exception as e:
            print(f"  ❌ {company_name}: unexpected error — {e}", flush=True)

    print(f"🌿 Greenhouse total: {len(results)} roles.", flush=True)
    return results


def scrape_lever(timeout: int = 10) -> list:
    """
    Queries the public Lever job board API for every company in
    LEVER_COMPANIES and returns matching internship roles as a list
    of normalized job dicts (same shape as jobspy output).

    Lever endpoint (no auth required):
      GET https://api.lever.co/v0/postings/{slug}?mode=json
      Returns: [ { "text" (title), "categories": {"location"}, "hostedUrl", "descriptionPlain" } ]
    """
    if requests is None:
        print("⚠️ Requests not available — skipping Lever scrape.", flush=True)
        return []

    results = []
    print(f"\n🔧 Scraping Lever for {len(LEVER_COMPANIES)} companies...", flush=True)

    for company_name, slug in LEVER_COMPANIES.items():
        try:
            url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
            resp = requests.get(url, timeout=timeout)

            if resp.status_code == 404:
                print(f"  ⚠️  {company_name}: slug '{slug}' not found (404) — update LEVER_COMPANIES.", flush=True)
                continue
            if resp.status_code != 200:
                print(f"  ⚠️  {company_name}: HTTP {resp.status_code}", flush=True)
                continue

            jobs = resp.json()
            if not isinstance(jobs, list):
                print(f"  ⚠️  {company_name}: unexpected response format.", flush=True)
                continue

            matched = 0

            for job in jobs:
                title = str(job.get("text", ""))
                if not _title_is_relevant(title):
                    continue

                categories = job.get("categories", {})
                loc_str = categories.get("location", "Unknown") if isinstance(categories, dict) else "Unknown"

                if not _is_us_location(loc_str):
                    continue

                # Lever provides plain-text description inline — pass it through
                # so Module 3 has text to extract from without a second fetch.
                description = str(job.get("descriptionPlain", "")).strip()

                results.append({
                    "title":       title,
                    "company":     company_name,
                    "location":    loc_str or "Unknown",
                    "site":        "lever",
                    "job_url":     job.get("hostedUrl", ""),
                    "description": description,
                })
                matched += 1

            if matched:
                print(f"  ✅ {company_name}: {matched} matching role(s).", flush=True)

        except requests.exceptions.Timeout:
            print(f"  ⚠️  {company_name}: request timed out.", flush=True)
        except Exception as e:
            print(f"  ❌ {company_name}: unexpected error — {e}", flush=True)

    print(f"🔧 Lever total: {len(results)} roles.", flush=True)
    return results


def scrape_ashby(timeout: int = 10) -> list:
    """
    Queries the public Ashby job board API for every company in ASHBY_COMPANIES.
    Returns matching internship roles as normalized job dicts.

    Ashby API endpoint (no auth required):
      GET https://api.ashbyhq.com/posting-api/job-board/{slug}
      Returns: {"jobPostings": [{"title", "location": {"city","region"}, "jobUrl",
                                  "descriptionPlain", "isListed", ...}]}

    Only returns listings where isListed=true (publicly visible roles).
    """
    if requests is None:
        print("⚠️ Requests not available — skipping Ashby scrape.", flush=True)
        return []

    results = []
    print(f"\n🔷 Scraping Ashby for {len(ASHBY_COMPANIES)} companies...", flush=True)

    for company_name, slug in ASHBY_COMPANIES.items():
        try:
            url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
            resp = requests.get(url, timeout=timeout)

            if resp.status_code == 404:
                print(f"  ⚠️  {company_name}: slug \'{slug}\' not found (404) — update ASHBY_COMPANIES.", flush=True)
                continue
            if resp.status_code != 200:
                print(f"  ⚠️  {company_name}: HTTP {resp.status_code}", flush=True)
                continue

            postings = resp.json().get("jobPostings", [])
            matched  = 0

            for job in postings:
                # Skip unlisted / internal roles
                if not job.get("isListed", True):
                    continue

                title = str(job.get("title", ""))
                if not _title_is_relevant(title):
                    continue

                # Ashby location is a nested object: {"city": "...", "region": "..."}
                loc_obj = job.get("location") or {}
                if isinstance(loc_obj, dict):
                    city   = loc_obj.get("city", "")
                    region = loc_obj.get("region", "")
                    loc_str = ", ".join(filter(None, [city, region])) or "Unknown"
                else:
                    loc_str = str(loc_obj) or "Unknown"

                if not _is_us_location(loc_str):
                    continue

                description = str(job.get("descriptionPlain", "")).strip()

                results.append({
                    "title":       title,
                    "company":     company_name,
                    "location":    loc_str,
                    "site":        "ashby",
                    "job_url":     job.get("jobUrl", ""),
                    "description": description,
                })
                matched += 1

            if matched:
                print(f"  ✅ {company_name}: {matched} matching role(s).", flush=True)

        except requests.exceptions.Timeout:
            print(f"  ⚠️  {company_name}: request timed out.", flush=True)
        except Exception as e:
            print(f"  ❌ {company_name}: unexpected error — {e}", flush=True)

    print(f"🔷 Ashby total: {len(results)} roles.", flush=True)
    return results


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("Loading company lists...", flush=True)
    master_safe_list = get_master_company_list()

    all_jobs = []

    # Split keywords into chunks of 4 to stay within search engine query limits
    chunk_size = 4
    keyword_chunks = [KEYWORDS[i:i + chunk_size] for i in range(0, len(KEYWORDS), chunk_size)]

    print(f"Scraping jobs in {len(keyword_chunks)} batches...", flush=True)

    for i, batch in enumerate(keyword_chunks):
        print(f"  - Batch {i+1}/{len(keyword_chunks)}: {batch}", flush=True)

        # Randomized sleep between batches to avoid Cloudflare/Akamai 403 blocks.
        # First batch runs immediately; all subsequent batches wait.
        if i > 0:
            sleep_time = random.uniform(15, 35)
            print(f"    ...sleeping {int(sleep_time)}s to avoid WAF detection...", flush=True)
            time.sleep(sleep_time)

        try:
            search_query = " OR ".join(batch)

            jobs = scrape_jobs(
                # FIX: Removed glassdoor and zip_recruiter. Both return hard
                # WAF/400 blocks on every single batch (confirmed in run logs)
                # and contribute zero results while adding noise. LinkedIn,
                # Indeed, and Google Jobs are the three reliable sources.
                site_name=["linkedin", "indeed", "google"],
                search_term=search_query,
                location="United States",
                results_wanted=50,
                hours_old=24,
            )

            if jobs is not None and not jobs.empty:
                print(f"    ✅ Got {len(jobs)} results.", flush=True)
                all_jobs.extend(jobs.to_dict("records"))
            else:
                print(f"    ⚠️ No results returned for batch {i+1}.", flush=True)

        except Exception as e:
            print(f"    ❌ Error in batch {i+1}: {e}", flush=True)
            continue

    print(f"\nRaw results from jobspy: {len(all_jobs)}", flush=True)

    # ── ATS scrapes (Greenhouse + Lever + Ashby) ─────────────────────────────
    # Lightweight JSON API calls — no sleep needed between them.
    greenhouse_jobs = scrape_greenhouse()
    lever_jobs      = scrape_lever()
    ashby_jobs      = scrape_ashby()
    all_jobs.extend(greenhouse_jobs)
    all_jobs.extend(lever_jobs)
    all_jobs.extend(ashby_jobs)

    print(f"Raw results total (jobspy + ATS): {len(all_jobs)}", flush=True)

    # ── Deduplication: condense same role across multiple cities ──────────────
    print("🧹 Condensing duplicates...", flush=True)
    condensed_jobs: dict = {}

    for job in all_jobs:
        company = str(job.get("company") or "Unknown").strip()
        title   = str(job.get("title")   or "Unknown").strip()

        # Skip rows with no company name — they will always fail the quality filter
        # and cause type errors if they slip through.
        if company in ("Unknown", "None", "", "nan"):
            continue

        key = (company.lower(), title.lower())
        loc = str(job.get("location") or "Unknown").strip()
        if loc in ("None", "nan", ""):
            loc = "Unknown"

        if key not in condensed_jobs:
            condensed_jobs[key] = job.copy()
            condensed_jobs[key]["location"] = loc
        else:
            # Same company+role seen in a different city: append the location.
            existing_locs = condensed_jobs[key].get("location", "")
            if loc and loc != "Unknown" and loc not in existing_locs:
                if not existing_locs or existing_locs == "Unknown":
                    condensed_jobs[key]["location"] = loc
                else:
                    condensed_jobs[key]["location"] = f"{existing_locs} | {loc}"

    unique_condensed_list = list(condensed_jobs.values())
    print(f"After dedup: {len(unique_condensed_list)} unique roles.", flush=True)

    # ── Quality filter ────────────────────────────────────────────────────────
    filtered_jobs = [
        j for j in unique_condensed_list
        if is_high_quality(j.get("company"), master_safe_list)
    ]
    print(f"After company filter: {len(filtered_jobs)} matches.", flush=True)

    # ── Output: Supabase write + email ────────────────────────────────────────
    if filtered_jobs:
        # Write to DB first so the dashboard has data even if email fails
        write_to_supabase(filtered_jobs)
        send_email(filtered_jobs)
        print(f"\n✅ Done. {len(filtered_jobs)} jobs written to Supabase and emailed.", flush=True)
    else:
        print("\n⚠️ No matches found in the master company list today.", flush=True)
        print("   Check that fortune1000.csv is in the repo root and the scraper returned results.", flush=True)


if __name__ == "__main__":
    main()