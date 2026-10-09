from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone


class AuditEvent(models.Model):
    # ---- Event classification ----
    EVENT_TYPE_CHOICES = [
        ("model.change", "Model Change"),
        ("auth.login", "Authentication"),
        ("permission.change", "Permission Change"),
        ("system", "System"),
    ]

    ACTION_CHOICES = [
        ("CREATE", "Create"),
        ("UPDATE", "Update"),
        ("DELETE", "Delete"),
        ("LOGIN_SUCCESS", "Login Success"),
        ("LOGIN_FAILED", "Login Failed"),
        ("LOGOUT", "Logout"),
    ]

    SEVERITY_CHOICES = [
        ("INFO", "Info"),
        ("WARN", "Warning"),
        ("SECURITY", "Security"),
        ("ERROR", "Error"),
    ]

    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)

    event_type = models.CharField(
        max_length=50, choices=EVENT_TYPE_CHOICES, db_index=True
    )
    action = models.CharField(
        max_length=50, choices=ACTION_CHOICES, db_index=True
    )
    severity = models.CharField(
        max_length=20, choices=SEVERITY_CHOICES, default="INFO"
    )

    message = models.TextField(blank=True)


    # ---- Actor (who did it) ----
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_events",
        db_index=True,
    )

    dealership = models.ForeignKey(
        "accounts.Dealership",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_events",
        db_index=True,
    )

    claim = models.ForeignKey(
        "claim.Claim",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_events",
        db_index=True,
    )

    line = models.ForeignKey(
        "claim.LineTable",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_events",
        db_index=True,
    )

    journal = models.ForeignKey(
        "claim.Journal",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_events",
        db_index=True,
    )

    # ---- Target object (what was acted on) ----
    content_type = models.ForeignKey(
        ContentType,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    object_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
    )
    content_object = GenericForeignKey("content_type", "object_id")

    # ---- Change payload ----
    # Example:
    # {
    #   "status": {"old": "Pending", "new": "Paid"},
    #   "amount": {"old": "100.00", "new": "125.00"}
    # }
    changes = models.JSONField(null=True, blank=True)

    # ---- Request / security context ----
    request_id = models.CharField(max_length=36, null=True, blank=True, db_index=True)
    ip_address = models.CharField(max_length=45, null=True, blank=True, db_index=True)
    user_agent = models.TextField(null=True, blank=True)
    session_key = models.CharField(max_length=64, null=True, blank=True, db_index=True)

    line_num = models.CharField(max_length=50, null=True, blank=True, db_index=True)

    # ---- Extra metadata (flexible) ----
    # Login failures, MFA, auth backend, URL path, HTTP method, etc.
    metadata = models.JSONField(null=True, blank=True)

    # ---- Optional multi-tenant support ----
    # Uncomment if/when needed
    # tenant_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "audit_event"
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["dealership", "occurred_at"]),
            models.Index(fields=["claim", "occurred_at"]),
            models.Index(fields=["line", "occurred_at"]),
            models.Index(fields=["journal", "occurred_at"]),
            models.Index(fields=["content_type", "object_id", "occurred_at"]),
            models.Index(fields=["event_type", "occurred_at"]),
            models.Index(fields=["actor", "occurred_at"]),
        ]

    def __str__(self):
        return f"[{self.occurred_at}] {self.event_type} {self.action}"
