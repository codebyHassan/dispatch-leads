import csv
import io
from datetime import datetime, timedelta
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q
from django.http import FileResponse, HttpResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from dateutil import parser as date_parser

from carriers.models import Carrier, SavedFilter
from carriers.utils import normalize_phone_e164, is_valid_email
from crm.models import Activity, AuditLog, Contact, Lead, Note, Task, Template
from sync.models import Settings as SystemSettings


@login_required
def dashboard_view(request):
    now = timezone.now()
    week_ago = now - timedelta(days=7)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    today_end = now.replace(hour=23, minute=59, second=59)
    week_end = now + timedelta(days=7)

    user_leads = Lead.objects.filter(owner=request.user)
    stage_counts_qs = user_leads.values("status").annotate(cnt=Count("id"))
    stage_map = {row["status"]: row["cnt"] for row in stage_counts_qs}

    stages = [
        ("New", stage_map.get("New", 0)),
        ("Contacted", stage_map.get("Contacted", 0)),
        ("Interested", stage_map.get("Interested", 0)),
        ("Negotiation", stage_map.get("Negotiation", 0)),
        ("Signed", stage_map.get("Signed", 0)),
        ("Rejected", stage_map.get("Rejected", 0)),
        ("Do Not Contact", stage_map.get("Do Not Contact", 0)),
    ]
    max_stage = max([c for _, c in stages] + [1])

    new_leads_week = user_leads.filter(created_at__gte=week_ago).count()
    calls_week = Activity.objects.filter(
        lead__owner=request.user, type="call", created_at__gte=week_ago
    ).count()
    signed_month = user_leads.filter(
        status="Signed", updated_at__gte=month_start
    ).count()

    open_tasks = Task.objects.select_related("lead", "lead__carrier").filter(
        lead__owner=request.user, is_done=False
    )
    overdue_tasks = open_tasks.filter(due_at__lt=now)[:15]
    today_tasks = open_tasks.filter(due_at__gte=now, due_at__lte=today_end)[:15]
    week_tasks = open_tasks.filter(due_at__gt=today_end, due_at__lte=week_end)[:15]

    saved_filters = SavedFilter.objects.filter(user=request.user).select_related("alert")

    lost_reasons = (
        user_leads.filter(status="Rejected")
        .exclude(lost_reason="")
        .values("lost_reason")
        .annotate(cnt=Count("id"))
        .order_by("-cnt")
    )

    return render(
        request,
        "crm/dashboard.html",
        {
            "total_carriers": Carrier.objects.count(),
            "total_leads": user_leads.count(),
            "stages": stages,
            "max_stage": max_stage,
            "new_leads_week": new_leads_week,
            "calls_week": calls_week,
            "signed_month": signed_month,
            "overdue_tasks": overdue_tasks,
            "today_tasks": today_tasks,
            "week_tasks": week_tasks,
            "saved_filters": saved_filters,
            "lost_reasons": lost_reasons,
        },
    )


@login_required
def lead_list_view(request):
    view_mode = request.GET.get("view", "list")
    status_filter = (request.GET.get("status") or "").strip()
    tag_filter = (request.GET.get("tag") or "").strip()
    q = (request.GET.get("q") or "").strip()

    leads_qs = Lead.objects.select_related("carrier").filter(owner=request.user)

    if status_filter:
        leads_qs = leads_qs.filter(status=status_filter)
    if tag_filter:
        leads_qs = leads_qs.filter(tags__icontains=tag_filter)
    if q:
        leads_qs = leads_qs.filter(
            Q(carrier__legal_name__icontains=q)
            | Q(carrier__dot_number__icontains=q)
            | Q(carrier__mc_number__icontains=q)
            | Q(carrier__phone_e164__icontains=q)
            | Q(tags__icontains=q)
        )

    # For board view, group leads by pipeline stage
    board_stages = [
        ("New", []),
        ("Contacted", []),
        ("Interested", []),
        ("Negotiation", []),
        ("Signed", []),
        ("Rejected", []),
        ("Do Not Contact", []),
    ]
    board_map = {name: items for name, items in board_stages}

    for ld in leads_qs:
        if ld.status in board_map:
            board_map[ld.status].append(ld)

    return render(
        request,
        "crm/lead_list.html",
        {
            "leads": leads_qs[:200],
            "board_stages": board_stages,
            "view_mode": view_mode,
            "status_filter": status_filter,
            "tag_filter": tag_filter,
            "q": q,
            "total_leads": leads_qs.count(),
        },
    )


