# =============================================================================
# enrichment.py — Module 3: AI Enrichment Pipeline
# Called by the "Run Enrichment" button in app.py.
#
# Pipeline per job:
#   Call 1 (Haiku)  — extract team signals + Google search queries from JD
#   Google search   — find hiring manager LinkedIn profile via site: operator
#   Claude parse    — extract manager name + title from search snippets
#   Call 2 (Haiku)  — generate personalized email, LinkedIn alumni query,
#                      and LinkedIn referral message
#   Apollo → Hunter — email waterfall using the found name
# =============================================================================

import os
import re
import json
import time
import requests
import streamlit as st

from urllib.parse import quote
from db import get_client


# =============================================================================
# CANDIDATE BACKGROUND PROFILE
# ─────────────────────────────────────────────────────────────────────────────
# This is the single source of truth Claude reads when writing your outreach.
# Be specific — vague entries produce vague emails. The more concrete detail
# you add here (exact metrics, tech stacks, project outcomes), the harder the
# generated copy hits.
# =============================================================================

CANDIDATE_PROFILE = {
    "name":       "Rish Potti",
    "university": "UNC Chapel Hill",
    "year":       "first-year Master's student in Computer Science",
    "major":      "Computer Science (MS)",

    # UG GPA included since MS GPA not yet established
    "gpa": "8.35/10 (B.Tech, NIT Rourkela)",

    # ── Work Experience ───────────────────────────────────────────────────────
    "experiences": [
        {
            "company":    "American Express",
            "role":       "Summer Data Science Intern",
            "highlights": [
                "Performed EDA and preprocessing on incident data using Pandas and Seaborn, "
                "identifying 8 concrete automation opportunities",
                "Built TensorFlow classification models to predict the probability of change "
                "failure, achieving 91% accuracy — integrated as a signal in SRE deployment gates",
                "Engineered a Doc2Vec + Scikit-Learn retrieval system to surface relevant error "
                "correction articles at incident time, reducing manual triage effort",
            ],
        },
        {
            "company":    "Shopalyst",
            "role":       "Summer Software Intern",
            "highlights": [
                "Contributed to an automated ad creative generation pipeline",
                "Processed shopping catalog images at scale using rembg and a deep learning "
                "background removal API, providing test data and validating output quality",
                "Used Pillow to transform raw product images to platform ad specifications",
            ],
        },
    ],

    # ── Research ──────────────────────────────────────────────────────────────
    "research": [
        {
            "institution": "NIT Rourkela",
            "role":        "Undergraduate Research Assistant",
            "highlights": [
                "Implemented brain lesion segmentation from scratch using a U-Net architecture "
                "on the ATLAS 2.0 MRI dataset, achieving 96.4% accuracy",
                "Preprocessed and visualized volumetric MR images using Nibabel and Matplotlib",
                "Evaluated and benchmarked state-of-the-art segmentation methods to identify "
                "the most effective current approaches",
            ],
        },
    ],

    # ── Projects ──────────────────────────────────────────────────────────────
    "projects": [
        {
            "name":        "Agentic Code Generation",
            "description": "Built a LangChain + LangGraph agent (backed by Gemini) that "
                           "automates end-to-end code generation and unit testing. "
                           "Designed an orchestrator-worker architecture enabling multi-file "
                           "project planning and coordinated code creation across modules. "
                           "Directly demonstrates practical LLM agentic systems experience.",
            "tech":        ["Python", "LangChain", "LangGraph", "Gemini", "Git"],
        },
        {
            "name":        "Heart Sound Classification",
            "description": "Preprocessed cardiac audio data using Librosa and Discrete Wavelet "
                           "Transform, then experimented with TensorFlow architectures to select "
                           "the most accurate model for classifying heart sounds. "
                           "Relevant for roles involving signal processing and medical AI.",
            "tech":        ["Python", "NumPy", "Librosa", "TensorFlow", "Jupyter"],
        },
        {
            "name":        "Brain Lesion Segmentation (U-Net)",
            "description": "Implemented a U-Net convolutional architecture from scratch in "
                           "Python/TensorFlow to segment brain lesions in MRI scans from the "
                           "ATLAS 2.0 dataset, achieving 96.4% accuracy. "
                           "Published as undergraduate research at NIT Rourkela.",
            "tech":        ["Python", "TensorFlow", "Nibabel", "NumPy", "Matplotlib"],
        },
        {
            "name":        "Job Hunter OSINT Pipeline",
            "description": "Designed and built a fully autonomous internship sourcing pipeline: "
                           "nightly GitHub Actions scraper (jobspy + Greenhouse/Lever ATS APIs "
                           "with WAF-bypass batching), Supabase PostgreSQL backend, Streamlit "
                           "triage dashboard, and a Claude-powered enrichment layer that extracts "
                           "hiring managers via NLP, runs an Apollo→Hunter email waterfall, and "
                           "generates personalized outreach copy and LinkedIn referral messages "
                           "per role. End-to-end MLOps and agentic systems in production.",
            "tech":        ["Python", "GitHub Actions", "Supabase", "Streamlit",
                            "Claude API", "LangChain concepts", "PostgreSQL", "REST APIs"],
        },
    ],

    # ── Skills ────────────────────────────────────────────────────────────────
    "skills": [
        "Python", "TensorFlow", "Pandas", "NumPy", "Scikit-Learn",
        "LangChain", "LangGraph", "SQL", "Git", "C++",
        "MLOps", "agentic systems", "NLP", "computer vision",
        "statistical modeling", "REST APIs",
    ],

    # ── Value Proposition ─────────────────────────────────────────────────────
    "value_prop": (
        "MS CS student at UNC Chapel Hill with production ML at American Express "
        "(91% accuracy change-failure model, 8 automation opportunities shipped), "
        "96.4%-accurate U-Net brain lesion segmentation research, and hands-on "
        "LangGraph agentic systems — I build things that reach production."
    ),
}


