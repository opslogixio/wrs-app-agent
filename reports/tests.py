from pathlib import Path
import tempfile

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Dealership
from core.settings import PublicAssetsFinder


class DocumentSecurityTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email='report@example.invalid')
        self.user.groups.add(Group.objects.create(name='dealer-admin'))
        self.own = Dealership.objects.create(name='Assigned Dealer')
        self.other = Dealership.objects.create(name='Other Dealer')
        self.user.dealership.add(self.own)
        self.client.force_login(self.user)

    def test_archived_report_download_checks_dealership_and_traversal(self):
        with tempfile.TemporaryDirectory() as directory, override_settings(REPORT_ROOT=Path(directory)):
            for dealer in (self.own, self.other):
                folder = Path(directory) / dealer.name.replace(' ', '_')
                folder.mkdir()
                (folder / 'report.pdf').write_bytes(b'%PDF-1.4\n')
            response = self.client.get(reverse('reports:download-report', args=['Assigned_Dealer/report.pdf']))
            self.assertEqual(response.status_code, 200)
            list(response.streaming_content)
            self.assertEqual(self.client.get(reverse('reports:download-report', args=['Other_Dealer/report.pdf'])).status_code, 404)
            self.assertEqual(self.client.get(reverse('reports:download-report', args=['../outside.pdf'])).status_code, 404)

    def test_collectstatic_excludes_private_documents(self):
        with tempfile.TemporaryDirectory() as directory, override_settings(STATICFILES_DIRS=[directory]):
            root = Path(directory)
            (root / 'public.css').write_text('body {}')
            for folder in ('upload', 'daily-report-pdf'):
                (root / folder).mkdir()
                (root / folder / 'private.pdf').write_bytes(b'%PDF-1.4')
            names = [name for name, _ in PublicAssetsFinder().list([])]
            self.assertIn('public.css', names)
            self.assertFalse(any(name.endswith('.pdf') for name in names))


class DailyReportIsolationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from claim.models import Claim, ClaimType, LineTable, RoStatus, Status
        from datetime import date
        cls.today = date.today()
        cls.own = Dealership.objects.create(name='Own')
        cls.other = Dealership.objects.create(name='Other')
        status = Status.objects.create(name='Paid')
        ro_status = RoStatus.objects.create(name='Open')
        claim_type = ClaimType.objects.create(name='Warranty')
        cls.claim = Claim.objects.create(dealership=cls.own, repair_order=123, ro_status=ro_status)
        foreign = Claim.objects.create(dealership=cls.other, repair_order=123, ro_status=ro_status)
        for claim, dealer, amount in ((cls.claim, cls.own, '10.25'), (cls.claim, cls.own, '20.50'), (foreign, cls.other, '999.00')):
            LineTable.objects.create(claim=claim, dealership=dealer, claim_type=claim_type, claim_status=status, claim_total=amount)

    def test_daily_report_does_not_mix_identical_repair_orders_between_dealerships(self):
        from .views import ReportService
        from decimal import Decimal
        with self.assertNumQueries(2):
            report = ReportService.generate_daily_report(self.own.pk, self.today)
            # Render-related FK access must also be served by the prefetched query.
            for item in report:
                for entry in item['line_data']:
                    _ = entry['line'].claim.ro_status.name
                    _ = entry['line'].claim_type.name
                    _ = entry['line'].claim_status.name
        self.assertEqual(len(report), 1)
        self.assertEqual(report[0]['paid_claim_total'], Decimal('30.75'))
        self.assertEqual({entry['line'].claim_id for entry in report[0]['line_data']}, {self.claim.pk})


