from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from carriers.models import Carrier
from sync.models import SyncJob
from sync.services import refresh_single_carrier, run_sync_job_sync, update_saved_filter_alerts


class Command(BaseCommand):
    help = "Run the scheduled daily delta sync (fetches new carriers and refreshes active leads' carriers)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--mode",
            choices=["seed", "live"],
            default="seed",
            help="Mode for daily delta sync (default: seed)",
        )
        parser.add_argument(
            "--delta-count",
            type=int,
            default=200,
            help="Number of recent carriers to check in daily delta (default: 200)",
        )

    def handle(self, *args, **options):
        mode = options["mode"]
        delta_count = options["delta_count"]

        job = SyncJob.objects.create(
            type="daily_sync",
            status="running",
            total=delta_count,
            started_at=timezone.now(),
        )
        self.stdout.write(f"Running Daily Sync Job #{job.pk}...")

        # 1. Run delta upsert
        run_sync_job_sync(job.pk, count=delta_count, mode=mode)

        # 2. Refresh carriers attached to active leads older than freshness window
        lead_carriers = Carrier.objects.filter(leads__isnull=False).distinct()[:50]
        refreshed_leads = 0
        for c in lead_carriers:
            _, _, _ = refresh_single_carrier(c, force=False)
            refreshed_leads += 1

        update_saved_filter_alerts()
        job.refresh_from_db()
        job.summary_message = (
            f"{job.summary_message} | Checked {refreshed_leads} lead carrier(s) & updated saved filter alerts."
        )
        job.save(update_fields=["summary_message"])
        self.stdout.write(self.style.SUCCESS(f"Daily Sync Job #{job.pk} completed."))