# =============================================================================
# ANTHROPIC CLIENT
# =============================================================================

def _get_anthropic():
    """Lazy import — avoids crashing on startup if the key isn't set."""
    try:
        import anthropic
        key = st.secrets.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            st.error("❌ ANTHROPIC_API_KEY not set in Streamlit secrets.")
            st.stop()
        return anthropic.Anthropic(api_key=key)
    except ImportError:
        st.error("❌ anthropic package not installed. Check requirements.txt.")
        st.stop()


# =============================================================================
# DOMAIN RESOLUTION
# =============================================================================

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
    normalized = company_name.lower().strip()
    if normalized in DOMAIN_MAP:
        return DOMAIN_MAP[normalized]
    for key, domain in DOMAIN_MAP.items():
        if key in normalized or normalized in key:
            return domain
    noise  = {"inc", "llc", "ltd", "corp", "corporation", "co", "group",
               "holdings", "global", "technologies", "solutions", "services"}
    clean  = re.sub(r"[^a-z0-9\s]", "", normalized)
    tokens = [t for t in clean.split() if t not in noise]
    return ("".join(tokens[:2]) + ".com") if tokens else None


# =============================================================================
# CLAUDE CALL 1 — JD SIGNAL EXTRACTION
# =============================================================================
# Instead of looking for a manager name inside the JD (rarely present),
# Claude reads the JD and extracts structured signals that let us search for
# the right person on LinkedIn: team name, function, and a ranked list of
# likely manager titles. This feeds the web search step below.

