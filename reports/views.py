from pathlib import Path
from django.db import transaction
from django.http import FileResponse, Http404
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.urls import reverse
from decorators.access import (in_group_required, accessible_dealerships, get_dealership,
    claims_for_user, lines_for_user, positive_id, safe_return_url, is_wrs_admin, DealershipAccessMixin)
from django.shortcuts import render, get_object_or_404, redirect
from datetime import date, datetime, timedelta
from django.http import HttpResponseRedirect, HttpResponse, HttpResponseBadRequest, JsonResponse, HttpResponseNotAllowed
from django.db.models import Prefetch
from django.views.generic import View, TemplateView
from django.template.loader import get_template, render_to_string
from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import user_passes_test
from django.forms import modelformset_factory
from django.core.paginator import Paginator
from io import BytesIO
import json, os
from xhtml2pdf import pisa
from django.utils import timezone
from accounts.models import Dealership, CustomUser
from claim.models import LineTable, Journal, Claim, RoStatus, Status, ClaimType, Discrepancy
from .models import HistoricalClaim, HistoricalLineTable, HistoricalJournal
from claim.views import get_claim_status_totals
from reports.forms import ReportsForm, ArchiveDailyReportsForm, DiscrepancyReportsForm
from reports.models import HistoricalClaim, HistoricalLineTable, HistoricalJournal
from django.conf import settings

## Function to check group for permissions ##########################################


def update_daily_report_database(dealership_id, start):
    #user = CustomUser.objects.filter(id__in=[2, 14])
    dealership = Dealership.objects.get(id=dealership_id)


    # Fetch LineTable records
    line_tables = LineTable.objects.filter(dealership_id=dealership_id, modified_date=start).order_by('claim__repair_order')

    # Extract relevant ForeignKey values from line_tables
    claim_status_names = line_tables.values_list('claim_status__name', flat=True).distinct()
    ro_status_names = line_tables.values_list('claim__ro_status__name', flat=True).distinct()
    claim_type_names = line_tables.values_list('claim_type__name', flat=True).distinct()
    discrepancy_ids = line_tables.values_list('discrepancy_id', flat=True).distinct()

    # Fetch only relevant ForeignKey instances
    statuses = {status.name: status for status in Status.objects.filter(name__in=claim_status_names)}
    ro_statuses = {status.name: status for status in RoStatus.objects.filter(name__in=ro_status_names)}
    claim_types = {ctype.name: ctype for ctype in ClaimType.objects.filter(name__in=claim_type_names)}
    discrepancies = {disc.id: disc for disc in Discrepancy.objects.filter(id__in=discrepancy_ids)}
    dealership = Dealership.objects.get(id=dealership_id)

    # Grouped data by repair_order
    repair_order_data = {}

    for line in line_tables:
        repair_order = line.claim.repair_order
        claim_status_name = line.claim_status.name
        ro_status_name = line.claim.ro_status.name

        #print("This is the trifecta", repair_order, claim_status_name, ro_status_name)

        # Skip records with a claim_status of 'New' or 'Rework'
        if claim_status_name in ('New', 'Rework'):
            continue

        if repair_order not in repair_order_data:
            repair_order_data[repair_order] = {
                'lines': [],
                'ro_status': ro_statuses.get(ro_status_name),
            }

        # Add line details to the repair_order group
        repair_order_data[repair_order]['lines'].append({
            'line_table_id': line.id,
            'line_num': line.line_num,
            'claim_type': claim_types.get(line.claim_type.name) if line.claim_type else None,
            'claim_total': line.claim_total,
            'claim_status': statuses.get(line.claim_status.name),
            'start_date': line.start_date,
            'paid_date': line.paid_date,
            'discrepancy': discrepancies.get(line.discrepancy_id) if line.discrepancy_id else None,
        })

    # Process grouped repair_order data
    report = []

    for repair_order, data in repair_order_data.items():
        ro_status = data['ro_status']
        lines = data['lines']

        # Create or update HistoricalClaim entry
        historical_claim, created = HistoricalClaim.objects.update_or_create(
            repair_order=repair_order,
            dealership=dealership,
            created_date=start,
            defaults={'ro_status': ro_status}
        )

        for line_data in lines:
            # Create or update HistoricalLineTable entry

            historical_line, line_created = HistoricalLineTable.objects.update_or_create(
                claim=historical_claim,
                line_num=line_data['line_num'],
                defaults={
                    'claim_type': line_data['claim_type'],
                    'claim_total': line_data['claim_total'],
                    'claim_status': line_data['claim_status'],
                    'dealership': dealership,
                    'start_date': line_data['start_date'],
                    'paid_date': line_data['paid_date'],
                    'discrepancy': line_data['discrepancy'],
                    'created_date': timezone.now() - timedelta(days=1)
                }
            )
            # Fetch comments specifically associated with this line
            line_journals = Journal.objects.filter(
                line_id=line_data['line_table_id'],
                user_id__in=[2, 14],
                created_date=start
            )
            #).values_list('comment', flat=True)

            #print(f"Comments for Line {line_data['line_num']}: {list(line_comments)}")

            # Create HistoricalJournal entries for this line
            for journal in line_journals:
                HistoricalJournal.objects.get_or_create(
                    line=historical_line,
                    user=journal.user,
                    comment=journal.comment,
                    comment_date=journal.created_date
                    #created_date=timezone.now() - timedelta(days=1)
                )

        # Add to report
        report.append({
            'repair_order': repair_order,
            'line_data': lines,
        })

    return report

