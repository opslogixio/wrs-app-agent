import logging
from django.template.loader import render_to_string
from xhtml2pdf import pisa
from io import BytesIO
from datetime import date, datetime
import os
from django.core.mail import EmailMessage, get_connection
from .models import Dealership, CustomUser
from reports.views import ReportService, get_claim_status_totals
from reports.jobs import local_asset

logger = logging.getLogger(__name__)

def generate_daily_pdf(output_dir, start_date=None):
    today = start_date or date.today()
    print(f"[Starting Report Run] Generating daily report for {today}")
    #today = datetime.strptime(start_date_request, '%Y-%m-%d').date()
    dealerships = Dealership.objects.all()
    
    # Setup AWS SES connection
    connection = get_connection(
        backend='django.core.mail.backends.smtp.EmailBackend',
        host='email-smtp.us-east-1.amazonaws.com', # update region if different
        port=587,
        username=os.environ['SES_SMTP_USERNAME'],
        password=os.environ['SES_SMTP_PASSWORD'],
        use_tls=True
    )

    for dealership in dealerships:
        report = ReportService.generate_daily_report(dealership.id, today)

        # Lets skip if there is no report
        if not report:
            print(f"[SKIP] No report data for {dealership.name} on {today}")
            continue

        claim_status_totals = get_claim_status_totals(dealership.id, today)

        context = {
            'report': report,
            'dealership': dealership.name,
            'report_type': "Daily Report",
            'claim_status_totals': claim_status_totals,
            'start_date': today.isoformat(),
        }

        html = render_to_string('reports/report_pdf.html', context)

        # Create nested output path: output_dir/<dealership>/<YYYY>/<MM>/<DD>/
        nested_dir = os.path.join(
            output_dir,
            dealership.name.replace(' ', '_'),
            str(today.year),
            f"{today.month:02d}",
            f"{today.day:02d}"
        )
        os.makedirs(nested_dir, exist_ok=True)

        filename = f"{dealership.name.replace(' ', '_')}-daily-report-{today}.pdf"
        output_path = os.path.join(nested_dir, filename)

        with open(output_path, "wb") as f:
            pisa_status = pisa.CreatePDF(html, dest=f, link_callback=local_asset)

        if pisa_status.err:
            print(f"[ERROR] Failed to generate PDF for {dealership.name}")
        else:
            print(f"[SUCCESS] PDF saved: {output_path}")

        users = CustomUser.objects.filter(dealership=dealership, receive_daily_report=True)

        for user in users:
            recipient_email = user.daily_report_email or user.email
            if not recipient_email:
                print(f"[WARNING] No email address found for user {user} at dealership {dealership.name}")
                continue


            email = EmailMessage(
                subject=f"{dealership.name} Daily Report - {today}",
                body=(
                    "Attached is your daily dealership report.\n\n"
                    "This email account is not monitored. Please DO NOT REPLY to this email.\n\n"
                    "(NOTE: The content of this email contains confidential information. "
                    "This information should not be shared or viewed by anyone other than the intended recipients. "
                    "If you received this email in error, please permanently delete the message, all of its contents "
                    "and notify the sender immediately.)"
                ),
                from_email='reports@warrantyrevenue.com',
                to=[recipient_email],
                reply_to=["ccausa@warrantyrevenue.com"],
                connection=connection
            )

            try:
                with open(output_path, 'rb') as pdf_file:
                    email.attach(filename, pdf_file.read(), 'application/pdf')
                email.send()
                print(f"[EMAIL SENT] Report sent to {recipient_email}")
                #logger.info(f"[EMAIL SENT] Report sent to chavez")
            except Exception as e:
                print(f"[ERROR] Failed to send email to {recipient_email}: {e}")
                #logger.error(f"[ERROR] Failed to send email to cchavez: {e}")

def test_email_delivery(
    to_email,
    subject="Test Email from Django",
    body=
        "Attached is your daily dealership report.\n\n"
        "This email account is not monitored. Please DO NOT REPLY to this email.\n\n"
        "(NOTE: The content of this email contains confidential information. "
        "This information should not be shared or viewed by anyone other than the intended recipients. "
        "If you received this email in error, please permanently delete the message, all of its contents "
        "and notify the sender immediately.)"

    ):
    """
    Send a test email using AWS SES SMTP credentials.
    Logs the success or failure of the attempt.
    """
    connection = get_connection(
        backend='django.core.mail.backends.smtp.EmailBackend',
        host='email-smtp.us-east-1.amazonaws.com',
        port=587,
        username=os.environ['SES_SMTP_USERNAME'],
        password=os.environ['SES_SMTP_PASSWORD'],
        use_tls=True
    )

    email = EmailMessage(
        subject=subject,
        body=body,
        from_email='reports@warrantyrevenue.com',
        to=[to_email],
        connection=connection
    )

    try:
        email.send()
        logger.info(f"[EMAIL SUCCESS] Test email sent to {to_email}")
        return True
    except Exception as e:
        logger.error(f"[EMAIL FAILED] Could not send test email to {to_email}: {e}")
        return False
