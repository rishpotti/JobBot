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
    "Data Science Intern Summer 2026",
    "Machine Learning Intern Summer 2026",
    "AI Engineering Intern 2026",
    "Software Engineer Intern Machine Learning"
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
    
    print("Scraping jobs from 5 sources...")
    try:
        jobs = scrape_jobs(
            # Added zip_recruiter and google (which aggregates many others)
            site_name=["linkedin", "indeed", "glassdoor", "zip_recruiter", "google"],
            search_term=" OR ".join(KEYWORDS),
            location="United States",
            results_wanted=100,  # Increased to capture more
            hours_old=24,
            country_urlpatterns={
                "Global": "https://www.linkedin.com/jobs/search/?keywords={}&location={}"
            }
        )
        
        jobs_list = jobs.to_dict('records')
        
        # Deduplicate by URL
        unique_jobs = {j.get('job_url'): j for j in jobs_list if j.get('job_url')}.values()
        
        # FILTER: Keep job if it matches our Master Safe List
        filtered_jobs = [
            j for j in unique_jobs 
            if is_high_quality(j.get('company'), master_safe_list)
        ]

        if filtered_jobs:
            send_email(filtered_jobs)
            print(f"Sent {len(filtered_jobs)} matches.")
        else:
            print("No matches found in the master list.")

    except Exception as e:
        print(f"Scraping error: {e}")

if __name__ == "__main__":
    main()