def extract_jd_signals(description: str, company: str, title: str) -> dict:
    """
    Reads the job description and extracts searchable signals about the team
    and the likely hiring manager's title/function.

    Returns:
    {
      "team_name":       str | None,   # e.g. "ML Platform", "Core AI"
      "team_function":   str | None,   # e.g. "builds ML infrastructure"
      "manager_titles":  list[str],    # ordered by likelihood, e.g.
                                       # ["Head of ML Engineering",
                                       #  "ML Engineering Manager",
                                       #  "Director of AI"]
      "search_queries":  list[str],    # 3 ready-to-use Google search strings,
                                       # most specific first
    }
    """
    client = _get_anthropic()

    system = """You are a recruiting intelligence assistant.
Your job is to read a job description and extract structured signals that can
be used to search LinkedIn for the hiring manager.

STRICT RULES:
- Respond ONLY with valid JSON. No markdown, no explanation, no preamble.
- manager_titles: list of 3 plausible titles for the person who would hire
  for this role, ordered most-specific first. Infer from the team description,
  tech stack, and seniority signals in the JD.
- search_queries: list of exactly 3 Google search strings to find that person
  on LinkedIn. Format each as:
    site:linkedin.com/in "[Company]" "[Title]"
  Vary the title across the three queries using manager_titles.
- If the JD mentions a team name, include it.
- team_function: one sentence describing what this team builds/does.

Example output:
{
  "team_name": "ML Platform",
  "team_function": "builds internal ML infrastructure and tooling for model training",
  "manager_titles": ["Head of ML Platform", "ML Engineering Manager", "Director of ML Infrastructure"],
  "search_queries": [
    "site:linkedin.com/in \"Stripe\" \"Head of ML Platform\"",
    "site:linkedin.com/in \"Stripe\" \"ML Engineering Manager\"",
    "site:linkedin.com/in \"Stripe\" \"Director of Machine Learning\""
  ]
}"""

    user = f"""Company: {company}
Role: {title}

Job Description:
{description[:3500]}

Extract the signals. Return only JSON."""

    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        raw = resp.content[0].text.strip()
        raw = re.sub(r"^```json|^```|```$", "", raw, flags=re.MULTILINE).strip()
        result = json.loads(raw)
        # Guarantee the keys exist
        result.setdefault("team_name", None)
        result.setdefault("team_function", None)
        result.setdefault("manager_titles", [])
        result.setdefault("search_queries", [])
        return result
    except (json.JSONDecodeError, Exception) as e:
        st.warning(f"⚠️ JD signal extraction failed for {company}: {e}")
        return {
            "team_name":      None,
            "team_function":  None,
            "manager_titles": [],
            "search_queries": [],
        }


# =============================================================================
# WEB SEARCH — FIND HIRING MANAGER VIA GOOGLE
# =============================================================================
# Uses Google's public search to find LinkedIn profiles matching the extracted
# title/company signals. No API key needed. Parses result snippets to extract
# a candidate name. Rate-limited by design — only called on-demand, 3-5 times
# per enrichment session, well within safe limits.

def _google_search_snippets(query: str, timeout: int = 8) -> list[str]:
    """
    Executes a Google search and returns a list of result snippet strings.
    Uses a browser-like User-Agent to avoid immediate bot detection.
    Returns up to 5 snippets, or an empty list on any failure.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        resp = requests.get(
            "https://www.google.com/search",
            params={"q": query, "num": 5, "hl": "en"},
            headers=headers,
            timeout=timeout,
        )
        if resp.status_code != 200:
            return []

        # Extract text from <span> and <div> tags that hold snippet content.
        # We use simple regex rather than a full HTML parser to avoid adding
        # a beautifulsoup dependency.
        text = resp.text

        # Pull all visible text blocks between tags, strip HTML
        raw_blocks = re.findall(r'<span[^>]*>(.*?)</span>', text, re.DOTALL)
        raw_blocks += re.findall(r'<div[^>]*class="[^"]*BNeawe[^"]*"[^>]*>(.*?)</div>', text, re.DOTALL)

        snippets = []
        seen = set()
        for block in raw_blocks:
            # Strip remaining HTML tags
            clean = re.sub(r'<[^>]+>', ' ', block).strip()
            clean = re.sub(r'\s+', ' ', clean)
            # Only keep blocks that look like person descriptions (contain name-like patterns)
            if len(clean) > 20 and clean not in seen:
                snippets.append(clean)
                seen.add(clean)
            if len(snippets) >= 8:
                break

        return snippets

    except Exception:
        return []


def search_for_manager(
    company:         str,
    search_queries:  list[str],
    manager_titles:  list[str],
) -> dict:
    """
    Runs up to 3 Google searches using the Claude-generated queries.
    Collects result snippets, then passes them to Claude to identify
    the most likely hiring manager name and title.

    Returns {"manager_name": str|None, "manager_title": str|None,
             "search_source": str}  where search_source describes which
    query produced the result.
    """
    client = _get_anthropic()

    all_snippets = []
    source_query = None

    for i, query in enumerate(search_queries[:3]):
        snippets = _google_search_snippets(query)
        if snippets:
            all_snippets.extend(snippets)
            if source_query is None:
                source_query = query
        # Small polite delay between searches
        if i < len(search_queries) - 1:
            time.sleep(1.5)

    if not all_snippets:
        return {"manager_name": None, "manager_title": None, "search_source": "no_results"}

    # Ask Claude to identify the most likely real person from the snippets
    system = """You are a name extraction assistant reading Google search result snippets.
