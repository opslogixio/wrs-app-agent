
from django.contrib.auth.models import AbstractUser, Group
from django.db import models, router, transaction
from django.utils import timezone
from datetime import date, datetime
import os
from accounts.models import CustomUser, Dealership

class ClaimType(models.Model):
    id = models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)
    name = models.CharField(help_text='Required. 50 characters or fewer.', max_length=50, verbose_name='claim type')
    description = models.TextField(max_length=1000, help_text='Enter a brief description of the claim type')

    # Metadata
    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name
    
class Status(models.Model):
    id = models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)
    name = models.CharField(help_text='Required. 50 characters or fewer', max_length=50, verbose_name='status name')
    description = models.TextField(max_length=1000, help_text='Enter a brief description of the status')

    # Metadata
    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name
    
class RoStatus(models.Model):
    id = models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)
    name = models.CharField(help_text='Required. 50 characters or fewer.', max_length=50, verbose_name='rostatus name')
    description = models.TextField(max_length=1000, help_text='Enter a brief description of the status')

    # Metadata
    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name
    
class Tag(models.Model):
    id = models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name
    
class Claim(models.Model):
    class Meta:
        indexes = [models.Index(fields=['dealership', 'repair_order'], name='claim_dealer_ro_idx')]

    id = models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)
    repair_order = models.IntegerField(help_text='Enter Repair Order Number')
    dealership = models.ForeignKey(Dealership, on_delete=models.CASCADE, verbose_name='dealership name', null=True, blank=True) 
    ro_status = models.ForeignKey(RoStatus, on_delete=models.CASCADE, verbose_name='ro status name', null=True, blank=True)
    claim_tag = models.ManyToManyField(Tag)
    created_date = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    modified_date = models.DateTimeField(auto_now=True, null=True, blank=True)

    # Metadata
    def __int__(self):
        return self.id

    def save(self, *args, **kwargs):
        using = kwargs.get('using') or router.db_for_write(type(self), instance=self)
        with transaction.atomic(using=using):
            old_dealership = None
            if self.pk:
                old_dealership = type(self).objects.using(using).select_for_update().filter(
                    pk=self.pk).values_list('dealership_id', flat=True).first()
            super().save(*args, **kwargs)
            update_fields = kwargs.get('update_fields')
            dealership_saved = update_fields is None or bool({'dealership', 'dealership_id'} & set(update_fields))
            if dealership_saved and old_dealership != self.dealership_id:
                for line in self.linetable_set.using(using).select_for_update():
                    line.dealership_id = self.dealership_id
                    line.save(using=using, update_fields=['dealership'])
    
def user_directory_path(instance, filename):
    # Get the file extension
    ext = os.path.splitext(filename)[1]
    now = datetime.now()
    timestamp = now.strftime("%Y%m%d%H%M%S")
    new_filename = f"{timestamp}_{filename}"
    return os.path.join("static", "upload", new_filename)

class PdfFile(models.Model):
    id = models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)
    pdf_name = models.CharField(max_length=100, verbose_name='pdf name', null=True, blank=True)
    pdf_file = models.FileField(upload_to=user_directory_path)
    claim = models.ForeignKey(Claim, on_delete=models.CASCADE, verbose_name='claim id', null=True, blank=True)
    created_date = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    modified_date = models.DateTimeField(auto_now=True, null=True, blank=True)

    # Metadata
    class Meta:
        ordering = ['created_date']

    def __str__(self):
        return self.pdf_name
    
class Discrepancy(models.Model):
    id = models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)
    labor = models.DecimalField(max_digits=10, decimal_places=2, help_text='Required. Dollar Amount', null=True, blank=True, default=0.00)
    parts = models.DecimalField(max_digits=10, decimal_places=2, help_text='Required. Dollar Amount', null=True, blank=True, default=0.00)
    maint = models.DecimalField(max_digits=10, decimal_places=2, help_text='Required. Dollar Amount', null=True, blank=True, default=0.00)
    other = models.DecimalField(max_digits=10, decimal_places=2, help_text='Required. Dollar Amount', null=True, blank=True, default=0.00)
    core = models.DecimalField(max_digits=10, decimal_places=2, help_text='Required. Dollar Amount', null=True, blank=True, default=0.00)
    rental = models.DecimalField(max_digits=10, decimal_places=2, help_text='Required. Dollar Amount', null=True, blank=True, default=0.00)
    sublet = models.DecimalField(max_digits=10, decimal_places=2, help_text='Required. Dollar Amount', null=True, blank=True, default=0.00)

    #Meta
    def __int__(self):
        return self.id

class LineTable(models.Model):
    id = models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)
    line_num = models.CharField(max_length=50, verbose_name='line num', null=True, blank=True, default='1')
    claim = models.ForeignKey(Claim, on_delete=models.CASCADE, verbose_name='claim id', null=True, blank=True)
    claim_type = models.ForeignKey(ClaimType, on_delete=models.CASCADE, verbose_name='claim type', null=True, blank=True)
    service_writer = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='service_writer_lines',
        null=True,
        blank=True
    )
    technician = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='technician_lines',
        null=True,
        blank=True
    )
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
    created_date = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    modified_date = models.DateTimeField(auto_now=True, null=True, blank=True)
    start_date = models.DateTimeField(null=True, blank=True)
    paid_date = models.DateTimeField(null=True, blank=True)
    compliant = models.BooleanField(null=True, blank=True)
    discrepancy = models.ForeignKey(Discrepancy, on_delete=models.SET_NULL, null=True, blank=True)

    # Metadata
    class Meta:
        ordering = ['id']
        indexes = [
            models.Index(fields=['dealership', 'claim_status', 'paid_date'], name='line_dealer_paid_idx'),
            models.Index(fields=['dealership', 'claim_status', 'start_date'], name='line_dealer_start_idx'),
        ]

    def __str__(self):
        return self.line_num
    
    def save(self, *args, **kwargs):
        # Check if service_writer and technician are assigned and add them to their respective groups
        if self.service_writer:
            service_writer_group, _ = Group.objects.get_or_create(name='Service Writer')
            self.service_writer.groups.add(service_writer_group)

        if self.technician:
            technician_group, _ = Group.objects.get_or_create(name='Technician')
            self.technician.groups.add(technician_group)

        super().save(*args, **kwargs)

    
class Journal(models.Model):
    id = models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)
    comment = models.TextField(verbose_name='comment', null=True, blank=True)
    line = models.ForeignKey(LineTable, on_delete=models.CASCADE, verbose_name='line id', null=True, blank=True)
    claim = models.ForeignKey(Claim, on_delete=models.CASCADE, verbose_name='claim id', null=True, blank=True)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, null=True, blank=True)
    created_date = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    modified_date = models.DateTimeField(auto_now=True, null=True, blank=True)

    # Metadata
    class Meta:
        ordering = ['created_date','line']

    def __str__(self):
        return self.comment or "No Comment"
    
class Event(models.Model):
    id = models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)
    claim = models.ForeignKey(Claim, on_delete=models.CASCADE, verbose_name='claim id', null=True, blank=True)
    line = models.ForeignKey(LineTable, on_delete=models.CASCADE, verbose_name='line id', null=True, blank=True)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, null=True, blank=True)
    comment = models.TextField(verbose_name='comment', null=True, blank=True)
    created_date = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    modified_date = models.DateTimeField(auto_now=True, null=True, blank=True)

    # Metadata
    class Meta:
        ordering = ['created_date','line']

    def __str__(self):
        return self.comment or "No Comment"