class ReportService:
    @staticmethod
    def generate_daily_report(dealership_id, start_date):
        lines = list(ReportService.daily_lines(start_date).filter(
            dealership_id=dealership_id, claim__dealership_id=dealership_id,
        ))
        grouped = {}
        for line in lines:
            grouped.setdefault(line.claim_id, []).append(line)
        report = []
        fields = {
            'Paid': 'paid_claim_total',
            'Requires Attention': 'requires_attention_claim_total',
            'Pending': 'pending_claim_total',
            'Rejected': 'rejected_claim_total',
            'Not Submitted': 'not_submitted_claim_total',
        }
        for claim_id, claim_lines in grouped.items():
            if not any(line.claim_status and line.claim_status.name not in {'New', 'Rework'} for line in claim_lines):
                continue
            item = {field: 0 for field in fields.values()}
            item['repair_order'] = claim_lines[0].claim.repair_order
            item['line_data'] = ReportService.get_line_data(claim_id, start_date, lines=claim_lines)
            for line in claim_lines:
                field = fields.get(line.claim_status.name if line.claim_status else '')
                if field:
                    item[field] += line.claim_total or 0
            report.append(item)
        return report

    @staticmethod
    def daily_lines(start_date):
        comments = Journal.objects.filter(user_id__in=[2, 14], created_date=start_date).order_by('created_date', 'pk')
        return (LineTable.objects.filter(modified_date=start_date)
            .select_related('claim', 'claim__ro_status', 'claim_status', 'claim_type', 'discrepancy')
            .prefetch_related(Prefetch('journal_set', queryset=comments, to_attr='report_comments'))
            .order_by('claim__repair_order', 'claim_id', 'id'))

    @staticmethod
    def get_line_data(claim_id, start_date, lines=None):
        if lines is None:
            lines = ReportService.daily_lines(start_date).filter(claim_id=claim_id)
        result = []
        for line in lines:
            comments = [journal.comment for journal in line.report_comments]
            result.append({'line': line, 'comments': comments, 'comment_count': len(comments)})
        return result
    
    @staticmethod
    def generate_archived_report(dealership_id, start_date):
        # Query HistoricalClaim by created_date (>= start_date)
        claims = HistoricalClaim.objects.filter(dealership_id=dealership_id, created_date__date=start_date).select_related('ro_status').prefetch_related(
            Prefetch(
                'historicallinetable_set', 
                queryset=HistoricalLineTable.objects.select_related('claim_status').prefetch_related(
                    Prefetch('historicaljournal_set', queryset=HistoricalJournal.objects.all(), to_attr='journals')
                ),
                to_attr='lines'
            )
        )
        #print("This is a historical claim", claims)

        # Create a dictionary to store results
        result = []
        
        # Loop through each claim (repair order)
        for claim in claims:
            claim_data = {
                'repair_order': claim.repair_order,
                'ro_status': claim.ro_status.name if claim.ro_status else '',
                'lines': []
            }
            
            # Loop through associated lines (HistoricalLineTable)
            for line in claim.lines:
                line_data = {
                    'line_num': line.line_num,
                    'claim_total': line.claim_total,
                    'claim_status': line.claim_status,
                    'comments': []
                }

                # Loop through associated comments (HistoricalJournal)
                for journal in line.journals:
                    line_data['comments'].append(journal.comment)

                # Append line data to the claim
                claim_data['lines'].append(line_data)

            # Append claim data to result list
            result.append(claim_data)

        return result
    
    @staticmethod
    def generate_discrepancy_report(dealership_id, start_date, end_date):
        # Query claims that have discrepancies within the date range
        # Filter LineTable objects by 'modified_date' within the date range and related to the given dealership
        discrepancy_lines = LineTable.objects.filter(
            claim__dealership=dealership_id,  # Ensure the claim belongs to the dealership
            modified_date__range=(start_date, end_date),  # Filter lines within the date range
            discrepancy__isnull=False  # Ensure there is a discrepancy
        ).select_related('claim', 'discrepancy')

        for line in discrepancy_lines:
            if line.discrepancy:
                line.total_discrepancy = ReportService.calculate_line_total(line.discrepancy)

        

        return discrepancy_lines
    
    @staticmethod
    def calculate_line_total(discrepancy):
        """Calculate the total for a discrepancy by summing its fields that have data."""
        total = 0
        fields = ['labor', 'parts', 'maint', 'core', 'rental', 'sublet', 'other']
        for field in fields:
            value = getattr(discrepancy, field, 0)  # Get the field value, default to 0 if None
            if value:  # Only sum if the value is not None or 0
                total += value
        return total
    
    @staticmethod
    def generate_ra_report(dealership_id, filter_request):
        ninety_days_ago = date.today() - timedelta(days=90)
        today = date.today()

        try:
            dealership = get_object_or_404(Dealership, id=dealership_id)

            # Filter logic based on 'filter_request'
            if filter_request == 'Aging':
                queryset = Claim.objects.filter(
                    linetable__claim_status__name='Requires Attention',
                    linetable__dealership_id=dealership_id, dealership=dealership,
                    linetable__start_date__lte=ninety_days_ago
                ).distinct().select_related('ro_status').prefetch_related('claim_tag',
                    Prefetch('linetable_set', queryset=LineTable.objects.filter(dealership_id=dealership_id).select_related('claim_status', 'claim_type').prefetch_related(Prefetch('journal_set', queryset=Journal.objects.order_by('-created_date', '-pk'))))
                )
            else:
                claim_status_obj = Status.objects.get(name=filter_request)
                queryset = Claim.objects.filter(
                    linetable__claim_status=claim_status_obj,
                    linetable__dealership_id=dealership_id, dealership=dealership
                ).distinct().select_related('ro_status').prefetch_related('claim_tag',
                    Prefetch('linetable_set', queryset=LineTable.objects.filter(dealership_id=dealership_id).select_related('claim_status', 'claim_type').prefetch_related(Prefetch('journal_set', queryset=Journal.objects.order_by('-created_date', '-pk'))))
                )

        except (Status.DoesNotExist, Dealership.DoesNotExist):
            queryset = Claim.objects.none()

        claim_data = []
        for claim in queryset:
            claim_info = {'claim': claim, 'lines': []}
            for line in claim.linetable_set.all():
                claim_age = (today - line.start_date).days if line.start_date else None

                # Fetch associated comments from Journal
                #comments = list(line.journal_set.values_list('comment', flat=True))
                comments_list = list(line.journal_set.all())
                latest_comment = comments_list[0] if comments_list else None
                comments = latest_comment.comment if latest_comment else "No Comment"

                claim_info['lines'].append({
                    'line': line,
                    'claim_age': claim_age,
                    'comments': comments  # Add comments to the line info
                })
            claim_data.append(claim_info)

        # Separate bodyshop and non-bodyshop claims
        bodyshop_claims = [data for data in claim_data if any(tag.name == 'Bodyshop' for tag in data['claim'].claim_tag.all())]
        ra_claims = [data for data in claim_data if not any(tag.name == 'Bodyshop' for tag in data['claim'].claim_tag.all())]

        return {'bodyshop_claims': bodyshop_claims, 'ra_claims': ra_claims}



