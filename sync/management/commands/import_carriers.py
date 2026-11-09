from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from crm.models import Template
from sync.models import Settings, SyncJob
from sync.services import run_sync_job_sync

User = get_user_model()


DEFAULT_TEMPLATES = [
    {
        "name": "Cold Call — New MC Dispatch Pitch",
        "type": "script",
        "body": (
            "Hi, am I speaking with the owner at {carrier_name}?\n\n"
            "Congrats on getting your authority active (MC-{mc_number}) in {state}! "
            "I'm calling from Dispatch Operations — we specialize in keeping {power_units}-truck fleets "
            "loaded on high-paying lanes without forcing any contracts. Are your trucks running spot loads "
            "this week or looking for dedicated lanes?"
        ),
    },
    {
        "name": "Intro Email — Dispatch Partnership",
        "type": "email",
        "body": (
            "Subject: High-Paying Lanes for {carrier_name} (MC #{mc_number})\n\n"
            "Hello {carrier_name} Team,\n\n"
            "We noticed your authority in {state} (DOT #{dot_number}) with {power_units} power unit(s). "
            "Our dispatch team handles rate negotiation, broker credit checks, lumper/detention collection, "
            "and paperwork so you can focus on driving.\n\n"
            "Reply with your preferred lanes and equipment type and we will send over 3 sample loads today."
        ),
    },
    {
        "name": "Quick SMS Follow-Up",
        "type": "text",
        "body": (
            "Hi {carrier_name} (MC-{mc_number}), just tried calling regarding load dispatch for your "
            "{power_units} truck(s) out of {state}. Let me know what lanes you need covered this week!"
        ),
    },
]


class Command(BaseCommand):
    help = "Import US carriers from Socrata API or load realistic dataset (default 10,000 carriers)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--count",
            type=int,
            default=10000,
            help="Number of carriers to import (default: 10000)",
        )
        parser.add_argument(
            "--mode",
            choices=["seed", "live"],
            default="seed",
            help="'seed' loads realistic US carrier data immediately; 'live' fetches from Socrata API with fallback.",
        )

    def handle(self, *args, **options):
        count = options["count"]
        mode = options["mode"]

        Settings.get_solo()
        if not User.objects.filter(username="admin").exists():
            User.objects.create_superuser("admin", "admin@example.com", "admin123")
            self.stdout.write(
                self.style.SUCCESS("Created default user: admin / admin123")
            )

        for tmpl in DEFAULT_TEMPLATES:
            Template.objects.get_or_create(
                name=tmpl["name"],
                defaults={"type": tmpl["type"], "body": tmpl["body"]},
            )

        job = SyncJob.objects.create(
            type="socrata_bulk" if mode == "live" else "seed_realistic",
            status="queued",
            total=count,
        )
        self.stdout.write(f"Starting SyncJob #{job.pk} (mode={mode}, count={count})...")
        run_sync_job_sync(job.pk, count=count, mode=mode)
        job.refresh_from_db()
        self.stdout.write(
            self.style.SUCCESS(
                f"Finished SyncJob #{job.pk}: status={job.status}, processed={job.processed}, "
                f"created={job.created_count}, updated={job.updated_count}"
            )
        )

