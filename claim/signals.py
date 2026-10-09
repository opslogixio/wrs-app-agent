# claim/signals.py
#
# Drop-in replacement: production-safe auditing signals.
# Key improvements:
# - Uses *_id fields and safe DB lookups in post_delete handlers (no dereferencing relations that may be gone).
# - Uses safe lookups in Journal handlers to avoid DoesNotExist during cascades.
# - Keeps your existing diff logic intact.

from django.db.models.signals import pre_save, post_save, post_delete
from django.dispatch import receiver

from auditlog.utils import log_model_event
from .models import Claim, LineTable, Journal


#def _diff(old, new):
#    """
#    old/new are dicts of field->value
#    returns {field: {"old":..., "new":...}} for changed fields
#    """
#    changes = {}
#    for k in new.keys():
#        if old.get(k) != new.get(k):
#            changes[k] = {"old": old.get(k), "new": new.get(k)}
#    return changes

def _safe_display(value):
    if value is None:
        return None

    try:
        return str(value)
    except Exception:
        return value


def _resolve_display(field, value):
    """
    Convert FK IDs into readable values.
    Keeps raw IDs while also storing human-readable labels.
    """

    if value is None:
        return {
            "raw": None,
            "display": None,
        }

    try:
        #
        # Claim fields
        #
        if field == "dealership_id":
            from accounts.models import Dealership

            obj = Dealership.objects.filter(pk=value).first()

            return {
                "raw": value,
                "display": obj.name if obj else value,
            }

        elif field == "claim_status_id":
            from claim.models import ClaimStatus

            obj = ClaimStatus.objects.filter(pk=value).first()

            return {
                "raw": value,
                "display": str(obj) if obj else value,
            }

        elif field == "ro_status_id":
            from claim.models import ROStatus

            obj = ROStatus.objects.filter(pk=value).first()

            return {
                "raw": value,
                "display": str(obj) if obj else value,
            }

        elif field == "service_writer_id":
            from accounts.models import CustomUser

            obj = CustomUser.objects.filter(pk=value).first()

            return {
                "raw": value,
                "display": obj.email if obj else value,
            }

        elif field == "technician_id":
            from accounts.models import CustomUser

            obj = CustomUser.objects.filter(pk=value).first()

            return {
                "raw": value,
                "display": obj.email if obj else value,
            }

        elif field == "claim_id":
            obj = Claim.objects.filter(pk=value).first()

            return {
                "raw": value,
                "display": obj.repair_order if obj else value,
            }

        elif field == "line_id":
            obj = LineTable.objects.filter(pk=value).first()

            if obj:
                display = f"Line {obj.line_num}"
            else:
                display = value

            return {
                "raw": value,
                "display": display,
            }

        #
        # Default fallback
        #
        return {
            "raw": value,
            "display": _safe_display(value),
        }

    except Exception:
        return {
            "raw": value,
            "display": _safe_display(value),
        }


def _diff(old, new):
    """
    old/new are dicts of field->value
    returns readable audit changes
    """

    changes = {}

    for k in new.keys():
        old_val = old.get(k)
        new_val = new.get(k)

        if old_val != new_val:
            changes[k] = {
                "old": _resolve_display(k, old_val),
                "new": _resolve_display(k, new_val),
            }

    return changes

def _safe_dealership_obj_from_id(dealership_id):
    if not dealership_id:
        return None
    # Local import to avoid circular imports at import-time
    from accounts.models import Dealership
    return Dealership.objects.filter(pk=dealership_id).first()


def _safe_dealership_id_from_claim_id(claim_id):
    if not claim_id:
        return None
    return (
        Claim.objects.filter(pk=claim_id)
        .values_list("dealership_id", flat=True)
        .first()
    )


def _safe_claim_id_from_line_id(line_id):
    if not line_id:
        return None
    return (
        LineTable.objects.filter(pk=line_id)
        .values_list("claim_id", flat=True)
        .first()
    )


