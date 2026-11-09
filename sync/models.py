from django.db import models
from django.utils import timezone


class Settings(models.Model):
    """Singleton configuration record for proxy, rate-limiting, API keys, and lead scoring."""

    proxy_url = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Optional HTTP or SOCKS5 proxy (e.g. socks5://user:pass@host:port)",
    )
    request_delay_ms = models.IntegerField(default=300)
    timeout_s = models.IntegerField(default=15)
    max_concurrency = models.IntegerField(default=2)
    qcmobile_webkey = models.CharField(max_length=255, blank=True, default="")
    socrata_app_token = models.CharField(max_length=255, blank=True, default="")
    freshness_hours = models.IntegerField(default=24)

    # Lead scoring weights & target fleet range (v1.1)
    target_fleet_min = models.IntegerField(default=1)
    target_fleet_max = models.IntegerField(default=10)
    weight_new_mc = models.IntegerField(default=25)
    weight_fleet_size = models.IntegerField(default=20)
    weight_phone = models.IntegerField(default=20)
    weight_email = models.IntegerField(default=15)
    weight_insurance = models.IntegerField(default=10)
    weight_safety = models.IntegerField(default=10)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "System Settings"
        verbose_name_plural = "System Settings"

    @classmethod
    def get_solo(cls) -> "Settings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def get_proxies(self) -> dict | None:
        url = (self.proxy_url or "").strip()
        if not url:
            return None
        return {"http": url, "https": url}


class SyncJob(models.Model):
    TYPE_CHOICES = [
        ("socrata_bulk", "Socrata Bulk Import"),
        ("seed_realistic", "Realistic Carrier Dataset Load"),
        ("daily_sync", "Scheduled Daily Sync"),
        ("carrier_refresh", "Single Carrier Refresh"),
        ("bulk_refresh", "Bulk Carrier Refresh"),
    ]
    STATUS_CHOICES = [
        ("queued", "Queued"),
        ("running", "Running"),
        ("done", "Done"),
        ("failed", "Failed"),
    ]

    type = models.CharField(max_length=64, choices=TYPE_CHOICES, default="socrata_bulk")
    status = models.CharField(
        max_length=32, choices=STATUS_CHOICES, default="queued", db_index=True
    )
    total = models.IntegerField(default=0)
    processed = models.IntegerField(default=0)
    created_count = models.IntegerField(default=0)
    updated_count = models.IntegerField(default=0)
    errors = models.JSONField(default=list, blank=True)
    summary_message = models.CharField(max_length=255, blank=True, default="")
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"Job #{self.pk} ({self.get_type_display()}) - {self.status}"

    @property
    def progress_percent(self) -> int:
        if self.total <= 0:
            return 100 if self.status == "done" else 0
        return min(100, int((self.processed / self.total) * 100))
