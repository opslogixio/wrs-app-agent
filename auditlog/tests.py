from unittest.mock import patch
from django.test import RequestFactory, TestCase
from accounts.models import Dealership
from claim.models import Claim
from .utils import log_model_event


class AuditPrivacyTests(TestCase):
    def test_session_credentials_are_not_copied_to_audit_records(self):
        dealer = Dealership.objects.create(name='Assigned')
        claim = Claim.objects.create(dealership=dealer, repair_order=1)
        request = RequestFactory().get('/')
        request.session = type('Session', (), {'session_key': 'sensitive-session-token'})()
        with patch('auditlog.utils.get_current_request', return_value=request):
            event = log_model_event(instance=claim, action='UPDATE', claim=claim, dealership=dealer)
        self.assertIsNone(event.session_key)