Your job is to identify the most likely hiring manager for the given role at the given company.

STRICT RULES:
- Respond ONLY with valid JSON. No markdown, no preamble.
- Extract a REAL FULL NAME from the snippets — first and last name.
- Only return a name if you are highly confident it belongs to a current employee
  in a management/leadership role at this company.
- Cross-reference: the name should appear in a snippet alongside the company name
  and a title consistent with the expected manager_titles list.
- If no credible match found, return null for both fields.
- Format: {"manager_name": "Jane Smith", "manager_title": "Head of ML Engineering"}
- No match:  {"manager_name": null, "manager_title": null}"""

    user = f"""Company: {company}
Expected manager title types: {', '.join(manager_titles[:3])}

Google search result snippets:
{chr(10).join(f'- {s}' for s in all_snippets[:12])}

Identify the hiring manager. Return only JSON."""

    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=120,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        raw = resp.content[0].text.strip()
        raw = re.sub(r"^```json|^```|```$", "", raw, flags=re.MULTILINE).strip()
        result = json.loads(raw)
        return {
            "manager_name":   result.get("manager_name"),
            "manager_title":  result.get("manager_title"),
            "search_source":  source_query or "google",
        }
    except (json.JSONDecodeError, Exception) as e:
        st.warning(f"⚠️ Manager name extraction from search failed: {e}")
        return {"manager_name": None, "manager_title": None, "search_source": "parse_error"}


# =============================================================================
# CLAUDE CALL 2 — PERSONALIZED OUTREACH GENERATION
# =============================================================================

def _build_profile_summary() -> str:
    """Serializes CANDIDATE_PROFILE into a compact string for the prompt."""
    p = CANDIDATE_PROFILE
    lines = [
        f"Name: {p['name']}",
        f"University: {p['university']} ({p['year']}, {p['major']})",
    ]
    if p.get("gpa"):
        lines.append(f"GPA: {p['gpa']}")

    lines.append("\nWork Experience:")
    for exp in p.get("experiences", []):
        lines.append(f"  • {exp['role']} at {exp['company']}")
        for h in exp.get("highlights", []):
            lines.append(f"    – {h}")

    if p.get("research"):
        lines.append("\nResearch Experience:")
        for r in p["research"]:
            lines.append(f"  • {r['role']} at {r['institution']}")
            for h in r.get("highlights", []):
                lines.append(f"    – {h}")

    lines.append("\nProjects:")
    for proj in p.get("projects", []):
        lines.append(f"  • {proj['name']}: {proj['description']}")
        lines.append(f"    Tech: {', '.join(proj.get('tech', []))}")

    lines.append(f"\nSkills: {', '.join(p.get('skills', []))}")
    lines.append(f"\nValue Proposition: {p.get('value_prop', '')}")
    return "\n".join(lines)


def generate_personalized_outreach(
    description:   str,
    company:       str,
    title:         str,
    manager_name:  str | None,
    team_name:     str | None = None,
    team_function: str | None = None,
) -> dict:
    """
    Generates three outreach pieces using the JD, the candidate profile,
    and team context extracted in Call 1.

    personalized_email_body — role-specific cold email body
    linkedin_search_query   — alumni search string for UNC referral
    linkedin_message        — ≤280-char LinkedIn connection note
    """
    client  = _get_anthropic()
    profile = _build_profile_summary()

    manager_line = (
        f"The hiring manager is {manager_name}."
        if manager_name
        else "The hiring manager's name is unknown — address the email to the team."
    )
    team_context = ""
    if team_name or team_function:
        team_context = f"\nTeam context: {team_name or ''} — {team_function or ''}".strip(" —")

    system = """You are an expert career coach who writes cold outreach that
