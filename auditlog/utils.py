from django.contrib.contenttypes.models import ContentType
from typing import Optional, Dict, Any
from .middleware import get_current_request, get_current_user, get_request_id
from .models import AuditEvent

import json
from decimal import Decimal
from datetime import date, datetime
from uuid import UUID


def _get_ip(request):
    if not request:
        return None
    return request.META.get("REMOTE_ADDR")


def _get_user_agent(request):
    if not request:
        return None
    return request.META.get("HTTP_USER_AGENT")


def _get_session_key(request):
    if not request:
        return None
    try:
        return request.session.session_key
    except Exception:
        return None


def _json_safe(value: Any):
    """Convert common non-JSON-serializable types to JSON-safe equivalents."""
    if value is None:
        return None

    if isinstance(value, Decimal):
        # Use str to avoid float rounding issues
        return str(value)

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, UUID):
        return str(value)

    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")

    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]

    return value


def _sanitize_json(payload):
    """Ensure payload is JSON serializable; fallback to string if not."""
    if payload is None:
        return None

    payload = _json_safe(payload)

    try:
        json.dumps(payload)
    except TypeError:
        return {"_unserializable": str(payload)}
    return payload


def log_model_event(
    *,
    instance,
    action: str,
    event_type: str = "model.change",
    severity: str = "INFO",
    message: str = "",
    changes: Optional[Dict] = None,
    actor=None,
    dealership=None,
    claim=None,
    line=None,
    journal=None,
    line_num=None,
    metadata: Optional[Dict] = None,
):
    """
    Generic logger for model changes.
    Automatically attaches request context and actor if not provided.
    """
    request = get_current_request()
    if actor is None:
        actor = get_current_user()

    ct = ContentType.objects.get_for_model(instance.__class__)

    # ✅ Make JSON safe before saving to JSONField
    changes = _sanitize_json(changes)
    metadata = _sanitize_json(metadata)

    evt = AuditEvent(
        event_type=event_type,
        action=action,
        severity=severity,
        message=message or "",
        actor=actor,
        content_type=ct,
        object_id=str(instance.pk) if instance.pk is not None else None,
        changes=changes,
        metadata=metadata,

        request_id=get_request_id(),
        ip_address=_get_ip(request),
        user_agent=_get_user_agent(request),
        session_key=_get_session_key(request),

        dealership=dealership,
        claim=claim,
        line=line,
        journal=journal,
        line_num=line_num,
    )
    evt.save()
    return evt
