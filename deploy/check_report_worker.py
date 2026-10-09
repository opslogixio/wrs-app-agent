"""Exercise the running report worker with an empty future report, then clean up."""
import os
from pathlib import Path
import secrets
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
import django
django.setup()

from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.db import connection, transaction
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from accounts.models import Dealership
from dashboard.services import build_dashboard
from reports.jobs import report_path
from reports.models import ReportJob

# Verify the real dealership data, queue pages, and grouped query budget.
with CaptureQueriesContext(connection) as queries:
    rows, totals = build_dashboard(Dealership.objects.all())
assert len(queries) == 3, len(queries)
print(f'Dashboard: {len(rows)} dealerships aggregated in {len(queries)} queries.')

client = Client(HTTP_HOST='wrs.opslogix.io', HTTP_X_FORWARDED_PROTO='https')
dealer = Dealership.objects.order_by('pk').first()
assert dealer is not None, 'At least one dealership is needed for the deployment check.'

# Dashboard/queue checks roll back fixtures; worker jobs need a committed row.
with transaction.atomic():
    user = get_user_model().objects.create_superuser(
        email=f'queue-check-{secrets.token_hex(8)}@example.invalid', password=secrets.token_urlsafe(24))
    user.dealership.add(dealer)
    client.force_login(user)
    for route, status in (('claim-queue', 'Rework'), ('new-claim-queue', 'New'),
        ('pending-claim-queue', 'Pending'), ('rework-claim-queue', 'Rework'),
        ('ra-claim-queue', 'Requires Attention'), ('ra-claim-queue', 'Aging')):
        with CaptureQueriesContext(connection) as queries:
            response = client.get(reverse('claim:' + route, args=[status]), {'dealership_id': dealer.pk})
        assert response.status_code == 200, (route, response.status_code)
        assert len(queries) <= 14, (route, len(queries))
    transaction.set_rollback(True)
print('All six queue routes rendered successfully against the imported database.')

user = get_user_model().objects.create_superuser(
    email=f'report-check-{secrets.token_hex(8)}@example.invalid', password=secrets.token_urlsafe(24))
job = None
try:
    user.dealership.add(dealer)
    client.force_login(user)
    response = client.post(reverse('reports:report-export'), {
        'dealership': dealer.name, 'report_type': 'Daily Report', 'start_date': '2099-01-01',
    })
    assert response.status_code == 302, response.status_code
    job = ReportJob.objects.get(requested_by=user)
    deadline = time.monotonic() + 45
    while job.state in {'queued', 'running'} and time.monotonic() < deadline:
        time.sleep(1)
        job.refresh_from_db()
    assert job.state == 'completed', (job.state, job.error)
    status = client.get(reverse('reports:report-job', args=[job.pk]), {'format': 'json'})
    assert status.status_code == 200 and status.json()['download_url'], status.status_code
    download = client.get(status.json()['download_url'])
    assert download.status_code == 200, download.status_code
    content = b''.join(download.streaming_content)
    assert content.startswith(b'%PDF-'), content[:20]
    from pypdf import PdfReader
    from io import BytesIO
    assert any(len(page.images) for page in PdfReader(BytesIO(content)).pages), 'PDF logo is missing'
    print(f'Systemd worker generated and authorized a {len(content)}-byte PDF; temporary records removed.')
finally:
    if job:
        report_path(job).unlink(missing_ok=True)
    Session.objects.filter(session_key=client.session.session_key).delete()
    user.delete()
