# =============================================================================
# job_bot.py  —  Module 1: Scraper Engine
# Runs daily via GitHub Actions. Scrapes job boards + ATS APIs, deduplicates,
# filters by master company list, drops roles already sent in a previous digest,
# writes the new ones to Supabase, and emails an HTML digest.
# =============================================================================

import html
import os
import random
import re
import smtplib
import time
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pandas as pd
import requests
from jobspy import scrape_jobs

print("---------- JOB BOT STARTING ----------", flush=True)

try:
    from supabase import create_client
except Exception as e:
    # Non-fatal: without Supabase we still email, but cannot dedup against history.
    print(f"⚠️ Supabase failed to import — no DB write / history dedup. Error: {e}", flush=True)
    create_client = None


# =============================================================================
# CONFIGURATION
# =============================================================================

# How far back jobspy searches. Wider than the daily schedule so a failed or
# skipped run does not lose postings; history dedup removes the overlap.
HOURS_OLD = 72

KEYWORDS = [
    # --- TIER 1: Core AI / ML Engineering ---
    "Machine Learning Engineer",
    "ML Engineer",
    "AI Engineer",
    "Artificial Intelligence Engineer",
    "Applied Scientist",
    "Applied Machine Learning Engineer",
    "Research Scientist",
    "Research Engineer",
    "Algorithm Engineer",

    # --- TIER 2: Data Science ---
    "Data Scientist",
    "Data Science Analyst",
    "Quantitative Researcher",
    "Quantitative Analyst",
    "Decision Scientist",
    "Risk Modeling Analyst",
    "Financial Engineer",

    # --- TIER 3: Generative AI / LLMs ---
    "Generative AI Engineer",
    "LLM Engineer",
    "NLP Engineer",
    "Natural Language Processing Engineer",
    "Computer Vision Engineer",
    "Deep Learning Engineer",

    # --- TIER 4: Software Engineering (AI/ML-adjacent) ---
    "Software Engineer Machine Learning",
    "Software Engineer AI",
    "Software Engineer Data",
    "Data Engineer",
    "MLOps Engineer",
    "AI Infrastructure Engineer",

    # --- TIER 5: Domain Specific (Bio/Health) ---
    "Biomedical Data Scientist",
    "Computational Biologist",
    "AI Scientist",
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

GREENHOUSE_COMPANIES = {
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
    "Waymo":                  "Waymo",             # capital W required
    "Anduril":                "andurilindustries",
}

LEVER_COMPANIES = {
    "Zoox":                   "zoox",
}

ASHBY_COMPANIES = {
    "OpenAI":                 "openai",
    "Cohere":                 "cohere",
    "Replit":                 "replit",
    "Notion":                 "notion",
    "Perplexity":             "Perplexity",  # case-sensitive slug
}


# ── Title filtering ──────────────────────────────────────────────────────────
# All matching is whole-word, so "intern" does not hit "Internal" and "iv"
# does not hit "Generative".

# ATS boards return every posting, so they are pre-filtered to the domain.
# Prefix match (leading word boundary only) so "data engineer" also catches
# "Data Engineering".
DOMAIN_KEYWORDS = [
    "data science", "data scientist",
    "machine learning", "ml engineer", "ml",
    "applied scientist", "applied machine learning", "applied ml",
    "artificial intelligence", "ai engineer", "ai infrastructure",
    "research scientist", "research engineer", "algorithm engineer",
    "quantitative", "quant",
    "decision science", "risk model", "financial engineer",
    "generative ai", "gen ai", "large language model", "llm",
    "natural language processing", "nlp",
    "computer vision", "deep learning",
    "mlops", "ml ops", "data engineer",
    "biomedical", "computational biology", "imaging ai",
]

# Titles that disqualify a role from any source: PhD-only, internships, and
# non-entry-level seniority.
EXCLUDE_TITLE_TERMS = [
    "phd", "ph.d", "doctorate", "doctoral",
    "intern", "internship", "co-op", "coop",
    "senior", "sr", "staff", "principal", "lead", "leader",
    "manager", "management", "director", "head of", "chief",
    "president", "vp",
    "ii", "iii", "iv",
    "expert", "fellow", "architect",
]


def _word_regex(terms, suffix_boundary=True) -> re.Pattern:
    """
    Compiles terms into one case-insensitive whole-word alternation.
    Lookarounds (not \\b) so terms starting/ending in punctuation still match.
    """
    body = "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))
    return re.compile(rf"(?<!\w)(?:{body})" + (r"(?!\w)" if suffix_boundary else ""), re.IGNORECASE)


DOMAIN_RE  = _word_regex(DOMAIN_KEYWORDS, suffix_boundary=False)
EXCLUDE_RE = _word_regex(EXCLUDE_TITLE_TERMS)

# ── Entry-level experience filtering ──────────────────────────────────────────
MAX_YEARS_EXPERIENCE   = 3     # Reject roles requiring more than this many years
KEEP_IF_NO_REQUIREMENT = True  # Keep roles that state no experience requirement

YEARS_PATTERNS = [re.compile(p) for p in (
    r'(\d+)\+?\s*-\s*\d+\s*years?',          # "3-5 years" → 3
    r'(\d+)\+\s*years?',                      # "5+ years"  → 5
    r'minimum\s+of\s+(\d+)\s*years?',         # "minimum of 4 years"
    r'at\s+least\s+(\d+)\s*years?',           # "at least 2 years"
    r'(\d+)\s*years?\s+of\s+(?:relevant\s+)?(?:professional\s+)?experience',
    r'(\d+)\s*\+?\s*yrs?',                    # "5+ yrs"
)]
# "must be at least 18 years of age" is not an experience requirement
AGE_RE = re.compile(r'\d+\s*years?\s*(?:of\s+age|old)')

# ── US location filtering ─────────────────────────────────────────────────────
# Roles are kept unless the location names a known non-US place. Blank or
# unrecognized locations are kept (better to over-include; the dashboard lets
# you reject). Whole-word match so "india" ≠ "Indiana", "uk" ≠ "Milwaukee".
NON_US_TERMS = [
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
]
NON_US_RE = _word_regex(NON_US_TERMS)


# =============================================================================
# HELPERS
# =============================================================================

def _normalize_company(name: str) -> str:
    return re.sub(r"\s+", " ", name.lower().replace(".", "").replace(",", "")).strip()


PRIORITY_RE = _word_regex([_normalize_company(p) for p in PRIORITY_COMPANIES])


def is_priority(company: str) -> bool:
    return bool(PRIORITY_RE.search(_normalize_company(company)))


def load_fortune_1000(filename: str = "fortune1000.csv") -> set:
    """Loads company names from the Fortune 1000 CSV; empty set on failure."""
    try:
        try:
            df = pd.read_csv(filename, encoding="utf-8")
        except UnicodeDecodeError:
            df = pd.read_csv(filename, encoding="latin1")
        df.columns = [c.lower().strip() for c in df.columns]
        col = "company" if "company" in df.columns else "name"
        companies = set(df[col].dropna().astype(str))
        print(f"✅ Loaded {len(companies)} companies from {filename}.", flush=True)
        return companies
    except Exception as e:
        print(f"⚠️ Could not load {filename}: {e} — using PRIORITY_COMPANIES only.", flush=True)
        return set()


class CompanyMatcher:
    """
    Whole-word company matching against the master list, built once.

    A job's company matches if either:
      - a master name appears as whole words inside it
        ("Walmart Global Tech" ⊇ "Walmart"), or
      - it is a leading word-prefix of a master name
        ("Capital One" ⊆ "Capital One Financial").
    """

    def __init__(self, names):
        normalized = {n for n in (_normalize_company(x) for x in names) if n}
        self._contains_re = _word_regex(normalized)
        self._prefixes = set()
        for n in normalized:
            words = n.split()
            for i in range(1, len(words) + 1):
                self._prefixes.add(" ".join(words[:i]))
        print(f"✅ Master company list ready: {len(normalized)} companies.", flush=True)

    def matches(self, company) -> bool:
        if not isinstance(company, str):
            return False
        norm = _normalize_company(company)
        return bool(norm) and (norm in self._prefixes or bool(self._contains_re.search(norm)))


def _title_excluded(title: str) -> bool:
    return bool(EXCLUDE_RE.search(title))


def _is_us_location(location: str) -> bool:
    loc = (location or "").lower().replace("new mexico", "")
    return not NON_US_RE.search(loc)


def _parse_min_years_required(text: str) -> int | None:
    """
    Returns the smallest stated years-of-experience requirement in the text
    (the most lenient reading, e.g. "3-5 years" → 3), or None if none stated.
    """
    if not text:
        return None
    t = AGE_RE.sub("", text.lower())
    found = [
        int(m.group(1))
        for pat in YEARS_PATTERNS
        for m in pat.finditer(t)
        if 0 <= int(m.group(1)) <= 20
    ]
    return min(found) if found else None


def _is_entry_level(title: str, description: str) -> bool:
    required = _parse_min_years_required(f"{title} {description}")
    if required is None:
        return KEEP_IF_NO_REQUIREMENT
    return required <= MAX_YEARS_EXPERIENCE


def _html_to_text(raw: str) -> str:
    """Greenhouse 'content' is entity-escaped HTML; reduce it to plain text."""
    text = html.unescape(raw or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


# =============================================================================
# SCRAPERS
# =============================================================================

def scrape_jobspy() -> list:
    """LinkedIn / Indeed / Google Jobs via jobspy, in keyword batches."""
    all_jobs = []
    chunk_size = 4
    batches = [KEYWORDS[i:i + chunk_size] for i in range(0, len(KEYWORDS), chunk_size)]
    print(f"Scraping jobspy in {len(batches)} batches...", flush=True)

    for i, batch in enumerate(batches):
        print(f"  - Batch {i+1}/{len(batches)}: {batch}", flush=True)
        if i > 0:
            # Randomized sleep between batches to avoid WAF 403 blocks.
            sleep_time = random.uniform(15, 35)
            print(f"    ...sleeping {int(sleep_time)}s...", flush=True)
            time.sleep(sleep_time)

        try:
            jobs = scrape_jobs(
                # glassdoor / zip_recruiter removed: they WAF-block every request.
                site_name=["linkedin", "indeed", "google"],
                search_term=" OR ".join(batch),
                location="United States",
                results_wanted=50,
                hours_old=HOURS_OLD,
            )
        except Exception as e:
            print(f"    ❌ Error in batch {i+1}: {e}", flush=True)
            continue

        if jobs is None or jobs.empty:
            print(f"    ⚠️ No results for batch {i+1}.", flush=True)
            continue

        # Convert NaN → None so `x or fallback` works on missing fields.
        jobs = jobs.astype(object).where(jobs.notna(), None)
        print(f"    ✅ Got {len(jobs)} results.", flush=True)
        all_jobs.extend(jobs.to_dict("records"))

    print(f"jobspy total: {len(all_jobs)}", flush=True)
    return all_jobs


def _parse_greenhouse(data) -> list:
    return [
        (j.get("title"), (j.get("location") or {}).get("name"),
         j.get("absolute_url"), _html_to_text(j.get("content", "")))
        for j in data.get("jobs", [])
    ]


def _parse_lever(data) -> list:
    if not isinstance(data, list):
        raise ValueError("unexpected response format")
    return [
        (j.get("text"), (j.get("categories") or {}).get("location"),
         j.get("hostedUrl"), j.get("descriptionPlain"))
        for j in data
    ]


def _parse_ashby(data) -> list:
    out = []
    for j in data.get("jobPostings", []):
        if not j.get("isListed", True):
            continue
        loc = j.get("locationName") or ""
        if not loc:
            loc_obj = j.get("location") or {}
            if isinstance(loc_obj, dict):
                city = loc_obj.get("locationName") or loc_obj.get("city", "")
                loc = ", ".join(filter(None, [city, loc_obj.get("region", "")]))
            elif isinstance(loc_obj, str):
                loc = loc_obj
        out.append((j.get("title"), loc, j.get("jobUrl") or j.get("applyUrl"),
                    j.get("descriptionPlain")))
    return out


ATS_SOURCES = [
    # (site label, companies, URL template, parser)
    ("greenhouse", GREENHOUSE_COMPANIES,
     "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true", _parse_greenhouse),
    ("lever", LEVER_COMPANIES,
     "https://api.lever.co/v0/postings/{slug}?mode=json", _parse_lever),
    ("ashby", ASHBY_COMPANIES,
     "https://api.ashbyhq.com/posting-api/job-board/{slug}", _parse_ashby),
]


def scrape_ats(site: str, companies: dict, url_template: str, parse, timeout: int = 15) -> list:
    """
    Queries one ATS's public job-board API for each company and returns
    domain-relevant, US-located postings in the same shape as jobspy rows.
    """
    results = []
    print(f"\n🔎 Scraping {site} for {len(companies)} companies...", flush=True)

    for company, slug in companies.items():
        try:
            resp = requests.get(url_template.format(slug=slug), timeout=timeout)
            if resp.status_code != 200:
                print(f"  ⚠️  {company}: HTTP {resp.status_code} for slug '{slug}'", flush=True)
                continue
            postings = parse(resp.json())
        except Exception as e:
            print(f"  ❌ {company}: {e}", flush=True)
            continue

        matched = 0
        for title, loc, url, desc in postings:
            title = str(title or "")
            loc = str(loc or "").strip() or "Unknown"
            if not DOMAIN_RE.search(title) or not _is_us_location(loc):
                continue
            results.append({
                "title":       title,
                "company":     company,
                "location":    loc,
                "site":        site,
                "job_url":     url or "",
                "description": str(desc or "").strip(),
            })
            matched += 1
        print(f"  → {company}: {matched}/{len(postings)} postings matched.", flush=True)

    print(f"{site} total: {len(results)} roles.", flush=True)
    return results


# =============================================================================
# DEDUP + FILTER
# =============================================================================

def _job_key(company: str, title: str) -> tuple:
    return (company.strip().lower(), title.strip().lower())


def condense_jobs(all_jobs: list) -> list:
    """Merges the same company+title seen in multiple cities/sources into one row."""
    condensed: dict = {}
    for job in all_jobs:
        company = str(job.get("company") or "").strip()
        title   = str(job.get("title") or "").strip()
        if not company or not title:
            continue

        loc = str(job.get("location") or "").strip() or "Unknown"
        key = _job_key(company, title)

        if key not in condensed:
            row = dict(job, company=company, title=title)
            row["job_url"] = str(job.get("job_url") or job.get("job_url_direct") or "").strip()
            row["_locations"] = [] if loc == "Unknown" else [loc]
            condensed[key] = row
        else:
            row = condensed[key]
            if loc != "Unknown" and loc not in row["_locations"]:
                row["_locations"].append(loc)
            # Prefer a source that came with a description.
            if not row.get("description") and job.get("description"):
                row["description"] = job["description"]

    for row in condensed.values():
        row["location"] = " | ".join(row.pop("_locations")) or "Unknown"
    return list(condensed.values())


def filter_jobs(jobs: list, matcher: CompanyMatcher) -> list:
    """Company quality → title exclusion → years-of-experience."""
    kept = []
    n_company = n_title = n_exp = 0
    for j in jobs:
        if not matcher.matches(j["company"]):
            n_company += 1
        elif _title_excluded(j["title"]):
            n_title += 1
        elif not _is_entry_level(j["title"], str(j.get("description") or "")):
            n_exp += 1
        else:
            kept.append(j)
    print(
        f"After filters: {len(kept)} matches (excluded — company-miss: {n_company}, "
        f"title/seniority: {n_title}, experience: {n_exp}).",
        flush=True,
    )
    return kept


# =============================================================================
# SUPABASE — history dedup + write
# =============================================================================

def get_supabase():
    if create_client is None:
        return None
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        print("⚠️ SUPABASE_URL / SUPABASE_SERVICE_KEY not set — no DB write / history dedup.", flush=True)
        return None
    try:
        return create_client(url, key)
    except Exception as e:
        print(f"⚠️ Supabase client failed: {e}", flush=True)
        return None


def fetch_seen(client) -> tuple[set, set] | None:
    """
    Returns (seen company+title keys, seen job URLs) for every job ever written
    to pending_jobs — i.e. everything already included in a previous digest,
    plus manual and rejected entries. Paginates past Supabase's 1000-row cap.
    Returns None if the lookup fails.
    """
    seen_keys, seen_urls = set(), set()
    page = 1000
    try:
        start = 0
        while True:
            rows = (
                client.table("pending_jobs")
                .select("company,title,job_url")
                .range(start, start + page - 1)
                .execute()
                .data or []
            )
            for r in rows:
                seen_keys.add(_job_key(r.get("company") or "", r.get("title") or ""))
                if r.get("job_url"):
                    seen_urls.add(r["job_url"].strip())
            if len(rows) < page:
                break
            start += page
    except Exception as e:
        print(f"⚠️ Could not load job history: {e}", flush=True)
        return None
    print(f"✅ Loaded {len(seen_keys)} previously seen jobs from Supabase.", flush=True)
    return seen_keys, seen_urls


def drop_seen(jobs: list, seen: tuple[set, set]) -> list:
    seen_keys, seen_urls = seen
    new = [
        j for j in jobs
        if _job_key(j["company"], j["title"]) not in seen_keys
        and (not j["job_url"] or j["job_url"] not in seen_urls)
    ]
    print(f"After history dedup: {len(new)} new roles ({len(jobs) - len(new)} already sent).", flush=True)
    return new


def write_to_supabase(client, jobs: list) -> None:
    """
    Upserts jobs into pending_jobs. ignore_duplicates on (company, title)
    preserves status changes made in the dashboard.
    """
    today = date.today().isoformat()
    records = [{
        "scraped_date": today,
        "title":        j["title"],
        "company":      j["company"],
        "location":     j["location"],
        "site":         str(j.get("site") or "Unknown"),
        "job_url":      j["job_url"],
        "description":  str(j.get("description") or "").strip(),
        "is_priority":  is_priority(j["company"]),
        "source":       "scraper",
        "status":       "pending",
    } for j in jobs]

    try:
        client.table("pending_jobs").upsert(
            records, on_conflict="company,title", ignore_duplicates=True,
        ).execute()
        print(f"✅ Wrote {len(records)} jobs to Supabase.", flush=True)
    except Exception as e:
        print(f"⚠️ Supabase write failed (these jobs may be re-sent tomorrow): {e}", flush=True)


# =============================================================================
# EMAIL
# =============================================================================

def send_email(jobs: list) -> None:
    """HTML digest; priority companies in gold, Fortune 1000 matches in green."""
    sender_email    = os.environ.get("EMAIL_USER")
    sender_password = os.environ.get("EMAIL_PASS")
    receiver_email  = os.environ.get("EMAIL_RECEIVER", "rishpotti@gmail.com")

    if not sender_email or not sender_password:
        print("❌ EMAIL_USER or EMAIL_PASS not set — skipping email.", flush=True)
        return

    esc = lambda v: html.escape(str(v or "Unknown"))
    today_str = date.today().strftime("%B %d, %Y")

    rows = []
    for job in sorted(jobs, key=lambda x: x["company"].lower()):
        style = ("background-color: #fff3cd; font-weight: bold;" if is_priority(job["company"])
                 else "background-color: #e6fffa;")
        link = job["job_url"]
        apply_cell = f'<a href="{html.escape(link, quote=True)}">Apply</a>' if link else "N/A"
        rows.append(
            f'<tr style="{style}"><td>{esc(job["company"])}</td><td>{esc(job["title"])}</td>'
            f'<td>{esc(job["location"])}</td><td>{esc(job.get("site"))}</td><td>{apply_cell}</td></tr>'
        )

    html_content = f"""
    <html>
    <body style="font-family: Arial, sans-serif; font-size: 14px; color: #333;">
    <h2>📋 Daily Job Digest — {today_str}</h2>
    <p>
      <strong>{len(jobs)} new roles</strong> since the last digest.
      <span style="color: #856404; font-weight: bold;">🟡 Gold = Priority company.</span>
      <span style="color: #0f5132;">🟢 Green = Fortune 1000 match.</span><br>
      Log into the <strong>Job Hunter Dashboard</strong> to target roles for enrichment.
    </p>
    <table border="1" cellpadding="6" cellspacing="0"
           style="border-collapse: collapse; width: 100%; font-size: 13px;">
      <tr style="background-color: #f2f2f2; text-align: left;">
        <th>Company</th><th>Role</th><th>Location(s)</th><th>Source</th><th>Link</th>
      </tr>
      {''.join(rows)}
    </table>
    </body>
    </html>
    """

    msg = MIMEMultipart()
    msg["Subject"] = f"🚀 Daily Job Digest ({today_str}): {len(jobs)} New Roles"
    msg["From"]    = sender_email
    msg["To"]      = receiver_email
    msg.attach(MIMEText(html_content, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, receiver_email, msg.as_string())
        print(f"✅ Email sent to {receiver_email}.", flush=True)
    except Exception as e:
        print(f"❌ Email send failed: {e}", flush=True)


# =============================================================================
# MAIN
# =============================================================================

def main():
    matcher = CompanyMatcher(set(PRIORITY_COMPANIES) | load_fortune_1000())

    all_jobs = scrape_jobspy()
    for source in ATS_SOURCES:
        all_jobs.extend(scrape_ats(*source))
    print(f"\nRaw results total: {len(all_jobs)}", flush=True)

    jobs = condense_jobs(all_jobs)
    print(f"After in-run dedup: {len(jobs)} unique roles.", flush=True)

    jobs = filter_jobs(jobs, matcher)

    client = get_supabase()
    seen = fetch_seen(client) if client else None
    if seen is None:
        print("⚠️ No job history available — digest may include previously sent roles.", flush=True)
    else:
        jobs = drop_seen(jobs, seen)

    if not jobs:
        print("\nℹ️ No new roles today — no email sent.", flush=True)
        return

    # Write before emailing so the dashboard has data even if email fails,
    # and so these roles are recorded as sent for the next run's dedup.
    if client:
        write_to_supabase(client, jobs)
    send_email(jobs)
    print(f"\n✅ Done. {len(jobs)} new jobs processed.", flush=True)


if __name__ == "__main__":
    main()
