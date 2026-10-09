"""Preserve legacy calendar dates as midnight in the application time zone."""
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo
from django.conf import settings
from django.db import migrations, models


FIELDS = {'Dealership': ['agreement_date', 'created_date']}


def preserve_dates(apps, schema_editor):
    zone = ZoneInfo(settings.TIME_ZONE)
    for name, fields in FIELDS.items():
        model = apps.get_model('accounts', name)
        manager = model.objects.using(schema_editor.connection.alias)
        batch = []
        for row in manager.only('pk', *fields).iterator(chunk_size=500):
            for field in fields:
                value = getattr(row, field)
                if value is not None:
                    # ALTER DATE to DATETIME produces naive midnight stored as UTC.
                    day = value.date()
                    setattr(row, field, datetime.combine(day, time.min, zone).astimezone(timezone.utc))
            batch.append(row)
            if len(batch) == 500:
                manager.bulk_update(batch, fields, batch_size=500)
                batch = []
        if batch:
            manager.bulk_update(batch, fields, batch_size=500)


class Migration(migrations.Migration):
    dependencies = [('accounts', '0002_customuser_daily_report_email_and_more')]
    operations = [
        migrations.AlterField(model_name='dealership', name='agreement_date', field=models.DateTimeField(null=True)),
        migrations.AlterField(model_name='dealership', name='created_date', field=models.DateTimeField(auto_now_add=True, null=True)),
        migrations.RunPython(preserve_dates),
    ]
