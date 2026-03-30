# =============================================================================
# enrichment.py — Module 3: AI Enrichment Pipeline
# Called by the "Run Enrichment" button in app.py.
# For each targeted job: extracts hiring manager via Claude Haiku, resolves
# the company domain, and runs Apollo → Hunter email waterfall.
# Writes results to enriched_jobs and updates pending_jobs.status.
# =============================================================================

import os
import re
import json
import requests
import streamlit as st

from urllib.parse import quote
from db import get_client


# =============================================================================
# ANTHROPIC CLIENT
# =============================================================================

def _get_anthropic():
    """Lazy import of anthropic to avoid crashing if the key isn't set yet."""
    try:
        import anthropic
        key = st.secrets.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            st.error("❌ ANTHROPIC_API_KEY not set in Streamlit secrets.")
            st.stop()
        return anthropic.Anthropic(api_key=key)
    except ImportError:
        st.error("❌ anthropic package not installed. Add it to requirements.txt.")
        st.stop()


# =============================================================================
# DOMAIN RESOLUTION
# =============================================================================

# Hardcoded map for priority companies — most reliable resolution method.
# For anything not in this map, a heuristic fallback is used.
DOMAIN_MAP: dict[str, str] = {
    "google": "google.com", "alphabet": "google.com",
    "apple": "apple.com",
    "meta": "meta.com", "facebook": "meta.com",
    "amazon": "amazon.com", "aws": "amazon.com",
    "microsoft": "microsoft.com",
    "netflix": "netflix.com",
    "nvidia": "nvidia.com",
    "tesla": "tesla.com",
    "adobe": "adobe.com",
    "salesforce": "salesforce.com",
    "oracle": "oracle.com",
    "intel": "intel.com",
    "amd": "amd.com",
    "cisco": "cisco.com",
    "ibm": "ibm.com",
    "intuit": "intuit.com",
    "uber": "uber.com",
    "lyft": "lyft.com",
    "airbnb": "airbnb.com",
    "spotify": "spotify.com",
    "snap": "snap.com",
    "pinterest": "pinterest.com",
    "linkedin": "linkedin.com",
    "databricks": "databricks.com",
    "snowflake": "snowflake.com",
    "palantir": "palantir.com",
    "openai": "openai.com",
    "anthropic": "anthropic.com",
    "deepmind": "deepmind.com",
    "american express": "americanexpress.com",
    "jpmorgan": "jpmorgan.com", "j.p. morgan": "jpmorgan.com", "chase": "chase.com",
    "goldman sachs": "goldmansachs.com",
    "morgan stanley": "morganstanley.com",
    "citi": "citi.com", "citigroup": "citi.com",
    "bank of america": "bankofamerica.com",
    "wells fargo": "wellsfargo.com",
    "capital one": "capitalone.com",
    "visa": "visa.com",
    "mastercard": "mastercard.com",
    "paypal": "paypal.com",
    "stripe": "stripe.com",
    "block": "block.xyz", "square": "squareup.com",
    "blackrock": "blackrock.com",
    "two sigma": "twosigma.com",
    "citadel": "citadel.com",
    "jane street": "janestreet.com",
    "fidelity": "fidelity.com",
    "vanguard": "vanguard.com",
    "bloomberg": "bloomberg.com",
    "sofi": "sofi.com",
    "chime": "chime.com",
    "discover": "discover.com",
    "pfizer": "pfizer.com",
    "moderna": "modernatx.com",
    "johnson & johnson": "jnj.com", "j&j": "jnj.com",
    "merck": "merck.com",
    "abbvie": "abbvie.com",
    "eli lilly": "lilly.com",
    "unitedhealth": "uhg.com",
    "optum": "optum.com",
    "cvs health": "cvshealth.com",
    "cigna": "cigna.com",
    "humana": "humana.com",
    "bristol myers squibb": "bms.com",
    "amgen": "amgen.com",
    "gilead": "gilead.com",
    "regeneron": "regeneron.com",
    "thermo fisher": "thermofisher.com",
    "medtronic": "medtronic.com",
    "ge healthcare": "gehealthcare.com",
    "walmart": "walmart.com",
    "target": "target.com",
    "home depot": "homedepot.com",
    "nike": "nike.com",
    "starbucks": "starbucks.com",
    "procter & gamble": "pg.com", "p&g": "pg.com",
    "coca-cola": "coca-cola.com",
    "pepsico": "pepsico.com",
    "fedex": "fedex.com",
    "ups": "ups.com",
    "deloitte": "deloitte.com",
    "pwc": "pwc.com",
    "ey": "ey.com",
    "kpmg": "kpmg.com",
    "accenture": "accenture.com",
    "mckinsey": "mckinsey.com",
    "bain": "bain.com",
    "bcg": "bcg.com",
    "boeing": "boeing.com",
    "lockheed martin": "lockheedmartin.com",
    "northrop grumman": "northropgrumman.com",
    "raytheon": "raytheon.com", "rtx": "rtx.com",
    "general dynamics": "gd.com",
    "anduril": "anduril.com",
    "spacex": "spacex.com",
    "ford": "ford.com",
    "general motors": "gm.com", "gm": "gm.com",
    "rivian": "rivian.com",
    "waymo": "waymo.com",
    "toyota": "toyota.com",
    "bmw": "bmw.com",
    # ATS companies
    "coinbase": "coinbase.com",
    "robinhood": "robinhood.com",
    "duolingo": "duolingo.com",
    "discord": "discord.com",
    "figma": "figma.com",
    "notion": "notion.so",
    "brex": "brex.com",
    "plaid": "plaid.com",
    "scale ai": "scale.com",
    "weights & biases": "wandb.ai",
    "hugging face": "huggingface.co",
    "cohere": "cohere.com",
    "replit": "replit.com",
    "benchling": "benchling.com",
    "tempus": "tempus.com",
    "recursion": "recursion.com",
    "perplexity": "perplexity.ai",
    "mistral ai": "mistral.ai",
    "together ai": "together.ai",
    "shield ai": "shield.ai",
}