@login_required
def lead_detail_view(request, lead_id: int):
    lead = get_object_or_404(
        Lead.objects.select_related("carrier"), pk=lead_id, owner=request.user
    )
    carrier = lead.carrier
    templates = Template.objects.all()

    # Pre-render templates with carrier placeholders
    rendered_templates = []
    for t in templates:
        body = (
            t.body.replace("{carrier_name}", carrier.legal_name or "")
            .replace("{mc_number}", carrier.mc_number or "")
            .replace("{dot_number}", carrier.dot_number or "")
            .replace("{state}", carrier.state or "")
            .replace("{power_units}", str(carrier.power_units or 1))
        )
        rendered_templates.append({"id": t.pk, "name": t.name, "type": t.get_type_display(), "body": body})

    notes = lead.notes.select_related("author").all()
    activities = lead.activities.all()[:40]
    tasks = lead.tasks.all()
    contacts = lead.contacts.all()

    return render(
        request,
        "crm/lead_detail.html",
        {
            "lead": lead,
            "carrier": carrier,
            "notes": notes,
            "activities": activities,
            "tasks": tasks,
            "contacts": contacts,
            "rendered_templates": rendered_templates,
            "status_choices": Lead.STATUS_CHOICES,
            "priority_choices": Lead.PRIORITY_CHOICES,
            "lost_reason_choices": Lead.LOST_REASON_CHOICES,
        },
    )


@login_required
def add_carrier_to_leads_view(request, dot: str):
    carrier = get_object_or_404(Carrier, dot_number=dot)
    lead, created = Lead.objects.get_or_create(
        carrier=carrier,
        owner=request.user,
        defaults={
            "status": "New",
            "expected_trucks": max(1, carrier.power_units),
        },
    )
    if created:
        lead.refresh_score()
        Activity.objects.create(
            lead=lead,
            type="system",
            body=f"Lead created from Carrier DOT #{carrier.dot_number} with status New.",
        )
        AuditLog.objects.create(
            user=request.user,
            object_type="Lead",
            object_id=str(lead.pk),
            action="CREATE",
            changes={"dot_number": carrier.dot_number, "status": "New"},
        )
        messages.success(request, f"Added {carrier.legal_name} to your Leads pipeline.")
    else:
        messages.info(request, f"{carrier.legal_name} was already in your pipeline.")
    return redirect("lead_detail", lead_id=lead.pk)