def get_claim_status_totals(dealership_id, start_date):
    from django.db.models import Sum
    totals = dict.fromkeys(['Paid', 'Requires_Attention', 'Pending', 'Rejected', 'Not_Submitted'], 0)
    rows = (LineTable.objects.filter(dealership_id=dealership_id, claim__dealership_id=dealership_id,
        modified_date=start_date).order_by().values('claim_status__name').annotate(total=Sum('claim_total')))
    for row in rows:
        key = (row['claim_status__name'] or '').replace(' ', '_')
        if key in totals:
            totals[key] = row['total'] or 0
    return {key: f'${value:,.2f}' for key, value in totals.items()}


@in_group_required('dealer-admin', 'wrs-admin')
@require_http_methods(['GET', 'POST'])
def export_to_pdf(request):
    """GET confirms parameters; CSRF-protected POST queues generation."""
    from .jobs import enqueue_report
    from .models import ReportJob
    params = request.POST if request.method == 'POST' else request.GET
    dealership = get_object_or_404(accessible_dealerships(request.user), name=params.get('dealership'))
    report_type = params.get('report_type')
    if report_type not in dict(ReportJob._meta.get_field('report_type').choices):
        return HttpResponseBadRequest('Invalid report type.')
    start_date = end_date = None
    try:
        if report_type != 'RA Report':
            start_date = datetime.strptime(params.get('start_date'), '%Y-%m-%d').date()
        if report_type == 'Discrepancy Report':
            end_date = datetime.strptime(params.get('end_date'), '%Y-%m-%d').date()
            if end_date < start_date:
                raise ValueError
    except (TypeError, ValueError):
        return HttpResponseBadRequest('Invalid report date range.')
    context = {'dealership': dealership.name, 'report_type': report_type,
        'start_date': start_date, 'end_date': end_date}
    if request.method == 'POST':
        try:
            job = enqueue_report(request.user, dealership, report_type, start_date, end_date)
        except ValueError as error:
            context['error'] = str(error)
            response = render(request, 'reports/export_request.html', context, status=429)
            response['Retry-After'] = '30'
            return response
        return redirect('reports:report-job', job_id=job.pk)
    return render(request, 'reports/export_request.html', context)


