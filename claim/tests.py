from core.dates import as_date, as_datetime
from datetime import date
from decimal import Decimal
from pathlib import Path
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import Dealership
from .forms import PdfFileForm
from .models import Claim, ClaimType, Journal, LineTable, PdfFile, RoStatus, Status, Tag


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

    def test_claim_delete_get_only_confirms(self):
        self.client.force_login(self.admin)
        url = reverse('claim:delete-claim', args=[self.own.name, self.claim.repair_order])
        self.assertContains(self.client.get(url), 'Are you sure')
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
            list(response.streaming_content)
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

    def test_assigned_dealer_claim_page_remains_accessible(self):
        response = self.client.get(reverse('claim:dealer-claim-update', args=[self.claim.pk, self.own.pk]))
        self.assertEqual(response.status_code, 200)
        form = response.context['form']
        for name in ('service_writer', 'technician'):
            self.assertEqual(set(form.fields[name].queryset.values_list('pk', flat=True)), {self.dealer.pk, self.viewer.pk})

    def test_admin_rejects_nonfinite_or_out_of_range_claim_totals(self):
        self.client.force_login(self.admin)
        for amount in ('NaN', 'Infinity', '100000000', '1.001'):
            with self.subTest(amount=amount):
                response = self.client.post(reverse('claim:line-updates'), {'line_id': self.line.pk, 'claim_status': self.status.pk, 'claim_total': amount})
                self.assertEqual(response.status_code, 400)
        self.line.refresh_from_db()
        self.assertEqual(self.line.claim_total, Decimal('123.45'))

    def test_valid_pdf_upload_and_authenticated_download(self):
        with tempfile.TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory, BASE_DIR=Path(directory)):
            response = self.client.post(reverse('claim:upload-pdf'), {'claim_id': self.claim.pk, 'pdf_file': SimpleUploadedFile('claim.pdf', b'%PDF-1.4\n')})
            self.assertEqual(response.status_code, 302)
            pdf = PdfFile.objects.get()
            response = self.client.get(reverse('claim:download-pdf', args=[pdf.pk]))
            self.assertEqual(response.status_code, 200)
            list(response.streaming_content)
            self.client.logout()
            self.assertEqual(self.client.get(reverse('claim:download-pdf', args=[pdf.pk])).status_code, 302)

    def test_new_claim_resolves_named_statuses_without_assuming_ids(self):
        new = Status.objects.create(name='New')
        tag = Tag.objects.create(name='Warranty')
        response = self.client.post(reverse('claim:claim-form', args=[self.own.pk]), {
            'dealership': self.own.pk, 'repair_order': '777',
            'claim_tag': [tag.pk], 'comment': 'Initial comment',
        })
        self.assertEqual(response.status_code, 302)
        claim = Claim.objects.get(dealership=self.own, repair_order=777)
        self.assertEqual(claim.ro_status, self.open)
        self.assertEqual(claim.linetable_set.get().claim_status, new)

    def test_failed_claim_creation_rolls_back_all_records(self):
        tag = Tag.objects.create(name='Missing Claim Type')
        before = Claim.objects.count()
        response = self.client.post(reverse('claim:claim-form', args=[self.own.pk]), {
            'dealership': self.own.pk, 'repair_order': '777',
            'claim_tag': [tag.pk], 'comment': 'Initial comment',
        })
        self.assertEqual(response.status_code, 404)
        self.assertEqual(Claim.objects.count(), before)
        self.assertFalse(Journal.objects.exists())


class QueuePaginationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dealer = Dealership.objects.create(name='Queue Dealer')
        cls.foreign = Dealership.objects.create(name='Foreign')
        cls.user = get_user_model().objects.create_user(email='queue@example.invalid')
        cls.user.groups.add(Group.objects.create(name='dealer-admin'))
        cls.user.dealership.add(cls.dealer)
        cls.open = RoStatus.objects.create(name='Open')
        cls.bodyshop = Tag.objects.create(name='Bodyshop')
        cls.statuses = {name: Status.objects.create(name=name) for name in ('New', 'Pending', 'Rework', 'Requires Attention')}
        for number in range(51):
            claim = Claim.objects.create(dealership=cls.dealer, repair_order=1000 + number, ro_status=cls.open)
            if number % 2 == 0:
                claim.claim_tag.add(cls.bodyshop)
            for status in cls.statuses.values():
                for line_num in ('1', '2'):
                    LineTable.objects.create(claim=claim, dealership=cls.dealer, claim_status=status,
                        start_date=as_datetime(date(2020, 1, 1)), line_num=line_num, claim_total='12.50')
        unrelated = Claim.objects.create(dealership=cls.foreign, repair_order=9999)
        LineTable.objects.create(claim=unrelated, dealership=cls.foreign, claim_status=cls.statuses['Pending'])

    def setUp(self):
        self.client.force_login(self.user)

    def test_every_queue_paginates_distinct_claims_and_preserves_scope(self):
        for route, status in (('claim-queue', 'Rework'), ('new-claim-queue', 'New'),
            ('pending-claim-queue', 'Pending'), ('rework-claim-queue', 'Rework'),
            ('ra-claim-queue', 'Requires Attention'), ('ra-claim-queue', 'Aging')):
            with self.subTest(route=route, status=status):
                url = reverse('claim:' + route, args=[status])
                response = self.client.get(url, {'dealership_id': self.dealer.pk})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context['paginator'].count, 51)
                self.assertNotContains(response, 'Page navigation example')
                claims = list(response.context['object_list'])
                self.assertEqual(len(claims), 50)
                self.assertEqual(len({claim.pk for claim in claims}), 50)
                self.assertContains(response, f'dealership_id={self.dealer.pk}&amp;page=2')
                second = self.client.get(url, {'dealership_id': self.dealer.pk, 'page': 2})
                self.assertEqual(len(second.context['object_list']), 1)
                self.assertFalse({c.pk for c in second.context['object_list']} & {c.pk for c in claims})
                self.assertEqual(self.client.get(url, {'dealership_id': self.foreign.pk}).status_code, 404)

    def test_rendered_queue_has_no_per_row_role_queries(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        url = reverse('claim:pending-claim-queue', args=['Pending'])
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(url, {'dealership_id': self.dealer.pk})
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(queries), 14)
        with CaptureQueriesContext(connection) as second_page_queries:
            self.client.get(url, {'dealership_id': self.dealer.pk, 'page': 2})
        self.assertEqual(len(queries), len(second_page_queries))
        self.assertContains(response, reverse('claim:dealer-claim-update', args=[
            Claim.objects.filter(dealership=self.dealer).order_by('-repair_order').first().pk, self.dealer.pk]))

    def test_bodyshop_and_regular_lines_render_ages_and_amounts(self):
        for route in ('pending-claim-queue', 'rework-claim-queue'):
            status = 'Pending' if route.startswith('pending') else 'Rework'
            response = self.client.get(reverse('claim:' + route, args=[status]), {'dealership_id': self.dealer.pk})
            self.assertContains(response, '$12.50', count=100)
            self.assertContains(response, '2020-01-01 00:00:00 EST', count=100)

    def test_queue_data_queries_are_bounded_and_foreign_lines_are_excluded(self):
        from .views import PendingClaimQueueListView
        from django.test import RequestFactory
        claim = Claim.objects.filter(dealership=self.dealer).order_by('-repair_order').first()
        LineTable.objects.create(claim=claim, dealership=self.foreign, claim_status=self.statuses['Pending'])
        request = RequestFactory().get('/', {'dealership_id': self.dealer.pk})
        request.user = self.user
        view = PendingClaimQueueListView()
        view.setup(request, filter_request='Pending')
        view.authorized_dealership = self.dealer
        with self.assertNumQueries(3):
            claims = list(view.get_queryset()[:50])
            for claim in claims:
                self.assertTrue(all(line.dealership_id == self.dealer.pk for line in claim.linetable_set.all()))
                _ = claim.ro_status.name
                list(claim.claim_tag.all())


class BodyshopQueueContextTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from datetime import timedelta
        cls.dealer = Dealership.objects.create(name='Bodyshop Context')
        cls.foreign = Dealership.objects.create(name='Foreign Context')
        cls.user = get_user_model().objects.create_user(email='bodyshop-context@example.invalid')
        cls.user.groups.add(Group.objects.create(name='dealer-admin'))
        cls.user.dealership.add(cls.dealer)
        cls.admin = get_user_model().objects.create_superuser(email='bodyshop-admin@example.invalid')
        cls.open = RoStatus.objects.create(name='Open')
        cls.bodyshop = Tag.objects.create(name='Bodyshop')
        cls.warranty = Tag.objects.create(name='Warranty')
        cls.claims = []
        cls.statuses = {name: Status.objects.create(name=name) for name in ('New', 'Pending', 'Rework', 'Requires Attention', 'Paid')}
        for number, bodyshop in ((70001, True), (70002, False)):
            claim = Claim.objects.create(dealership=cls.dealer, repair_order=number, ro_status=cls.open)
            claim.claim_tag.add(cls.warranty)
            if bodyshop:
                claim.claim_tag.add(cls.bodyshop)
            cls.claims.append(claim)
            Journal.objects.create(claim=claim, user=cls.user, comment=f'Initial comment for {number}')
            for index, (name, status) in enumerate(cls.statuses.items(), 1):
                LineTable.objects.create(claim=claim, dealership=cls.dealer, claim_status=status,
                    line_num=f'{index}', claim_total='23.45', start_date=as_datetime(date.today() - timedelta(days=100)))
            LineTable.objects.create(claim=claim, dealership=cls.dealer, claim_status=cls.statuses['Requires Attention'],
                line_num='recent-attention', start_date=as_datetime(date.today() - timedelta(days=10)), claim_total='42.10')
            LineTable.objects.create(claim=claim, dealership=cls.dealer, claim_status=cls.statuses['Requires Attention'],
                line_num='undated-attention', start_date=None, claim_total='52.10')
            LineTable.objects.create(claim=claim, dealership=cls.foreign, claim_status=cls.statuses['Pending'],
                line_num='foreign-line', claim_total='999')
        foreign_claim = Claim.objects.create(dealership=cls.foreign, repair_order=79999, ro_status=cls.open)
        foreign_claim.claim_tag.add(cls.bodyshop)
        LineTable.objects.create(claim=foreign_claim, dealership=cls.foreign, claim_status=cls.statuses['Pending'])

    def test_each_bodyshop_and_regular_table_matches_its_context(self):
        from .test_helpers import QueueTableParser
        queues = (
            ('claim-queue', 'Rework', 'other_claims', False),
            ('new-claim-queue', 'New', 'new_claims', False),
            ('pending-claim-queue', 'Pending', 'pending_claims', True),
            ('rework-claim-queue', 'Rework', 'rework_claims', True),
            ('ra-claim-queue', 'Requires Attention', 'ra_claims', True),
            ('ra-claim-queue', 'Aging', 'ra_claims', True),
        )
        for user in (self.user, self.admin):
            self.client.force_login(user)
            for route, status, section, has_lines in queues:
                with self.subTest(user=user.pk, queue=status, route=route):
                    response = self.client.get(reverse('claim:' + route, args=[status]), {'dealership_id': self.dealer.pk})
                    self.assertEqual(response.status_code, 200)
                    tables = QueueTableParser(response.content.decode()).tables
                    self.assertEqual(set(tables), {'bodyshopTable', 'claimsTable'})
                    self.assertEqual(response.content.decode().count('js/table-sort.js'), 1)
                    for table, context_key, expected_claim in (
                        ('bodyshopTable', 'bodyshop_claims', self.claims[0]),
                        ('claimsTable', section, self.claims[1]),
                    ):
                        context = response.context[context_key]
                        self.assertEqual(len(context), 1)
                        claim = context[0]['claim'] if has_lines else context[0]
                        self.assertEqual(claim.pk, expected_claim.pk)
                        rows = tables[table]
                        count = 3 if status == 'Requires Attention' else 1
                        self.assertEqual(len(rows), count)
                        update_route = 'claim-update' if user.is_superuser else 'dealer-claim-update'
                        link = reverse('claim:' + update_route, args=[claim.pk, self.dealer.pk])
                        for row in rows:
                            self.assertEqual(row['cells'][0], str(claim.repair_order))
                            self.assertEqual(row['links'], [link])
                        if has_lines:
                            entries = context[0]['lines']
                            self.assertEqual({row['cells'][1] for row in rows}, {entry['line'].line_num for entry in entries})
                            expected_status = 'Requires Attention' if status == 'Aging' else status
                            for entry, row in zip(entries, rows):
                                self.assertEqual(entry['line'].claim_status.name, expected_status)
                                self.assertEqual(entry['line'].dealership_id, self.dealer.pk)
                                self.assertEqual(row['cells'][4], str(entry['claim_age']) if entry['claim_age'] is not None else 'None')
                            if status == 'Aging':
                                self.assertEqual(entries[0]['line'].line_num, '4')
                        elif route == 'new-claim-queue':
                            self.assertIn(f'Initial comment for {claim.repair_order}', rows[0]['cells'][-1])

    def test_bodyshop_section_is_hidden_when_no_matching_bodyshop_claims_exist(self):
        self.client.force_login(self.user)
        self.claims[0].claim_tag.clear()
        from .test_helpers import QueueTableParser
        for route, status in (('claim-queue', 'Rework'), ('new-claim-queue', 'New'),
            ('pending-claim-queue', 'Pending'), ('rework-claim-queue', 'Rework'),
            ('ra-claim-queue', 'Requires Attention'), ('ra-claim-queue', 'Aging')):
            with self.subTest(route=route, status=status):
                response = self.client.get(reverse('claim:' + route, args=[status]), {'dealership_id': self.dealer.pk})
                self.assertFalse(response.context['bodyshop'])
                self.assertEqual(response.context['bodyshop_claims'], [])
                self.assertNotIn('bodyshopTable', QueueTableParser(response.content.decode()).tables)


class ImageAttachmentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dealer = Dealership.objects.create(name='Image Dealer')
        cls.foreign = Dealership.objects.create(name='Other Images')
        cls.user = get_user_model().objects.create_user(email='images@example.invalid')
        cls.user.groups.add(Group.objects.create(name='dealer-admin'))
        cls.user.dealership.add(cls.dealer)
        cls.claim = Claim.objects.create(dealership=cls.dealer, repair_order=8000)
        cls.foreign_claim = Claim.objects.create(dealership=cls.foreign, repair_order=8000)
        cls.open = RoStatus.objects.create(name='Open')
        cls.new = Status.objects.create(name='New')
        cls.tag = Tag.objects.create(name='Warranty')
        ClaimType.objects.create(name='Warranty')

    def setUp(self):
        self.client.force_login(self.user)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.override = override_settings(BASE_DIR=Path(self.directory.name), MEDIA_ROOT=self.directory.name)
        self.override.enable()
        self.addCleanup(self.override.disable)

    @staticmethod
    def image_bytes(format, animated=False):
        from io import BytesIO
        from PIL import Image
        buffer = BytesIO()
        image = Image.new('RGB', (2, 2), 'blue')
        options = {'save_all': True, 'append_images': [Image.new('RGB', (2, 2), 'red')]} if animated else {}
        image.save(buffer, format=format, **options)
        return buffer.getvalue()

    def test_each_image_format_uploads_and_downloads_with_correct_mime(self):
        for extension, format, mime in (('png', 'PNG', 'image/png'), ('jpg', 'JPEG', 'image/jpeg'),
            ('jpeg', 'JPEG', 'image/jpeg'), ('GIF', 'GIF', 'image/gif')):
            with self.subTest(extension=extension):
                content = self.image_bytes(format, animated=format == 'GIF')
                response = self.client.post(reverse('claim:upload-pdf'), {'claim_id': self.claim.pk,
                    'pdf_file': SimpleUploadedFile(f'claim.{extension}', content, content_type='application/octet-stream')})
                self.assertEqual(response.status_code, 302)
                file = PdfFile.objects.order_by('-pk').first()
                response = self.client.get(reverse('claim:download-pdf', args=[file.pk]))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response['Content-Type'], mime)
                self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
                self.assertIn('attachment;', response['Content-Disposition'])
                self.assertEqual(b''.join(response.streaming_content), content)

    def test_image_validation_rejects_spoofing_corruption_and_unsupported_formats(self):
        for name, content in (
            ('script.png', b'<script>alert(1)</script>'), ('renamed.jpg', self.image_bytes('PNG')),
            ('truncated.png', self.image_bytes('PNG')[:25]), ('image.svg', b'<svg></svg>'),
            ('photo.webp', self.image_bytes('PNG')), ('renamed.pdf', self.image_bytes('JPEG')),
        ):
            with self.subTest(name=name):
                response = self.client.post(reverse('claim:upload-pdf'), {'claim_id': self.claim.pk,
                    'pdf_file': SimpleUploadedFile(name, content)})
                self.assertEqual(response.status_code, 400)
        self.assertFalse(PdfFile.objects.exists())

    def test_images_retain_dealership_and_csrf_protection(self):
        url = reverse('claim:upload-pdf')
        response = self.client.post(url, {'claim_id': self.foreign_claim.pk,
            'pdf_file': SimpleUploadedFile('foreign.png', self.image_bytes('PNG'))})
        self.assertEqual(response.status_code, 404)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(url, {'claim_id': self.claim.pk,
            'pdf_file': SimpleUploadedFile('csrf.png', self.image_bytes('PNG'))}).status_code, 403)
        self.assertFalse(PdfFile.objects.exists())
        self.client.post(url, {'claim_id': self.claim.pk,
            'pdf_file': SimpleUploadedFile('own.png', self.image_bytes('PNG'))})
        file = PdfFile.objects.get()
        file.claim = self.foreign_claim
        file.save()
        self.assertEqual(self.client.get(reverse('claim:download-pdf', args=[file.pk])).status_code, 404)

    def test_claim_creation_accepts_image_attachment(self):
        response = self.client.post(reverse('claim:claim-form', args=[self.dealer.pk]), {
            'dealership': self.dealer.pk, 'repair_order': 8001, 'claim_tag': [self.tag.pk],
            'comment': 'Image evidence', 'pdf_file': SimpleUploadedFile('evidence.jpeg', self.image_bytes('JPEG')),
        })
        self.assertEqual(response.status_code, 302)
        file = PdfFile.objects.get()
        self.assertEqual(file.claim.repair_order, 8001)
        self.assertTrue(file.pdf_file.name.endswith('.jpeg'))

    def test_all_attachment_forms_accept_images_and_preserve_file_position(self):
        from .forms import ClaimLineUpdateForm, LinePdfFileForm
        from .validators import validate_claim_file
        upload = SimpleUploadedFile('image.png', self.image_bytes('PNG'))
        upload.seek(4)
        validate_claim_file(upload)
        self.assertEqual(upload.tell(), 4)
        for form in (PdfFileForm, ClaimLineUpdateForm, LinePdfFileForm):
            field = form.base_fields['pdf_file']
            field.clean(SimpleUploadedFile('image.gif', self.image_bytes('GIF')))
            with self.assertRaises(ValidationError):
                field.clean(SimpleUploadedFile('bad.png', b'not an image'))

    def test_attachment_size_and_pixel_limits_are_enforced(self):
        from .validators import validate_claim_file
        with self.assertRaises(ValidationError):
            validate_claim_file(SimpleUploadedFile('large.png', b'x' * (10 * 1024 * 1024 + 1)))
        with patch('claim.validators.MAX_IMAGE_PIXELS', 1), self.assertRaises(ValidationError):
            validate_claim_file(SimpleUploadedFile('large-pixels.png', self.image_bytes('PNG')))

    def test_upload_controls_list_all_supported_formats(self):
        for route, args in (('claim-form', [self.dealer.pk]), ('dealer-claim-update', [self.claim.pk, self.dealer.pk])):
            response = self.client.get(reverse('claim:' + route, args=args))
            self.assertContains(response, 'accept=".pdf,.png,.jpeg,.jpg,.gif"')
        admin = get_user_model().objects.create_superuser(email='imageadmin@example.invalid')
        self.client.force_login(admin)
        self.assertContains(self.client.get(reverse('claim:claim-update', args=[self.claim.pk, self.dealer.pk])),
            'accept=".pdf,.png,.jpeg,.jpg,.gif"')


class CompletionDateRequirementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dealer = Dealership.objects.create(name='Completion Dates')
        cls.admin = get_user_model().objects.create_superuser(email='completion@example.invalid')
        cls.statuses = {name: Status.objects.create(name=name) for name in ('New', 'Pending', 'Requires Attention', 'Rework', 'No Warranty', 'Not Submitted', 'Rejected')}
        cls.type = ClaimType.objects.create(name='Warranty')
        cls.other_type = ClaimType.objects.create(name='Repair')
        cls.claim = Claim.objects.create(dealership=cls.dealer, repair_order=9001,
            ro_status=RoStatus.objects.create(name='Open'))
        cls.line = LineTable.objects.create(claim=cls.claim, dealership=cls.dealer,
            line_num='1', claim_type=cls.type, claim_status=cls.statuses['New'], claim_total='10.00')
        cls.second = LineTable.objects.create(claim=cls.claim, dealership=cls.dealer,
            line_num='2', claim_type=cls.type, claim_status=cls.statuses['New'], claim_total='20.00')

    def setUp(self):
        self.client.force_login(self.admin)
        self.url = reverse('claim:line-updates')
        self.edit_url = reverse('claim:claim-update', args=[self.claim.pk, self.dealer.pk])

    def payload(self, status):
        return {'line_id': self.line.pk, 'line_num': 'edited-line', 'claim_type': self.other_type.pk,
            'claim_status': self.statuses[status].pk, 'claim_total': '123.45', 'start_date': '',
            'comment': 'User entered comment <evidence>', 'compliant': 'on'}

    @staticmethod
    def fields(response, line_id):
        import html5lib
        root = html5lib.parse(response.content.decode(), namespaceHTMLElements=False)
        form = next(node for node in root.iter('form') if node.get('id') == f'line_form_{line_id}')
        return {node.get('name'): node for node in form.iter() if node.get('name')}

    def test_required_statuses_reject_missing_date_without_saving_and_preserve_fields(self):
        for status in ('Pending', 'Requires Attention'):
            with self.subTest(status=status):
                payload = self.payload(status)
                response = self.client.post(self.url, payload)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.url, self.edit_url + f'#line_form_{self.line.pk}')
                self.line.refresh_from_db()
                self.assertEqual(self.line.claim_status.name, 'New')
                self.assertEqual(self.line.claim_total, Decimal('10.00'))
                self.assertFalse(Journal.objects.exists())
                response = self.client.get(response.url)
                self.assertContains(response, 'Completion Date is required')
                fields = self.fields(response, self.line.pk)
                self.assertEqual(fields['line_num'].get('value'), 'edited-line')
                self.assertEqual(fields['claim_total'].get('value'), '123.45')
                self.assertEqual(fields['comment'].text.strip(), payload['comment'])
                self.assertIn('checked', fields['compliant'].attrib)
                for field in ('claim_type', 'claim_status'):
                    selected = next(option for option in fields[field] if 'selected' in option.attrib)
                    self.assertEqual(selected.get('value'), str(payload[field]))
                self.assertNotIn('line_edit_draft', self.client.session)
                other = self.fields(response, self.second.pk)
                self.assertEqual(other['claim_total'].get('value'), '20.00')
                self.assertEqual((other['comment'].text or '').strip(), '')

    def test_user_can_add_date_and_resubmit_preserved_values(self):
        for status in ('Pending', 'Requires Attention'):
            with self.subTest(status=status):
                payload = self.payload(status)
                response = self.client.post(self.url, payload)
                self.client.get(response.url)
                payload['start_date'] = 'October 08, 2026'
                response = self.client.post(self.url, payload)
                self.assertEqual(response.status_code, 302)
                self.line.refresh_from_db()
                self.assertEqual(as_date(self.line.start_date), date(2026, 10, 8))
                self.assertEqual(self.line.claim_status.name, status)
                self.assertEqual(self.line.claim_total, Decimal('123.45'))
                self.assertTrue(self.line.compliant)
                self.assertEqual(Journal.objects.filter(line=self.line).count(), 1 if status == 'Pending' else 2)

    def test_explicit_date_clear_is_rejected_but_omitted_date_is_retained(self):
        LineTable.objects.filter(pk=self.line.pk).update(claim_status=self.statuses['Pending'], start_date=as_datetime(date(2026, 10, 8)))
        response = self.client.post(self.url, {'line_id': self.line.pk, 'claim_status': self.statuses['Pending'].pk, 'start_date': ''})
        self.assertEqual(response.url, self.edit_url + f'#line_form_{self.line.pk}')
        self.line.refresh_from_db()
        self.assertEqual(as_date(self.line.start_date), date(2026, 10, 8))
        response = self.client.post(self.url, {'line_id': self.line.pk, 'claim_status': self.statuses['Pending'].pk, 'comment': 'Keep existing date'})
        self.line.refresh_from_db()
        self.assertEqual(as_date(self.line.start_date), date(2026, 10, 8))
        self.assertEqual(Journal.objects.filter(line=self.line).count(), 1)

    def test_optional_status_can_save_without_date(self):
        payload = self.payload('Rework')
        response = self.client.post(self.url, payload)
        self.assertEqual(response.status_code, 302)
        self.line.refresh_from_db()
        self.assertEqual(self.line.claim_status.name, 'Rework')
        self.assertIsNone(self.line.start_date)

    def test_invalid_date_and_missing_comment_preserve_values(self):
        payload = self.payload('Pending')
        payload['start_date'] = 'not-a-date'
        response = self.client.post(self.url, payload)
        response = self.client.get(response.url)
        self.assertEqual(self.fields(response, self.line.pk)['start_date'].get('value'), 'not-a-date')
        payload = self.payload('Requires Attention')
        payload['start_date'] = 'October 08, 2026'
        payload['comment'] = ''
        response = self.client.post(self.url, payload)
        response = self.client.get(response.url)
        self.assertContains(response, 'A comment is required')
        self.assertEqual(self.fields(response, self.line.pk)['start_date'].get('value'), 'October 08, 2026')
        self.assertFalse(Journal.objects.exists())

    def test_completion_date_endpoint_cannot_clear_required_dates(self):
        LineTable.objects.filter(pk=self.line.pk).update(claim_status=self.statuses['Requires Attention'], start_date=as_datetime(date(2026, 10, 8)))
        response = self.client.post(reverse('claim:start-date', args=[self.line.pk]), {'start_date': ''})
        self.assertEqual(response.status_code, 400)
        self.line.refresh_from_db()
        self.assertEqual(as_date(self.line.start_date), date(2026, 10, 8))

    def test_dealer_cannot_gain_permission_to_edit_completion_date(self):
        dealer = get_user_model().objects.create_user(email='completion-dealer@example.invalid')
        dealer.groups.add(Group.objects.create(name='dealer-admin'))
        dealer.dealership.add(self.dealer)
        self.client.force_login(dealer)
        response = self.client.post(self.url, {'line_id': self.line.pk, 'start_date': 'October 08, 2026'})
        self.assertEqual(response.status_code, 403)

    def test_no_warranty_accepts_empty_comments_for_admin_and_dealer(self):
        dealer = get_user_model().objects.create_user(email='no-warranty@example.invalid')
        dealer.groups.add(Group.objects.create(name='dealer-admin'))
        dealer.dealership.add(self.dealer)
        for user in (self.admin, dealer):
            with self.subTest(user=user.email):
                LineTable.objects.filter(pk=self.line.pk).update(
                    claim_status=self.statuses['Rework' if user.is_superuser else 'No Warranty'])
                self.client.force_login(user)
                response = self.client.post(self.url, {'line_id': self.line.pk,
                    'claim_status': self.statuses['No Warranty'].pk, 'comment': ''})
                self.assertEqual(response.status_code, 302)
                self.line.refresh_from_db()
                self.assertEqual(self.line.claim_status, self.statuses['No Warranty'])
                self.assertFalse(Journal.objects.exists())

    def test_other_restricted_statuses_still_require_comments(self):
        for status in ('Not Submitted', 'Rejected', 'Requires Attention'):
            with self.subTest(status=status):
                payload = self.payload(status)
                payload.update(comment='', start_date='October 08, 2026')
                response = self.client.post(self.url, payload)
                self.assertContains(self.client.get(response.url), 'A comment is required')
                self.line.refresh_from_db()
                self.assertEqual(self.line.claim_status, self.statuses['New'])
        self.assertFalse(Journal.objects.exists())

    def test_completion_timestamp_is_saved_and_rendered_without_losing_time(self):
        from core.dates import datetime_input
        payload = self.payload('Pending')
        payload['start_date'] = '2026-10-08T16:42:37'
        response = self.client.post(self.url, payload)
        self.assertEqual(response.status_code, 302)
        self.line.refresh_from_db()
        self.assertEqual(datetime_input(self.line.start_date), payload['start_date'])
        response = self.client.get(self.edit_url)
        self.assertEqual(self.fields(response, self.line.pk)['start_date'].get('value'), payload['start_date'])



