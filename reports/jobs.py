from core.dates import as_date, as_datetime
"""Database-backed export queue. The worker renders PDFs outside HTTP requests."""
import logging
from datetime import timedelta
from pathlib import Path
from urllib.parse import unquote, urlsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils import timezone
from xhtml2pdf import pisa

from decorators.access import accessible_dealerships, group_names, is_wrs_admin
from .models import ReportJob

logger = logging.getLogger(__name__)
MAX_PENDING = 5
MAX_ATTEMPTS = 3
LEASE = timedelta(minutes=30)


def enqueue_report(user, dealership, report_type, start_date=None, end_date=None):
    start_date, end_date = as_datetime(start_date), as_datetime(end_date)
    # Serialize submissions per user so simultaneous clicks cannot bypass the limit.
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=user.pk)
        active = ReportJob.objects.filter(requested_by=user, state__in=['queued', 'running'])
        duplicate = active.filter(dealership=dealership, report_type=report_type, start_date=start_date, end_date=end_date).first()
        if duplicate:
            return duplicate
        if active.count() >= MAX_PENDING:
            raise ValueError('You already have five reports waiting. Please wait for one to finish.')
        return ReportJob.objects.create(requested_by=user, dealership=dealership,
            report_type=report_type, start_date=start_date, end_date=end_date)


def claim_next_job():
    now = timezone.now()
    with transaction.atomic():
        candidates = ReportJob.objects.filter(
            Q(state='queued') | Q(state='running', started_at__lt=now - LEASE),
        )
        # MariaDB 10.6+ supports SKIP LOCKED; SQLite is used only in isolated tests.
        candidates = candidates.select_for_update(skip_locked=connection.features.has_select_for_update_skip_locked)
        job = candidates.first()
        if job is None:
            return None
        if job.attempts >= MAX_ATTEMPTS:
            job.state, job.error, job.finished_at = 'failed', 'Report processing was interrupted. Please request it again.', now
            job.save(update_fields=['state', 'error', 'finished_at'])
            return job
        job.state, job.started_at, job.finished_at = 'running', now, None
        job.attempts += 1
        job.error = ''
        job.save(update_fields=['state', 'started_at', 'finished_at', 'attempts', 'error'])
        return job


def report_path(job):
    return Path(settings.REPORT_ROOT) / 'jobs' / f'{job.pk}.pdf'


def report_filename(job):
    from django.utils.text import slugify
    day = as_date(job.start_date) or timezone.localdate(job.created_at)
    return f"{slugify(job.dealership.name)}-{slugify(job.report_type)}-{day.isoformat()}.pdf"


def local_asset(uri, relative_uri):
    """Resolve local static files only; never fetch URLs supplied by PDF content."""
    parsed = urlsplit(uri)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith(settings.STATIC_URL):
        raise ValueError('PDF assets must be local static files.')
    name = unquote(parsed.path[len(settings.STATIC_URL):])
    if '..' in Path(name).parts or Path(name).is_absolute():
        raise ValueError('Invalid PDF asset path.')
    # Prefer repository assets: the PDF engine confines document reads to its
    # working directory, while collectstatic may live outside that directory.
    found = finders.find(name)
    if found:
        return found
    root = Path(settings.STATIC_ROOT).resolve()
    path = (root / name).resolve()
    if path.is_relative_to(root) and path.is_file():
        return str(path)
    raise ValueError('PDF asset is missing.')


def render_report(job, destination):
    from .views import ReportService, get_claim_status_totals
    context = {'dealership': job.dealership.name, 'report_type': job.report_type,
        'start_date': as_date(job.start_date).isoformat() if job.start_date else '',
        'end_date': as_date(job.end_date).isoformat() if job.end_date else ''}
    if job.report_type == 'Daily Report':
        report = ReportService.generate_daily_report(job.dealership_id, job.start_date)
        context['claim_status_totals'] = get_claim_status_totals(job.dealership_id, job.start_date)
        template = 'reports/report_pdf.html'
    elif job.report_type == 'Archived Report':
        report = ReportService.generate_archived_report(job.dealership_id, job.start_date)
        template = 'reports/archive_report_pdf.html'
    elif job.report_type == 'Discrepancy Report':
        report = ReportService.generate_discrepancy_report(job.dealership_id, job.start_date, job.end_date)
        template = 'reports/discrepancy_pdf.html'
    elif job.report_type == 'RA Report':
        report = ReportService.generate_ra_report(job.dealership_id, 'Requires Attention')
        context['report_type'] = 'Requires Attention Report'
        template = 'reports/rareport_pdf.html'
    else:
        raise ValueError('Invalid report type.')
    context.update(report=report, message='' if report else 'There is no report to export')
    content = render_to_string(template, context)
    result = pisa.CreatePDF(content, dest=destination, link_callback=local_asset)
    if result.err:
        raise ValueError('PDF rendering failed.')


def process_job(job):
    if job.state != 'running':
        return
    path = report_path(job)
    # Attempt-specific files prevent a late expired worker overwriting a newer result.
    temporary = path.with_suffix(f'.{job.attempts}.tmp')
    try:
        user = job.requested_by
        if (not user.is_active or
            (not is_wrs_admin(user) and not group_names(user).intersection({'dealer-admin', 'wrs-admin'})) or
            not accessible_dealerships(user).filter(pk=job.dealership_id).exists()):
            raise PermissionDenied('Report access was revoked.')
        path.parent.mkdir(parents=True, exist_ok=True)
        with temporary.open('wb') as destination:
            render_report(job, destination)
        with transaction.atomic():
            current = ReportJob.objects.select_for_update().get(pk=job.pk)
            if current.state != 'running' or current.attempts != job.attempts:
                return
            temporary.replace(path)
            current.state, current.finished_at = 'completed', timezone.now()
            current.save(update_fields=['state', 'finished_at'])
    except Exception:
        logger.exception('Report generation failed for job %s', job.pk)
        ReportJob.objects.filter(pk=job.pk, state='running', attempts=job.attempts).update(
            state='failed', finished_at=timezone.now(),
            error='Unable to generate this report. Please request it again or contact an administrator.',
        )
    finally:
        temporary.unlink(missing_ok=True)


def remove_expired_reports():
    """Remove abandoned exports after one hour; downloaded exports are removed immediately."""
    cutoff = timezone.now() - timedelta(hours=1)
    expired = ReportJob.objects.filter(state__in=['completed', 'failed'], finished_at__lt=cutoff)
    for job in expired.iterator(chunk_size=100):
        report_path(job).unlink(missing_ok=True)
        job.delete()
    directory = Path(settings.REPORT_ROOT) / 'jobs'
    if directory.is_dir():
        for path in directory.iterdir():
            if path.is_file() and path.suffix in {'.pdf', '.tmp'} and path.stat().st_mtime < cutoff.timestamp():
                path.unlink(missing_ok=True)
