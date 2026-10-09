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


class DashboardAggregationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from claim.models import RoStatus
        cls.dealer = Dealership.objects.create(name='Totals')
        cls.other = Dealership.objects.create(name='Other')
        cls.open = RoStatus.objects.create(name='Open')
        cls.statuses = {name: Status.objects.create(name=name) for name in ('New', 'Pending', 'Rework', 'Requires Attention', 'Paid')}
        cls.claim = Claim.objects.create(dealership=cls.dealer, repair_order=10, ro_status=cls.open)
        completed = Claim.objects.create(dealership=cls.dealer, repair_order=20, ro_status=cls.open)
        Claim.objects.create(dealership=cls.dealer, repair_order=30, ro_status=cls.open)
        for status, amount, when, compliant, claim in (
            ('New', '1', None, None, cls.claim), ('Pending', '10', None, None, cls.claim),
            ('Rework', '20', None, None, cls.claim), ('Requires Attention', '30', None, None, cls.claim),
            ('Paid', '40', date(2026, 1, 5), True, completed),
            ('Paid', '50', date(2025, 12, 5), False, completed),
        ):
            line = LineTable.objects.create(claim=claim, dealership=cls.dealer, claim_status=cls.statuses[status],
                claim_total=amount, start_date=date(2025, 1, 1), paid_date=when, compliant=compliant)
            LineTable.objects.filter(pk=line.pk).update(created_date=date(2026, 1, 1))
        LineTable.objects.create(claim=cls.claim, dealership=cls.other, claim_status=cls.statuses['Paid'], claim_total='999')

    def test_grouped_dashboard_totals_and_january_previous_year(self):
        from unittest.mock import patch
        from .services import build_dashboard
        with patch('dashboard.services.localdate', return_value=date(2026, 1, 10)):
            with self.assertNumQueries(3):
                rows, totals = build_dashboard(Dealership.objects.filter(pk=self.dealer.pk))
        row = rows[0]
        self.assertEqual(row['pending_claims_total'], '10.00')
        self.assertEqual(row['rework_claims_total'], '20.00')
        self.assertEqual(row['requires_attention_expire_count'], 1)
        self.assertEqual(row['in_queue_total'], '60.00')
        self.assertEqual(row['paid_claims_monthly_total'], '40.00')
        self.assertEqual(row['paid_claims_previous_total'], '50.00')
        self.assertEqual(row['paid_claims_yearly_total'], '40.00')
        self.assertEqual(row['paid_claims_nc_total'], '40.00')
        self.assertEqual(row['claim_compliance'], 50)
        self.assertEqual(row['open_ro_count'], 2)
        self.assertEqual(row['open_ro_total'], '90.00')
        self.assertEqual(totals['agg_open_ro_count'], 2)
        self.assertEqual(totals['agg_monthly_total'], '40.00')

    def test_query_budget_is_constant_with_many_dealerships(self):
        from .services import build_dashboard
        Dealership.objects.bulk_create([Dealership(name=f'Empty {i}') for i in range(20)])
        with self.assertNumQueries(3):
            rows, totals = build_dashboard(Dealership.objects.all())
        self.assertEqual(len(rows), 22)
        empty = next(row for row in rows if row['dealership'] == 'Empty 0')
        self.assertEqual(empty['open_ro_total'], '0.00')
        self.assertEqual(empty['claim_compliance'], 100)
        self.assertEqual(totals['agg_pending_claims_count'], 1)

    def test_empty_dashboard_does_not_require_status_lookup(self):
        from .services import build_dashboard
        rows, totals = build_dashboard([])
        self.assertEqual(rows, [])
        self.assertEqual(totals['agg_open_ro_count'], 0)
