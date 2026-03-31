# =============================================================================
# app.py — Job Hunter OSINT Pipeline Dashboard
# Module 2 (Triage) + Module 4 (Output) combined.
# Deploy via Streamlit Community Cloud pointing to streamlit_app/app.py
# =============================================================================

import streamlit as st
import pandas as pd
from datetime import date

from db import (
    fetch_pending_jobs,
    fetch_enriched_ready,
    fetch_history,
    fetch_stats,
    mark_targeted,
    mark_contacted,
    mark_rejected,
    insert_manual_job,
)
from enrichment import run_enrichment

# =============================================================================
# PAGE CONFIG
# =============================================================================

st.set_page_config(
    page_title="Job Hunter",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =============================================================================
# CUSTOM CSS — Dark terminal aesthetic
# IBM Plex Mono for headings, DM Sans for body.
# Amber gold accent (#f59e0b) consistent with priority highlighting in emails.
# =============================================================================

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;1,9..40,300&display=swap');

/* ── Global ─────────────────────────────────────────────────────────────── */
html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif;
    background-color: #0a0e17;
    color: #cbd5e1;
}

/* ── Headings ───────────────────────────────────────────────────────────── */
h1, h2, h3, h4 {
    font-family: 'IBM Plex Mono', monospace !important;
    letter-spacing: -0.02em;
}

/* ── Main header ────────────────────────────────────────────────────────── */
.main-header {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 1.6rem;
    font-weight: 600;
    color: #f1f5f9;
    letter-spacing: -0.03em;
    padding: 0.5rem 0 0.25rem 0;
    border-bottom: 1px solid #1e2d40;
    margin-bottom: 1.25rem;
}
.main-header span {
    color: #f59e0b;
}