def resolve_domain(company_name: str) -> str | None:
    """
    Resolves a company name to its primary web domain.

    Priority order:
      1. Exact match in hardcoded DOMAIN_MAP
      2. Partial match (e.g. "Goldman Sachs & Co." matches "goldman sachs")
      3. Heuristic: strip noise words and concatenate first two tokens + .com
         (e.g. "Acme Analytics Corp" → "acmeanalytics.com")
    """
    normalized = company_name.lower().strip()

    # 1. Exact match
    if normalized in DOMAIN_MAP:
        return DOMAIN_MAP[normalized]

    # 2. Partial match — either the map key is inside the company name or vice versa
    for key, domain in DOMAIN_MAP.items():
        if key in normalized or normalized in key:
            return domain

    # 3. Heuristic fallback
    noise = {"inc", "llc", "ltd", "corp", "corporation", "co", "group",
             "holdings", "global", "technologies", "solutions", "services"}
    clean  = re.sub(r"[^a-z0-9\s]", "", normalized)
    tokens = [t for t in clean.split() if t not in noise]

    if tokens:
        candidate = "".join(tokens[:2]) + ".com"
        return candidate

    return None


# =============================================================================
# STEP 1 — CLAUDE HAIKU NLP EXTRACTION
# =============================================================================

def extract_hiring_manager(description: str, company: str, title: str) -> dict:
    """
    Calls Claude Haiku with a strict JSON-only prompt to extract the hiring
    manager's name and title from the job description text.

    Returns {"hiring_manager_name": str|None, "manager_title": str|None}.
    Defaults to null on any ambiguity — never guesses.
    """
    client = _get_anthropic()

    system = """You are a precise information extraction assistant.
Extract the hiring manager's name and title from the provided job description.

STRICT RULES — follow exactly:
- Respond ONLY with a single valid JSON object. No markdown, no explanation, no preamble.
- Only extract a SPECIFIC NAMED PERSON. "Our recruiting team" or "the hiring manager" are NOT valid.
- The target person is typically the team lead, engineering manager, or department head.
- If you are not highly confident a real named person is present, return null for both fields.
- Valid:   {"hiring_manager_name": "Jane Smith", "manager_title": "Head of ML Engineering"}
- No name: {"hiring_manager_name": null, "manager_title": null}"""

    user = f"""Company: {company}
Role: {title}

Job Description (first 3000 chars):
{description[:3000]}

Extract the hiring manager. Return only JSON."""

    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        raw = resp.content[0].text.strip()
        # Strip accidental markdown fences if the model adds them
        raw = re.sub(r"^```json|^```|```$", "", raw, flags=re.MULTILINE).strip()
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"hiring_manager_name": None, "manager_title": None}
    except Exception as e:
        st.warning(f"⚠️ Claude extraction error: {e}")
        return {"hiring_manager_name": None, "manager_title": None}


