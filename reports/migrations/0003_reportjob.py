import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0002_customuser_daily_report_email_and_more'),
        ('reports', '0002_historicaljournal_comment_date'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ReportJob',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('report_type', models.CharField(choices=[(name, name) for name in ('Daily Report', 'Archived Report', 'Discrepancy Report', 'RA Report')], max_length=30)),
                ('start_date', models.DateField(blank=True, null=True)),
                ('end_date', models.DateField(blank=True, null=True)),
                ('state', models.CharField(choices=[('queued', 'Queued'), ('running', 'Generating'), ('completed', 'Ready'), ('failed', 'Failed')], default='queued', max_length=12)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('finished_at', models.DateTimeField(blank=True, null=True)),
                ('attempts', models.PositiveSmallIntegerField(default=0)),
                ('error', models.CharField(blank=True, max_length=200)),
                ('dealership', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='accounts.dealership')),
                ('requested_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['created_at', 'id'],
                'indexes': [models.Index(fields=['state', 'created_at'], name='report_job_queue_idx')],
            },
        ),
    ]
