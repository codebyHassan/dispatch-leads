import csv
import json
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from carriers.filters import apply_carrier_filters
from carriers.models import Carrier, FilterAlert, SavedFilter
from crm.models import Activity, Lead, Note
from sync.services import refresh_single_carrier

SORT_OPTIONS = [
    ("-authority_grant_date", "MC Age: Newest First"),
    ("authority_grant_date", "MC Age: Oldest First"),
    ("legal_name", "Legal Name (A–Z)"),
    ("-legal_name", "Legal Name (Z–A)"),
    ("-power_units", "Power Units (High–Low)"),
    ("power_units", "Power Units (Low–High)"),
    ("-drivers", "Drivers (High–Low)"),
    ("state", "State (A–Z)"),
    ("dot_number", "DOT Number"),
    ("mc_number", "MC Number"),
    ("-last_synced_at", "Recently Synced"),
]


def _ensure_default_presets(user):
    if SavedFilter.objects.filter(user=user).exists():
        return
    defaults = [
        ("New MC under 90 days", "mc_age_max=90&mc_age_unit=days&authority_status=Active"),
        ("Small fleet 1-5 trucks Texas", "power_min=1&power_max=5&state=TX&authority_status=Active"),
        ("Insurance Expiring <30d", "insurance_expiring=30&authority_status=Active"),
    ]
    for name, qstr in defaults:
        sf = SavedFilter.objects.create(user=user, name=name, query_string=qstr)
        qd = QueryDict(qstr)
        cnt = apply_carrier_filters(Carrier.objects.all(), qd, user=user).count()
        FilterAlert.objects.create(saved_filter=sf, new_count=cnt)


def _write_carriers_csv_response(carriers_iterable, filename: str = "carriers.csv") -> HttpResponse:
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow(
        [
            "DOT Number",
            "MC Number",
            "Legal Name",
            "DBA Name",
            "Authority Status",
            "Authority Type",
            "Authority Grant Date",
            "MC Age (Days)",
            "Power Units",
            "Drivers",
            "Trailers",
            "Operation Type",
            "Cargo Types",
            "State",
            "City",
            "ZIP",
            "Address",
            "Phone (E.164)",
            "Email",
            "Website",
            "Safety Rating",
            "OOS %",
            "Crashes (24m)",
            "Inspections (24m)",
            "Insurance On File",
            "Insurance Amount",
            "Insurance Expiry",
            "Last Synced At",
        ]
    )
    for c in carriers_iterable:
        writer.writerow(
            [
                c.dot_number,
                c.mc_number,
                c.legal_name,
                c.dba_name,
                c.authority_status,
                c.authority_type,
                c.authority_grant_date.isoformat() if c.authority_grant_date else "",
                c.mc_age_days if c.mc_age_days is not None else "",
                c.power_units,
                c.drivers,
                c.trailers,
                c.operation_type,
                ", ".join(c.cargo_types or []),
                c.state,
                c.city,
                c.zip_code,
                c.address,
                c.phone_e164 or c.phone,
                c.email if c.email_valid else "",
                c.website,
                c.safety_rating,
                c.oos_percent,
                c.crash_count_24m,
                c.inspection_count_24m,
                "Yes" if c.insurance_on_file else "No",
                c.insurance_amount,
                c.insurance_expiry.isoformat() if c.insurance_expiry else "",
                c.last_synced_at.strftime("%Y-%m-%d %H:%M:%S") if c.last_synced_at else "",
            ]
        )
    return response


