import csv
import json
import os
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render

from carriers.models import Carrier
from crm.models import Activity, Lead
from pdf_register_scraper import enrich_pdf_rows_batch, parse_fmcsa_register_pdf


@login_required
def pdf_scraper_web_view(request):
    """
    Dedicated FMCSA Register PDF Uploader & Live Multi-Source Enricher Page (/pdf-scraper/).
    """
    return render(request, "carriers/pdf_scraper.html")


@login_required
def api_process_register_pdf(request):
    """
    Accepts an uploaded FMCSA Register PDF (`pdf_file` in request.FILES) or `use_sample=1`,
    parses all applicant rows across all pages (<0.3s), and enriches every row with
    LIVE FMCSA data NOT present in the PDF:
      - MC / Docket Number (`MC-XXXXXXX`)
      - Official Email Address
      - Verified Company Officer / Owner Name (replaces `undefined undefined`)
      - Authority Status (`ACTIVE`, `PENDING`, `NOT ACTIVE`)
      - Exact Entity Type (`CARRIER`, `CARRIER/BROKER`, `BROKER`, `FREIGHT FORWARDER`)
      - BIPD / Broker Bond Insurance Status & Dollar Amount
      - Power Units (Trucks) & Total Drivers
      - MC Age (Months)
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    auto_add_leads = request.POST.get("auto_add_leads") in ["true", "1", "on", True]
    use_sample = request.POST.get("use_sample") in ["true", "1", True]

    pdf_source = None
    filename = "FMCSA_Register.pdf"

    if "pdf_file" in request.FILES:
        uploaded = request.FILES["pdf_file"]
        filename = uploaded.name
        if not filename.lower().endswith(".pdf"):
            return JsonResponse({"error": "Please upload a valid .pdf file."}, status=400)
        pdf_source = uploaded.read()
    elif use_sample:
        sample_path = os.path.join(settings.BASE_DIR, "static", "REGISTER20260901.pdf")
        if os.path.exists(sample_path):
            pdf_source = sample_path
            filename = "REGISTER20260901.pdf"

    if not pdf_source:
        return JsonResponse(
            {"error": "Please select an FMCSA Register PDF file to upload."},
            status=400,
        )

    try:
        parsed = parse_fmcsa_register_pdf(pdf_source)
    except Exception as exc:
        return JsonResponse(
            {"error": f"Failed to parse PDF file: {exc}"},
            status=400,
        )

    raw_rows = parsed.get("rows", [])
    if not raw_rows:
        return JsonResponse(
            {"error": "No valid USDOT applicant rows were found in this PDF."},
            status=400,
        )

    # Enrich all extracted rows from live FMCSA Census & L&I registries in parallel batches
    enriched = enrich_pdf_rows_batch(raw_rows, max_workers=30)

    # Optionally import enriched carriers into CRM Leads Pipeline
    imported_count = 0
    if auto_add_leads:
        for r in enriched:
            dot = r.get("dot_number")
            if not dot:
                continue
            carrier, _ = Carrier.objects.update_or_create(
                dot_number=dot,
                defaults={
                    "mc_number": r.get("mc_number") or "",
                    "legal_name": r.get("legal_name") or f"USDOT {dot}",
                    "dba_name": r.get("dba_name") or "",
                    "phone": r.get("phone") or "",
                    "phone_e164": r.get("phone") or "",
                    "email": r.get("email") or "",
                    "state": r.get("state") or "",
                    "city": r.get("city") or "",
                    "power_units": r.get("power_units") or 0,
                    "drivers": r.get("drivers") or 0,
                    "authority_status": "Active" if r.get("is_active") else "Inactive",
                },
            )
            lead, created = Lead.objects.get_or_create(
                carrier=carrier,
                owner=request.user,
                defaults={
                    "status": "New",
                    "source": f"PDF Register Enricher ({filename})",
                },
            )
            if created:
                lead.refresh_score(save=True)
                Activity.objects.create(
                    lead=lead,
                    type="system",
                    body=(
                        f"Imported & enriched from FMCSA Register PDF ({filename}, Page {r.get('page')}): "
                        f"USDOT {dot} | MC: {r.get('mc_number') or 'Pending'} | "
                        f"Email: {r.get('email') or 'N/A'} | Status: {r.get('status_label')}"
                    ),
                )
                imported_count += 1

    total = len(enriched)
    mc_found_count = sum(1 for r in enriched if r.get("mc_number"))
    email_found_count = sum(1 for r in enriched if r.get("email"))
    active_count = sum(1 for r in enriched if r.get("is_active"))
    pending_count = total - active_count
    carrier_count = sum(1 for r in enriched if "CARRIER" in r.get("entity_type", ""))
    broker_count = sum(1 for r in enriched if "BROKER" in r.get("entity_type", ""))
    recovered_officers = sum(1 for r in enriched if r.get("officer_recovered"))

    return JsonResponse({
        "success": True,
        "filename": filename,
        "num_pages": parsed.get("num_pages", 0),
        "release_date_notice": parsed.get("release_date_notice", ""),
        "total": total,
        "mc_found_count": mc_found_count,
        "email_found_count": email_found_count,
        "active_count": active_count,
        "pending_count": pending_count,
        "carrier_count": carrier_count,
        "broker_count": broker_count,
        "recovered_officers": recovered_officers,
        "imported_count": imported_count,
        "results": enriched,
    })


@login_required
def export_pdf_enriched_csv_view(request):
    """Downloads all PDF-extracted + Live-FMCSA-enriched rows as a complete CSV file."""
    if request.method != "POST":
        return HttpResponse("POST required", status=405)

    raw_json = request.POST.get("results_json", "[]")
    try:
        data = json.loads(raw_json)
    except Exception:
        data = []

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="fmcsa_pdf_enriched_leads.csv"'
    writer = csv.writer(response)
    writer.writerow([
        "PDF Page",
        "USDOT Number",
        "MC Number (Live Enriched)",
        "Entity Type",
        "PDF Category",
        "Authority Status (Live)",
        "Insurance / Bond (Live)",
        "Company Legal Name",
        "DBA Name (Live)",
        "Owner / Officer Name",
        "Business Phone",
        "Cell Phone (Live)",
        "Official Email (Live Enriched)",
        "MC Age (Months)",
        "Filing Date",
        "City",
        "State",
        "ZIP",
        "Full Mailing Address",
        "Trucks / Power Units (Live)",
        "Drivers (Live)",
        "Cargo Carried (Live)",
    ])
    for r in data:
        writer.writerow([
            r.get("page"),
            r.get("dot_number"),
            f"MC-{r['mc_number']}" if r.get("mc_number") else "Pending Docket",
            r.get("entity_type"),
            r.get("pdf_category"),
            r.get("status_label"),
            r.get("insurance_status"),
            r.get("legal_name"),
            r.get("dba_name"),
            r.get("owner_name"),
            r.get("phone"),
            r.get("cell_phone"),
            r.get("email"),
            r.get("mc_age_months"),
            r.get("filing_date"),
            r.get("city"),
            r.get("state"),
            r.get("zip_code"),
            r.get("address"),
            r.get("power_units"),
            r.get("drivers"),
            r.get("cargo_carried"),
        ])
    return response