def accessible_report_job(request, job_id):
    from .models import ReportJob
    jobs = ReportJob.objects.filter(dealership__in=accessible_dealerships(request.user))
    if not is_wrs_admin(request.user):
        jobs = jobs.filter(requested_by=request.user)
    return get_object_or_404(jobs.select_related('dealership'), pk=job_id)


@in_group_required('dealer-admin', 'wrs-admin')
@require_GET
def report_job_status(request, job_id):
    from .jobs import report_path
    job = accessible_report_job(request, job_id)
    ready = job.state == 'completed' and report_path(job).is_file()
    download = reverse('reports:report-job-download', args=[job.pk]) if ready else None
    response = (JsonResponse({'state': job.state, 'label': job.get_state_display(),
        'error': job.error, 'download_url': download}) if request.GET.get('format') == 'json'
        else render(request, 'reports/export_status.html', {'job': job, 'download_url': download}))
    response['Cache-Control'] = 'private, no-store'
    return response


@in_group_required('dealer-admin', 'wrs-admin')
@require_GET
def download_report_job(request, job_id):
    from .jobs import report_path
    job = accessible_report_job(request, job_id)
    if job.state != 'completed':
        raise Http404
    path = report_path(job)
    if not path.is_file():
        raise Http404
    response = FileResponse(path.open('rb'), as_attachment=True, filename=f'report-{job.pk}.pdf', content_type='application/pdf')
    response['Cache-Control'] = 'private, no-store'
    return response


def get_repair_orders_by_date(dealership_id, start_date): # THIS IS NO LONGER USED ----------------------------------------
    # Query HistoricalClaim by created_date (>= start_date)
    claims = HistoricalClaim.objects.filter(dealership_id=dealership_id, created_date__date=start_date).select_related('ro_status').prefetch_related(
        Prefetch(
            'historicallinetable_set', 
            queryset=HistoricalLineTable.objects.select_related('claim_status').prefetch_related(
                Prefetch('historicaljournal_set', queryset=HistoricalJournal.objects.all(), to_attr='journals')
            ),
            to_attr='lines'
        )
    )

    # Create a dictionary to store results
    result = []
    
    # Loop through each claim (repair order)
    for claim in claims:
        claim_data = {
            'repair_order': claim.repair_order,
            'ro_status': claim.ro_status.name if claim.ro_status else '',
            'lines': []
        }

        # Loop through associated lines (HistoricalLineTable)
        for line in claim.lines:
            line_data = {
                'line_num': line.line_num,
                'claim_total': line.claim_total,
                'claim_status': line.claim_status,
                'comments': []
            }

            # Loop through associated comments (HistoricalJournal)
            for journal in line.journals:
                line_data['comments'].append(journal.comment)

            # Append line data to the claim
            claim_data['lines'].append(line_data)

        # Append claim data to result list
        result.append(claim_data)

    return result