@login_required
def carrier_list_view(request):
    """
    Main Carrier Search view with 10-group left filter panel, MC age filtering,
    saved filters, sorting, pagination, and bulk actions.
    """
    _ensure_default_presets(request.user)

    qs = apply_carrier_filters(Carrier.objects.all(), request.GET, user=request.user)

    sort_param = (request.GET.get("sort") or "-authority_grant_date").strip()
    allowed_sorts = {
        "dot_number", "-dot_number",
        "mc_number", "-mc_number",
        "legal_name", "-legal_name",
        "state", "-state",
        "power_units", "-power_units",
        "drivers", "-drivers",
        "authority_grant_date", "-authority_grant_date",
        "authority_status", "-authority_status",
        "safety_rating", "-safety_rating",
        "last_synced_at", "-last_synced_at",
    }
    if sort_param not in allowed_sorts:
        sort_param = "-authority_grant_date"
    qs = qs.order_by(sort_param, "id")

    per_page_str = request.GET.get("per_page", "25")
    per_page = int(per_page_str) if per_page_str in {"25", "50", "100"} else 25

    paginator = Paginator(qs, per_page)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    page_carrier_ids = [c.id for c in page_obj.object_list]
    user_leads = {
        ld.carrier_id: ld
        for ld in Lead.objects.filter(
            owner=request.user, carrier_id__in=page_carrier_ids
        )
    }
    for c in page_obj.object_list:
        c.user_lead = user_leads.get(c.id)

    saved_filters = SavedFilter.objects.filter(user=request.user).select_related("alert")

    sf_id = request.GET.get("saved_filter_id")
    if sf_id and sf_id.isdigit():
        FilterAlert.objects.filter(
            saved_filter_id=int(sf_id), saved_filter__user=request.user
        ).update(new_count=0, last_seen_at=timezone.now())

    query_without_page = request.GET.copy()
    query_without_page.pop("page", None)
    query_without_page.pop("saved_filter_id", None)

    query_without_sort = query_without_page.copy()
    query_without_sort.pop("sort", None)

    return render(
        request,
        "carriers/list.html",
        {
            "page_obj": page_obj,
            "total_count": paginator.count,
            "per_page": per_page,
            "sort": sort_param,
            "sort_options": SORT_OPTIONS,
            "saved_filters": saved_filters,
            "query_string": query_without_page.urlencode(),
            "query_without_sort": query_without_sort.urlencode(),
            "params": request.GET,
        },
    )


@login_required
def save_filter_view(request):
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        query_string = (request.POST.get("query_string") or "").strip()
        if not name:
            messages.error(request, "Please provide a name for the saved filter.")
        else:
            sf, _ = SavedFilter.objects.update_or_create(
                user=request.user,
                name=name,
                defaults={"query_string": query_string},
            )
            qd = QueryDict(query_string)
            cnt = apply_carrier_filters(Carrier.objects.all(), qd, user=request.user).count()
            FilterAlert.objects.update_or_create(
                saved_filter=sf,
                defaults={"new_count": 0, "last_seen_at": timezone.now()},
            )
            messages.success(
                request, f"Saved filter preset '{name}' ({cnt} matching carriers)."
            )
            return redirect(f"/carriers/?{query_string}&saved_filter_id={sf.pk}")
    return redirect("carrier_list")


@login_required
def delete_saved_filter_view(request, filter_id: int):
    if request.method == "POST":
        SavedFilter.objects.filter(pk=filter_id, user=request.user).delete()
        messages.success(request, "Saved filter deleted.")
    return redirect("carrier_list")


@login_required
def bulk_carrier_action_view(request):
    if request.method != "POST":
        return redirect("carrier_list")

    action = (request.POST.get("bulk_action") or "").strip()
    dots = request.POST.getlist("selected_dots")
    return_query = (request.POST.get("return_query") or "").strip()
    redirect_url = f"/carriers/?{return_query}" if return_query else "/carriers/"

    if not dots:
        messages.error(request, "Select at least one carrier row first.")
        return redirect(redirect_url)

    # Exclude Do Not Contact carriers from bulk add & export per PRD 5.7
    dnc_carrier_ids = set(
        Lead.objects.filter(status="Do Not Contact").values_list("carrier_id", flat=True)
    )
    selected_carriers = list(Carrier.objects.filter(dot_number__in=dots))

    if action == "add_to_leads":
        added = 0
        skipped_existing = 0
        skipped_dnc = 0
        for c in selected_carriers:
            if c.id in dnc_carrier_ids:
                skipped_dnc += 1
                continue
            lead, created = Lead.objects.get_or_create(
                carrier=c,
                owner=request.user,
                defaults={
                    "status": "New",
                    "expected_trucks": max(1, c.power_units),
                },
            )
            if created:
                lead.refresh_score()
                Activity.objects.create(
                    lead=lead,
                    type="system",
                    body=f"Lead created via bulk action from Carrier Search (DOT #{c.dot_number}).",
                )
                added += 1
            else:
                skipped_existing += 1
        messages.success(
            request,
            f"Bulk Add to Leads: {added} created, {skipped_existing} already in pipeline"
            + (f", {skipped_dnc} skipped (Do Not Contact)." if skipped_dnc else "."),
        )
        return redirect(redirect_url)

    elif action == "refresh_data":
        refreshed = 0
        changed_total = 0
        for c in selected_carriers[:50]:
            _, changes, _ = refresh_single_carrier(c, force=True)
            refreshed += 1
            changed_total += len(changes)
        messages.success(
            request,
            f"Bulk Refreshed {refreshed} carrier(s) ({changed_total} field change(s) recorded).",
        )
        return redirect(redirect_url)

    elif action == "export_csv":
        exportable = [c for c in selected_carriers if c.id not in dnc_carrier_ids]
        return _write_carriers_csv_response(exportable, filename="carriers_selected.csv")

    return redirect(redirect_url)


