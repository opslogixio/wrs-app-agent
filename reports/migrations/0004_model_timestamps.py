"""Preserve legacy calendar dates as midnight in the application time zone."""
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo
from django.conf import settings
from django.db import migrations, models


FIELDS = {'HistoricalLineTable': ['start_date', 'paid_date'], 'HistoricalJournal': ['comment_date'], 'ReportJob': ['start_date', 'end_date']}


def preserve_dates(apps, schema_editor):
    zone = ZoneInfo(settings.TIME_ZONE)
    for name, fields in FIELDS.items():
        model = apps.get_model('reports', name)
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
    dependencies = [('reports', '0003_reportjob')]
    operations = [
        migrations.AlterField(model_name='historicallinetable', name='start_date', field=models.DateTimeField(null=True, blank=True)),
        migrations.AlterField(model_name='historicallinetable', name='paid_date', field=models.DateTimeField(null=True, blank=True)),
        migrations.AlterField(model_name='historicaljournal', name='comment_date', field=models.DateTimeField(null=True, blank=True)),
        migrations.AlterField(model_name='reportjob', name='start_date', field=models.DateTimeField(null=True, blank=True)),
        migrations.AlterField(model_name='reportjob', name='end_date', field=models.DateTimeField(null=True, blank=True)),
        migrations.RunPython(preserve_dates),
    ]