/* ── Stat cards ─────────────────────────────────────────────────────────── */
.stat-card {
    background: #111827;
    border: 1px solid #1e2d40;
    border-radius: 8px;
    padding: 1rem 1.25rem;
    text-align: center;
}
.stat-number {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 2rem;
    font-weight: 600;
    color: #f1f5f9;
    line-height: 1;
}
.stat-number.gold { color: #f59e0b; }
.stat-number.green { color: #10b981; }
.stat-number.blue { color: #60a5fa; }
.stat-label {
    font-size: 0.7rem;
    color: #64748b;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-top: 0.35rem;
    font-family: 'IBM Plex Mono', monospace;
}

/* ── Section labels ─────────────────────────────────────────────────────── */
.section-label {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.65rem;
    font-weight: 500;
    color: #475569;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    margin-bottom: 0.6rem;
}

/* ── Enrichment result cards ────────────────────────────────────────────── */
.result-card {
    background: #111827;
    border: 1px solid #1e2d40;
    border-radius: 8px;
    padding: 1rem 1.25rem;
    margin-bottom: 0.75rem;
    transition: border-color 0.15s ease;
}
.result-card:hover { border-color: #334155; }
.result-card.priority { border-left: 3px solid #f59e0b; }

.result-company {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.85rem;
    font-weight: 600;
    color: #f1f5f9;
}
.result-title {
    font-size: 0.8rem;
    color: #94a3b8;
    margin-top: 0.1rem;
}
.result-location {
    font-size: 0.72rem;
    color: #475569;
    margin-top: 0.1rem;
}
.manager-name {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.8rem;
    color: #e2e8f0;
}
.manager-title-text {
    font-size: 0.72rem;
    color: #64748b;
}
.email-text {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.75rem;
    color: #60a5fa;
    word-break: break-all;
}
.confidence-high  { color: #10b981; font-family: 'IBM Plex Mono', monospace; font-size: 0.72rem; }
.confidence-mid   { color: #f59e0b; font-family: 'IBM Plex Mono', monospace; font-size: 0.72rem; }
.confidence-low   { color: #ef4444; font-family: 'IBM Plex Mono', monospace; font-size: 0.72rem; }
.no-contact       { color: #475569; font-size: 0.78rem; font-style: italic; }

/* ── Source badge ───────────────────────────────────────────────────────── */
.badge {
    display: inline-block;
    padding: 0.1rem 0.45rem;
    border-radius: 4px;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.6rem;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    background: #1e2d40;
    color: #64748b;
    vertical-align: middle;
}
.badge.priority { background: #451a03; color: #f59e0b; }
.badge.manual   { background: #1a2e1a; color: #4ade80; }

/* ── Sidebar ────────────────────────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background-color: #0d1321;
    border-right: 1px solid #1e2d40;
}
[data-testid="stSidebar"] .stMarkdown p {
    font-size: 0.78rem;
    color: #475569;
    font-family: 'IBM Plex Mono', monospace;
}

/* ── Tabs ───────────────────────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {
    background-color: transparent;
    border-bottom: 1px solid #1e2d40;
    gap: 0.5rem;
}
.stTabs [data-baseweb="tab"] {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.72rem;
    font-weight: 500;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: #475569;
    border-radius: 4px 4px 0 0;
    padding: 0.5rem 1rem;
}
.stTabs [aria-selected="true"] {
    background-color: #111827 !important;
    color: #f59e0b !important;
    border-bottom: 2px solid #f59e0b !important;
}

/* ── Buttons ────────────────────────────────────────────────────────────── */
.stButton > button {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.72rem;
    font-weight: 500;
    letter-spacing: 0.04em;
    border-radius: 5px;
    border: 1px solid #1e2d40;
    background-color: #111827;
    color: #94a3b8;
    transition: all 0.15s ease;
}
.stButton > button:hover {
    border-color: #334155;
    color: #e2e8f0;
    background-color: #1e293b;
}
.stButton > button[kind="primary"] {
    background-color: #f59e0b;
    border-color: #f59e0b;
    color: #0a0e17;
    font-weight: 600;
}
.stButton > button[kind="primary"]:hover {
    background-color: #d97706;
    border-color: #d97706;
    color: #0a0e17;
}

/* ── Data editor ────────────────────────────────────────────────────────── */
[data-testid="stDataFrame"] {
    border: 1px solid #1e2d40;
    border-radius: 8px;
    overflow: hidden;
}

/* ── Input fields ───────────────────────────────────────────────────────── */
.stTextInput input, .stTextArea textarea, .stSelectbox select {
    background-color: #111827 !important;
    border: 1px solid #1e2d40 !important;
    color: #e2e8f0 !important;
    font-family: 'DM Sans', sans-serif;
    border-radius: 6px;
}
.stTextInput input:focus, .stTextArea textarea:focus {
    border-color: #f59e0b !important;
    box-shadow: 0 0 0 1px #f59e0b22 !important;
}

/* ── Divider ────────────────────────────────────────────────────────────── */
hr {
    border-color: #1e2d40;
    margin: 1.25rem 0;
}

/* ── Streamlit element cleanup ──────────────────────────────────────────── */
.block-container { padding-top: 1.5rem; }
footer { display: none; }
#MainMenu { visibility: hidden; }
</style>
""", unsafe_allow_html=True)


# =============================================================================
# HEADER
# =============================================================================

st.markdown(
    f'<div class="main-header">🎯 Job Hunter <span>OSINT</span> Pipeline'
    f'<span style="font-size:0.75rem; color:#475569; float:right; font-weight:400;">'
    f'{date.today().strftime("%A, %B %d %Y")}</span></div>',
    unsafe_allow_html=True,
)

# =============================================================================
# SIDEBAR
# =============================================================================

with st.sidebar:
    st.markdown('<div class="section-label">Filters</div>', unsafe_allow_html=True)
    days_back      = st.slider("Days of history", min_value=1, max_value=14, value=3,
                               help="How many past days of scraped jobs to show")
    priority_only  = st.checkbox("Priority companies only", value=False)

    st.markdown("---")
    st.markdown('<div class="section-label">API Credit Usage</div>', unsafe_allow_html=True)
    st.markdown("Apollo: **50** credits/mo free", unsafe_allow_html=False)
    st.markdown("Hunter: **25** credits/mo free", unsafe_allow_html=False)
    st.markdown("Only enrich roles you genuinely intend to pursue.", unsafe_allow_html=False)

    st.markdown("---")
    if st.button("🔄 Refresh data"):
        st.cache_resource.clear()
        st.rerun()


# =============================================================================
# STATS BAR
# =============================================================================

stats = fetch_stats()
c1, c2, c3, c4 = st.columns(4)

with c1:
    st.markdown(
        f'<div class="stat-card">'
        f'<div class="stat-number">{stats["total_today"]}</div>'
        f'<div class="stat-label">Scraped Today</div></div>',
        unsafe_allow_html=True,
    )
with c2:
    st.markdown(
        f'<div class="stat-card">'
        f'<div class="stat-number gold">{stats["priority_today"]}</div>'
        f'<div class="stat-label">Priority Today</div></div>',
        unsafe_allow_html=True,
    )
with c3:
    st.markdown(
        f'<div class="stat-card">'
        f'<div class="stat-number green">{stats["enriched"]}</div>'
        f'<div class="stat-label">Ready to Contact</div></div>',
        unsafe_allow_html=True,
    )
with c4:
    st.markdown(
        f'<div class="stat-card">'
        f'<div class="stat-number blue">{stats["contacted"]}</div>'
        f'<div class="stat-label">Contacted (All Time)</div></div>',
        unsafe_allow_html=True,
    )

st.markdown("<div style='height:1.25rem'></div>", unsafe_allow_html=True)


# =============================================================================
# TABS
# =============================================================================

tab1, tab2, tab3 = st.tabs([
    "📋  Daily Hopper",
    "✏️  Manual Injection",
    "📊  Outreach History",
])


# ─────────────────────────────────────────────────────────────────────────────
# TAB 1 — DAILY HOPPER
# ─────────────────────────────────────────────────────────────────────────────

with tab1:

    # ── Load data ─────────────────────────────────────────────────────────────
    pending = fetch_pending_jobs(days_back=days_back, priority_only=priority_only)

    # ── Pending / Targeted grid ───────────────────────────────────────────────
    st.markdown('<div class="section-label">Pending Roles — check boxes then hit Run Enrichment</div>',
                unsafe_allow_html=True)

    hopper_jobs = [j for j in pending if j.get("status") in ("pending", "targeted")]

    if not hopper_jobs:
        st.markdown(
            '<p style="color:#475569; font-size:0.85rem; font-style:italic;">'
            'No pending roles. Either the scraper hasn\'t run yet, '
            'or everything has been processed.</p>',
            unsafe_allow_html=True,
        )
    else:
        # Build display dataframe
        rows = []
        for j in hopper_jobs:
            rows.append({
                "_id":       j["id"],
                "Target":    j.get("is_targeted", False),
                "⭐":         j.get("is_priority", False),
                "Company":   j.get("company", ""),
                "Role":      j.get("title", ""),
                "Location":  j.get("location", ""),
                "Source":    j.get("site", ""),
                "Date":      str(j.get("scraped_date", ""))[:10],
                "Link":      j.get("job_url", ""),
            })

        df = pd.DataFrame(rows)

        edited = st.data_editor(
            df,
            column_config={
                "_id":      st.column_config.NumberColumn("ID",     width="small",  disabled=True),
                "Target":   st.column_config.CheckboxColumn("🎯",    width="small"),
                "⭐":        st.column_config.CheckboxColumn("⭐",    width="small",  disabled=True),
                "Company":  st.column_config.TextColumn("Company",  width="medium", disabled=True),
                "Role":     st.column_config.TextColumn("Role",     width="large",  disabled=True),
                "Location": st.column_config.TextColumn("Location", width="medium", disabled=True),
                "Source":   st.column_config.TextColumn("Source",   width="small",  disabled=True),
                "Date":     st.column_config.TextColumn("Date",     width="small",  disabled=True),
                "Link":     st.column_config.LinkColumn("🔗",        width="small",  disabled=True),
            },
            hide_index=True,
            use_container_width=True,
            height=min(400, 56 + len(rows) * 36),
            key="hopper_grid",
        )

        # ── Enrichment button ─────────────────────────────────────────────────
        targeted_ids = edited[edited["Target"] == True]["_id"].tolist()

        st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)
        btn_col, info_col = st.columns([2, 6])

        with btn_col:
            enrich_btn = st.button(
                f"🔍 Run Enrichment  ({len(targeted_ids)} selected)",
                type="primary",
                disabled=(len(targeted_ids) == 0),
                use_container_width=True,
            )
        with info_col:
            if targeted_ids:
                st.markdown(
                    f'<p style="color:#64748b; font-size:0.75rem; font-family: IBM Plex Mono, monospace; '
                    f'padding-top:0.55rem;">Will consume up to {len(targeted_ids)} Apollo + Hunter credits.</p>',
                    unsafe_allow_html=True,
                )

        if enrich_btn and targeted_ids:
            mark_targeted(targeted_ids)
            selected = [j for j in hopper_jobs if j["id"] in targeted_ids]
            bar = st.progress(0, text="Starting enrichment…")

            for idx, job in enumerate(selected):
                bar.progress(
                    (idx + 1) / len(selected),
                    text=f"Enriching {idx+1}/{len(selected)}: {job['company']} — {job['title']}"
                )
                run_enrichment(job)

            bar.empty()
            st.success(f"✅ Enrichment complete for {len(selected)} role(s). See results below.")
            st.rerun()

    # ── Ready to Contact section ───────────────────────────────────────────────
    enriched = fetch_enriched_ready()

    if enriched:
        st.markdown("<hr>", unsafe_allow_html=True)
        st.markdown(
            f'<div class="section-label">Ready to Contact — {len(enriched)} role(s)</div>',
            unsafe_allow_html=True,
        )

        for job in enriched:
            company     = job.get("company", "Unknown")
            title       = job.get("title", "Unknown")
            location    = job.get("location", "")
            is_priority = job.get("is_priority", False)
            source      = job.get("source", "scraper")

            # Pull enrichment record (Supabase returns it as a list)
            enrichment_list = job.get("enriched_jobs") or []
            e = enrichment_list[0] if enrichment_list else {}

            manager_name    = e.get("manager_name")
            manager_title   = e.get("manager_title")
            manager_email   = e.get("manager_email")
            confidence      = e.get("email_confidence") or 0
            email_source    = e.get("email_source", "")
            mailto          = e.get("mailto_link")
            extr_status     = e.get("extraction_status", "no_manager_found")
            email_body      = e.get("personalized_email_body")
            li_search       = e.get("linkedin_search_query")
            li_message      = e.get("linkedin_message")

            priority_class = "priority" if is_priority else ""
            priority_badge = '<span class="badge priority">⭐ Priority</span> ' if is_priority else ""
            manual_badge   = '<span class="badge manual">Manual</span> ' if source == "manual" else ""

            if confidence >= 70:
                conf_icon = "●"; conf_cls = "confidence-high"
            elif confidence >= 40:
                conf_icon = "●"; conf_cls = "confidence-mid"
            else:
                conf_icon = "●"; conf_cls = "confidence-low"

            # ── Top info card ─────────────────────────────────────────────────
            card_html = f"""
<div class="result-card {priority_class}">
  <div style="display:flex; justify-content:space-between; align-items:flex-start;">
    <div>
      <div class="result-company">{priority_badge}{manual_badge}{company}</div>
      <div class="result-title">{title}</div>
      <div class="result-location">{location}</div>
    </div>
    <div style="text-align:right; min-width:220px;">"""

            if manager_name:
                card_html += f"""
      <div class="manager-name">👤 {manager_name}</div>
      <div class="manager-title-text">{manager_title or ''}</div>"""

            if manager_email:
                card_html += f"""
      <div style="margin-top:0.35rem;">
        <div class="email-text">{manager_email}</div>
        <div class="{conf_cls}">{conf_icon} {confidence}% confidence · {email_source}</div>
      </div>"""
            elif extr_status == "no_email_found":
                card_html += '<div class="no-contact" style="margin-top:0.35rem;">Manager found — no email located</div>'
            else:
                card_html += '<div class="no-contact" style="margin-top:0.35rem;">No hiring manager found in JD</div>'

            card_html += "</div></div></div>"
            st.markdown(card_html, unsafe_allow_html=True)

            # ── Action buttons ────────────────────────────────────────────────
            btn1, btn2, btn3, btn4 = st.columns([2, 2, 2, 2])
            with btn1:
                if mailto:
                    st.link_button("✉️ Open in Mail", mailto, use_container_width=True)
            with btn2:
                if st.button("✅ Mark Contacted", key=f"contact_{job['id']}", use_container_width=True):
                    mark_contacted(
                        job_id=job["id"],
                        manager_email=manager_email or "",
                        company=company,
                        title=title,
                    )
                    st.toast(f"Marked {company} as contacted.", icon="✅")
                    st.rerun()
            with btn3:
                if st.button("❌ Reject", key=f"reject_{job['id']}", use_container_width=True):
                    mark_rejected(job["id"])
                    st.toast(f"Rejected {company} — {title}.", icon="🗑️")
                    st.rerun()
            with btn4:
                if st.button("🔄 Re-enrich", key=f"reenrich_{job['id']}", use_container_width=True,
                             help="Delete stale enrichment data and re-run the full pipeline"):
                    from db import get_client as _gc
                    # Delete old enriched_jobs rows for this job
                    _gc().table("enriched_jobs").delete().eq("pending_job_id", job["id"]).execute()
                    # Reset status so it re-enters the pipeline
                    _gc().table("pending_jobs").update(
                        {"status": "pending", "is_targeted": False}
                    ).eq("id", job["id"]).execute()
                    st.toast(f"Reset {company} — check the box in the hopper to re-enrich.", icon="🔄")
                    st.rerun()

            # ── Outreach detail expanders ─────────────────────────────────────
            exp_col1, exp_col2 = st.columns(2)

            # Left: personalized email preview
            with exp_col1:
                with st.expander("📝 Email preview", expanded=False):
                    if email_body:
                        manager_first = (manager_name or "").split()[0] if manager_name else "there"
                        full_preview = (
                            f"**Hi {manager_first},**\n\n"
                            f"{email_body.strip()}\n\n"
                            f"**Best,**  \n**Rish**"
                        )
                        st.markdown(
                            f'<div style="font-size:0.82rem; color:#cbd5e1; '
                            f'line-height:1.7; white-space:pre-wrap;">'
                            f'{email_body.strip()}</div>',
                            unsafe_allow_html=True,
                        )
                        st.caption(
                            "Salutation and sign-off are added automatically when you "
                            "click Open in Mail."
                        )
                    else:
                        st.caption("Email body generation failed — fallback body used.")

            # Right: LinkedIn referral workflow
            with exp_col2:
                with st.expander("🔗 LinkedIn referral", expanded=False):
                    st.markdown(
                        '<div class="section-label" style="margin-bottom:0.5rem;">'
                        'Step 1 — Find a UNC alum at this company</div>',
                        unsafe_allow_html=True,
                    )
                    if li_search:
                        li_url = (
                            "https://www.linkedin.com/search/results/people/?"
                            f"keywords={li_search.replace(' ', '%20')}"
                            "&origin=GLOBAL_SEARCH_HEADER"
                        )
                        st.link_button(
                            "🔍 Search LinkedIn for UNC alumni",
                            li_url,
                            use_container_width=True,
                        )
                        st.markdown(
                            f'<div style="font-family:\'IBM Plex Mono\',monospace; '
                            f'font-size:0.7rem; color:#475569; margin-top:0.35rem;">'
                            f'{li_search}</div>',
                            unsafe_allow_html=True,
                        )
                    else:
                        st.caption("No LinkedIn search query generated.")

                    st.markdown(
                        '<div class="section-label" style="margin:0.75rem 0 0.5rem;">'
                        'Step 2 — Send this connection note</div>',
                        unsafe_allow_html=True,
                    )
                    if li_message:
                        char_count = len(li_message)
                        count_color = "#10b981" if char_count <= 280 else "#ef4444"
                        st.markdown(
                            f'<div style="background:#0d1321; border:1px solid #1e2d40; '
                            f'border-radius:6px; padding:0.75rem 1rem; '
                            f'font-size:0.82rem; color:#e2e8f0; line-height:1.6;">'
                            f'{li_message}</div>'
                            f'<div style="font-family:\'IBM Plex Mono\',monospace; '
                            f'font-size:0.65rem; color:{count_color}; '
                            f'text-align:right; margin-top:0.25rem;">'
                            f'{char_count}/280 chars</div>',
                            unsafe_allow_html=True,
                        )
                        # Copy-to-clipboard via a selectbox workaround
                        st.code(li_message, language=None)
                        st.caption("Select all and copy the text above to paste into LinkedIn.")
                    else:
                        st.caption("LinkedIn message generation failed.")

            st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# TAB 2 — MANUAL INJECTION
# ─────────────────────────────────────────────────────────────────────────────

with tab2:
    st.markdown(
        '<div class="section-label">Manually Add a Role</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p style="color:#64748b; font-size:0.82rem; margin-bottom:1.25rem;">'
        'For roles found on X, Discord, Slack, or niche company career pages that '
        'the scraper won\'t catch. A complete job description gives Claude '
        'more text to extract the hiring manager\'s name from.</p>',
        unsafe_allow_html=True,
    )

    col_form, col_tip = st.columns([3, 2])

    with col_form:
        company_in = st.text_input(
            "Company",
            placeholder="e.g. Citadel",
            key="manual_company",
        )
        title_in = st.text_input(
            "Job Title",
            placeholder="e.g. Quantitative Researcher Intern 2026",
            key="manual_title",
        )
        jd_in = st.text_area(
            "Full Job Description",
            placeholder="Paste the complete job description here.\n\n"
                        "The richer the text, the better Claude can identify the hiring manager.\n"
                        "Include any 'About the team' or 'Who you'll work with' sections.",
            height=320,
            key="manual_jd",
        )

        st.markdown("<div style='height:0.25rem'></div>", unsafe_allow_html=True)

        can_submit = bool(company_in and title_in and jd_in)
        submitted  = st.button(
            "➕ Add to Pipeline",
            type="primary",
            disabled=not can_submit,
            use_container_width=False,
        )

        if submitted and can_submit:
            insert_manual_job(company_in.strip(), title_in.strip(), jd_in.strip())
            st.success(
                f"✅ **{title_in.strip()}** at **{company_in.strip()}** added. "
                f"It will appear in the Daily Hopper — check the box and run enrichment when ready."
            )
            # Clear inputs by incrementing a key suffix via session state
            for k in ["manual_company", "manual_title", "manual_jd"]:
                if k in st.session_state:
                    del st.session_state[k]
            st.rerun()

    with col_tip:
        st.markdown("""
<div style="background:#111827; border:1px solid #1e2d40; border-radius:8px; padding:1.25rem; margin-top:1.6rem;">
  <div style="font-family:'IBM Plex Mono',monospace; font-size:0.65rem; color:#475569;
              text-transform:uppercase; letter-spacing:0.1em; margin-bottom:0.75rem;">
    Tips for better extraction
  </div>
  <ul style="color:#64748b; font-size:0.78rem; padding-left:1rem; margin:0; line-height:1.8;">
    <li>Include the full "About the team" section — it often names the manager</li>
    <li>Look for "You'll work with [Name]" or "Reporting to [Name]"</li>
    <li>Add any LinkedIn post text announcing the role</li>
    <li>If you already know the manager's name, add a line like<br>
        <code style="color:#f59e0b; font-size:0.72rem;">Hiring manager: Jane Smith, Head of ML</code></li>
  </ul>
</div>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# TAB 3 — OUTREACH HISTORY
# ─────────────────────────────────────────────────────────────────────────────

with tab3:
    st.markdown('<div class="section-label">All-Time Outreach Log</div>', unsafe_allow_html=True)

    history = fetch_history()

    if not history:
        st.markdown(
            '<p style="color:#475569; font-size:0.85rem; font-style:italic;">'
            'No outreach logged yet. Mark roles as Contacted from the Daily Hopper.</p>',
            unsafe_allow_html=True,
        )
    else:
        rows = []
        for h in history:
            parent = h.get("pending_jobs") or {}
            rows.append({
                "Date":    str(h.get("contacted_at", ""))[:10],
                "Company": parent.get("company", h.get("company", "—")),
                "Role":    parent.get("title",   h.get("title",   "—")),
                "Email":   h.get("manager_email", "—"),
                "Source":  parent.get("site", "—"),
                "Link":    parent.get("job_url", ""),
                "Notes":   h.get("notes", ""),
            })

        history_df = pd.DataFrame(rows)

        st.dataframe(
            history_df,
            column_config={
                "Date":    st.column_config.TextColumn("Date",    width="small"),
                "Company": st.column_config.TextColumn("Company", width="medium"),
                "Role":    st.column_config.TextColumn("Role",    width="large"),
                "Email":   st.column_config.TextColumn("Email",   width="medium"),
                "Source":  st.column_config.TextColumn("Source",  width="small"),
                "Link":    st.column_config.LinkColumn("🔗",       width="small"),
                "Notes":   st.column_config.TextColumn("Notes",   width="medium"),
            },
            hide_index=True,
            use_container_width=True,
            height=min(500, 56 + len(rows) * 36),
        )

        # ── Summary metrics ──────────────────────────────────────────────────
        st.markdown("<hr>", unsafe_allow_html=True)
        m1, m2, m3 = st.columns(3)

        with m1:
            st.metric("Total Outreach", len(rows))
        with m2:
            unique_companies = history_df["Company"].nunique()
            st.metric("Unique Companies", unique_companies)
        with m3:
            this_week = history_df[history_df["Date"] >= str(
                date.today().isocalendar()[0]
            )].shape[0] if rows else 0
            st.metric("This Week", this_week)