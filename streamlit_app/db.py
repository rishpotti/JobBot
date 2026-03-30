# =============================================================================
# db.py — Supabase client and all database helpers
# Shared by app.py and enrichment.py. All reads/writes go through here.
# =============================================================================

import os
import streamlit as st
from supabase import create_client, Client
from datetime import date, timedelta


# =============================================================================
# CLIENT
# =============================================================================

@st.cache_resource
def get_client() -> Client:
    """
    Returns a cached Supabase client. Uses the anon key (appropriate for the
    Streamlit dashboard — row-level security is not configured, so reads and
    writes both work with the anon key from the user's session).

    Reads credentials from Streamlit secrets first, then falls back to
    environment variables so the app works in both local dev and cloud.
    """
    url = st.secrets.get("SUPABASE_URL") or os.environ.get("SUPABASE_URL")
    key = st.secrets.get("SUPABASE_KEY") or os.environ.get("SUPABASE_KEY")

    if not url or not key:
        st.error("❌ Supabase credentials missing. Add SUPABASE_URL and SUPABASE_KEY to Streamlit secrets.")
        st.stop()

    return create_client(url, key)


# =============================================================================
# READS
# =============================================================================

def fetch_pending_jobs(days_back: int = 3, priority_only: bool = False) -> list:
    """
    Returns all jobs scraped within the last `days_back` days that have not
    yet been contacted or rejected. Includes their enrichment data via the
    embedded enriched_jobs relationship.

    Ordered: priority companies first, then alphabetically by company name.
    """
    client   = get_client()
    since    = (date.today() - timedelta(days=days_back)).isoformat()

    query = (
        client.table("pending_jobs")
        .select("*, enriched_jobs(*)")
        .gte("scraped_date", since)
        .not_.in_("status", ["contacted", "rejected"])
        .order("is_priority", desc=True)
        .order("company", desc=False)
    )

    if priority_only:
        query = query.eq("is_priority", True)

    return query.execute().data or []


def fetch_enriched_ready() -> list:
    """
    Returns all jobs with status='enriched' that haven't been contacted or
    rejected yet — i.e., roles that are ready for outreach.
    Includes enrichment data.
    """
    client = get_client()
    return (
        client.table("pending_jobs")
        .select("*, enriched_jobs(*)")
        .eq("status", "enriched")
        .order("company")
        .execute()
        .data or []
    )


def fetch_history() -> list:
    """
    Returns the full contacted_history log, joined with the parent job's
    company and title, ordered most-recent first.
    """
    client = get_client()
    return (
        client.table("contacted_history")
        .select("*, pending_jobs(company, title, site, job_url)")
        .order("contacted_at", desc=True)
        .execute()
        .data or []
    )


def fetch_stats() -> dict:
    """
    Returns headline counts for the stats bar:
      - total_today:  jobs scraped today
      - priority_today: priority jobs scraped today
      - enriched:     jobs in 'enriched' status (ready to contact)
      - contacted:    total contacted all-time
    """
    client  = get_client()
    today   = date.today().isoformat()

    total_today = (
        client.table("pending_jobs")
        .select("id", count="exact")
        .eq("scraped_date", today)
        .execute()
        .count or 0
    )
    priority_today = (
        client.table("pending_jobs")
        .select("id", count="exact")
        .eq("scraped_date", today)
        .eq("is_priority", True)
        .execute()
        .count or 0
    )
    enriched = (
        client.table("pending_jobs")
        .select("id", count="exact")
        .eq("status", "enriched")
        .execute()
        .count or 0
    )
    contacted = (
        client.table("contacted_history")
        .select("id", count="exact")
        .execute()
        .count or 0
    )

    return {
        "total_today":    total_today,
        "priority_today": priority_today,
        "enriched":       enriched,
        "contacted":      contacted,
    }


# =============================================================================
# WRITES
# =============================================================================

def mark_targeted(job_ids: list[int]) -> None:
    """Sets is_targeted=True and status='targeted' for the given job IDs."""
    if not job_ids:
        return
    get_client().table("pending_jobs").update({
        "is_targeted": True,
        "status":      "targeted",
    }).in_("id", job_ids).execute()


def mark_contacted(
    job_id:        int,
    manager_email: str,
    company:       str,
    title:         str,
    notes:         str = "",
) -> None:
    """
    Appends a row to contacted_history and flips the parent job's status
    to 'contacted' so it no longer appears in the daily hopper.
    Both writes happen in sequence; if the history insert fails the status
    update is still attempted so the job doesn't get stuck in 'enriched'.
    """
    client = get_client()
    try:
        client.table("contacted_history").insert({
            "pending_job_id": job_id,
            "manager_email":  manager_email,
            "company":        company,
            "title":          title,
            "notes":          notes,
        }).execute()
    except Exception as e:
        st.warning(f"⚠️ History log failed for job {job_id}: {e}")

    client.table("pending_jobs").update({
        "status": "contacted",
    }).eq("id", job_id).execute()


def mark_rejected(job_id: int) -> None:
    """Marks a job as rejected so it disappears from the hopper."""
    get_client().table("pending_jobs").update({
        "status": "rejected",
    }).eq("id", job_id).execute()


def insert_manual_job(company: str, title: str, description: str) -> None:
    """
    Inserts a manually added job into pending_jobs.
    Uses upsert so re-submitting the same company+title is a no-op.
    """
    get_client().table("pending_jobs").upsert({
        "company":     company,
        "title":       title,
        "description": description,
        "source":      "manual",
        "status":      "pending",
        "is_priority":  False,   # User can target it manually in the hopper
        "scraped_date": date.today().isoformat(),
    }, on_conflict="company,title", ignore_duplicates=True).execute()