# =============================================================================
# STEP 2A — APOLLO.IO EMAIL LOOKUP (PRIMARY)
# =============================================================================

def lookup_apollo(first: str, last: str, domain: str) -> dict | None:
    """
    Searches Apollo.io for a verified email address.
    Returns {"email": str, "confidence": int, "source": "apollo"} or None.
    Confidence is mapped from Apollo's email_status field:
      verified → 90, likely → 70, guessed → 40, otherwise → 0.
    """
    api_key = st.secrets.get("APOLLO_API_KEY") or os.environ.get("APOLLO_API_KEY")
    if not api_key:
        return None

    STATUS_CONFIDENCE = {
        "verified":  90,
        "likely":    70,
        "guessed":   40,
    }

    try:
        resp = requests.post(
            "https://api.apollo.io/v1/people/match",
            headers={"x-api-key": api_key, "Content-Type": "application/json"},
            json={"first_name": first, "last_name": last, "domain": domain},
            timeout=10,
        )
        resp.raise_for_status()
        person = resp.json().get("person") or {}
        email  = person.get("email", "")
        status = person.get("email_status", "").lower()

        if email and "@" in email:
            return {
                "email":      email,
                "confidence": STATUS_CONFIDENCE.get(status, 0),
                "source":     "apollo",
            }
    except requests.exceptions.Timeout:
        st.warning("⚠️ Apollo request timed out — falling back to Hunter.")
    except Exception as e:
        st.warning(f"⚠️ Apollo error: {e}")

    return None


# =============================================================================
# STEP 2B — HUNTER.IO EMAIL LOOKUP (FALLBACK)
# =============================================================================