actually gets responses. Your emails and LinkedIn messages are specific,
confident, and make the recipient feel that ignoring this candidate would be
a mistake. You never use filler phrases like 'highly motivated individual'
or 'I believe I would be a great fit'. Every sentence earns its place by
connecting a concrete candidate achievement to a concrete company need.

Respond ONLY with a valid JSON object containing exactly these three keys:
  personalized_email_body  — string (email body only, no salutation or sign-off)
  linkedin_search_query    — string
  linkedin_message         — string (≤280 chars)

No markdown. No explanation. No preamble. Only the JSON object."""

    user = f"""ROLE: {title} at {company}
{manager_line}{team_context}

JOB DESCRIPTION (read carefully — pull specific details from this):
{description[:4000]}

CANDIDATE BACKGROUND (map these to the JD):
{profile}

Generate the three outreach pieces. Requirements:

EMAIL BODY (no salutation, no sign-off — those are added separately):
- Open by naming something specific from the JD: a stated technical challenge,
  the team's mission, or a specific tool/method they mention. Do not open with
  "I" — open with a statement about the company or the role.
- Paragraph 2: connect ONE specific candidate achievement to that JD detail
  with a concrete metric or outcome. Be direct: "At Amex, I built X which gave
  me direct experience with Y — exactly what you describe needing."
- Paragraph 3: name one more relevant project or skill that addresses another
  stated JD requirement. Be concrete.
- Close: single clear ask — 15-minute call or resume review.
- Tone: confident peer-to-peer, not supplicant. 3–4 paragraphs, zero fluff.

LINKEDIN SEARCH QUERY:
- Format: "[University] [Company] [2–3 role-relevant keywords]"
- Example: "UNC Chapel Hill Stripe data science machine learning"
- Will be pasted directly into LinkedIn search to find alumni at this company.

