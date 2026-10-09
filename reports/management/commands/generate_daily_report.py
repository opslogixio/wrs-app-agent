from django.core.management.base import BaseCommand
from accounts.models import Dealership
from datetime import date, timedelta
from reports.views import update_daily_report_database

class Command(BaseCommand):
    help = "python3 manage.py generate_daily_report"

    def handle(self, *args, **kwargs):
        # Example: generate a report for each dealership
        dealerships = Dealership.objects.all()
        report_type = "Daily Report"
        #start = date.today()
        start = date.today() - timedelta(days=1)
        
        for dealership in dealerships:
            dealership_id = dealership.id
            report = update_daily_report_database(dealership_id, start)
            # You can add logic to save the report to the database or send it via email
            print(f"Generated report for dealership {dealership.name}")
            print("Here is the report!", report)

        