def _safe_line_num_from_line_id(line_id):
    if not line_id:
        return None
    return (
        LineTable.objects.filter(pk=line_id)
        .values_list("line_num", flat=True)
        .first()
    )


# --------------------
# Claim auditing
# --------------------
@receiver(pre_save, sender=Claim)
def claim_pre_save(sender, instance: Claim, **kwargs):
    if not instance.pk:
        instance._audit_old = None
        return

    old = (
        Claim.objects.filter(pk=instance.pk)
        .values("repair_order", "dealership_id", "ro_status_id")
        .first()
    )
    instance._audit_old = old


@receiver(post_save, sender=Claim)
def claim_post_save(sender, instance: Claim, created, **kwargs):
    if created:
        log_model_event(
            instance=instance,
            action="CREATE",
            dealership=instance.dealership,
            claim=instance,
            message="Claim created",
            changes=None,
        )
    else:
        old = getattr(instance, "_audit_old", None) or {}
        new = (
            Claim.objects.filter(pk=instance.pk)
            .values("repair_order", "dealership_id", "ro_status_id")
            .first()
            or {}
        )

        changes = _diff(old, new)
        if changes:
            log_model_event(
                instance=instance,
                action="UPDATE",
                dealership=instance.dealership,
                claim=instance,
                message="Claim updated",
                changes=changes,
            )


@receiver(post_delete, sender=Claim)
def claim_post_delete(sender, instance: Claim, **kwargs):
    # Avoid dereferencing anything that might cascade; Claim still has dealership_id on instance
    dealership = _safe_dealership_obj_from_id(getattr(instance, "dealership_id", None))

    log_model_event(
        instance=instance,
        action="DELETE",
        dealership=dealership,
        claim=None,
        message="Claim deleted",
        changes=None,
        metadata={"deleted_pk": instance.pk},
    )


# --------------------
# LineTable auditing
# --------------------
@receiver(pre_save, sender=LineTable)
def line_pre_save(sender, instance: LineTable, **kwargs):
    if not instance.pk:
        instance._audit_old = None
        return

    old = (
        LineTable.objects.filter(pk=instance.pk)
        .values(
            "line_num",
            "claim_id",
            "dealership_id",
            "claim_type_id",
            "service_writer_id",
            "technician_id",
            "claim_total",
            "claim_status_id",
            "start_date",
            "paid_date",
            "compliant",
            "discrepancy_id",
        )
        .first()
    )
    instance._audit_old = old


@receiver(post_save, sender=LineTable)
def line_post_save(sender, instance: LineTable, created, **kwargs):
    # Safe dealership resolution: prefer line.dealership_id, else claim.dealership_id
    dealership_id = getattr(instance, "dealership_id", None)
    if not dealership_id and getattr(instance, "claim_id", None):
        dealership_id = _safe_dealership_id_from_claim_id(instance.claim_id)

    dealership = _safe_dealership_obj_from_id(dealership_id)

    if created:
        log_model_event(
            instance=instance,
            action="CREATE",
            dealership=dealership,
            claim=instance.claim,  # safe for save handlers
            line=instance,
            line_num=instance.line_num,
            message="Line created",
            changes=None,
        )
    else:
        old = getattr(instance, "_audit_old", None) or {}
        new = (
            LineTable.objects.filter(pk=instance.pk)
            .values(
                "line_num",
                "claim_id",
                "dealership_id",
                "claim_type_id",
                "service_writer_id",
                "technician_id",
                "claim_total",
                "claim_status_id",
                "start_date",
                "paid_date",
                "compliant",
                "discrepancy_id",
            )
            .first()
            or {}
        )

        changes = _diff(old, new)
        if changes:
            log_model_event(
                instance=instance,
                action="UPDATE",
                dealership=dealership,
                claim=instance.claim,  # safe for save handlers
                line=instance,
                line_num=instance.line_num,
                message="Line updated",
                changes=changes,
            )