LINKEDIN MESSAGE (HARD LIMIT: ≤280 characters — count carefully):
- Start with: "Fellow Tar Heel here —"
- Name the specific role you're applying to.
- ONE concrete credential hook tied to what this company does.
- End with: "Would you be open to a quick chat?"
- No company praise. No generic enthusiasm. ≤280 chars, non-negotiable."""

    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1200,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        raw = resp.content[0].text.strip()
        raw = re.sub(r"^```json|^```|```$", "", raw, flags=re.MULTILINE).strip()
        result = json.loads(raw)

        li_msg = result.get("linkedin_message") or ""
        if len(li_msg) > 280:
            li_msg = li_msg[:277] + "..."
        result["linkedin_message"] = li_msg

        return {
            "personalized_email_body": result.get("personalized_email_body"),
            "linkedin_search_query":   result.get("linkedin_search_query"),
            "linkedin_message":        result.get("linkedin_message"),
        }

    except (json.JSONDecodeError, Exception) as e:
        st.warning(f"⚠️ Outreach generation failed for {company}: {e}")
        return {
            "personalized_email_body": None,
            "linkedin_search_query":   f"UNC Chapel Hill {company} data science machine learning",
            "linkedin_message":        None,
        }



# =============================================================================
# EMAIL LOOKUP — APOLLO (PRIMARY)
# =============================================================================

def lookup_apollo(first: str, last: str, domain: str) -> dict | None:
    api_key = st.secrets.get("APOLLO_API_KEY") or os.environ.get("APOLLO_API_KEY")
    if not api_key:
        return None
    STATUS_CONFIDENCE = {"verified": 90, "likely": 70, "guessed": 40}
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
            return {"email": email, "confidence": STATUS_CONFIDENCE.get(status, 0), "source": "apollo"}
    except requests.exceptions.Timeout:
        st.warning("⚠️ Apollo timed out — trying Hunter.")
    except Exception as e:
        st.warning(f"⚠️ Apollo error: {e}")
    return None


# =============================================================================
# EMAIL LOOKUP — HUNTER (FALLBACK)
# =============================================================================

def lookup_hunter(first: str, last: str, domain: str) -> dict | None:
    api_key = st.secrets.get("HUNTER_API_KEY") or os.environ.get("HUNTER_API_KEY")
    if not api_key:
        return None
    try:
        resp = requests.get(
            "https://api.hunter.io/v2/email-finder",
            params={"domain": domain, "first_name": first, "last_name": last, "api_key": api_key},
            timeout=10,
        )
        resp.raise_for_status()
        data  = resp.json().get("data") or {}
        email = data.get("email", "")
        score = int(data.get("score") or 0)
        if email and "@" in email:
            return {"email": email, "confidence": score, "source": "hunter"}
    except requests.exceptions.Timeout:
        st.warning("⚠️ Hunter timed out.")
    except Exception as e:
        st.warning(f"⚠️ Hunter error: {e}")
    return None


# =============================================================================
# MASTER ENRICHMENT FUNCTION
# =============================================================================

def run_enrichment(job: dict) -> dict:
    """
    Full pipeline for one job:
      1. Claude Call 1 — extract team signals + Google search queries from JD
      2. Google search — find hiring manager LinkedIn profile via site: operator
      3. Claude parse  — extract manager name + title from search snippets
      4. Claude Call 2 — generate personalized email body, LinkedIn alumni
                         search query, and LinkedIn referral message
      5. Domain resolution
      6. Apollo → Hunter email waterfall using the found name
      7. Build mailto with personalized body
      8. Write to enriched_jobs; update pending_jobs.status → 'enriched'
    """
    job_id      = job["id"]
    company     = job.get("company", "")
    title       = job.get("title", "")
    description = job.get("description", "")

    # ── Step 1: Extract JD signals + search queries ───────────────────────────
    signals       = extract_jd_signals(description, company, title)
    team_name     = signals.get("team_name")
    team_function = signals.get("team_function")
    search_queries = signals.get("search_queries", [])
    manager_titles = signals.get("manager_titles", [])

    # ── Step 2+3: Search Google → parse manager name ─────────────────────────
    found         = search_for_manager(company, search_queries, manager_titles)
    manager_name  = found.get("manager_name")
    manager_title = found.get("manager_title")
    search_source = found.get("search_source", "")

    # ── Step 4: Personalized outreach (always runs, richer with team context) ─
    outreach         = generate_personalized_outreach(
        description, company, title, manager_name,
        team_name=team_name, team_function=team_function,
    )
    email_body       = outreach.get("personalized_email_body")
    linkedin_search  = outreach.get("linkedin_search_query")
    linkedin_message = outreach.get("linkedin_message")

    # ── Step 5: Domain resolution ─────────────────────────────────────────────
    domain = resolve_domain(company)

    # ── Step 6: Email waterfall ───────────────────────────────────────────────
    email_result = None
    if manager_name and domain:
        parts = manager_name.strip().split()
        first = parts[0]  if parts          else ""
        last  = parts[-1] if len(parts) > 1 else ""
        email_result = lookup_apollo(first, last, domain)
        if not email_result or email_result["confidence"] < 40:
            hunter = lookup_hunter(first, last, domain)
            if hunter and (not email_result or hunter["confidence"] > email_result["confidence"]):
                email_result = hunter

    # ── Step 7: Build mailto ──────────────────────────────────────────────────
    mailto = None
    if email_result and email_result.get("email"):
        mailto = build_mailto(
            email_result["email"], manager_name, company, title, email_body=email_body
        )

    # ── Step 8: Status + persist ──────────────────────────────────────────────
    if email_result and email_result.get("email"):
        extraction_status = "success"
    elif manager_name:
        extraction_status = "no_email_found"
    else:
        extraction_status = "no_manager_found"

    record = {
        "pending_job_id":          job_id,
        "manager_name":            manager_name,
        "manager_title":           manager_title,
        "manager_email":           email_result.get("email")      if email_result else None,
        "email_confidence":        email_result.get("confidence") if email_result else None,
        "email_source":            email_result.get("source")     if email_result else None,
        "company_domain":          domain,
        "mailto_link":             mailto,
        "extraction_status":       extraction_status,
        "personalized_email_body": email_body,
        "linkedin_search_query":   linkedin_search,
        "linkedin_message":        linkedin_message,
        "linkedin_search_queries": search_queries,   # store all 3 queries for debugging
        "manager_search_source":   search_source,    # which query produced the result
    }

    db = get_client()
    db.table("enriched_jobs").insert(record).execute()
    db.table("pending_jobs").update({"status": "enriched"}).eq("id", job_id).execute()

    return record