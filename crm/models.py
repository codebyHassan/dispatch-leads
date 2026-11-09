from django.conf import settings
from django.db import models
from django.utils import timezone
from carriers.models import Carrier
from sync.models import Settings as SystemSettings


class Lead(models.Model):
    STATUS_CHOICES = [
        ("New", "New"),
        ("Contacted", "Contacted"),
        ("Interested", "Interested"),
        ("Negotiation", "Negotiation"),
        ("Signed", "Signed"),
        ("Rejected", "Rejected"),
        ("Do Not Contact", "Do Not Contact"),
    ]
    PRIORITY_CHOICES = [
        ("Low", "Low"),
        ("Medium", "Medium"),
        ("High", "High"),
    ]
    LOST_REASON_CHOICES = [
        ("", "—"),
        ("Has dispatcher", "Has dispatcher"),
        ("Not interested", "Not interested"),
        ("Wrong number", "Wrong number"),
        ("Too small", "Too small"),
        ("Other", "Other"),
    ]

    carrier = models.ForeignKey(
        Carrier, on_delete=models.CASCADE, related_name="leads"
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="leads",
    )
    status = models.CharField(
        max_length=32, choices=STATUS_CHOICES, default="New", db_index=True
    )
    priority = models.CharField(
        max_length=16, choices=PRIORITY_CHOICES, default="Medium", db_index=True
    )
    source = models.CharField(max_length=64, default="Carrier Search")
    tags = models.CharField(max_length=255, blank=True, default="")

    expected_trucks = models.IntegerField(default=1)
    fee_percent = models.FloatField(default=7.0)
    expected_monthly_value = models.DecimalField(
        max_digits=10, decimal_places=2, default=0.00
    )

    lost_reason = models.CharField(
        max_length=64, choices=LOST_REASON_CHOICES, blank=True, default="", db_index=True
    )
    dnc_reason = models.CharField(max_length=255, blank=True, default="")
    dnc_at = models.DateTimeField(null=True, blank=True)

    score = models.IntegerField(default=0, db_index=True)
    score_breakdown = models.JSONField(default=dict, blank=True)

    next_followup_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_contact_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["carrier", "owner"], name="unique_lead_per_carrier_owner"
            )
        ]

    def __str__(self) -> str:
        return f"Lead: {self.carrier.legal_name} ({self.status})"

    def compute_score(self, cfg: SystemSettings | None = None) -> tuple[int, dict]:
        if cfg is None:
            cfg = SystemSettings.get_solo()
        c = self.carrier
        breakdown = {}
        total = 0

        # 1. New MC age (< 90 days)
        if c.is_new_authority:
            breakdown["New MC (<90d)"] = cfg.weight_new_mc
            total += cfg.weight_new_mc
        else:
            breakdown["New MC (<90d)"] = 0

        # 2. Fleet size in target range
        if cfg.target_fleet_min <= c.power_units <= cfg.target_fleet_max:
            breakdown[f"Target Fleet ({cfg.target_fleet_min}-{cfg.target_fleet_max})"] = cfg.weight_fleet_size
            total += cfg.weight_fleet_size
        else:
            breakdown[f"Target Fleet ({cfg.target_fleet_min}-{cfg.target_fleet_max})"] = 0

        # 3. Phone present
        has_phone = bool(c.phone_e164 or c.phone or self.contacts.exclude(phone="").exists())
        breakdown["Phone Present"] = cfg.weight_phone if has_phone else 0
        if has_phone:
            total += cfg.weight_phone

        # 4. Email present
        has_email = bool((c.email and c.email_valid) or self.contacts.exclude(email="").exists())
        breakdown["Email Present"] = cfg.weight_email if has_email else 0
        if has_email:
            total += cfg.weight_email

        # 5. Insurance active
        ins_ok = bool(c.insurance_on_file and not c.has_insurance_alert)
        breakdown["Active Insurance"] = cfg.weight_insurance if ins_ok else 0
        if ins_ok:
            total += cfg.weight_insurance

        # 6. Safety not Unsatisfactory
        safety_ok = c.safety_rating != "Unsatisfactory"
        breakdown["Safety OK"] = cfg.weight_safety if safety_ok else 0
        if safety_ok:
            total += cfg.weight_safety

        score = min(100, max(0, total))
        return score, breakdown

    def refresh_score(self, cfg: SystemSettings | None = None, save: bool = True):
        score, breakdown = self.compute_score(cfg=cfg)
        self.score = score
        self.score_breakdown = breakdown
        if save and self.pk:
            Lead.objects.filter(pk=self.pk).update(
                score=score, score_breakdown=breakdown
            )


class Contact(models.Model):
    SOURCE_CHOICES = [
        ("FMCSA", "FMCSA"),
        ("Call", "Call"),
        ("Website", "Website"),
        ("Email reply", "Email reply"),
        ("Enrichment", "Enrichment"),
        ("Other", "Other"),
    ]

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="contacts")
    name = models.CharField(max_length=128)
    role = models.CharField(max_length=64, blank=True, default="Owner / Dispatcher")
    phone = models.CharField(max_length=64, blank=True, default="")
    email = models.CharField(max_length=255, blank=True, default="")
    source = models.CharField(max_length=32, choices=SOURCE_CHOICES, default="Call")
    added_by_user = models.BooleanField(default=True)
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_primary", "name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.role})"


class Note(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="notes")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lead_notes"
    )
    body = models.TextField()
    is_pinned = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_pinned", "-created_at"]

    def __str__(self) -> str:
        return f"Note on {self.lead_id} by {self.author}"


class Activity(models.Model):
    TYPE_CHOICES = [
        ("call", "Call"),
        ("email", "Email"),
        ("text", "Text"),
        ("meeting", "Meeting"),
        ("system", "System"),
    ]
    OUTCOME_CHOICES = [
        ("", "—"),
        ("No answer", "No answer"),
        ("Voicemail", "Voicemail"),
        ("Spoke", "Spoke"),
        ("Callback requested", "Callback requested"),
        ("Not interested", "Not interested"),
    ]

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="activities")
    type = models.CharField(max_length=32, choices=TYPE_CHOICES, default="call")
    outcome = models.CharField(
        max_length=64, choices=OUTCOME_CHOICES, blank=True, default=""
    )
    body = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_type_display()} on Lead #{self.lead_id}"


class Task(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="tasks")
    title = models.CharField(max_length=255)
    due_at = models.DateTimeField(db_index=True)
    repeat_days = models.IntegerField(default=0, help_text="0 = no repeat")
    is_done = models.BooleanField(default=False, db_index=True)
    done_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["is_done", "due_at"]

    def __str__(self) -> str:
        return f"Task: {self.title} (Due {self.due_at})"


class Template(models.Model):
    TYPE_CHOICES = [
        ("script", "Call Script"),
        ("email", "Email Template"),
        ("text", "SMS / Text Template"),
    ]

    name = models.CharField(max_length=128)
    type = models.CharField(max_length=32, choices=TYPE_CHOICES, default="script")
    body = models.TextField(
        help_text="Placeholders: {carrier_name}, {mc_number}, {dot_number}, {state}, {power_units}"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["type", "name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.get_type_display()})"


class AuditLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
    )
    object_type = models.CharField(max_length=64, db_index=True)
    object_id = models.CharField(max_length=64, db_index=True)
    action = models.CharField(max_length=64)
    changes = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.action} {self.object_type} #{self.object_id}"