@login_required
def export_carriers_csv_view(request):
    """Export all carriers matching current URL filters to CSV (excluding DNC)."""
    qs = apply_carrier_filters(Carrier.objects.all(), request.GET, user=request.user)
    sort_param = (request.GET.get("sort") or "-authority_grant_date").strip()
    qs = qs.order_by(sort_param, "id")[:10000]
    return _write_carriers_csv_response(qs.iterator(chunk_size=1000), filename="carriers.csv")


@login_required
def carrier_detail_view(request, dot: str):
    carrier = get_object_or_404(Carrier, dot_number=dot)
    lead = Lead.objects.filter(carrier=carrier, owner=request.user).first()
    changes = carrier.changes.all()[:50]

    dup_q = Q()
    if carrier.phone_e164:
        dup_q |= Q(phone_e164=carrier.phone_e164)
    if carrier.email and carrier.email_valid:
        dup_q |= Q(email=carrier.email)
    duplicate_carriers = (
        Carrier.objects.filter(dup_q).exclude(pk=carrier.pk)[:5] if dup_q else []
    )

    return render(
        request,
        "carriers/detail.html",
        {
            "carrier": carrier,
            "lead": lead,
            "changes": changes,
            "duplicate_carriers": duplicate_carriers,
            "raw_json_pretty": json.dumps(carrier.raw_json or {}, indent=2, default=str),
        },
    )


@login_required
def carrier_refresh_view(request, dot: str):
    carrier = get_object_or_404(Carrier, dot_number=dot)
    if request.method == "POST":
        updated, changes, source_used = refresh_single_carrier(carrier, force=True)
        if changes:
            messages.success(
                request,
                f"Refreshed DOT #{updated.dot_number} via {source_used} ({len(changes)} field change(s) logged).",
            )
        else:
            messages.success(
                request,
                f"Refreshed DOT #{updated.dot_number} via {source_used} (all fields up to date).",
            )
    return redirect("carrier_detail", dot=carrier.dot_number)


@login_required
def global_search_view(request):
    q = (request.GET.get("q") or "").strip()
    carriers_found = []
    leads_found = []
    notes_found = []

    if q:
        carriers_found = Carrier.objects.filter(
            Q(legal_name__icontains=q)
            | Q(dba_name__icontains=q)
            | Q(dot_number__icontains=q)
            | Q(mc_number__icontains=q)
            | Q(phone__icontains=q)
            | Q(phone_e164__icontains=q)
            | Q(email__icontains=q)
        )[:30]

        leads_found = (
            Lead.objects.select_related("carrier")
            .filter(owner=request.user)
            .filter(
                Q(carrier__legal_name__icontains=q)
                | Q(carrier__dot_number__icontains=q)
                | Q(carrier__mc_number__icontains=q)
                | Q(carrier__phone_e164__icontains=q)
                | Q(carrier__email__icontains=q)
                | Q(tags__icontains=q)
            )[:30]
        )

        notes_found = (
            Note.objects.select_related("lead", "lead__carrier")
            .filter(lead__owner=request.user, body__icontains=q)[:30]
        )

    return render(
        request,
        "carriers/global_search.html",
        {
            "q": q,
            "carriers_found": carriers_found,
            "leads_found": leads_found,
            "notes_found": notes_found,
        },
    )