@login_required
def lead_update_status_view(request, lead_id: int):
    lead = get_object_or_404(Lead, pk=lead_id, owner=request.user)
    if request.method == "POST":
        old_status = lead.status
        new_status = request.POST.get("status", "").strip()
        lost_reason = request.POST.get("lost_reason", "").strip()
        dnc_reason = request.POST.get("dnc_reason", "").strip()

        if new_status in dict(Lead.STATUS_CHOICES):
            lead.status = new_status
            if new_status == "Rejected":
                lead.lost_reason = lost_reason
            elif new_status == "Do Not Contact":
                lead.dnc_reason = dnc_reason
                lead.dnc_at = timezone.now()
            elif new_status == "Contacted":
                lead.last_contact_at = timezone.now()
                # Follow-up cadence: Suggest next follow-up task 2 days out if none open
                if not lead.tasks.filter(is_done=False).exists():
                    Task.objects.create(
                        lead=lead,
                        title=f"Follow-up call with {lead.carrier.legal_name}",
                        due_at=timezone.now() + timedelta(days=2),
                    )

            lead.save()
            Activity.objects.create(
                lead=lead,
                type="system",
                body=f"Status changed from {old_status} to {new_status}"
                + (f" (Reason: {lost_reason})" if lost_reason else "")
                + (f" (DNC Reason: {dnc_reason})" if dnc_reason else ""),
            )
            AuditLog.objects.create(
                user=request.user,
                object_type="Lead",
                object_id=str(lead.pk),
                action="STATUS_CHANGE",
                changes={"old_status": old_status, "new_status": new_status, "lost_reason": lost_reason},
            )
            messages.success(request, f"Lead status updated to {new_status}.")
    return redirect("lead_detail", lead_id=lead.pk)


@login_required
def lead_update_details_view(request, lead_id: int):
    """Update deal info, tags, and priority."""
    lead = get_object_or_404(Lead, pk=lead_id, owner=request.user)
    if request.method == "POST":
        lead.priority = request.POST.get("priority", lead.priority)
        lead.tags = request.POST.get("tags", lead.tags).strip()
        try:
            lead.expected_trucks = max(1, int(request.POST.get("expected_trucks", lead.expected_trucks)))
        except ValueError:
            pass
        try:
            lead.fee_percent = float(request.POST.get("fee_percent", lead.fee_percent))
        except ValueError:
            pass
        try:
            lead.expected_monthly_value = float(request.POST.get("expected_monthly_value", lead.expected_monthly_value))
        except ValueError:
            pass
        lead.save()
        messages.success(request, "Deal information saved.")
    return redirect("lead_detail", lead_id=lead.pk)


@login_required
def lead_manual_enrich_view(request, lead_id: int):
    """
    Manual contact enrichment (PRD 5.6 & 5.7).
    Edits carrier contact fields (phone, email, website, owner_name) and marks them
    added_by_user=True with source, ensuring background sync NEVER overwrites them.
    """
    lead = get_object_or_404(Lead.objects.select_related("carrier"), pk=lead_id, owner=request.user)
    carrier = lead.carrier
    if request.method == "POST":
        phone = (request.POST.get("phone") or "").strip()
        email = (request.POST.get("email") or "").strip()
        website = (request.POST.get("website") or "").strip()
        owner_name = (request.POST.get("owner_name") or "").strip()
        source = (request.POST.get("source") or "Call").strip()

        changes = {}
        if phone:
            carrier.phone = phone
            carrier.phone_e164 = normalize_phone_e164(phone)
            carrier.phone_added_by_user = True
            carrier.phone_source = source
            changes["phone"] = carrier.phone_e164
        if email:
            carrier.email = email
            carrier.email_valid = is_valid_email(email)
            carrier.email_added_by_user = True
            carrier.email_source = source
            changes["email"] = carrier.email
        if website:
            carrier.website = website
            carrier.website_added_by_user = True
            carrier.website_source = source
            changes["website"] = carrier.website
        if owner_name:
            carrier.owner_name = owner_name
            carrier.owner_added_by_user = True
            carrier.owner_source = source
            changes["owner_name"] = carrier.owner_name

        carrier.save()
        lead.refresh_score(save=True)

        Activity.objects.create(
            lead=lead,
            type="system",
            body=f"Contact fields manually enriched (Source: {source}): {', '.join(changes.keys())}. Protected from future sync overwrites.",
        )
        AuditLog.objects.create(
            user=request.user,
            object_type="CarrierEnrichment",
            object_id=str(carrier.dot_number),
            action="MANUAL_ENRICH",
            changes=changes,
        )
        messages.success(request, "Carrier contact details enriched and locked against sync overwrites.")
    return redirect("lead_detail", lead_id=lead.pk)


