"""Preserve legacy calendar dates as midnight in the application time zone."""
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo
from django.conf import settings
from django.db import migrations, models


FIELDS = {'Claim': ['created_date', 'modified_date'], 'PdfFile': ['created_date', 'modified_date'], 'LineTable': ['created_date', 'modified_date', 'start_date', 'paid_date'], 'Journal': ['created_date', 'modified_date'], 'Event': ['created_date', 'modified_date']}


def preserve_dates(apps, schema_editor):
    zone = ZoneInfo(settings.TIME_ZONE)
    for name, fields in FIELDS.items():
        model = apps.get_model('claim', name)
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
    dependencies = [('claim', '0003_security_baseline_indexes')]
    operations = [
        migrations.AlterField(model_name='claim', name='created_date', field=models.DateTimeField(auto_now_add=True, null=True, blank=True)),
        migrations.AlterField(model_name='claim', name='modified_date', field=models.DateTimeField(auto_now=True, null=True, blank=True)),
        migrations.AlterField(model_name='pdffile', name='created_date', field=models.DateTimeField(auto_now_add=True, null=True, blank=True)),
        migrations.AlterField(model_name='pdffile', name='modified_date', field=models.DateTimeField(auto_now=True, null=True, blank=True)),
        migrations.AlterField(model_name='linetable', name='created_date', field=models.DateTimeField(auto_now_add=True, null=True, blank=True)),
        migrations.AlterField(model_name='linetable', name='modified_date', field=models.DateTimeField(auto_now=True, null=True, blank=True)),
        migrations.AlterField(model_name='linetable', name='start_date', field=models.DateTimeField(null=True, blank=True)),
        migrations.AlterField(model_name='linetable', name='paid_date', field=models.DateTimeField(null=True, blank=True)),
        migrations.AlterField(model_name='journal', name='created_date', field=models.DateTimeField(auto_now_add=True, null=True, blank=True)),
        migrations.AlterField(model_name='journal', name='modified_date', field=models.DateTimeField(auto_now=True, null=True, blank=True)),
        migrations.AlterField(model_name='event', name='created_date', field=models.DateTimeField(auto_now_add=True, null=True, blank=True)),
        migrations.AlterField(model_name='event', name='modified_date', field=models.DateTimeField(auto_now=True, null=True, blank=True)),
        migrations.RunPython(preserve_dates),
    ]