def lookup_hunter(first: str, last: str, domain: str) -> dict | None:
    """
    Searches Hunter.io for an email address.
    Returns {"email": str, "confidence": int, "source": "hunter"} or None.
    Hunter's score field is already 0–100, used directly as confidence.
    """
    api_key = st.secrets.get("HUNTER_API_KEY") or os.environ.get("HUNTER_API_KEY")
    if not api_key:
        return None

    try:
        resp = requests.get(
            "https://api.hunter.io/v2/email-finder",
            params={
                "domain":     domain,
                "first_name": first,
                "last_name":  last,
                "api_key":    api_key,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data  = resp.json().get("data") or {}
        email = data.get("email", "")
        score = int(data.get("score") or 0)

        if email and "@" in email:
            return {
                "email":      email,
                "confidence": score,
                "source":     "hunter",
            }
    except requests.exceptions.Timeout:
        st.warning("⚠️ Hunter request timed out.")
    except Exception as e:
        st.warning(f"⚠️ Hunter error: {e}")

    return None


# =============================================================================
# STEP 3 — MAILTO LINK BUILDER
# =============================================================================

# ── PERSONALISE THESE BEFORE YOUR FIRST LIVE RUN ──────────────────────────
YOUR_NAME       = "Rishabhdev Potti"
YOUR_YEAR       = "first year Master's student"
YOUR_UNIVERSITY = "UNC Chapel Hill"
YOUR_MAJOR      = "Computer Science"
YOUR_SKILL_1    = "Machine Learning"
YOUR_SKILL_2    = "building LLM-based tools"
# ──────────────────────────────────────────────────────────────────────────


def build_mailto(email: str, manager_name: str, company: str, title: str) -> str:
    """
    Builds a mailto: URI with pre-filled subject and body.
    Clicking it opens the user's default email client ready to send.
    """
    first    = (manager_name or "").split()[0] if manager_name else "there"
    subject  = quote(f"Application: {title} — Summer 2026")
    body     = quote(
        f"Hi {first},\n\n"
        f"I came across the {title} opening at {company} and wanted to reach "
        f"out directly. I'm a {YOUR_YEAR} at {YOUR_UNIVERSITY} studying "
        f"{YOUR_MAJOR}, with hands-on experience in {YOUR_SKILL_1} and "
        f"{YOUR_SKILL_2}.\n\n"
        f"I've attached my resume for your review. Would you have 15 minutes "
        f"to connect this week?\n\n"
        f"Best,\n{YOUR_NAME}"
    )
    return f"mailto:{email}?subject={subject}&body={body}"


# =============================================================================
# MASTER ENRICHMENT FUNCTION
# =============================================================================

def run_enrichment(job: dict) -> dict:
    """
    Runs the full enrichment pipeline for a single job dict:
      1. Claude Haiku extracts hiring manager name + title
      2. Domain is resolved from company name
      3. Apollo → Hunter waterfall returns email + confidence
      4. mailto link is built
      5. Results written to enriched_jobs; pending_jobs.status updated

    Returns the enrichment result dict (same shape as the enriched_jobs row).
    """
    job_id      = job["id"]
    company     = job.get("company", "")
    title       = job.get("title", "")
    description = job.get("description", "")

    # ── Step 1: NLP extraction ───────────────────────────────────────────────
    extracted     = extract_hiring_manager(description, company, title)
    manager_name  = extracted.get("hiring_manager_name")
    manager_title = extracted.get("manager_title")

    # ── Step 2: Domain resolution ────────────────────────────────────────────
    domain = resolve_domain(company)

    # ── Step 3: Email waterfall ──────────────────────────────────────────────
    email_result = None
    if manager_name and domain:
        parts = manager_name.strip().split()
        first = parts[0]  if parts           else ""
        last  = parts[-1] if len(parts) > 1  else ""

        # Apollo first
        email_result = lookup_apollo(first, last, domain)

        # Waterfall to Hunter if Apollo returned nothing or low confidence
        if not email_result or email_result["confidence"] < 40:
            hunter = lookup_hunter(first, last, domain)
            if hunter:
                # Take whichever has higher confidence
                if not email_result or hunter["confidence"] > email_result["confidence"]:
                    email_result = hunter

    # ── Step 4: Build mailto ─────────────────────────────────────────────────
    mailto = None
    if email_result and email_result.get("email"):
        mailto = build_mailto(
            email_result["email"],
            manager_name or "",
            company,
            title,
        )

    # ── Step 5: Determine extraction status ──────────────────────────────────
    if email_result and email_result.get("email"):
        extraction_status = "success"
    elif manager_name:
        extraction_status = "no_email_found"
    else:
        extraction_status = "no_manager_found"

    # ── Step 6: Persist to Supabase ──────────────────────────────────────────
    record = {
        "pending_job_id":    job_id,
        "manager_name":      manager_name,
        "manager_title":     manager_title,
        "manager_email":     email_result.get("email")       if email_result else None,
        "email_confidence":  email_result.get("confidence")  if email_result else None,
        "email_source":      email_result.get("source")      if email_result else None,
        "company_domain":    domain,
        "mailto_link":       mailto,
        "extraction_status": extraction_status,
    }

    client = get_client()
    client.table("enriched_jobs").insert(record).execute()
    client.table("pending_jobs").update({"status": "enriched"}).eq("id", job_id).execute()

    return record