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
            response.close()
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
