"""Verify deployed queue totals and dealer workflows, rolling back all fixtures."""
import os
from pathlib import Path
import secrets
import sys
from decimal import Decimal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
import django
django.setup()
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import transaction
from django.test import Client
from django.test.utils import setup_test_environment, teardown_test_environment
from django.urls import reverse
from accounts.models import Dealership
from claim.models import Claim, ClaimType, Journal, LineTable, RoStatus, Status, Tag
from core.dates import clean_datetime

setup_test_environment()
try:
    with transaction.atomic():
        token = secrets.token_hex(6)
        admin = get_user_model().objects.create_superuser(email=f'workflow-admin-{token}@example.invalid')
        client = Client(HTTP_HOST='wrs.opslogix.io', HTTP_X_FORWARDED_PROTO='https')
        client.force_login(admin)
        checked = orders = 0
        for dealer in Dealership.objects.all():
            response = client.get(reverse('reports:open-reports-view', args=[dealer.pk]))
            assert response.status_code == 200
            for claim in response.context['open_claims']:
                expected = sum((amount or Decimal('0.00') for amount in
                    LineTable.objects.filter(claim=claim, dealership=dealer).values_list('claim_total', flat=True)), Decimal('0.00'))
                assert claim.repair_order_total == expected, (claim.pk, claim.repair_order_total, expected)
                orders += 1
            assert 'Total Dollars' in response.content.decode()
            checked += 1
        print(f'Verified {orders} repair-order totals in {checked} dealership queues.')

        dealer = Dealership.objects.first()
        user = get_user_model().objects.create_user(email=f'workflow-dealer-{token}@example.invalid')
        user.groups.add(Group.objects.get(name='dealer-admin'))
        user.dealership.add(dealer)
        client.force_login(user)
        tag = Tag.objects.filter(name__in=ClaimType.objects.values('name')).order_by('pk').first()
        assert tag is not None, 'A claim tag with a matching claim type is required.'
        statuses = {status.name: status for status in Status.objects.all()}
        number = max(1, Claim.objects.order_by('-repair_order').values_list('repair_order', flat=True).first() or 0) + 1
        create_url = reverse('claim:claim-form', args=[dealer.pk])
        for offset, action in enumerate(('submit', 'add_another', 'add_another')):
            response = client.post(create_url, {'dealership': dealer.pk, 'repair_order': number + offset,
                'claim_tag': [tag.pk], 'comment': 'Temporary deployment verification', 'action': action})
            assert response.status_code == 302
            claim = Claim.objects.get(dealership=dealer, repair_order=number + offset)
            expected = reverse('claim:dealer-claim-update', args=[claim.pk, dealer.pk]) if action == 'submit' else create_url + '?add_another=1'
            assert response.url == expected, response.url
            page = client.get(response.url)
            assert page.status_code == 200
            if action == 'add_another':
                assert not page.context['claim_form'].is_bound
                assert '>Done</a>' in page.content.decode()
        line = claim.linetable_set.get()
        for current, expected, default in (
            ('Requires Attention', {'Rework', 'Not Submitted'}, 'Rework'),
            ('Rejected', {'Rejected', 'Rework'}, 'Rejected'),
            ('No Warranty', {'No Warranty', 'Rework'}, 'No Warranty'),
            ('Not Submitted', {'Not Submitted', 'Rework'}, 'Not Submitted'),
        ):
            LineTable.objects.filter(pk=line.pk).update(claim_status=statuses[current], start_date=clean_datetime('2026-10-08T14:32:10'))
            page = client.get(reverse('claim:dealer-claim-update', args=[claim.pk, dealer.pk]))
            rendered = next(row for row in page.context['line_table'] if row.pk == line.pk)
            assert {option['name'] for option in rendered.dealer_status_options} == expected
            assert rendered.dealer_status_selected == str(statuses[default].pk)
            if current != 'Requires Attention':
                rejected = client.post(reverse('claim:line-updates'), {'line_id': line.pk, 'claim_status': statuses['Rework'].pk})
                line.refresh_from_db()
                assert rejected.status_code == 302 and line.claim_status.name == current
            accepted = client.post(reverse('claim:line-updates'), {'line_id': line.pk,
                'claim_status': statuses['Rework'].pk, 'comment': 'Verified dealer rework comment'})
            line.refresh_from_db()
            assert accepted.status_code == 302 and line.claim_status.name == 'Rework'
        for name in ('Rework', 'New', 'Pending', 'Paid'):
            LineTable.objects.filter(pk=line.pk).update(claim_status=statuses[name])
            page = client.get(reverse('claim:dealer-claim-update', args=[claim.pk, dealer.pk]))
            rendered = next(row for row in page.context['line_table'] if row.pk == line.pk)
            assert not rendered.dealer_status_options, name
            forged = client.post(reverse('claim:line-updates'), {'line_id': line.pk,
                'claim_status': statuses['No Warranty'].pk, 'comment': 'Forbidden transition'})
            line.refresh_from_db()
            assert forged.status_code == 403 and line.claim_status.name == name
            accepted = client.post(reverse('claim:line-updates'), {'line_id': line.pk, 'comment': 'Allowed comment'})
            line.refresh_from_db()
            assert accepted.status_code == 302 and line.claim_status.name == name
        print('Verified Submit, repeated Add another claim, Done, dealer dropdown defaults, required rework comments, and read-only statuses.')
        transaction.set_rollback(True)
    print('All temporary users, claims, lines, comments, audit events, and sessions rolled back.')
finally:
    teardown_test_environment()
