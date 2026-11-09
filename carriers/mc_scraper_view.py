import csv
import json
import re
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from multi_source_scraper import scrape_mc_batch_real
from carriers.models import Carrier
from crm.models import Lead, Activity


@login_required
def mc_scraper_web_view(request):
    """
    Dedicated Web Scraper with:
    1. Single MC + Next Count (e.g. 1811001 + next 100/200 MCs automatically generated)
    2. Direct List of MCs
    3. AJAX JSON streaming endpoint for animated loader
    4. Entity Type (Carrier / Broker / Forwarder)
    5. Clear "NOT ACTIVE" / "ACTIVE" Badges
    6. Insurance on file status ($1M BIPD)
    7. CSV Download & Auto-Lead Import
    """
    return render(request, "carriers/mc_scraper.html")


@login_required
def api_scrape_mc_batch(request):
    """
    High-speed AJAX API endpoint that accepts:
    - start_mc: integer (e.g. 1811001)
    - count: integer (e.g. 50, 100, 200, 500)
    - mc_list: optional custom comma-separated list
    - auto_add_leads: boolean
    Returns live JSON payload with full carrier/broker details and active/not-active status.
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else {}
    except Exception:
        data = request.POST

    start_mc_raw = str(data.get("start_mc") or "").strip()
    count = int(data.get("count") or 50)
    count = max(1, min(1000, count))  # Limit batch to 1000 per scrape
    raw_custom_mcs = str(data.get("custom_mcs") or "").strip()
    auto_add_leads = bool(data.get("auto_add_leads", False))

    mc_list = []

    # Mode 1: Start MC + Next Count (e.g. 1811001 -> 1811002, 1811003...)
    if start_mc_raw:
        clean_start = re.sub(r"\D", "", start_mc_raw)
        if clean_start.isdigit():
            base_num = int(clean_start)
            mc_list = [str(base_num + i) for i in range(count)]

    # Mode 2: Custom List or Paste
    if not mc_list and raw_custom_mcs:
        found = re.findall(r"\b\d{5,8}\b", raw_custom_mcs)
        mc_list = list(dict.fromkeys(found))[:count]

    if not mc_list:
        return JsonResponse({"error": "Please provide a valid Starting MC number (e.g. 1811001) or a list of MCs."}, status=400)

    # Scrape 100% REAL FMCSA L&I government registry concurrently across 50 workers
    results = scrape_mc_batch_real(mc_list=mc_list, max_workers=50)

    # Auto import into CRM if requested
    imported_count = 0
    if auto_add_leads:
        for r in results:
            dot = r.get("dot_number") or f"MC{r['mc_number']}"
            carrier, _ = Carrier.objects.update_or_create(
                dot_number=dot,
                defaults={
                    "mc_number": r["mc_number"],
                    "legal_name": r["legal_name"] or f"MC {r['mc_number']}",
                    "dba_name": r.get("dba_name", ""),
                    "phone": r.get("phone", ""),
                    "phone_e164": r.get("phone", ""),
                    "email": r.get("email", ""),
                    "state": r.get("state", ""),
                    "city": r.get("city", ""),
                    "power_units": r.get("power_units", 0),
                    "drivers": r.get("drivers", 0),
                    "authority_status": "Active" if r.get("is_active") else "Inactive",
                }
            )
            lead, created = Lead.objects.get_or_create(
                carrier=carrier,
                owner=request.user,
                defaults={"status": "New", "source": "Multi-Source MC Scraper"}
            )
            if created:
                lead.refresh_score(save=True)
                Activity.objects.create(
                    lead=lead,
                    type="system",
                    body=f"Created via Bulk MC Scraper tool (MC #{r['mc_number']} - {r['entity_type']} - Status: {r['status_label']})."
                )
                imported_count += 1

    active_count = sum(1 for r in results if r.get("is_active"))
    not_active_count = len(results) - active_count
    broker_count = sum(1 for r in results if "Broker" in r.get("entity_type", ""))
    carrier_count = len(results) - broker_count

    return JsonResponse({
        "success": True,
        "total": len(results),
        "active_count": active_count,
        "not_active_count": not_active_count,
        "carrier_count": carrier_count,
        "broker_count": broker_count,
        "imported_count": imported_count,
        "results": results,
    })


@login_required
def export_scraped_csv_view(request):
    """Downloads scraped MC records as formatted CSV."""
    if request.method != "POST":
        return HttpResponse("POST required", status=405)

    raw_json = request.POST.get("results_json", "[]")
    try:
        data = json.loads(raw_json)
    except Exception:
        data = []

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="scraped_mc_leads.csv"'
    writer = csv.writer(response)
    writer.writerow([
        "MC Number", "DOT Number", "Entity Type", "Authority Status",
        "Insurance Status", "Company Legal Name", "DBA Name", "Owner / Officer", "Phone (Direct)",
        "Email", "MC Age (Months)", "Issue Date", "State", "City", "Trucks (PU)", "Drivers", "Source"
    ])
    for r in data:
        writer.writerow([
            r.get("mc_number"),
            r.get("dot_number"),
            r.get("entity_type"),
            r.get("status_label"),
            r.get("insurance_status"),
            r.get("legal_name"),
            r.get("dba_name"),
            r.get("owner_name"),
            r.get("phone"),
            r.get("email"),
            r.get("mc_age_months"),
            r.get("grant_date"),
            r.get("state"),
            r.get("city"),
            r.get("power_units"),
            r.get("drivers"),
            r.get("source"),
        ])
    return response