class BackgroundReportTests(TestCase):
    def setUp(self):
        from .models import ReportJob
        self.jobs = ReportJob
        self.dealer = Dealership.objects.create(name='Export Dealer')
        self.foreign = Dealership.objects.create(name='Foreign')
        self.user = get_user_model().objects.create_user(email='export@example.invalid')
        self.user.groups.add(Group.objects.create(name='dealer-admin'))
        self.user.dealership.add(self.dealer)
        self.other_user = get_user_model().objects.create_user(email='otherexport@example.invalid')
        self.other_user.groups.add(Group.objects.get(name='dealer-admin'))
        self.other_user.dealership.add(self.dealer)
        self.client.force_login(self.user)
        self.url = reverse('reports:report-export')
        self.params = {'dealership': self.dealer.name, 'report_type': 'Daily Report', 'start_date': '2026-10-08'}
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.override = override_settings(REPORT_ROOT=Path(self.directory.name))
        self.override.enable()
        self.addCleanup(self.override.disable)

    def queue(self):
        from .jobs import enqueue_report
        from datetime import date
        return enqueue_report(self.user, self.dealer, 'Daily Report', date(2026, 10, 8))

    def test_get_confirms_without_enqueuing_and_post_returns_status_page(self):
        from unittest.mock import patch
        self.assertEqual(self.client.get(self.url, self.params).status_code, 200)
        self.assertFalse(self.jobs.objects.exists())
        with patch('reports.jobs.render_report') as render:
            response = self.client.post(self.url, self.params)
            render.assert_not_called()
        job = self.jobs.objects.get()
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()['status_url'], reverse('reports:report-job', args=[job.pk]))
        self.assertEqual(job.state, 'queued')
        self.assertEqual(self.client.post(self.url, self.params).status_code, 202)
        self.assertEqual(self.jobs.objects.count(), 1)
        self.assertEqual(self.client.get(reverse('reports:report-export').rsplit('report_export/', 1)[0] + 'jobs/').status_code, 404)

    def test_export_validation_authorization_and_csrf(self):
        from django.test import Client
        for params, code in ((dict(self.params, dealership=self.foreign.name), 404),
            (dict(self.params, start_date='bad'), 400), (dict(self.params, report_type='Unknown'), 400),
            (dict(self.params, report_type='Discrepancy Report', end_date='2026-10-01'), 400)):
            self.assertEqual(self.client.post(self.url, params).status_code, code)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(self.url, self.params).status_code, 403)
        self.assertFalse(self.jobs.objects.exists())

    def test_per_user_limit_applies_to_distinct_requests(self):
        from datetime import date
        from .jobs import enqueue_report
        for day in range(1, 6):
            enqueue_report(self.user, self.dealer, 'Daily Report', date(2026, 10, day))
        response = self.client.post(self.url, self.params)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(self.jobs.objects.count(), 5)

    def test_worker_creates_real_pdf_and_authenticated_download(self):
        from .jobs import claim_next_job, process_job, report_path
        job = self.queue()
        claimed = claim_next_job()
        self.assertEqual(claimed.pk, job.pk)
        self.assertIsNone(claim_next_job())
        process_job(claimed)
        job.refresh_from_db()
        self.assertEqual(job.state, 'completed', job.error)
        self.assertTrue(report_path(job).read_bytes().startswith(b'%PDF-'))
        from pypdf import PdfReader
        self.assertTrue(any(len(page.images) for page in PdfReader(report_path(job)).pages))
        status = self.client.get(reverse('reports:report-job', args=[job.pk]))
        self.assertEqual(status.json()['state'], 'completed')
        self.assertTrue(status.json()['download_url'])
        response = self.client.get(status.json()['download_url'])
        self.assertEqual(response.status_code, 200)
        self.assertTrue(b''.join(response.streaming_content).startswith(b'%PDF-'))
        self.assertFalse(report_path(job).exists())
        self.assertFalse(self.jobs.objects.filter(pk=job.pk).exists())

    def test_every_report_type_renders_data_in_local_pdf(self):
        from .jobs import enqueue_report, claim_next_job, process_job, report_path
        from claim.models import Claim, ClaimType, LineTable, RoStatus, Status, Discrepancy
        from .models import HistoricalClaim, HistoricalLineTable
        from django.utils import timezone
        from pypdf import PdfReader
        status = Status.objects.create(name='Requires Attention')
        open_status = RoStatus.objects.create(name='Open')
        claim_type = ClaimType.objects.create(name='Warranty')
        discrepancy = Discrepancy.objects.create(labor='10')
        claim = Claim.objects.create(dealership=self.dealer, repair_order=7654321, ro_status=open_status)
        LineTable.objects.create(claim=claim, dealership=self.dealer, claim_status=status,
            claim_type=claim_type, claim_total='123.45', discrepancy=discrepancy)
        historical = HistoricalClaim.objects.create(dealership=self.dealer, repair_order=7654321,
            ro_status=open_status, created_date=timezone.now())
        HistoricalLineTable.objects.create(claim=historical, dealership=self.dealer, claim_status=status, claim_total='123.45')
        today = timezone.localdate()
        for name in ('Daily Report', 'Archived Report', 'Discrepancy Report', 'RA Report'):
            with self.subTest(report_type=name):
                job = enqueue_report(self.user, self.dealer, name,
                    None if name == 'RA Report' else today,
                    today if name == 'Discrepancy Report' else None)
                process_job(claim_next_job())
                job.refresh_from_db()
                self.assertEqual(job.state, 'completed', job.error)
                self.assertTrue(report_path(job).is_file())
                reader = PdfReader(report_path(job))
                self.assertTrue(any(len(page.images) for page in reader.pages), f'{name} logo is missing')
                from pypdf.generic import ContentStream
                for page in reader.pages:
                    for operands, operator in ContentStream(page.get_contents(), reader).operations:
                        if operator == b'cm':
                            self.assertLess(abs(float(operands[4])), float(page.mediabox.width), 'Graphic translated outside page')
                            self.assertLess(abs(float(operands[5])), float(page.mediabox.height), 'Graphic translated outside page')
                text = '\n'.join(page.extract_text() for page in reader.pages)
                self.assertIn('7654321', text)
                self.assertIn(self.dealer.name, text)
                if name != 'RA Report':
                    self.assertIn(today.isoformat(), text)

    def test_foreign_user_or_revoked_membership_cannot_read_job(self):
        job = self.queue()
        self.client.force_login(self.other_user)
        self.assertEqual(self.client.get(reverse('reports:report-job', args=[job.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('reports:report-job-download', args=[job.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('reports:report-export').rsplit('report_export/', 1)[0] + 'jobs/').status_code, 404)
        self.client.force_login(self.user)
        self.user.dealership.clear()
        self.assertEqual(self.client.get(reverse('reports:report-job', args=[job.pk])).status_code, 404)

    def test_worker_rechecks_membership_and_leaves_no_partial_file(self):
        from .jobs import claim_next_job, process_job, report_path
        job = self.queue()
        self.user.dealership.clear()
        with self.assertLogs('reports.jobs', level='ERROR'):
            process_job(claim_next_job())
        job.refresh_from_db()
        self.assertEqual(job.state, 'failed')
        self.assertFalse(report_path(job).exists())

    def test_interrupted_worker_is_recovered_and_attempts_are_bounded(self):
        from .jobs import claim_next_job, LEASE, MAX_ATTEMPTS
        from datetime import timedelta
        from django.utils import timezone
        job = self.queue()
        self.jobs.objects.filter(pk=job.pk).update(state='running', started_at=timezone.now() - LEASE - timedelta(seconds=1), attempts=1)
        claimed = claim_next_job()
        self.assertEqual(claimed.attempts, 2)
        self.jobs.objects.filter(pk=job.pk).update(started_at=timezone.now() - LEASE - timedelta(seconds=1), attempts=MAX_ATTEMPTS)
        self.assertEqual(claim_next_job().state, 'failed')
        self.assertIsNone(claim_next_job())

    def test_expired_attempt_cannot_publish_over_new_worker(self):
        from .jobs import claim_next_job, process_job, report_path
        from unittest.mock import patch
        job = self.queue()
        claimed = claim_next_job()
        self.jobs.objects.filter(pk=job.pk).update(attempts=2)
        def render(job, destination):
            destination.write(b'%PDF-test')
        with patch('reports.jobs.render_report', side_effect=render):
            process_job(claimed)
        self.assertFalse(report_path(job).exists())
        self.assertFalse(list(Path(self.directory.name).rglob('*.tmp')))

    def test_pdf_assets_reject_remote_urls_and_traversal(self):
        from .jobs import local_asset
        for uri in ('https://example.invalid/logo.png', 'file:///etc/passwd', '/static/../secret.png', '/static/%2e%2e/secret.png'):
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                local_asset(uri, '')

    def test_expired_exports_are_removed_and_job_folder_cannot_use_legacy_download(self):
        from datetime import timedelta
        from django.utils import timezone
        from .jobs import report_path, remove_expired_reports
        job = self.queue()
        self.jobs.objects.filter(pk=job.pk).update(state='completed', finished_at=timezone.now() - timedelta(days=8))
        path = report_path(job)
        path.parent.mkdir(parents=True)
        path.write_bytes(b'%PDF-test')
        self.assertEqual(self.client.get(reverse('reports:download-report', args=[f'jobs/{job.pk}.pdf'])).status_code, 404)
        remove_expired_reports()
        self.assertFalse(path.exists())
        self.assertFalse(self.jobs.objects.exists())


from django.test import TransactionTestCase, skipUnlessDBFeature


class ReportWorkerConcurrencyTests(TransactionTestCase):
    @skipUnlessDBFeature('has_select_for_update_skip_locked')
    def test_worker_skips_job_locked_by_another_connection(self):
        import threading
        from django.db import close_old_connections, transaction
        from .models import ReportJob
        from .jobs import claim_next_job
        dealer = Dealership.objects.create(name='Concurrent')
        user = get_user_model().objects.create_user(email='concurrent@example.invalid')
        first = ReportJob.objects.create(dealership=dealer, requested_by=user, report_type='RA Report')
        second = ReportJob.objects.create(dealership=dealer, requested_by=user, report_type='RA Report')
        results = []
        errors = []
        def claim():
            close_old_connections()
            try:
                results.append(claim_next_job().pk)
            except Exception as error:
                errors.append(error)
            finally:
                close_old_connections()
        with transaction.atomic():
            ReportJob.objects.select_for_update().get(pk=first.pk)
            worker = threading.Thread(target=claim, daemon=True)
            worker.start()
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive(), 'Worker blocked instead of skipping a locked job')
        self.assertEqual(errors, [])
        self.assertEqual(results, [second.pk])


class ReportTaskTests(TestCase):
    def setUp(self):
        from claim.models import Claim, LineTable, Status
        self.dealer = Dealership.objects.create(name='Task Reports')
        self.admin = get_user_model().objects.create_user(email='new-admin@example.invalid')
        self.admin.groups.add(Group.objects.create(name='wrs-admin'))
        self.user = get_user_model().objects.create_user(email='dealer-comment@example.invalid')
        self.user.groups.add(Group.objects.create(name='dealer-admin'))
        self.user.dealership.add(self.dealer)
        self.claim = Claim.objects.create(dealership=self.dealer, repair_order=555)
        self.line = LineTable.objects.create(claim=self.claim, dealership=self.dealer,
            claim_status=Status.objects.create(name='Requires Attention'))
        self.client.force_login(self.user)

    def test_ra_reports_include_admin_comments_from_latest_comment_day(self):
        from datetime import timedelta
        from django.utils import timezone
        from claim.models import Journal
        from .views import ReportService
        today = timezone.localdate()
        old = Journal.objects.create(claim=self.claim, line=self.line, user=self.admin, comment='Old admin comment')
        Journal.objects.filter(pk=old.pk).update(created_date=today - timedelta(days=2))
        first = Journal.objects.create(claim=self.claim, line=self.line, user=self.admin, comment='Latest first')
        second = Journal.objects.create(claim=self.claim, line=self.line, user=self.admin, comment='Latest second <unsafe>')
        Journal.objects.filter(pk__in=[first.pk, second.pk]).update(created_date=today - timedelta(days=1))
        Journal.objects.create(claim=self.claim, line=self.line, user=self.user, comment='Exclude dealer comment today')
        report = ReportService.generate_ra_report(self.dealer.pk, 'Requires Attention')
        text = report['ra_claims'][0]['lines'][0]['comments']
        self.assertIn('Latest first', text)
        self.assertIn('Latest second', text)
        self.assertNotIn('Old admin', text)
        self.assertNotIn('dealer comment', text)
        from django.template.loader import render_to_string
        for template in ('reports/rareport_pdf.html', 'reports/ra_reportsview.html'):
            html = render_to_string(template, {**report, 'dealership': self.dealer, 'dealership_id': self.dealer.pk})
            self.assertNotIn('<unsafe>', html)

    def test_daily_comments_use_group_membership_and_requested_date(self):
        from django.utils import timezone
        from claim.models import Journal
        from .views import ReportService
        Journal.objects.create(claim=self.claim, line=self.line, user=self.admin, comment='Dynamic admin comment')
        Journal.objects.create(claim=self.claim, line=self.line, user=self.user, comment='Dealer comment')
        data = ReportService.get_line_data(self.claim.pk, timezone.localdate())
        self.assertEqual(data[0]['comments'], ['Dynamic admin comment'])

    def test_no_admin_comments_produces_placeholder(self):
        from .views import ReportService
        self.assertEqual(ReportService.generate_ra_report(self.dealer.pk, 'Requires Attention')['ra_claims'][0]['lines'][0]['comments'], 'No Comment')

    def test_archive_page_uses_post_export_even_without_existing_pdf(self):
        from django.template.loader import render_to_string
        html = render_to_string('reports/archivedailyreportsview.html', {
            'dealership': self.dealer, 'report_type': 'Archived Report', 'start_date': '2026-10-09', 'pdf_exists': False})
        self.assertIn('method="post"', html)
        self.assertNotIn('report_export/?', html)

    def test_ready_download_is_attachment_for_every_report_type(self):
        from datetime import date
        from django.utils import timezone
        from .jobs import enqueue_report, report_path
        with tempfile.TemporaryDirectory() as directory, override_settings(REPORT_ROOT=Path(directory)):
            for name in ('Daily Report', 'Archived Report', 'Discrepancy Report', 'RA Report'):
                job = enqueue_report(self.user, self.dealer, name, date(2026, 10, 9))
                job.state, job.finished_at = 'completed', timezone.now()
                job.save()
                path = report_path(job)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'%PDF-1.4\n')
                response = self.client.get(reverse('reports:report-job-download', args=[job.pk]))
                self.assertTrue(response['Content-Disposition'].startswith('attachment;'))
                self.assertIn(f'task-reports-{name.lower().replace(" ", "-")}-2026-10-09.pdf', response['Content-Disposition'])
                self.assertEqual(b''.join(response.streaming_content), b'%PDF-1.4\n')
                self.assertFalse(path.exists())
                self.assertEqual(self.client.get(reverse('reports:report-job', args=[job.pk])).status_code, 404)
