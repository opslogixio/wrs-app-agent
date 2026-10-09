from decimal import Decimal
import html5lib
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from accounts.models import Dealership
from claim.models import Claim, LineTable, RoStatus, Status


class OpenQueueTotalsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dealer = Dealership.objects.create(name='Queue Totals')
        cls.foreign = Dealership.objects.create(name='Foreign Totals')
        cls.user = get_user_model().objects.create_user(email='totals@example.invalid')
        cls.user.groups.add(Group.objects.create(name='dealer-admin'))
        cls.user.dealership.add(cls.dealer)
        cls.admin = get_user_model().objects.create_superuser(email='totals-admin@example.invalid')
        cls.open = RoStatus.objects.create(name='Open')
        cls.closed = RoStatus.objects.create(name='Closed')
        cls.paid = Status.objects.create(name='Paid')
        cls.no_warranty = Status.objects.create(name='No Warranty')
        cls.pending = Status.objects.create(name='Pending')
        cls.claim = Claim.objects.create(dealership=cls.dealer, repair_order=111, ro_status=cls.open)
        for amount, status, dealer in (('1000.25', cls.paid, cls.dealer), ('2000.50', cls.no_warranty, cls.dealer),
            (None, cls.paid, cls.dealer), ('999999.99', cls.paid, cls.foreign)):
            LineTable.objects.create(claim=cls.claim, dealership=dealer, claim_status=status, claim_total=amount)
        cls.empty = Claim.objects.create(dealership=cls.dealer, repair_order=112, ro_status=cls.open)
        cls.blocked = Claim.objects.create(dealership=cls.dealer, repair_order=113, ro_status=cls.open)
        LineTable.objects.create(claim=cls.blocked, dealership=cls.dealer, claim_status=cls.pending, claim_total='300.00')
        Claim.objects.create(dealership=cls.dealer, repair_order=114, ro_status=cls.closed)
        Claim.objects.create(dealership=cls.foreign, repair_order=115, ro_status=cls.open)

    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse('reports:open-reports-view', args=[self.dealer.pk])

    def test_totals_sum_all_own_lines_once_and_render_sortable_dollars(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        claims = {claim.pk: claim for claim in response.context['open_claims']}
        self.assertEqual(set(claims), {self.claim.pk, self.empty.pk})
        self.assertEqual(claims[self.claim.pk].repair_order_total, Decimal('3000.75'))
        self.assertEqual(claims[self.empty.pk].repair_order_total, Decimal('0.00'))
        self.assertContains(response, '$3,000.75')
        self.assertContains(response, '$0.00')
        self.assertContains(response, 'data-sort="3000.75"')
        self.assertContains(response, 'Total Dollars')
        self.assertNotContains(response, '999,999.99')
        root = html5lib.parse(response.content.decode(), namespaceHTMLElements=False)
        table = next(node for node in root.iter('table') if node.get('id') == 'bodyshopTable')
        self.assertEqual(len(list(table.iter('th'))), 6)
        for row in table.iter('tr'):
            cells = list(row.iter('td'))
            if cells:
                self.assertEqual(len(cells), 6)

    def test_links_follow_user_role_and_access_stays_scoped(self):
        for user, route in ((self.user, 'dealer-claim-update'), (self.admin, 'claim-update')):
            self.client.force_login(user)
            self.assertContains(self.client.get(self.url), reverse('claim:' + route, args=[self.claim.pk, self.dealer.pk]))
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('reports:open-reports-view', args=[self.foreign.pk])).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