@login_required
def lead_add_contact_view(request, lead_id: int):
    lead = get_object_or_404(Lead, pk=lead_id, owner=request.user)
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        role = (request.POST.get("role") or "Dispatcher").strip()
        phone = (request.POST.get("phone") or "").strip()
        email = (request.POST.get("email") or "").strip()
        source = (request.POST.get("source") or "Call").strip()
        is_primary = request.POST.get("is_primary") == "on"

        if name:
            if is_primary:
                lead.contacts.filter(is_primary=True).update(is_primary=False)
            Contact.objects.create(
                lead=lead,
                name=name,
                role=role,
                phone=normalize_phone_e164(phone) or phone,
                email=email,
                source=source,
                is_primary=is_primary,
                added_by_user=True,
            )
            lead.refresh_score(save=True)
            Activity.objects.create(
                lead=lead,
                type="system",
                body=f"Added contact person: {name} ({role}) - Phone: {phone}, Email: {email}",
            )
            messages.success(request, f"Contact person {name} added.")
    return redirect("lead_detail", lead_id=lead.pk)


@login_required
def lead_add_note_view(request, lead_id: int):
    lead = get_object_or_404(Lead, pk=lead_id, owner=request.user)
    if request.method == "POST":
        body = (request.POST.get("body") or "").strip()
        is_pinned = request.POST.get("is_pinned") == "on"
        if body:
            Note.objects.create(
                lead=lead,
                author=request.user,
                body=body,
                is_pinned=is_pinned,
            )
            Activity.objects.create(
                lead=lead,
                type="system",
                body=f"Note added by {request.user.username}: {body[:60]}...",
            )
            messages.success(request, "Note added.")
    return redirect("lead_detail", lead_id=lead.pk)


@login_required
def lead_toggle_pin_note_view(request, lead_id: int, note_id: int):
    note = get_object_or_404(Note, pk=note_id, lead_id=lead_id, lead__owner=request.user)
    note.is_pinned = not note.is_pinned
    note.save(update_fields=["is_pinned"])
    return redirect("lead_detail", lead_id=lead_id)


@login_required
def lead_delete_note_view(request, lead_id: int, note_id: int):
    note = get_object_or_404(Note, pk=note_id, lead_id=lead_id, lead__owner=request.user)
    note.delete()
    messages.success(request, "Note removed.")
    return redirect("lead_detail", lead_id=lead_id)


@login_required
def lead_log_activity_view(request, lead_id: int):
    lead = get_object_or_404(Lead, pk=lead_id, owner=request.user)
    if request.method == "POST":
        act_type = request.POST.get("type", "call")
        outcome = request.POST.get("outcome", "")
        body = (request.POST.get("body") or "").strip()

        Activity.objects.create(
            lead=lead,
            type=act_type,
            outcome=outcome,
            body=body,
        )
        lead.last_contact_at = timezone.now()
        lead.save(update_fields=["last_contact_at"])
        messages.success(request, f"{act_type.capitalize()} logged.")
    return redirect("lead_detail", lead_id=lead.pk)


@login_required
def lead_add_task_view(request, lead_id: int):
    lead = get_object_or_404(Lead, pk=lead_id, owner=request.user)
    if request.method == "POST":
        title = (request.POST.get("title") or "").strip()
        due_str = request.POST.get("due_at", "")
        repeat_days = int(request.POST.get("repeat_days") or 0)

        if title and due_str:
            try:
                due_dt = date_parser.parse(due_str)
                if timezone.is_naive(due_dt):
                    due_dt = timezone.make_aware(due_dt)
                Task.objects.create(
                    lead=lead,
                    title=title,
                    due_at=due_dt,
                    repeat_days=repeat_days,
                )
                messages.success(request, "Follow-up task scheduled.")
            except Exception as e:
                messages.error(request, f"Invalid date: {e}")
    return redirect("lead_detail", lead_id=lead.pk)


