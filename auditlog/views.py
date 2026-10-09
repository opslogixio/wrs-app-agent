from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render
from datetime import datetime, time, timedelta
from django.utils import timezone
from accounts.models import Dealership
from .models import AuditEvent


def _change_value_display(value):
    if isinstance(value, dict):
        if "display" in value:
            return value.get("display") or "—"
        if "raw" in value:
            return value.get("raw") or "—"

    if value is None:
        return "—"

    return str(value)


def _format_changes_for_display(changes):
    if not changes:
        return []

    rows = []

    for field, values in changes.items():
        old_value = values.get("old") if isinstance(values, dict) else None
        new_value = values.get("new") if isinstance(values, dict) else None

        rows.append({
            "field": field.replace("_id", "").replace("_", " ").title(),
            "old": _change_value_display(old_value),
            "new": _change_value_display(new_value),
        })

    return rows

@login_required
def audit_event_list(request):
    tz = timezone.get_current_timezone()
    
    qs = (
        AuditEvent.objects
        .select_related(
            "actor",
            "dealership",
            "claim",
            "line",
            "journal",
            "content_type",
        )
        .order_by("-occurred_at")
    )

    # ---- Filters (GET params) ----
    q = request.GET.get("q", "").strip()
    event_type = request.GET.get("event_type", "").strip()
    action = request.GET.get("action", "").strip()
    actor_id = request.GET.get("actor_id", "").strip()
    dealership_id = request.GET.get("dealership_id", "").strip()
    claim_id = request.GET.get("claim_id", "").strip()
    line_id = request.GET.get("line_id", "").strip()
    journal_id = request.GET.get("journal_id", "").strip()
    date_from = request.GET.get("date_from", "").strip()  # YYYY-MM-DD
    date_to = request.GET.get("date_to", "").strip()      # YYYY-MM-DD
    dealership = request.GET.get("dealership", "").strip()
    actor = request.GET.get("actor", "").strip()
    repair_order = request.GET.get("repair_order", "").strip()
    line = request.GET.get("line", "").strip()
    journal = request.GET.get("journal", "").strip()

    if q:
        search_filter = (
            Q(message__icontains=q)
            | Q(ip_address__icontains=q)
            | Q(object_id__icontains=q)
            | Q(changes__icontains=q)
            | Q(metadata__icontains=q)

            # readable values
            | Q(actor__email__icontains=q)
            | Q(dealership__name__icontains=q)
            | Q(claim__repair_order__icontains=q)
            | Q(journal__comment__icontains=q)
        )

        # legacy/admin ID values
        # Only search integer/FK fields when q is numeric.
        if q.isdigit():
            search_filter |= (
                Q(actor_id=int(q))
                | Q(dealership_id=int(q))
                | Q(claim_id=int(q))
                | Q(line_id=int(q))
                | Q(journal_id=int(q))
                | Q(line_num=int(q))
            )

        qs = qs.filter(search_filter)

    if event_type:
        qs = qs.filter(event_type=event_type)

    if action:
        qs = qs.filter(action=action)

    # friendly filters
    if dealership:
        if dealership.isdigit():
            qs = qs.filter(dealership_id=int(dealership))
        else:
            qs = qs.filter(dealership__name__icontains=dealership)

    if actor:
        qs = qs.filter(actor__email__icontains=actor)

    if repair_order:
        qs = qs.filter(claim__repair_order__icontains=repair_order)

    if line:
        qs = qs.filter(
            Q(line_num__icontains=line)
            | Q(line__line_num__icontains=line)
        )

    if journal:
        qs = qs.filter(journal__comment__icontains=journal)

    # legacy/admin ID filters
    if actor_id.isdigit():
        qs = qs.filter(actor_id=int(actor_id))

    if dealership_id.isdigit():
        qs = qs.filter(dealership_id=int(dealership_id))

    if claim_id.isdigit():
        qs = qs.filter(claim_id=int(claim_id))

    if line_id.isdigit():
        qs = qs.filter(line_id=int(line_id))

    if journal_id.isdigit():
        qs = qs.filter(journal_id=int(journal_id))

    # date range
    if date_from:
        df = datetime.strptime(date_from, "%Y-%m-%d").date()
        start_dt = timezone.make_aware(datetime.combine(df, time.min), tz)
        qs = qs.filter(occurred_at__gte=start_dt)

    if date_to:
        dt = datetime.strptime(date_to, "%Y-%m-%d").date()
        end_dt = timezone.make_aware(datetime.combine(dt + timedelta(days=1), time.min), tz)
        qs = qs.filter(occurred_at__lt=end_dt)


    # ---- Pagination ----
    paginator = Paginator(qs, 50)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    for event in page_obj.object_list:
        event.changes_display = _format_changes_for_display(event.changes)

    # For dropdowns in the template
    context = {
        "page_obj": page_obj,
        "filters": {
            "q": q,
            "event_type": event_type,
            "action": action,
            "actor_id": actor_id,
            "dealership_id": dealership_id,
            "claim_id": claim_id,
            "line_id": line_id,
            "journal_id": journal_id,
            "date_from": date_from,
            "date_to": date_to,
            "dealership": dealership,
            "actor": actor,
            "repair_order": repair_order,
            "line": line,
            "journal": journal,
            
        },
        "event_type_choices": AuditEvent.EVENT_TYPE_CHOICES,
        "action_choices": AuditEvent.ACTION_CHOICES,
        "dealership_choices": Dealership.objects.all().order_by("name"),
    }

    return render(request, "auditlog/event_list.html", context)
