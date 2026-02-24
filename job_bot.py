import csv
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from jobspy import scrape_jobs
import pandas as pd

# --- CONFIGURATION ---
KEYWORDS = [
    # --- TIER 1: The "Standard" Data & ML Titles ---
    "Data Science Intern Summer 2026",
    "Data Scientist Intern Summer 2026",
    "Machine Learning Intern Summer 2026",
    "Machine Learning Engineer Intern 2026",
    "Artificial Intelligence Intern 2026",
    "AI Engineer Intern 2026",
    
    # --- TIER 2: The "Prestige" Tech Titles (Amazon/Microsoft/Nvidia style) ---
    # These often pay 30-50% more than standard "Data Analyst" roles
    "Applied Scientist Intern 2026",
    "Applied Machine Learning Intern 2026",
    "Research Scientist Intern 2026",
    "Research Engineer Intern 2026",
    "Algorithm Engineer Intern 2026",
    
    # --- TIER 3: Fintech & Quant (High Fit for your Amex Background) ---
    # These roles value your "Incident Data" & "Change Failure" project experience
    "Quantitative Researcher Intern 2026",
    "Quantitative Analyst Intern 2026",
    "Quant Developer Intern 2026",
    "Financial Engineering Intern 2026",
    "Decision Science Intern 2026",  # Common in Banks/Insurance
    "Risk Modeling Intern 2026",
    
    # --- TIER 4: Emerging Tech (GenAI / LLMs) ---
    # Companies hiring specifically for the new wave
    "Generative AI Intern 2026",
    "LLM Intern 2026",
    "Large Language Model Intern 2026",
    "Natural Language Processing Intern 2026",
    "Computer Vision Intern 2026",
    "Deep Learning Intern 2026",
    
    # --- TIER 5: The "Hidden" Engineering Roles ---
    # Often listed as SWE but are actually 100% ML work
    "Software Engineer Intern Machine Learning",
    "Software Engineer Intern AI",
    "Software Engineer Intern Data",
    "Data Engineer Intern Summer 2026",
    "MLOps Intern 2026",
    "AI Infrastructure Intern 2026",
    
    # --- TIER 6: Domain Specific (Bio/Health for your U-Net project) ---
    "Biomedical Data Science Intern",
    "Computational Biology Intern", 
    "Imaging AI Intern"
]

# EXPANDED PRIORITY LIST
# Categorized by sector for better targeting based on your resume

PRIORITY_COMPANIES = [
    # --- TIER 1: BIG TECH & AI (The "Obvious" Targets) ---
    "Google", "Alphabet", "Apple", "Meta", "Facebook", "Amazon", "AWS", 
    "Microsoft", "Netflix", "Nvidia", "Tesla", "Adobe", "Salesforce", 
    "Oracle", "Intel", "AMD", "Cisco", "IBM", "Intuit", "Uber", "Lyft", 
    "Airbnb", "Spotify", "Snap", "Pinterest", "LinkedIn", "Databricks", 
    "Snowflake", "Palantir", "OpenAI", "Anthropic", "DeepMind",

    # --- TIER 2: FINTECH & BANKING (High match for your Amex experience) ---
    # These pay very well and view your Amex internship as a "seal of approval"
    "American Express", "JPMorgan", "J.P. Morgan", "Chase", "Goldman Sachs", 
    "Morgan Stanley", "Citi", "Citigroup", "Bank of America", "Wells Fargo", 
    "Capital One", "Visa", "Mastercard", "PayPal", "Stripe", "Block", "Square", 
    "BlackRock", "Two Sigma", "Citadel", "Jane Street", "Fidelity", "Vanguard", 
    "Bloomberg", "SoFi", "Chime", "Discover",

    # --- TIER 3: HEALTHCARE & PHARMA (High match for your Medical Imaging project) ---
    # Stable, recession-proof, and heavily investing in AI for drug discovery/diagnostics
    "Pfizer", "Moderna", "Johnson & Johnson", "J&J", "Merck", "AbbVie", 
    "Eli Lilly", "UnitedHealth", "Optum", "CVS Health", "Cigna", "Elevance", 
    "Humana", "Bristol Myers Squibb", "Amgen", "Gilead", "Regeneron", 
    "Thermo Fisher", "Medtronic", "Boston Scientific", "GE HealthCare",

    # --- TIER 4: RETAIL, LOGISTICS & CONSULTING (High Volume Hiring) ---
    # Walmart/Target are actually massive tech employers now (supply chain AI)
    "Walmart", "Target", "Costco", "Home Depot", "Lowe's", "Nike", 
    "Starbucks", "Procter & Gamble", "P&G", "Coca-Cola", "PepsiCo", 
    "FedEx", "UPS", "Deloitte", "PwC", "EY", "KPMG", "Accenture", 
    "McKinsey", "Bain", "BCG",

    # --- TIER 5: DEFENSE, AUTO & AEROSPACE ---
    # High job security, often require US Citizenship (which you have)
    "Boeing", "Lockheed Martin", "Northrop Grumman", "Raytheon", "RTX", 
    "General Dynamics", "L3Harris", "Anduril", "SpaceX", "Blue Origin", 
    "Ford", "General Motors", "GM", "Rivian", "Waymo", "Zoox", "Cruise", 
    "Toyota", "Honda", "BMW"
]

