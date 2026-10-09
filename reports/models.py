import uuid

from django.db import models
from accounts.models import CustomUser, Dealership
from claim.models import Claim, RoStatus, ClaimType, Status, Discrepancy

class HistoricalClaim(models.Model):
    id = models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)
    repair_order = models.IntegerField(help_text='Enter Repair Order Number')
    dealership = models.ForeignKey(Dealership, on_delete=models.CASCADE, verbose_name='Dealership name', null=True, blank=True)
    ro_status = models.ForeignKey(RoStatus, on_delete=models.CASCADE, verbose_name='ro status name', null=True, blank=True)
    created_date = models.DateTimeField()

class HistoricalLineTable(models.Model):
    id = models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)
    claim = models.ForeignKey(HistoricalClaim, on_delete=models.CASCADE, verbose_name='claim id', null=True, blank=True)
    line_num = models.CharField(max_length=50, verbose_name='line num', null=True, blank=True, default='1')
    claim_type = models.ForeignKey(ClaimType, on_delete=models.CASCADE, verbose_name='claim type', null=True, blank=True)
    claim_total = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text='Required. Dollar Amount',
        verbose_name='claim total',
        null=True,
        blank=True,
        default=0.00
    )
    claim_status = models.ForeignKey(Status, on_delete=models.CASCADE, verbose_name='claim status name', null=True, blank=True, default=1)
    dealership = models.ForeignKey(Dealership, on_delete=models.CASCADE, verbose_name='dealership name', null=True, blank=True)
    start_date = models.DateTimeField(null=True, blank=True)
    paid_date = models.DateTimeField(null=True, blank=True)
    compliant = models.BooleanField(null=True, blank=True)
    discrepancy = models.ForeignKey(Discrepancy, on_delete=models.CASCADE, null=True, blank=True)
    created_date = models.DateTimeField(auto_now_add=True)

class HistoricalJournal(models.Model):
    id = models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)
    comment = models.TextField(verbose_name='comment', null=True, blank=True)
    line = models.ForeignKey(HistoricalLineTable, on_delete=models.CASCADE, verbose_name='line id', null=True, blank=True)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, null=True, blank=True)
    created_date = models.DateTimeField(auto_now_add=True)
    comment_date = models.DateTimeField(null=True, blank=True)

class dummyTable(models.Model):
    id = models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)
    name = models.CharField(max_length=50, verbose_name='line num', null=True, blank=True, default='1')

class ReportJob(models.Model):
    """Durable PDF export requests; documents are served only after authorization."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dealership = models.ForeignKey(Dealership, on_delete=models.CASCADE)
    requested_by = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    report_type = models.CharField(max_length=30, choices=[
        (name, name) for name in ('Daily Report', 'Archived Report', 'Discrepancy Report', 'RA Report')
    ])
    start_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)
    state = models.CharField(max_length=12, default='queued', choices=[
        ('queued', 'Queued'), ('running', 'Generating'), ('completed', 'Ready'), ('failed', 'Failed'),
    ])
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    error = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['created_at', 'id']
        indexes = [models.Index(fields=['state', 'created_at'], name='report_job_queue_idx')]
