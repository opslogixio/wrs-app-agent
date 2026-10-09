"""Verify rendered Bodyshop sections against live queue contexts without retaining fixtures."""
import os
from pathlib import Path
import secrets
import sys
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
import django
django.setup()

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client
from django.test.utils import setup_test_environment, teardown_test_environment
from django.urls import reverse
from accounts.models import Dealership
from claim.test_helpers import QueueTableParser

queues = (
    ('claim-queue', 'Rework', 'other_claims', False),
    ('new-claim-queue', 'New', 'new_claims', False),
    ('pending-claim-queue', 'Pending', 'pending_claims', True),
    ('rework-claim-queue', 'Rework', 'rework_claims', True),
    ('ra-claim-queue', 'Requires Attention', 'ra_claims', True),
    ('ra-claim-queue', 'Aging', 'ra_claims', True),
)
setup_test_environment()
try:
    with transaction.atomic():
        user = get_user_model().objects.create_superuser(email=f'bodyshop-check-{secrets.token_hex(8)}@example.invalid')
        dealers = list(Dealership.objects.all())
        user.dealership.set(dealers)
        client = Client(HTTP_HOST='wrs.opslogix.io', HTTP_X_FORWARDED_PROTO='https')
        client.force_login(user)
        checked = 0
        bodyshop_counts = dict.fromkeys([route + ':' + status for route, status, _, _ in queues], 0)
        for dealer in dealers:
            for route, status, section, has_lines in queues:
                response = client.get(reverse('claim:' + route, args=[status]), {'dealership_id': dealer.pk})
                assert response.status_code == 200, (dealer.pk, route, response.status_code)
                context = response.context
                tables = QueueTableParser(response.content.decode()).tables
                assert ('bodyshopTable' in tables) == bool(context['bodyshop_claims']), (dealer.pk, route)
                assert bool(context['bodyshop']) == bool(context['bodyshop_claims'])
                assert response.content.decode().count('js/table-sort.js') == 1
                for table, key, is_bodyshop in (
                    ('bodyshopTable', 'bodyshop_claims', True), ('claimsTable', section, False),
                ):
                    expected = []
                    for entry in context[key]:
                        claim = entry['claim'] if has_lines else entry
                        assert claim.dealership_id == dealer.pk
                        assert any(tag.name == 'Bodyshop' for tag in claim.claim_tag.all()) == is_bodyshop
                        link = reverse('claim:claim-update', args=[claim.pk, dealer.pk])
                        if has_lines:
                            for line_data in entry['lines']:
                                line = line_data['line']
                                assert line.dealership_id == dealer.pk
                                assert line.claim_status.name == ('Requires Attention' if status == 'Aging' else status)
                                if status == 'Aging':
                                    assert line.start_date and line.start_date <= date.today() - timedelta(days=90)
                                expected.append((str(claim.repair_order), str(line.line_num), link))
                        else:
                            expected.append((str(claim.repair_order), None, link))
                    actual = [(row['cells'][0], row['cells'][1] if has_lines else None, row['links'][0])
                        for row in tables.get(table, [])]
                    assert actual == expected, (dealer.pk, route, status, table)
                bodyshop_counts[route + ':' + status] += len(context['bodyshop_claims'])
                checked += 1
        transaction.set_rollback(True)
    print(f'Verified both rendered sections in {checked} queue views across {len(dealers)} dealerships.')
    print('Bodyshop claims on first pages:', bodyshop_counts)
    print('Temporary user and sessions rolled back; no claim records changed.')
finally:
    teardown_test_environment()