@login_required
def lead_toggle_task_view(request, lead_id: int, task_id: int):
    task = get_object_or_404(Task, pk=task_id, lead_id=lead_id, lead__owner=request.user)
    task.is_done = not task.is_done
    task.done_at = timezone.now() if task.is_done else None
    task.save(update_fields=["is_done", "done_at"])

    # If repeating task was marked done, create next instance
    if task.is_done and task.repeat_days > 0:
        Task.objects.create(
            lead=task.lead,
            title=task.title,
            due_at=task.due_at + timedelta(days=task.repeat_days),
            repeat_days=task.repeat_days,
        )
    return redirect("lead_detail", lead_id=lead_id)


@login_required
def export_leads_csv_view(request):
    """Export current user's leads to CSV (excluding DNC unless filtered)."""
    leads = Lead.objects.select_related("carrier").filter(owner=request.user)
    status_filter = request.GET.get("status")
    if status_filter:
        leads = leads.filter(status=status_filter)
    else:
        leads = leads.exclude(status="Do Not Contact")

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="leads.csv"'
    writer = csv.writer(response)
    writer.writerow([
        "Lead ID", "DOT Number", "MC Number", "Legal Name", "Status",
        "Priority", "Score", "State", "City", "Phone", "Email", "Expected Trucks",
        "Fee %", "Expected Monthly Value", "Tags", "Lost Reason", "Created Date", "Last Contact"
    ])
    for l in leads:
        c = l.carrier
        writer.writerow([
            l.pk, c.dot_number, c.mc_number, c.legal_name, l.status,
            l.priority, l.score, c.state, c.city, c.phone_e164 or c.phone,
            c.email, l.expected_trucks, l.fee_percent, l.expected_monthly_value,
            l.tags, l.lost_reason, l.created_at.strftime("%Y-%m-%d"),
            l.last_contact_at.strftime("%Y-%m-%d %H:%M") if l.last_contact_at else ""
        ])
    return response


@login_required
def import_leads_csv_view(request):
    """Import leads from CSV matching by DOT or MC number (PRD 5.5)."""
    if request.method == "POST" and request.FILES.get("csv_file"):
        csv_file = request.FILES["csv_file"]
        decoded = csv_file.read().decode("utf-8-sig", errors="ignore")
        reader = csv.DictReader(io.StringIO(decoded))

        imported = 0
        skipped = 0
        for row in reader:
            dot = (row.get("DOT Number") or row.get("dot_number") or row.get("DOT") or "").strip()
            mc = (row.get("MC Number") or row.get("mc_number") or row.get("MC") or "").strip()
            status = (row.get("Status") or row.get("status") or "New").strip()

            carrier = None
            if dot:
                carrier = Carrier.objects.filter(dot_number=dot).first()
            if not carrier and mc:
                clean_mc = "".join(ch for ch in mc if ch.isdigit())
                carrier = Carrier.objects.filter(mc_number=clean_mc).first()

            if carrier:
                lead, created = Lead.objects.get_or_create(
                    carrier=carrier,
                    owner=request.user,
                    defaults={"status": status if status in dict(Lead.STATUS_CHOICES) else "New"}
                )
                if created:
                    lead.refresh_score(save=True)
                    imported += 1
                else:
                    skipped += 1
            else:
                skipped += 1

        messages.success(request, f"Imported {imported} leads from CSV ({skipped} skipped/already present).")
        return redirect("lead_list")

    return render(request, "crm/import_leads.html")


@login_required
def download_backup_db_view(request):
    """Full database backup button - downloads the active db.sqlite3 file (PRD 5.5 & 123)."""
    db_path = settings.BASE_DIR / "db.sqlite3"
    if not db_path.exists():
        raise Http404("Database file not found.")

    response = FileResponse(open(db_path, "rb"), as_attachment=True, filename="dispatch_leads_backup.sqlite3")
    return response
