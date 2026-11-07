# JobBot

Daily job scraper. Every day at 12:00 UTC, a GitHub Action:

1. Scrapes LinkedIn / Indeed / Google Jobs (via jobspy) plus the Greenhouse, Lever and Ashby job boards listed in `job_bot.py`.
2. Keeps entry-level, US-based AI/ML/data roles at companies in `PRIORITY_COMPANIES` or `fortune1000.csv`.
3. Drops anything already sent in a previous digest (tracked in Supabase).
4. Saves the new roles to Supabase and emails you an HTML digest.

`streamlit_app/` is an optional dashboard and is not needed for the daily email.

## Restarting an existing setup

1. **Supabase:** open the project in the dashboard and click **Restore** if it is paused. To start the history fresh, run `truncate table pending_jobs cascade;` in the SQL Editor. This also empties the dashboard tables that reference it (`enriched_jobs`, `contacted_history`). The next digest will then include every currently matching role.
2. **GitHub Actions:** GitHub disables scheduled workflows after 60 days without repo activity. Go to **Actions → Daily Job Scraper** and click **Enable workflow** if a banner says it is disabled.
3. Push to `main`, then click **Run workflow** to test.

If the old Supabase project is gone, follow the full setup below and update the two `SUPABASE_*` secrets.

## Setup from scratch

### 1. Supabase (job history)

1. Create a project at https://supabase.com (the free tier is fine).
2. Open **SQL Editor** and run:

   ```sql
   create table if not exists pending_jobs (
     id            bigint generated always as identity primary key,
     scraped_date  date,
     title         text not null,
     company       text not null,
     location      text,
     site          text,
     job_url       text,
     description   text,
     is_priority   boolean default false,
     is_targeted   boolean default false,
     source        text,
     status        text default 'pending',
     created_at    timestamptz default now(),
     unique (company, title)
   );

   -- Block public (anon-key) access. The scraper uses the service-role key,
   -- which bypasses RLS.
   alter table pending_jobs enable row level security;
   ```

3. Go to **Project Settings → API** and copy:
   - the **Project URL** → `SUPABASE_URL`
   - the **service_role** key → `SUPABASE_SERVICE_KEY`. If the newer `sb_secret_...` key is rejected, use the legacy service_role JWT under "Legacy API keys".

Free-tier projects get paused after a period of inactivity. If the digest log shows `Could not load job history`, open the Supabase dashboard and restore the project.

### 2. Gmail app password (sending the email)

1. Turn on 2-Step Verification for the sending Google account.
2. Create an app password at https://myaccount.google.com/apppasswords.
3. Use the 16-character password as `EMAIL_PASS`. Your normal Gmail password will not work.

### 3. GitHub repository secrets

In the repo, go to **Settings → Secrets and variables → Actions → New repository secret** and add:

| Secret | Value |
|---|---|
| `EMAIL_USER` | Gmail address that sends the digest |
| `EMAIL_PASS` | Gmail app password from step 2 |
| `EMAIL_RECEIVER` | Address that receives the digest |
| `SUPABASE_URL` | Project URL from step 1 |
| `SUPABASE_SERVICE_KEY` | service_role key from step 1 |

### 4. Run it

- Push to `main`. Scheduled workflows only run from the default branch.
- **Actions → Daily Job Scraper → Run workflow** triggers a run manually. The first run takes about 5 minutes because of the sleeps between jobspy batches.
- Check the run log for `Loaded N previously seen jobs`, `After history dedup`, and `Email sent`.

### Run locally (optional)

```bash
pip install -r requirements.txt
export EMAIL_USER=... EMAIL_PASS=... EMAIL_RECEIVER=... SUPABASE_URL=... SUPABASE_SERVICE_KEY=...
python job_bot.py
```

## Tuning

All settings are at the top of `job_bot.py`:

- `KEYWORDS`: search terms for jobspy.
- `PRIORITY_COMPANIES`: highlighted in gold in the email; always pass the company filter.
- `GREENHOUSE_COMPANIES` / `LEVER_COMPANIES` / `ASHBY_COMPANIES`: company → job-board slug.
- `EXCLUDE_TITLE_TERMS`: seniority/intern/PhD words that reject a title.
- `MAX_YEARS_EXPERIENCE`: roles requiring more years than this are dropped.
- Schedule: the `cron` line in `.github/workflows/daily_scrape.yml`.

To re-send everything (for example, after changing filters), delete rows from `pending_jobs` in Supabase.
