# Truck Dispatch Lead Finder & CRM

A web tool for truck dispatch sales agents to discover dispatch-ready US trucking companies from public transport sources, filter carriers with sub-second queries, and manage deals inside a built-in sales CRM.

---

## 3 Quick-Start Commands

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run database migrations and seed 10,000 realistic US carriers
python manage.py migrate
python manage.py import_carriers --count 10000 --mode seed

# 3. Start local development server
python manage.py runserver
```

Open `http://127.0.0.1:8000/` in your browser.
- **Default Sign In:** `admin` / `admin123`

---

## Key Features

1. **Carrier Search & Sub-Second Filtering:**
   - 10 comprehensive filter groups: Identity, Authority, MC Age (days/months/years with `<90d` **NEW** badge), Location & ZIP radius, Fleet Size, Operation & Cargo types, Safety & OOS %, Insurance & Expiry Window, Contact Completeness, and Lead Pipeline status.
   - Default view automatically hides carriers marked **Do Not Contact**.
   - Server-side sorting, pagination (`25`, `50`, `100`), bookmarkable URLs, and saved filter presets with `FilterAlert` indicators.
   - Bulk actions: Add to Leads (with duplicate & DNC protection), Export Filtered CSV, and Bulk Refresh.

2. **Mini CRM & Sales Pipeline:**
   - Visual Kanban Board and Table List views across all pipeline stages (`New`, `Contacted`, `Interested`, `Negotiation`, `Signed`, `Rejected`, `Do Not Contact`).
   - Read-only **All Carrier Info Panel** with quick copy buttons, `Missing` badges, and contact completeness counters (`X/7 fields`).
   - **Pakistan to US Timezone Intelligence:** Shows live carrier local time with dynamic **"Good time to call" (9 AM – 5 PM)** badge and dual-timezone task due dates.
   - **Manual Enrichment Protection:** User-added phones, emails, websites, and owner names are flagged `added_by_user=True` with audit logging and will **never** be overwritten by background sync jobs.
   - **Call Scripts & Templates:** Auto-populates `{carrier_name}`, `{mc_number}`, `{dot_number}`, `{state}`, and `{power_units}` with 1-click clipboard copy.
   - Notes with pin-to-top, activity timeline, 2-day follow-up cadence automation on `Contacted`, repeating tasks, and reasons for loss tracking.

3. **Data Connectors, Proxy & US Compliance:**
   - **FMCSA Socrata API (`az4n-8mr2`):** Bulk import of carrier census and authority filings.
   - **FMCSA QCMobile API:** Real-time per-carrier lookup via official WebKey.
   - **FMCSA SAFER Snapshot:** HTML fallback parser.
   - **Pakistan VPN / Proxy Settings:** Configurable HTTP/SOCKS5 proxy, timeout, and request delay under `/settings/`.
   - Built-in connection diagnostic tester with geo-block detection.
   - 1-Click SQLite database backup download under `/backup/db/`.

---

## Unit Testing

Run the test suite covering MC age calculations, filter queries, connector normalization, duplicate protection, and CRM workflows:

```bash
python manage.py test
```

