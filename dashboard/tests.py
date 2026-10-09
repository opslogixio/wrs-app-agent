from datetime import date
from decimal import Decimal
import json

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse

from accounts.models import Dealership
from claim.models import Claim, ClaimType, LineTable, Status
from context_processors import user_dealerships
from .views import get_charts_data


class ChartPerformanceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(email='chart@example.invalid')
        cls.dealer = Dealership.objects.create(name='Assigned')
        cls.foreign = Dealership.objects.create(name='Foreign')
        cls.user.dealership.add(cls.dealer)
        cls.paid = Status.objects.create(name='Paid')
        cls.pending = Status.objects.create(name='Pending')
        cls.type = ClaimType.objects.create(name='Warranty')
        cls.claim = Claim.objects.create(dealership=cls.dealer, repair_order=1)
        cls.year = date.today().year
        for amount, when, status, dealer in (
            ('10.25', date(cls.year, 1, 1), cls.paid, cls.dealer),
            ('20.50', date(cls.year, 1, 31), cls.paid, cls.dealer),
            ('99.00', date(cls.year - 1, 1, 1), cls.paid, cls.dealer),
            ('88.00', date(cls.year, 1, 1), cls.pending, cls.dealer),
            ('77.00', date(cls.year, 1, 1), cls.paid, cls.foreign),
        ):
            LineTable.objects.create(claim=cls.claim, dealership=dealer, claim_type=cls.type, claim_status=status, paid_date=when, claim_total=Decimal(amount))

    def test_chart_totals_and_constant_query_budget(self):
        request = RequestFactory().get('/')
        request.user = self.user
        ClaimType.objects.bulk_create([ClaimType(name=f'Type {i}') for i in range(10)])
        with self.assertNumQueries(4):
            response = get_charts_data(request, self.dealer.pk)
        series = json.loads(response.content)['series']
        warranty = next(row for row in series if row['name'] == 'Warranty')
        self.assertEqual(Decimal(warranty['data'][0]), Decimal('30.75'))
        self.assertEqual(warranty['data'][1:], [0] * 11)
        self.assertTrue(all(row['data'] == [0] * 12 for row in series if row['name'] != 'Warranty'))

    def test_chart_requires_login_and_dealership_membership(self):
        url = reverse('dashboard:get_charts_data', args=[self.foreign.pk])
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_context_processor_evaluates_membership_once(self):
        request = RequestFactory().get('/')
        request.user = self.user
        request.session = {}
        with self.assertNumQueries(1):
            result = user_dealerships(request)
            self.assertEqual(list(result['user_dealerships']), [self.dealer])
            self.assertEqual(result['user_stat'], 'single_user')