@in_group_required('dealer-admin', 'wrs-admin')
@require_POST
@transaction.atomic
def update_ro_status(request):
    try:
        data = json.loads(request.body)
        if not isinstance(data, dict):
            raise ValueError
        claim_ids = data.get('claim_ids')
        if not isinstance(claim_ids, list) or not 1 <= len(claim_ids) <= 200:
            raise ValueError
        if any(type(value) is not int or value <= 0 for value in claim_ids):
            raise ValueError
        status_name = data.get('ro_status')
        if not isinstance(status_name, str) or not status_name:
            raise ValueError
    except (ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({'success': False, 'error': 'Invalid claim IDs or status.'}, status=400)
    ro_status = get_object_or_404(RoStatus, name=status_name)
    claims = list(claims_for_user(request.user).select_for_update().filter(pk__in=claim_ids))
    if len(claims) != len(set(claim_ids)):
        raise Http404
    for claim in claims:
        claim.ro_status = ro_status
        # Keep save signals so audit logging remains complete.
        claim.save(update_fields=['ro_status', 'modified_date'])
    return JsonResponse({'success': True})


@method_decorator(in_group_required('dealer-admin', 'wrs-admin'), name='dispatch')
class Reports(DealershipAccessMixin, TemplateView):

    template_name = 'reports/reports.html'
  
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        dealership_id = self.kwargs.get('dealership_id') or self.request.GET.get('dealership_id')
        dealership = get_object_or_404(accessible_dealerships(self.request.user), id=dealership_id)
        context['dealership'] = dealership.name
        context['dealerships'] = accessible_dealerships(self.request.user)
        user = self.request.user
        is_superuser = user.is_superuser
        context['is_superuser'] = is_superuser
        current_date = date.today()
        #context['start'] = current_date.strftime('%d %b, %Y')
        yesterday = date.today() - timedelta(days=1)
        context['start'] = yesterday.strftime('%d %b, %Y')
        context['start_date'] = current_date.strftime('%d %b, %Y')
        context['end_date'] = current_date.strftime('%d %b, %Y')

        form = ReportsForm(initial={
                'dealership': context['dealership'],
                'start': context['start'],
                #'start_date': context['start_date'],
                #'end_date': context['end_date'],
                'dealership_id': dealership_id,
            })
        
        if 'dealership' in form.fields and hasattr(form.fields['dealership'], 'queryset'):
            form.fields['dealership'].queryset = accessible_dealerships(self.request.user)
        context['form'] = form
        return context
    
@method_decorator(in_group_required('dealer-admin', 'wrs-admin'), name='dispatch')
class DailyReportsView(DealershipAccessMixin, View):
    template_name = 'reports/dailyreportsview.html'

    def get_context_data(self, **kwargs):
        context = {}
        user = self.request.user
        context['is_superuser'] = user.is_superuser
        return context

    def get(self, request, *args, **kwargs):
        dealership_id = kwargs.get('dealership_id')
        dealership = get_object_or_404(accessible_dealerships(self.request.user), pk=dealership_id)
        start_date = timezone.localdate()

        report = ReportService.generate_daily_report(dealership.id, start_date)

        context = self.get_context_data(**kwargs)
        if not report:
            context.update({
                'message': "There is no daily report as of right now, check back later",
                'start_date': start_date.strftime('%Y-%m-%d'),
                'dealership': dealership,
                'report_type': "Daily Report",
            })
        else:
            context.update({
                'report': report,
                'start_date': start_date.strftime('%Y-%m-%d'),
                'dealership': dealership,
                'report_type': "Daily Report",
            })

        return render(request, self.template_name, context)

@method_decorator(in_group_required('dealer-admin', 'wrs-admin'), name='dispatch')
class ArchiveDailyReportsView(View):
    form_class = ArchiveDailyReportsForm
    template_name = 'reports/archivedailyreportsview.html'

    def get(self, request):
        form = self.form_class()
        return render(request, self.template_name, {'form': form})

    def post(self, request):
        form = self.form_class(request.POST)
        if form.is_valid():
            # Process the data in form.cleaned_data
            dealership = form.cleaned_data['dealership']
            dealership = get_object_or_404(accessible_dealerships(self.request.user), name=dealership)
            dealership_id = dealership.id

            report_type = form.cleaned_data['report_type']
            start = form.cleaned_data['start']
            start_date = start
            start_date_path = start_date.strftime("%Y/%m/%d")
            dealership_slug = dealership.name.replace(" ", "_")
            relative_path = f"{dealership_slug}/{start_date_path}/{dealership_slug}-daily-report-{start_date}.pdf"
            pdf_url = reverse("reports:download-report", kwargs={"relative_path": relative_path})
            pdf_exists = os.path.exists(
                Path(settings.REPORT_ROOT) / relative_path
            )
            #start_date = datetime.strptime(start, '%d %b, %Y').date()
            #start_date = datetime.strptime(start, '%Y-%m-%d').date()
            #report = get_repair_orders_by_date(dealership_id, start_date)
            report = ReportService.generate_archived_report(dealership.id, start_date)
            if not report:
                context = { 
                    'message': "There is no report data for this date",
                    'dealership': dealership,
                    'report_type': "Archived Report",
                    'start_date': start_date.strftime('%Y-%m-%d'),
                }
            else:
                context = { 
                    'report': report,
                    'dealership': dealership,
                    'pdf_url': pdf_url,
                    'pdf_exists': pdf_exists,
                    'report_type': "Archived Report",
                    'start_date': start_date.strftime('%Y-%m-%d'),
                }

            return render(request, self.template_name, context)
        else:
            return HttpResponse("Invalid form data")

@method_decorator(in_group_required('dealer-admin', 'wrs-admin'), name='dispatch')        
class OpenClaimsReportView(DealershipAccessMixin, View):
    template_name = 'reports/openreportsview.html'

    def get_context_data(self, **kwargs):
        # Context setup
        context = {}
        
        dealership_id = self.kwargs.get('dealership_id') or self.request.GET.get('dealership_id')
        dealership = get_object_or_404(accessible_dealerships(self.request.user), id=dealership_id)

        # Get the 'Open' ro_status instance
        open_status = get_object_or_404(RoStatus, name='Open')
        
        # Query all claims where ro_status is 'Open'
        # List of statuses to exclude
        excluded_statuses = ['New', 'Pending', 'Requires Attention', 'Rework']

        # Exclude claims that have any line with one of the excluded statuses
        open_claims = Claim.objects.filter(
                dealership_id=dealership,
                ro_status=open_status
            ).exclude(
                id__in=Claim.objects.filter(
                    linetable__claim_status__name__in=excluded_statuses
                ).values('id')  # Get all claims that have lines with excluded statuses
            )
        
        # Pass the open claims and report type to the template context
        context['open_claims'] = open_claims
        context['report_type'] = "Open Claims"
        context['dealership'] = dealership
        context['dealership_id'] = dealership_id
        
        return context

    def get(self, request, *args, **kwargs):
        # Get the context
        context = self.get_context_data(**kwargs)
        
        # Render the template with the context
        return render(request, self.template_name, context)

@method_decorator(in_group_required('dealer-admin', 'wrs-admin'), name='dispatch')
class DiscrepancyReportView(View):
    form_class = DiscrepancyReportsForm
    template_name = 'reports/discrepancyreportsview.html'

    def get_context_data(self, **kwargs):
        # Context setup
        context = {}
        dealership_id = self.kwargs.get('dealership_id') or self.request.GET.get('dealership_id')
        dealership = get_object_or_404(accessible_dealerships(self.request.user), id=dealership_id)

        context['report_type'] = "Discrepancy Report"
        context['dealership'] = dealership
        return context

    #def calculate_line_total(self, discrepancy):
    #    """Calculate the total for a discrepancy by summing its fields that have data."""
    #    total = 0
    #    fields = ['labor', 'parts', 'maint', 'core', 'rental', 'sublet', 'other']
    #    for field in fields:
    #        value = getattr(discrepancy, field, 0)  # Get the field value, default to 0 if None
    #        if value:  # Only sum if the value is not None or 0
    #            total += value
    #    return total
    
    def post(self, request):
        form = self.form_class(request.POST)
        if form.is_valid():
            # Process the data in form.cleaned_data
            dealership = form.cleaned_data['dealership']
            dealership = get_object_or_404(accessible_dealerships(self.request.user), id=dealership)
            dealership_id = dealership.id

            # Get the start and end date from the form
            start_date = form.cleaned_data['start_date']
            end_date = form.cleaned_data['end_date']

            report = ReportService.generate_discrepancy_report(dealership.id, start_date, end_date)

            # Query claims that have discrepancies within the date range
            # Filter LineTable objects by 'modified_date' within the date range and related to the given dealership
            #discrepancy_lines = LineTable.objects.filter(
            #    claim__dealership=dealership,  # Ensure the claim belongs to the dealership
            #    modified_date__range=(start_date, end_date),  # Filter lines within the date range
            #    discrepancy__isnull=False  # Ensure there is a discrepancy
            #).select_related('claim', 'discrepancy')

            #for line in discrepancy_lines:
            #    if line.discrepancy:
            #        line.total_discrepancy = self.calculate_line_total(line.discrepancy)

            # Prepare the report data
            #if not discrepancy_lines.exists():
            if not report:
                context = {
                    'message': "There is no report data for this date range.",
                    'dealership': dealership,
                    'report_type': "Discrepancy Report",
                    'start_date': start_date,
                    'end_date': end_date,
                }
            else:
                context = {
                    'discrepancy_lines': report,
                    'dealership': dealership,
                    'report_type': "Discrepancy Report",
                    'start_date': start_date,
                    'end_date': end_date,
                }

            return render(request, self.template_name, context)
        else:
            return HttpResponse("Invalid form data")
            

    def get(self, request, *args, **kwargs):
        # Get the context
        context = self.get_context_data(**kwargs)
        form = self.form_class()
        if 'dealership' in form.fields and hasattr(form.fields['dealership'], 'queryset'):
            form.fields['dealership'].queryset = accessible_dealerships(self.request.user)
        context['form'] = form
        # Render the template with the context
        return render(request, self.template_name, context)

@method_decorator(in_group_required('dealer-admin', 'wrs-admin'), name='dispatch')
class RaReportView(DealershipAccessMixin, View):
    model = Claim
    template_name = 'reports/ra_reportsview.html'
    context_object_name = 'ra_claim_queue'
    bodyshop = False

    def get_context_data(self, **kwargs):
        context = {}
        filter_request = self.kwargs.get('filter_request')
        dealership_id = self.request.GET.get('dealership_id')
        dealership = get_object_or_404(accessible_dealerships(self.request.user), id=dealership_id)
        user = self.request.user

        # Use ReportService to generate the report
        filtered_claims = ReportService.generate_ra_report(dealership_id, filter_request)

        context['claim_status'] = filter_request
        context['user_groups'] = user.groups.all()
        context['dealership'] = dealership
        context['dealership_id'] = dealership_id
        context['bodyshop'] = self.bodyshop
        context['bodyshop_claims'] = filtered_claims['bodyshop_claims']
        context['ra_claims'] = filtered_claims['ra_claims']
        context['report_type'] = "RA Report"
        
        return context

    def get(self, request, *args, **kwargs):
        # Use the get method to render the template with context
        context = self.get_context_data(**kwargs)
        return render(request, self.template_name, context)


# HISTORICAL UPDATE AND DELETE
# Decorator to check if the user belongs to a specific group

@in_group_required('wrs-admin')
def historical_claim_view(request):
    ClaimFormSet = modelformset_factory(HistoricalClaim, fields=('repair_order', 'dealership', 'ro_status', 'created_date'), extra=0)
    
    if request.method == 'POST':
        formset = ClaimFormSet(request.POST)
        if formset.is_valid():
            formset.save()
            return redirect('historicalclaim-list')
    else:
        formset = ClaimFormSet()

    return render(request, 'reports/historicalclaim.html', {'formset': formset})

@in_group_required('wrs-admin')
def historical_linetable_view(request):
    LineTableFormSet = modelformset_factory(HistoricalLineTable, fields=('claim', 'line_num', 'claim_type', 'claim_total', 'claim_status', 'dealership', 'start_date', 'paid_date', 'compliant', 'discrepancy'), extra=0)
    
    if request.method == 'POST':
        formset = LineTableFormSet(request.POST)
        if formset.is_valid():
            formset.save()
            return redirect('historicallinetable-list')
    else:
        formset = LineTableFormSet()

    return render(request, 'reports/historicallinetable.html', {'formset': formset})

@in_group_required('wrs-admin')
def historical_journal_view(request):
    JournalFormSet = modelformset_factory(HistoricalJournal, fields=('comment', 'line', 'user'), extra=0)
    
    # Fetch all records
    historical_journals = HistoricalJournal.objects.all().order_by('id')  # Adjust ordering as needed

    # Paginate the records (e.g., 50 records per page)
    paginator = Paginator(historical_journals, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Create a formset only for the current page
    if request.method == 'POST':
        formset = JournalFormSet(request.POST, queryset=page_obj.object_list)
        if formset.is_valid():
            formset.save()
            return redirect('historicaljournal-list')
    else:
        formset = JournalFormSet(queryset=page_obj.object_list)

    return render(request, 'reports/historicaljournal.html', {'formset': formset, 'page_obj': page_obj})

# View the PDF files per dealership
@in_group_required('wrs-admin')
def list_report_files(request):
    base_dir = settings.REPORT_ROOT
    if not Path(base_dir).is_dir():
        return render(request, 'reports/report_file_browser.html', {'folder_structure': []})

    folder_structure = []

    for dealership in sorted(os.listdir(base_dir)):
        if dealership == 'jobs':
            continue
        dealership_path = os.path.join(base_dir, dealership)
        if os.path.isdir(dealership_path):
            years = []
            for year in sorted(os.listdir(dealership_path)):
                year_path = os.path.join(dealership_path, year)
                if os.path.isdir(year_path):
                    months = []
                    for month in sorted(os.listdir(year_path)):
                        month_path = os.path.join(year_path, month)
                        if os.path.isdir(month_path):
                            days = []
                            for day in sorted(os.listdir(month_path)):
                                day_path = os.path.join(month_path, day)
                                if os.path.isdir(day_path):
                                    files = sorted([
                                        f for f in os.listdir(day_path)
                                        if f.endswith('.pdf')
                                    ])
                                    days.append({
                                        'day': day,
                                        'files': files,
                                        'path': f'{dealership}/{year}/{month}/{day}/'
                                    })
                            months.append({'month': month, 'days': days})
                    years.append({'year': year, 'months': months})
            folder_structure.append({'dealership': dealership, 'years': years})

    return render(request, 'reports/report_file_browser.html', {
        'folder_structure': folder_structure
    })


@in_group_required('dealer-admin', 'wrs-admin')
@require_GET
def download_report(request, relative_path):
    root = Path(settings.REPORT_ROOT).resolve()
    path = (root / relative_path).resolve()
    if not path.is_relative_to(root) or path.suffix.lower() != '.pdf' or not path.is_file():
        raise Http404
    folder = Path(relative_path).parts[0]
    if folder == 'jobs':
        raise Http404
    # Legacy filenames use dealership names; ambiguous folder names fail closed.
    matches = [dealer for dealer in Dealership.objects.all() if dealer.name.replace(' ', '_') == folder]
    if len(matches) != 1:
        raise Http404
    get_dealership(request.user, matches[0].pk)
    response = FileResponse(path.open('rb'), as_attachment=True, filename=path.name, content_type='application/pdf')
    response['Cache-Control'] = 'private, no-store'
    return response


@in_group_required('dealer-admin', 'wrs-admin')
@require_GET
def report_jobs(request):
    from .models import ReportJob
    jobs = (ReportJob.objects.filter(requested_by=request.user,
        dealership__in=accessible_dealerships(request.user)).select_related('dealership').order_by('-created_at', '-id'))
    page = Paginator(jobs, 25).get_page(request.GET.get('page'))
    response = render(request, 'reports/export_list.html', {'page_obj': page})
    response['Cache-Control'] = 'private, no-store'
    return response
