from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from carriers.models import Carrier
from sync.models import Settings, SyncJob
from sync.services import launch_sync_job_async, test_network_sources


@login_required
def sync_dashboard_view(request):
    cfg = Settings.get_solo()
    network_results = None
    geo_warning = False

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "test_network":
            network_results = test_network_sources()
            geo_warning = any(not r["ok"] for r in network_results)
        elif action == "start_sync":
            mode = request.POST.get("mode", "seed")
            count = int(request.POST.get("count") or 10000)
            count = max(100, min(50000, count))
            job_type = "socrata_bulk" if mode == "live" else "seed_realistic"
            job = launch_sync_job_async(job_type=job_type, count=count, mode=mode)
            messages.success(
                request,
                f"Started background SyncJob #{job.pk} ({job.get_type_display()} — {count} carriers).",
            )
            return redirect(f"/sync/?watch={job.pk}")
        elif action == "run_daily_sync":
            job = launch_sync_job_async(job_type="daily_sync", count=250, mode="seed")
            messages.success(
                request,
                f"Started Daily Delta SyncJob #{job.pk} (updates carrier deltas & saved filter alerts).",
            )
            return redirect(f"/sync/?watch={job.pk}")

    jobs = SyncJob.objects.all()[:20]
    active_job_id = request.GET.get("watch")
    if not active_job_id:
        running = SyncJob.objects.filter(status__in=["queued", "running"]).first()
        if running:
            active_job_id = running.pk

    # Check if latest job had network/geo fallback errors
    latest_job = jobs[0] if jobs else None
    if latest_job and latest_job.errors:
        geo_warning = True

    return render(
        request,
        "sync/index.html",
        {
            "cfg": cfg,
            "jobs": jobs,
            "active_job_id": active_job_id,
            "network_results": network_results,
            "geo_warning": geo_warning,
            "total_carriers": Carrier.objects.count(),
        },
    )


@login_required
def sync_job_status_json(request, job_id: int):
    job = get_object_or_404(SyncJob, pk=job_id)
    return JsonResponse(
        {
            "id": job.pk,
            "type": job.get_type_display(),
            "status": job.status,
            "total": job.total,
            "processed": job.processed,
            "created_count": job.created_count,
            "updated_count": job.updated_count,
            "progress_percent": job.progress_percent,
            "errors": job.errors,
            "summary_message": job.summary_message,
            "started_at": job.started_at.strftime("%Y-%m-%d %H:%M:%S") if job.started_at else "",
            "finished_at": job.finished_at.strftime("%Y-%m-%d %H:%M:%S") if job.finished_at else "",
        }
    )