@receiver(post_delete, sender=LineTable)
def line_post_delete(sender, instance: LineTable, **kwargs):
    # DO NOT dereference instance.claim or instance.dealership here (cascade may have removed related rows).
    claim_id = getattr(instance, "claim_id", None)
    dealership_id = getattr(instance, "dealership_id", None)

    if not dealership_id and claim_id:
        dealership_id = _safe_dealership_id_from_claim_id(claim_id)

    dealership = _safe_dealership_obj_from_id(dealership_id)
    claim_obj = Claim.objects.filter(pk=claim_id).first() if claim_id else None

    log_model_event(
        instance=instance,
        action="DELETE",
        dealership=dealership,
        claim=claim_obj,
        line=None,
        line_num=getattr(instance, "line_num", None),
        message="Line deleted",
        metadata={"deleted_pk": instance.pk},
    )


# --------------------
# Journal auditing
# --------------------
@receiver(pre_save, sender=Journal)
def journal_pre_save(sender, instance: Journal, **kwargs):
    if not instance.pk:
        instance._audit_old = None
        return

    old = (
        Journal.objects.filter(pk=instance.pk)
        .values("comment", "line_id", "claim_id", "user_id")
        .first()
    )
    instance._audit_old = old


@receiver(post_save, sender=Journal)
def journal_post_save(sender, instance: Journal, created, **kwargs):
    # Prefer IDs to avoid DoesNotExist surprises; safe for saves but consistent with deletes.
    claim_id = getattr(instance, "claim_id", None)
    line_id = getattr(instance, "line_id", None)

    if not claim_id and line_id:
        claim_id = _safe_claim_id_from_line_id(line_id)

    dealership_id = _safe_dealership_id_from_claim_id(claim_id)
    dealership = _safe_dealership_obj_from_id(dealership_id)
    line_num = _safe_line_num_from_line_id(line_id)

    claim_obj = Claim.objects.filter(pk=claim_id).first() if claim_id else None
    line_obj = LineTable.objects.filter(pk=line_id).first() if line_id else None

    if created:
        log_model_event(
            instance=instance,
            action="CREATE",
            dealership=dealership,
            claim=claim_obj,
            line=line_obj,
            journal=instance,
            line_num=line_num,
            message="Journal entry created",
            changes=None,
        )
    else:
        old = getattr(instance, "_audit_old", None) or {}
        new = (
            Journal.objects.filter(pk=instance.pk)
            .values("comment", "line_id", "claim_id", "user_id")
            .first()
            or {}
        )

        changes = _diff(old, new)
        if changes:
            log_model_event(
                instance=instance,
                action="UPDATE",
                dealership=dealership,
                claim=claim_obj,
                line=line_obj,
                journal=instance,
                line_num=line_num,
                message="Journal entry updated",
                changes=changes,
            )


@receiver(post_delete, sender=Journal)
def journal_post_delete(sender, instance: Journal, **kwargs):
    # DO NOT dereference instance.line or instance.claim here (cascade may have removed related rows).
    claim_id = getattr(instance, "claim_id", None)
    line_id = getattr(instance, "line_id", None)

    if not claim_id and line_id:
        claim_id = _safe_claim_id_from_line_id(line_id)

    dealership_id = _safe_dealership_id_from_claim_id(claim_id)
    dealership = _safe_dealership_obj_from_id(dealership_id)
    line_num = _safe_line_num_from_line_id(line_id)

    claim_obj = Claim.objects.filter(pk=claim_id).first() if claim_id else None
    line_obj = LineTable.objects.filter(pk=line_id).first() if line_id else None

    log_model_event(
        instance=instance,
        action="DELETE",
        dealership=dealership,
        claim=claim_obj,
        line=line_obj,
        journal=None,
        line_num=line_num,
        message="Journal entry deleted",
        metadata={"deleted_pk": instance.pk},
    )