class RepairOrderSearchTests(TestCase):
    setUpTestData = classmethod(SecurityBaselineTests.setUpTestData.__func__)
    setUp = SecurityBaselineTests.setUp

    def search(self, query='123', **extra):
        return self.client.get(reverse('claim:search-ro'), {
            'dealership_id': self.own.pk, 'repair_order': query, **extra})

    def test_search_displays_details_and_repeat_search(self):
        self.claim.claim_tag.add(Tag.objects.create(name='Bodyshop'))
        Journal.objects.create(claim=self.claim, line=self.line, user=self.dealer,
            comment='Customer called <script>alert(1)</script>')
        attachment = PdfFile.objects.create(claim=self.claim, pdf_name='Repair photo', pdf_file='private/photo.png')
        response = self.search(' 123 ')
        for text in ('Repair Order 123', 'Requires Attention', 'Warranty', '$123.45', 'Bodyshop',
                     'name="repair_order"', 'value="123"'):
            self.assertContains(response, text)
        for hidden in ('Compliant', 'Service Writer', 'Technician', 'Comments', 'Attachments', 'Repair photo', 'Customer called'):
            self.assertNotContains(response, hidden)
        self.assertNotContains(response, reverse('claim:download-pdf', args=[attachment.pk]))
        self.assertContains(response, reverse('claim:dealer-claim-update', args=[self.claim.pk, self.own.pk]))
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertEqual([claim.pk for claim in response.context['repair_orders']], [self.claim.pk])

    def test_search_formats_all_dollar_amounts_with_commas(self):
        from .models import Discrepancy
        self.line.claim_total = Decimal('1234567.89')
        self.line.discrepancy = Discrepancy.objects.create(labor=Decimal('2345.67'))
        self.line.save()
        response = self.search()
        self.assertContains(response, '$1,234,567.89', count=2)
        self.assertContains(response, '$2,345.67')

    def test_search_rejects_foreign_dealership_and_legacy_line_leaks(self):
        response = self.search(dealership_id=self.other.pk)
        self.assertEqual(response.status_code, 404)
        rogue = LineTable.objects.create(claim=self.claim, dealership=self.other,
            line_num='foreign-line-secret', claim_status=self.status)
        Journal.objects.create(claim=self.claim, line=rogue, comment='foreign-comment-secret')
        response = self.search()
        self.assertNotContains(response, 'foreign-line-secret')
        self.assertNotContains(response, 'foreign-comment-secret')
        self.assertEqual(response.context['repair_orders'][0].search_total, Decimal('123.45'))

    def test_empty_and_unmatched_search_keep_search_form(self):
        for query in ('', ' ', '999999', '<script>'):
            with self.subTest(query=query):
                response = self.search(query)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'name="repair_order"')
                self.assertEqual(response.context['page_obj'].paginator.count, 0)
        self.client.logout()
        self.assertEqual(self.search().status_code, 302)

    def test_search_paginates_without_related_query_growth(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as queries:
            self.search()
        initial_count = len(queries)
        for number in range(11):
            claim = Claim.objects.create(dealership=self.own, repair_order=12300 + number, ro_status=self.open)
            LineTable.objects.create(claim=claim, dealership=self.own, claim_status=self.status)
            Journal.objects.create(claim=claim, user=self.dealer, comment='Another comment')
        with CaptureQueriesContext(connection) as queries:
            response = self.search()
        self.assertEqual(len(queries), initial_count)
        self.assertEqual(len(response.context['repair_orders']), 10)
        self.assertContains(response, 'repair_order=123&amp;page=2')
        page = self.search(page=2).context['page_obj']
        self.assertEqual(len(page), 2)
        self.assertEqual(page.paginator.count, 12)

    def test_admin_and_viewer_links_match_permissions(self):
        self.client.force_login(self.admin)
        self.assertContains(self.search(), reverse('claim:claim-update', args=[self.claim.pk, self.own.pk]))
        self.client.force_login(self.viewer)
        self.assertNotContains(self.search(), 'View / edit claim')


class ClaimReassignmentAndDeleteTests(TestCase):
    setUpTestData = classmethod(SecurityBaselineTests.setUpTestData.__func__)

    def setUp(self):
        self.client.force_login(self.admin)

    def test_portal_reassignment_moves_lines_and_preserves_related_records(self):
        journal = Journal.objects.create(claim=self.claim, line=self.line, comment='Keep this comment')
        attachment = PdfFile.objects.create(claim=self.claim, pdf_name='Keep file', pdf_file='private/file.pdf')
        url = reverse('claim:update-claim', args=[self.own.name, self.claim.repair_order])
        response = self.client.post(url, {'dealership': self.other.pk,
            'repair_order': self.claim.repair_order, 'ro_status': self.open.pk})
        self.assertRedirects(response, reverse('claim:claim-update', args=[self.claim.pk, self.other.pk]))
        self.line.refresh_from_db()
        self.assertEqual(self.line.dealership_id, self.other.pk)
        self.assertEqual(Journal.objects.get(pk=journal.pk).line_id, self.line.pk)
        self.assertEqual(PdfFile.objects.get(pk=attachment.pk).claim_id, self.claim.pk)
        self.client.force_login(self.dealer)
        self.assertEqual(self.client.get(reverse('claim:dealer-claim-update', args=[self.claim.pk, self.own.pk])).status_code, 404)
        self.dealer.dealership.set([self.other])
        response = self.client.get(reverse('claim:dealer-claim-update', args=[self.claim.pk, self.other.pk]))
        self.assertContains(response, 'Keep this comment')

    def test_direct_model_update_moves_every_line(self):
        second = LineTable.objects.create(claim=self.claim, dealership=self.own, claim_status=self.rework)
        self.claim.dealership = self.other
        self.claim.save(update_fields=['dealership'])
        self.assertEqual(set(LineTable.objects.filter(claim=self.claim).values_list('dealership_id', flat=True)), {self.other.pk})

    def test_move_rolls_back_when_line_update_fails(self):
        self.claim.dealership = self.other
        with patch('claim.models.LineTable.save', side_effect=RuntimeError('Failed line save')):
            with self.assertRaises(RuntimeError):
                self.claim.save(update_fields=['dealership'])
        self.claim.refresh_from_db()
        self.line.refresh_from_db()
        self.assertEqual(self.claim.dealership_id, self.own.pk)
        self.assertEqual(self.line.dealership_id, self.own.pk)

    def test_unpersisted_dealership_change_does_not_move_lines(self):
        self.claim.dealership = self.other
        self.claim.save(update_fields=['ro_status'])
        self.line.refresh_from_db()
        self.assertEqual(self.line.dealership_id, self.own.pk)

    def test_dealer_cannot_reassign_claim(self):
        self.client.force_login(self.dealer)
        response = self.client.post(reverse('claim:update-claim', args=[self.own.name, self.claim.repair_order]),
            {'dealership': self.other.pk, 'repair_order': self.claim.repair_order, 'ro_status': self.open.pk})
        self.assertEqual(response.status_code, 403)

    def test_each_delete_get_confirms_without_mutation_and_cancel_is_available(self):
        from .models import Discrepancy
        discrepancy = Discrepancy.objects.create(labor=10)
        self.line.discrepancy = discrepancy
        self.line.save(update_fields=['discrepancy'])
        journal = Journal.objects.create(claim=self.claim, line=self.line, comment='Retain until confirmed')
        urls = [reverse('claim:delete-line', args=[self.line.pk]),
            reverse('claim:delete-claim', args=[self.own.name, self.claim.repair_order]),
            reverse('claim:delete-journal', args=[journal.pk]),
            reverse('claim:delete-discrepancy', args=[discrepancy.pk, self.line.pk])]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(response, 'Are you sure')
                self.assertContains(response, 'Cancel')
        self.assertTrue(LineTable.objects.filter(pk=self.line.pk).exists())
        self.assertTrue(Claim.objects.filter(pk=self.claim.pk).exists())
        self.assertTrue(Journal.objects.filter(pk=journal.pk).exists())
        self.assertTrue(Discrepancy.objects.filter(pk=discrepancy.pk).exists())
        response = self.client.post(urls[0])
        self.assertEqual(response.status_code, 302)
        self.assertFalse(LineTable.objects.filter(pk=self.line.pk).exists())

    def test_delete_confirmation_requires_admin_and_escapes_line_names(self):
        self.line.line_num = "<script>alert('delete')</script>"
        self.line.save(update_fields=['line_num'])
        url = reverse('claim:delete-line', args=[self.line.pk])
        self.assertContains(self.client.get(url), '&lt;script&gt;')
        self.client.force_login(self.dealer)
        self.assertEqual(self.client.get(url).status_code, 403)
