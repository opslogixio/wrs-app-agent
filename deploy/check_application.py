"""Run after migrations with the same environment as the systemd service."""
import os
from pathlib import Path
import secrets
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

import django

django.setup()

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import connection, transaction
from django.test import Client

with connection.cursor() as cursor:
    cursor.execute('SELECT VERSION(), DATABASE()')
    version, database = cursor.fetchone()
    assert 'MariaDB' in version, version
    assert database == os.environ.get('DB_NAME', 'wrs_app'), database
print(f'Database connection passed: {database}, {version}')

client = Client(HTTP_HOST='wrs.opslogix.io', HTTP_X_FORWARDED_PROTO='https')
assert client.get('/accounts/login/').status_code == 200
assert client.get('/').status_code == 302
assert client.get('/admin/').status_code == 302

# Exercise authentication and database writes, then roll all fixtures back.
with transaction.atomic():
    password = secrets.token_urlsafe(24)
    email = f'deployment-check-{secrets.token_hex(8)}@example.invalid'
    user = get_user_model().objects.create_superuser(email=email, password=password)
    group, _ = Group.objects.get_or_create(name='wrs-admin')
    user.groups.add(group)
    from accounts.models import Dealership
    user.dealership.set(Dealership.objects.all())
    response = client.post('/accounts/login/', {'username': email, 'password': password})
    assert response.status_code == 302, response.status_code
    assert client.get('/admin/').status_code == 200
    dashboard = client.get(response['Location'])
    assert dashboard.status_code == 200, dashboard.status_code
    transaction.set_rollback(True)
print('Login page, redirects, authenticated admin, and dashboard passed; test records rolled back.')
