from datetime import date
from decimal import Decimal
from pathlib import Path
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import Dealership
from .forms import PdfFileForm
from .models import Claim, ClaimType, Journal, LineTable, PdfFile, RoStatus, Status


class SecurityBaselineTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.own = Dealership.objects.create(name='Assigned')
        cls.other = Dealership.objects.create(name='Other')
        cls.open = RoStatus.objects.create(name='Open')
        cls.closed = RoStatus.objects.create(name='Closed')
        cls.status = Status.objects.create(name='Requires Attention')
        cls.rework = Status.objects.create(name='Rework')
        cls.paid = Status.objects.create(name='Paid')
        cls.claim_type = ClaimType.objects.create(name='Warranty')
        cls.claim = Claim.objects.create(dealership=cls.own, repair_order=123, ro_status=cls.open)
        cls.foreign = Claim.objects.create(dealership=cls.other, repair_order=123, ro_status=cls.open)
        cls.line = LineTable.objects.create(claim=cls.claim, dealership=cls.own, claim_type=cls.claim_type, claim_status=cls.status, claim_total=Decimal('123.45'), compliant=True)
        cls.foreign_line = LineTable.objects.create(claim=cls.foreign, dealership=cls.other, claim_status=cls.status)
        cls.dealer = get_user_model().objects.create_user(email='dealer@example.invalid', password='test-password')
        cls.dealer.groups.add(Group.objects.create(name='dealer-admin'))
        cls.dealer.dealership.add(cls.own)
        cls.viewer = get_user_model().objects.create_user(email='viewer@example.invalid', password='test-password')
        cls.viewer.dealership.add(cls.own)
        cls.admin = get_user_model().objects.create_superuser(email='admin@example.invalid', password='test-password')

    def setUp(self):
        self.client.force_login(self.dealer)

    def test_mutations_require_login(self):
        self.client.logout()
        for name in ('upload-pdf', 'global-comment', 'line-updates', 'add-line', 'ro-status', 'start-date'):
            args = [self.line.pk] if name == 'start-date' else []
            with self.subTest(name=name):
                response = self.client.post(reverse('claim:' + name, args=args), {'claim_id': self.claim.pk, 'line_id': self.line.pk})
                self.assertEqual(response.status_code, 302)
                self.assertIn('/accounts/login/', response.url)
        self.assertFalse(Journal.objects.exists())

    def test_dealer_cannot_access_foreign_claim_view_or_queue(self):
        urls = [
            reverse('claim:dealer-claim-update', args=[self.foreign.pk, self.other.pk]),
            reverse('claim:claim-form', args=[self.other.pk]),
            reverse('claim:claim-queue', args=['Requires Attention']) + f'?dealership_id={self.other.pk}',
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_claim_and_dealership_identifiers_must_match(self):
        self.assertEqual(self.client.get(reverse('claim:dealer-claim-update', args=[self.foreign.pk, self.own.pk])).status_code, 404)

    def test_dealer_direct_form_post_cannot_modify_claim(self):
        response = self.client.post(reverse('claim:dealer-claim-update', args=[self.claim.pk, self.own.pk]), {'repair_order': 999})
        self.assertEqual(response.status_code, 405)
        self.claim.refresh_from_db()
        self.assertEqual(self.claim.repair_order, 123)

    def test_foreign_mutations_do_not_write(self):
        for name, data in (
            ('global-comment', {'claim_id': self.foreign.pk, 'comment': 'unauthorized'}),
            ('ro-status', {'claim_id': self.foreign.pk, 'ro_status': self.closed.pk}),
            ('line-updates', {'line_id': self.foreign_line.pk, 'claim_status': self.rework.pk}),
        ):
            with self.subTest(name=name):
                self.assertEqual(self.client.post(reverse('claim:' + name), data).status_code, 404)
        self.foreign.refresh_from_db()
        self.assertEqual(self.foreign.ro_status_id, self.open.pk)
        self.assertFalse(Journal.objects.exists())

    def test_dealer_can_comment_and_change_permitted_status_without_changing_compliance(self):
        response = self.client.post(reverse('claim:line-updates'), {'line_id': self.line.pk, 'claim_status': self.rework.pk, 'comment': 'Reviewed'}, HTTP_REFERER='https://attacker.invalid/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/dashboard/')
        self.line.refresh_from_db()
        self.assertEqual(self.line.claim_status_id, self.rework.pk)
        self.assertTrue(self.line.compliant)
        self.assertEqual(Journal.objects.get().comment, 'Reviewed')

    def test_dealer_cannot_change_financial_fields_or_mark_line_paid(self):
        for fields in ({'claim_total': '1.00'}, {'claim_status': self.paid.pk}, {'line_num': '99'}, {'claim_type': '999'}):
            with self.subTest(fields=fields):
                response = self.client.post(reverse('claim:line-updates'), {'line_id': self.line.pk, 'claim_status': self.rework.pk, **fields})
                self.assertEqual(response.status_code, 403)
        self.line.refresh_from_db()
        self.assertEqual(self.line.claim_total, Decimal('123.45'))
        self.assertEqual(self.line.claim_status_id, self.status.pk)

    def test_mutation_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.dealer)
        self.assertEqual(client.post(reverse('claim:global-comment'), {'claim_id': self.claim.pk, 'comment': 'no token'}).status_code, 403)

    def test_invalid_identifiers_fail_without_server_error(self):
        self.assertEqual(self.client.post(reverse('claim:global-comment'), {'claim_id': 'invalid', 'comment': 'x'}).status_code, 404)

    def test_claim_delete_is_post_only(self):
        self.client.force_login(self.admin)
        url = reverse('claim:delete-claim', args=[self.own.name, self.claim.repair_order])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertTrue(Claim.objects.filter(pk=self.claim.pk).exists())
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertFalse(Claim.objects.filter(pk=self.claim.pk).exists())

    def test_global_search_is_scoped(self):
        response = self.client.get(reverse('claim:global-search'), {'q': '123'})
        self.assertEqual(list(response.context['claims']), [self.claim])

    def test_viewer_cannot_mutate_or_read_audit_log(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.post(reverse('claim:ro-status'), {'claim_id': self.claim.pk, 'ro_status': self.closed.pk}).status_code, 403)
        self.assertEqual(self.client.get(reverse('auditlog:event_list')).status_code, 403)

    def test_pdf_signature_and_size_are_validated(self):
        for filename, content in [('bad.pdf', b'<script>unsafe</script>'), ('bad.html', b'%PDF-1.4'), ('large.pdf', b'%PDF-' + b'x' * (10 * 1024 * 1024))]:
            with self.subTest(filename=filename):
                form = PdfFileForm(files={'pdf_file': SimpleUploadedFile(filename, content)})
                self.assertFalse(form.is_valid())
        form = PdfFileForm(files={'pdf_file': SimpleUploadedFile('valid.pdf', b'%PDF-1.4\n')})
        self.assertTrue(form.is_valid())

    def test_pdf_download_is_authorized_and_blocks_path_escape(self):
        with tempfile.TemporaryDirectory() as directory, override_settings(BASE_DIR=Path(directory)):
            upload = Path(directory) / 'static' / 'upload'
            upload.mkdir(parents=True)
            (upload / 'claim.pdf').write_bytes(b'%PDF-1.4\n')
            pdf = PdfFile.objects.create(claim=self.claim, pdf_file='static/upload/claim.pdf', pdf_name='claim')
            response = self.client.get(reverse('claim:download-pdf', args=[pdf.pk]))
            self.assertEqual(response.status_code, 200)
            response.close()
            pdf.claim = self.foreign
            pdf.save()
            self.assertEqual(self.client.get(reverse('claim:download-pdf', args=[pdf.pk])).status_code, 404)
            pdf.claim = self.claim
            pdf.pdf_file = '../outside.pdf'
            pdf.save()
            self.assertEqual(self.client.get(reverse('claim:download-pdf', args=[pdf.pk])).status_code, 404)

    def test_batch_status_update_is_atomic_and_scoped(self):
        url = reverse('reports:ro-status')
        response = self.client.post(url, {'claim_ids': [self.claim.pk, self.foreign.pk], 'ro_status': 'Closed'}, content_type='application/json')
        self.assertEqual(response.status_code, 404)
        self.claim.refresh_from_db()
        self.assertEqual(self.claim.ro_status_id, self.open.pk)
        response = self.client.post(url, {'claim_ids': [self.claim.pk], 'ro_status': 'Closed'}, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.claim.refresh_from_db()
        self.assertEqual(self.claim.ro_status_id, self.closed.pk)

    def test_invalid_batch_body_is_not_an_internal_error(self):
        for data in ([], {'claim_ids': '1'}, {'claim_ids': [True], 'ro_status': 'Closed'}, {'claim_ids': [1] * 201, 'ro_status': 'Closed'}):
            with self.subTest(data=data):
                self.assertEqual(self.client.post(reverse('reports:ro-status'), data, content_type='application/json').status_code, 400)

    def test_report_export_is_scoped_and_validates_type_and_dates(self):
        url = reverse('reports:report-export')
        self.assertEqual(self.client.get(url, {'dealership': self.other.name, 'report_type': 'RA Report'}).status_code, 404)
        self.assertEqual(self.client.get(url, {'dealership': self.own.name, 'report_type': 'unknown'}).status_code, 400)
        self.assertEqual(self.client.get(url, {'dealership': self.own.name, 'report_type': 'Daily Report', 'start_date': 'invalid'}).status_code, 400)

    def test_pdf_upload_cannot_target_foreign_claim(self):
        response = self.client.post(reverse('claim:upload-pdf'), {'claim_id': self.foreign.pk, 'pdf_file': SimpleUploadedFile('file.pdf', b'%PDF-1.4\n')})
        self.assertEqual(response.status_code, 404)
        self.assertFalse(PdfFile.objects.exists())
