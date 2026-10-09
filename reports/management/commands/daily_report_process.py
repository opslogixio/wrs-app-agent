from django.core.management.base import BaseCommand
from reports.utils import generate_daily_pdf
from claim.models import Dealership
from datetime import date, timedelta
import os

class Command(BaseCommand):
    help = 'Generate and save daily report PDFs into nested dealership folders by date'

    def handle(self, *args, **options):
        #today = date.today()
        today = date.today() - timedelta(days=1)
        output_dir = 'static/daily-report-pdf'

        generate_daily_pdf(output_dir, start_date=today)
        self.stdout.write(self.style.SUCCESS("Daily PDFs generated and saved."))
