from datetime import date, datetime, timedelta
from importlib import import_module
from zoneinfo import ZoneInfo

from django.apps import apps
from django.db import connection, models
from django.test import TestCase
from django.utils import timezone

from accounts.models import Dealership
from core.dates import as_date, as_datetime, clean_datetime, datetime_input
from claim.models import Claim, Journal, LineTable, Status
from reports.views import ReportService


class TimestampTests(TestCase):
    def test_no_date_only_model_fields_remain(self):
        for app in ('accounts', 'claim', 'reports', 'auditlog'):
            for model in apps.get_app_config(app).get_models():
                for field in model._meta.fields:
                    self.assertNotEqual(type(field), models.DateField, f'{model.__name__}.{field.name}')

    def test_datetime_input_round_trip_preserves_local_time(self):
        stamp = clean_datetime('2026-10-09T17:23:45')
        self.assertTrue(timezone.is_aware(stamp))
        self.assertEqual(datetime_input(stamp), '2026-10-09T17:23:45')
        self.assertEqual(clean_datetime('October 09, 2026'), as_datetime(date(2026, 10, 9)))
        self.assertEqual(as_date(as_datetime(date(2026, 1, 1))), date(2026, 1, 1))

    def test_migration_preserves_summer_winter_and_null_dates(self):
        dealer = Dealership.objects.create(name='Timestamp migration')
        migration = import_module('accounts.migrations.0003_model_timestamps')
        for day in (date(2026, 1, 1), date(2026, 7, 1), date(2026, 11, 1)):
            raw = datetime.combine(day, datetime.min.time(), ZoneInfo('UTC'))
            Dealership.objects.filter(pk=dealer.pk).update(agreement_date=raw, created_date=None)
            with connection.schema_editor(atomic=False) as editor:
                migration.preserve_dates(apps, editor)
            dealer.refresh_from_db()
            self.assertEqual(as_date(dealer.agreement_date), day)
            self.assertEqual(timezone.localtime(dealer.agreement_date).hour, 0)
            self.assertIsNone(dealer.created_date)

    def test_daily_report_includes_late_evening_but_not_next_day(self):
        dealer = Dealership.objects.create(name='Timestamp reporting')
        claim = Claim.objects.create(dealership=dealer, repair_order=987)
        status = Status.objects.create(name='Paid')
        line = LineTable.objects.create(dealership=dealer, claim=claim, claim_status=status)
        late = clean_datetime('2026-10-09T23:59:59')
        LineTable.objects.filter(pk=line.pk).update(modified_date=late)
        self.assertEqual(list(ReportService.daily_lines(date(2026, 10, 9)).values_list('pk', flat=True)), [line.pk])
        self.assertFalse(ReportService.daily_lines(date(2026, 10, 10)).exists())
        line.refresh_from_db()
        self.assertEqual(line.modified_date, late)
        self.assertEqual(line.modified_date.microsecond, 0)
