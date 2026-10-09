"""Snapshot and verify app rows around DATE migrations; run only on the DB host."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
import django
django.setup()
from django.conf import settings
from django.db import connection

parser = argparse.ArgumentParser()
parser.add_argument('mode', choices=['snapshot', 'verify'])
parser.add_argument('path', type=Path)
args = parser.parse_args()
previous = json.loads(args.path.read_text()) if args.mode == 'verify' else {}
result = {}
with connection.cursor() as cursor:
    for table in connection.introspection.table_names(cursor):
        if not table.startswith(('accounts_', 'claim_', 'reports_', 'auditlog_')):
            continue
        cursor.execute(f'SHOW COLUMNS FROM `{table}`')
        columns = cursor.fetchall()
        dates = [row[0] for row in columns if row[1].lower() == 'date']
        if args.mode == 'verify':
            assert not dates, (table, 'DATE columns remain', dates)
            dates = previous[table]['dates']
        names = [row[0] for row in columns]
        indexes = [names.index(name) for name in dates]
        cursor.execute(f'SELECT * FROM `{table}` ORDER BY ' + ', '.join(f'`{name}`' for name in names))
        digest = hashlib.sha256()
        count = 0
        for values in cursor:
            values = list(values)
            for index in indexes:
                if values[index] is not None and args.mode == 'verify':
                    value = values[index]
                    assert isinstance(value, datetime), (table, names[index], type(value))
                    local = value.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(settings.TIME_ZONE))
                    assert local.hour == local.minute == local.second == local.microsecond == 0, (table, names[index], 'legacy date is not local midnight')
                    values[index] = local.date()
            digest.update(json.dumps(values, default=str, separators=(',', ':')).encode())
            count += 1
        result[table] = {'rows': count, 'digest': digest.hexdigest(), 'dates': dates}
if args.mode == 'snapshot':
    args.path.write_text(json.dumps(result))
    args.path.chmod(0o600)
else:
    assert result == previous, 'Row counts or values changed during migration'
print(f'{args.mode}: {len(result)} tables, {sum(row["rows"] for row in result.values())} rows, {sum(len(row["dates"]) for row in result.values())} date columns. All checks passed.')
