from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('claim', '0002_alter_linetable_discrepancy')]
    operations = [
        migrations.AddIndex(model_name='claim', index=models.Index(fields=['dealership', 'repair_order'], name='claim_dealer_ro_idx')),
        migrations.AddIndex(model_name='linetable', index=models.Index(fields=['dealership', 'claim_status', 'paid_date'], name='line_dealer_paid_idx')),
        migrations.AddIndex(model_name='linetable', index=models.Index(fields=['dealership', 'claim_status', 'start_date'], name='line_dealer_start_idx')),
    ]
