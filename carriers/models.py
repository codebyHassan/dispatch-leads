from datetime import date
from django.conf import settings
from django.db import models
from django.utils import timezone as dj_timezone
from .utils import (
    format_mc_age,
    get_carrier_local_time_info,
    is_valid_email,
    normalize_phone_e164,
    resolve_timezone,
)


class Carrier(models.Model):
    STATUS_CHOICES = [
        ("Active", "Active"),
        ("Inactive", "Inactive"),
        ("Pending", "Pending"),
    ]
    AUTHORITY_TYPE_CHOICES = [
        ("Common", "Common"),
        ("Contract", "Contract"),
        ("Both", "Both"),
        ("Broker", "Broker"),
    ]
    SAFETY_CHOICES = [
        ("Satisfactory", "Satisfactory"),
        ("Conditional", "Conditional"),
        ("Unsatisfactory", "Unsatisfactory"),
        ("Unrated", "Unrated"),
    ]

    dot_number = models.CharField(max_length=20, unique=True, db_index=True)
    mc_number = models.CharField(max_length=20, blank=True, default="", db_index=True)
    legal_name = models.CharField(max_length=255, db_index=True)
    dba_name = models.CharField(max_length=255, blank=True, default="", db_index=True)

    status = models.CharField(max_length=32, default="Active", db_index=True)
    authority_grant_date = models.DateField(null=True, blank=True, db_index=True)
    authority_status = models.CharField(
        max_length=32, choices=STATUS_CHOICES, default="Active", db_index=True
    )
    authority_type = models.CharField(
        max_length=32, choices=AUTHORITY_TYPE_CHOICES, default="Common", db_index=True
    )
    authority_revoked_at = models.DateField(null=True, blank=True)
    mcs150_date = models.DateField(null=True, blank=True)

    operation_type = models.CharField(max_length=64, default="Interstate", db_index=True)
    cargo_types = models.JSONField(default=list, blank=True)
    equipment_tags = models.JSONField(default=list, blank=True)

    power_units = models.IntegerField(default=0, db_index=True)
    drivers = models.IntegerField(default=0, db_index=True)
    trailers = models.IntegerField(default=0)

    state = models.CharField(max_length=10, blank=True, default="", db_index=True)
    city = models.CharField(max_length=128, blank=True, default="", db_index=True)
    zip_code = models.CharField(max_length=20, blank=True, default="", db_index=True)
    address = models.CharField(max_length=255, blank=True, default="")
    country = models.CharField(max_length=10, default="US", db_index=True)
    timezone = models.CharField(max_length=64, default="America/Chicago")

    phone = models.CharField(max_length=64, blank=True, default="", db_index=True)
    phone_e164 = models.CharField(max_length=32, blank=True, default="", db_index=True)
    phone_added_by_user = models.BooleanField(default=False)
    phone_source = models.CharField(max_length=32, blank=True, default="FMCSA")

    email = models.CharField(max_length=255, blank=True, default="", db_index=True)
    email_valid = models.BooleanField(default=False, db_index=True)
    email_added_by_user = models.BooleanField(default=False)
    email_source = models.CharField(max_length=32, blank=True, default="FMCSA")

    website = models.CharField(max_length=255, blank=True, default="")
    website_added_by_user = models.BooleanField(default=False)
    website_source = models.CharField(max_length=32, blank=True, default="")

    owner_name = models.CharField(max_length=255, blank=True, default="")
    owner_added_by_user = models.BooleanField(default=False)
    owner_source = models.CharField(max_length=32, blank=True, default="")

    safety_rating = models.CharField(
        max_length=32, choices=SAFETY_CHOICES, default="Unrated", db_index=True
    )
    oos_percent = models.FloatField(default=0.0, db_index=True)
    crash_count_24m = models.IntegerField(default=0, db_index=True)
    inspection_count_24m = models.IntegerField(default=0, db_index=True)
    basic_alerts = models.BooleanField(default=False, db_index=True)

    insurance_on_file = models.BooleanField(default=False, db_index=True)
    insurance_amount = models.IntegerField(default=0, db_index=True)
    insurance_expiry = models.DateField(null=True, blank=True, db_index=True)

    last_synced_at = models.DateTimeField(default=dj_timezone.now, db_index=True)
    source = models.CharField(max_length=64, default="socrata")
    raw_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-authority_grant_date", "legal_name"]
        indexes = [
            models.Index(fields=["state", "authority_grant_date"]),
            models.Index(fields=["authority_status", "power_units"]),
            models.Index(fields=["phone_e164"]),
        ]

    def __str__(self) -> str:
        mc_str = f" (MC-{self.mc_number})" if self.mc_number else ""
        return f"{self.legal_name} [DOT {self.dot_number}{mc_str}]"

    def save(self, *args, **kwargs):
        if self.phone and not self.phone_e164:
            self.phone_e164 = normalize_phone_e164(self.phone)
        elif not self.phone:
            self.phone_e164 = ""
        self.email_valid = is_valid_email(self.email)
        self.timezone = resolve_timezone(self.state, self.zip_code)
        super().save(*args, **kwargs)

    @property
    def mc_age_days(self) -> int | None:
        if not self.authority_grant_date:
            return None
        delta = date.today() - self.authority_grant_date
        return max(0, delta.days)

    @property
    def mc_age_display(self) -> str:
        return format_mc_age(self.mc_age_days)

    @property
    def is_new_authority(self) -> bool:
        days = self.mc_age_days
        return days is not None and 0 <= days < 90

    @property
    def local_time_info(self) -> dict:
        return get_carrier_local_time_info(self.timezone)

    @property
    def has_insurance_alert(self) -> bool:
        if not self.insurance_on_file:
            return True
        if self.insurance_expiry:
            days_left = (self.insurance_expiry - date.today()).days
            return days_left <= 30
        return False

    @property
    def has_authority_alert(self) -> bool:
        return self.authority_status != "Active" or self.authority_revoked_at is not None

    @property
    def contact_completeness(self) -> tuple[int, int]:
        """Return (filled_count, total_7) across key contact/identity fields."""
        fields = [
            bool(self.phone_e164 or self.phone),
            bool(self.email and self.email_valid),
            bool(self.website),
            bool(self.owner_name),
            bool(self.address),
            bool(self.city and self.state),
            bool(self.mc_number),
        ]
        return sum(1 for f in fields if f), 7


class CarrierChange(models.Model):
    carrier = models.ForeignKey(
        Carrier, on_delete=models.CASCADE, related_name="changes"
    )
    field = models.CharField(max_length=64)
    old_value = models.TextField(blank=True, default="")
    new_value = models.TextField(blank=True, default="")
    changed_at = models.DateTimeField(default=dj_timezone.now, db_index=True)

    class Meta:
        ordering = ["-changed_at"]

    def __str__(self) -> str:
        return f"{self.carrier.dot_number}: {self.field} ({self.old_value} -> {self.new_value})"


class SavedFilter(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_filters"
    )
    name = models.CharField(max_length=128)
    query_string = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class FilterAlert(models.Model):
    saved_filter = models.OneToOneField(
        SavedFilter, on_delete=models.CASCADE, related_name="alert"
    )
    last_seen_at = models.DateTimeField(default=dj_timezone.now)
    new_count = models.IntegerField(default=0)

    def __str__(self) -> str:
        return f"{self.saved_filter.name}: {self.new_count} new"
