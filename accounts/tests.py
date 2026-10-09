from contextlib import redirect_stdout
from io import StringIO

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from .custom_backend import CustomBackend


class AuthenticationTests(TestCase):
    def test_authentication_without_request_and_without_sensitive_output(self):
        user = get_user_model().objects.create_user(email='login@example.invalid', password='test-password')
        output = StringIO()
        with redirect_stdout(output):
            result = CustomBackend().authenticate(None, username=user.email, password='test-password')
        self.assertEqual(result.pk, user.pk)
        self.assertEqual(output.getvalue(), '')

    def test_superuser_without_role_group_redirects_to_admin_dashboard(self):
        user = get_user_model().objects.create_superuser(email='admin@example.invalid', password='test-password')
        self.assertEqual(CustomBackend().get_redirect_url(user), '/dashboard/admin/')