def load_fortune_1000(filename="fortune1000.csv"):
    """
    Loads Fortune 1000 companies from a CSV file.
    Returns a set of company names.
    """
    companies = set()
    try:
        # Tries to read the CSV. Assumes a column named 'company' or 'Company' exists.
        df = pd.read_csv(filename)
        
        # Clean up column names to be safe
        df.columns = [c.lower().strip() for c in df.columns]
        
        if 'company' in df.columns:
            companies.update(df['company'].astype(str).tolist())
        elif 'name' in df.columns:
             companies.update(df['name'].astype(str).tolist())
        
        print(f"Successfully loaded {len(companies)} companies from {filename}")
    except Exception as e:
        print(f"⚠️ Could not load {filename}: {e}")
        print("Using only the manual PRIORITY_COMPANIES list.")
        
    return companies

def get_master_company_list():
    """Merges your manual list with the Fortune 1000 list."""
    fortune_list = load_fortune_1000()
    
    # Combine sets to remove duplicates
    master_list = set(PRIORITY_COMPANIES) | fortune_list
    return list(master_list)

def is_high_quality(job_company, master_list):
    """
    Checks if the job_company is in the master list.
    Uses fuzzy matching to catch things like 'Walmart Global Tech' matching 'Walmart'.
    """
    if not job_company: return False
    
    # Normalize the job company name (lowercase, remove punctuation)
    job_norm = job_company.lower().replace(".", "").replace(",", "")
    
    for safe_company in master_list:
        safe_norm = safe_company.lower().replace(".", "").replace(",", "")
        
        # Check if one is inside the other (e.g. "Google" in "Google LLC")
        if safe_norm in job_norm or job_norm in safe_norm:
            return True
            
    return False

def send_email(jobs):
    sender_email = os.environ.get("EMAIL_USER")
    sender_password = os.environ.get("EMAIL_PASS")
    receiver_email = "rishpotti@gmail.com"

    if not sender_email or not sender_password:
        print("Error: Email credentials not set.")
        return

    msg = MIMEMultipart()
    msg['Subject'] = f"🚀 Daily Job Digest: {len(jobs)} Roles Found"
    msg['From'] = sender_email
    msg['To'] = receiver_email

    html_content = """
    <html><body>
    <h2>Daily Internship Digest</h2>
    <table border="1" cellpadding="5" style="border-collapse: collapse; width: 100%;">
    <tr style="background-color: #f2f2f2;">
        <th>Role</th>
        <th>Company</th>
        <th>Location</th>
        <th>Source</th>
        <th>Link</th>
    </tr>
    """
    
    for job in jobs:
        company = job.get('company', 'Unknown')
        
        # Gold for Priority Match, Green for Safe/Fortune 1000 Match
        if any(p.lower() in company.lower() for p in PRIORITY_COMPANIES):
            row_style = "style='background-color: #fff3cd; font-weight: bold;'" 
        else:
            row_style = "style='background-color: #e6fffa;'" 

        link = job.get('job_url') or job.get('job_url_direct') or "#"
        
        html_content += f"""
        <tr {row_style}>
            <td>{job.get('title')}</td>
            <td>{company}</td>
            <td>{job.get('location')}</td>
            <td>{job.get('site', 'Unknown')}</td>
            <td><a href="{link}">Apply</a></td>
        </tr>
        """

    html_content += "</table></body></html>"
    msg.attach(MIMEText(html_content, 'html'))

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, receiver_email, msg.as_string())

def main():
    print("Loading company lists...")
    master_safe_list = get_master_company_list()
    
    all_jobs = []
    
    # Split keywords into chunks of 5 to avoid search engine limits
    chunk_size = 5
    keyword_chunks = [KEYWORDS[i:i + chunk_size] for i in range(0, len(KEYWORDS), chunk_size)]
    
    print(f"Scraping jobs in {len(keyword_chunks)} batches...")
    
    for i, batch in enumerate(keyword_chunks):
        print(f"  - Batch {i+1}/{len(keyword_chunks)}: {batch}")
        try:
            # We explicitly search for "Summer 2026" to avoid old roles
            search_query = " OR ".join(batch)
            
            jobs = scrape_jobs(
                site_name=["linkedin", "indeed", "glassdoor", "zip_recruiter", "google"],
                search_term=search_query,
                location="United States",
                results_wanted=20, # Smaller number per batch adds up to a lot
                hours_old=24, 
                country_urlpatterns={
                    "Global": "https://www.linkedin.com/jobs/search/?keywords={}&location={}"
                }
            )
            
            # Append results to our master list
            if not jobs.empty:
                all_jobs.extend(jobs.to_dict('records'))
                
        except Exception as e:
            print(f"    Error in batch {i+1}: {e}")
            continue

    # Deduplicate (since some keywords might find the same job)
    unique_jobs = {j.get('job_url'): j for j in all_jobs if j.get('job_url')}.values()
    
    # Filter for Quality
    filtered_jobs = [
        j for j in unique_jobs 
        if is_high_quality(j.get('company'), master_safe_list)
    ]

    if filtered_jobs:
        send_email(filtered_jobs)
        print(f"Sent {len(filtered_jobs)} unique matches.")
    else:
        print("No matches found in the master list today.")