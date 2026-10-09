from core.dates import as_date, clean_datetime, datetime_input
from django.utils import timezone
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404
from django.conf import settings
from pathlib import Path
from .validators import validate_claim_file, ATTACHMENT_CONTENT_TYPES
from decorators.access import (in_group_required, accessible_dealerships, get_dealership,
    claims_for_user, lines_for_user, positive_id, safe_return_url, is_wrs_admin, DealershipAccessMixin)
from django.shortcuts import render, redirect, get_object_or_404
from django.forms.models import inlineformset_factory
from django.forms import modelformset_factory
from django.utils.decorators import method_decorator
from django.urls import reverse_lazy, reverse
from decimal import Decimal, InvalidOperation
from django.core.exceptions import ValidationError
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from datetime import date, datetime, timedelta
from django.utils.dateformat import DateFormat
from django.views.generic import View, FormView, CreateView, ListView, DetailView, TemplateView, UpdateView, DeleteView
from django.views.generic.edit import UpdateView
from django.views.decorators.http import require_POST, require_GET, require_http_methods
from django.http import HttpResponseRedirect, HttpResponse, HttpResponseBadRequest, JsonResponse, HttpResponseNotAllowed, Http404
from django.db.models import Q, OuterRef, Subquery, Count, Prefetch
from io import BytesIO
from xhtml2pdf import pisa
from collections import OrderedDict
from django.template.loader import get_template, render_to_string
from decorators.dealeraccess import user_has_dealership_access
from collections import defaultdict
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from django.db import transaction
from auditlog.models import AuditEvent
from .models import Claim, Journal, PdfFile, LineTable, ClaimType, Status, Dealership, Discrepancy, Tag, RoStatus, Event, CustomUser
from .forms import ClaimForm, JournalForm, PdfFileForm, ClaimUpdateForm, ClaimLineUpdateForm, ClaimLineUpdateForm, ReportsForm, DiscrepancyForm, LineUpdateForm

## Function to check group for permissions ##########################################


def is_superuser(user):
    return user.is_superuser

## VIEWS RELATE TO CLAIMS ##################################################  CLAIMS  ##########################################

#####################################################################################
# THIS HANDLES THE INITIAL CLAIM INPUT
#####################################################################################

@method_decorator(in_group_required('dealer-admin', 'wrs-admin'), name='dispatch')
#@method_decorator(user_passes_test(is_superuser) or in_group_required('Dealer Admin'), name='dispatch')
@method_decorator(transaction.atomic, name='post')
class ClaimFormView(DealershipAccessMixin, View):
    claim_form_class = ClaimForm
    journal_form_class = JournalForm
    pdffile_form_class = PdfFileForm
    template_name = 'claim/claim_form.html'

    def get(self, request, dealership_id):
        claim_form = self.claim_form_class()
        claim_form.fields['dealership'].queryset = accessible_dealerships(request.user).filter(pk=dealership_id)
        journal_form = self.journal_form_class()
        pdffile_form = self.pdffile_form_class()
        user = request.user
        dealerships = Dealership.objects.filter(id=dealership_id)
        tags = Tag.objects.all()
        return render(request, self.template_name, {
            'claim_form': claim_form,
            'journal_form': journal_form,
            'pdffile_form': pdffile_form,
            'dealerships': dealerships,
            'tags': tags,
            'adding_multiple': request.GET.get('add_another') == '1',
        })

    def post(self, request, dealership_id):
        action = request.POST.get('action', 'submit')
        if action not in {'submit', 'add_another'}:
            return HttpResponseBadRequest('Invalid submit action.')
        claim_form = self.claim_form_class(request.POST)
        claim_form.fields['dealership'].queryset = accessible_dealerships(request.user).filter(pk=dealership_id)
        journal_form = self.journal_form_class(request.POST)
        pdffile_form = self.pdffile_form_class(request.POST, request.FILES)
        user = request.user

        if claim_form.is_valid() and journal_form.is_valid() and pdffile_form.is_valid():
            # Create a new Claim
            claim = claim_form.save(commit=False)
            dealership = claim_form.cleaned_data['dealership'].id
            claim.dealership_id = dealership


            # Update the claim_tag in the Claim
            #claim.claim_tag = claim_form.cleaned_data['claim_tag']
            claim.ro_status = get_object_or_404(RoStatus, name='Open')
            claim.save()

            claim.claim_tag.set(claim_form.cleaned_data['claim_tag'])

            # Get the list of tags from the form cleaned_data
            tag_list = claim_form.cleaned_data['claim_tag']
            # Find the tag with the highest 'id' from the list
            if tag_list:
                highest_id_tag = max(tag_list, key=lambda tag: tag.id)
                # Pontential use if tags need to be None:
                # highest_id_tag = max(tag_list, default=None, key=lambda tag: tag.id) if tag_list else None
                initial_claim_type = highest_id_tag  # Set 'initial_type' to the tag with the highest 'id'
            else:
                initial_claim_type = None

            if initial_claim_type.name == 'Bodyshop':
             initial_claim_type = get_object_or_404(ClaimType, name='Repair')
            claim_type_init = get_object_or_404(ClaimType, name=initial_claim_type.name)
            # Create a new Journal entry associated with the Claim
            journal = journal_form.save(commit=False)
            journal_comment = journal_form.cleaned_data['comment']
            #print(journal_comment)
            journal.claim = claim
            journal.user = user
            journal.comment = journal_comment
            journal.save()

            # Create a new LineTable entry associated with the Claim
            line_table = LineTable.objects.create(
                claim=claim,
                dealership_id=dealership,
                claim_type=claim_type_init,
                claim_status=get_object_or_404(Status, name='New'),
            )

            # Handle uploaded PDF file
            pdf_file = pdffile_form.cleaned_data['pdf_file']

            if pdf_file:
                now = datetime.now()
                timestamp = now.strftime("%Y%m%d%H%M%S")
                pdf_filename = f"{timestamp}_{pdf_file.name}"

                #pdf_name = pdf_file.name
                PdfFile.objects.create(
                    pdf_name=pdf_filename,
                    pdf_file=pdf_file,
                    claim=claim
                )

            messages.success(request, f'Claim for repair order {claim.repair_order} was created.')
            if action == 'add_another':
                return redirect(reverse('claim:claim-form', args=[dealership_id]) + '?add_another=1')
            route = 'claim-update' if is_wrs_admin(user) else 'dealer-claim-update'
            return redirect(reverse('claim:' + route, args=[claim.pk, dealership_id]))

        else:

            dealerships = Dealership.objects.filter(id=dealership_id)
            tags = Tag.objects.all()
            return render(request, self.template_name, {
                'claim_form': claim_form,
                'journal_form': journal_form,
                'pdffile_form': pdffile_form,
                'dealerships': dealerships,
                'tags': tags,
                'adding_multiple': action == 'add_another' or request.GET.get('add_another') == '1',
            })

        #dealerships = Dealership.objects.filter(users=user)
        #tags = Tag.objects.all()
        #return render(request, self.template_name, {
        #    'claim_form': claim_form,
        #    'journal_form': journal_form,
        #    'pdffile_form': pdffile_form,
        #    'dealerships': dealerships,
        #    'tags': tags
        #})

#####################################################################################
# NOT USED
#####################################################################################

@method_decorator(in_group_required('dealer-admin', 'wrs-admin'), name='dispatch')
class ClaimListView(ListView):
    model = Claim
    template_name = 'claim/claim_list.html'
    context_object_name = 'claims'

    def get_queryset(self):
        # Get the current user's dealership_id
        dealership_id = self.kwargs.get('dealership_id')
        #dealership_id = self.request.user.dealership_id

        # Filter the claims based on the user's dealership_id
        queryset = super().get_queryset().filter(dealership_id=dealership_id)

        return queryset

#####################################################################################
# NOT USED
#####################################################################################

@method_decorator(in_group_required('dealer-admin', 'wrs-admin'), name='dispatch')
class ClaimDetailView(DetailView):
    model = Claim
    template_name = 'claim/claim_detail.html'
    context_object_name = 'claim'

#####################################################################################
# This only being used for 'rework' queue
#####################################################################################

class PaginatedClaimQueue(DealershipAccessMixin, ListView):
    """Paginate claims before loading their lines or splitting Bodyshop sections."""
    model = Claim
    paginate_by = 50
    section_name = 'other_claims'
    include_line_ages = False
    include_initial_comment = False

    def get_queryset(self):
        status = self.kwargs['filter_request']
        filters = {'linetable__claim_status__name': status}
        if status == 'Aging':
            filters = {
                'linetable__claim_status__name': 'Requires Attention',
                'linetable__start_date__date__lte': timezone.localdate() - timedelta(days=90),
            }
        lines = LineTable.objects.filter(
            dealership=self.authorized_dealership,
            **{key.removeprefix('linetable__'): value for key, value in filters.items()},
        ).select_related('claim_status', 'claim_type', 'discrepancy').order_by('pk')
        queryset = (Claim.objects.filter(dealership=self.authorized_dealership,
                linetable__dealership=self.authorized_dealership, **filters)
            .distinct().select_related('ro_status', 'dealership')
            .prefetch_related(Prefetch('linetable_set', queryset=lines), 'claim_tag')
            .order_by('-repair_order', '-pk'))
        if self.include_initial_comment:
            comment = (Journal.objects.filter(claim_id=OuterRef('pk'), line_id__isnull=True)
                .order_by('created_date', 'pk').values('comment')[:1])
            queryset = queryset.annotate(new_comment=Subquery(comment))
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        bodyshop, other = [], []
        tags = {}
        today = timezone.localdate()
        for claim in context['object_list']:
            claim_tags = list(claim.claim_tag.all())
            tags.update({tag.pk: tag for tag in claim_tags})
            item = claim
            if self.include_line_ages:
                item = {'claim': claim, 'lines': [
                    {'line': line, 'claim_age': (today - as_date(line.start_date)).days + 1 if line.start_date else None}
                    for line in claim.linetable_set.all()
                ]}
            target = bodyshop if any(tag.name == 'Bodyshop' for tag in claim_tags) else other
            target.append(item)
        query = self.request.GET.copy()
        query.pop('page', None)
        context.update({
            'claim_status': self.kwargs['filter_request'],
            'dealership': self.authorized_dealership,
            'dealership_id': self.authorized_dealership.pk,
            'is_wrs_admin': is_wrs_admin(self.request.user),
            'bodyshop': bool(bodyshop), 'bodyshop_claims': bodyshop,
            self.section_name: other, 'tags': list(tags.values()),
            'pagination_query': query.urlencode(), 'custom_pagination': True,
        })
        return context


@method_decorator(in_group_required('dealer-admin', 'wrs-admin'), name='dispatch')
class ClaimQueueListView(PaginatedClaimQueue):
    template_name = 'claim/claim_queue.html'
    context_object_name = 'claim_queue'


@method_decorator(in_group_required('dealer-admin', 'wrs-admin'), name='dispatch')
class NewClaimQueueListView(PaginatedClaimQueue):
    template_name = 'claim/new_claim_queue.html'
    context_object_name = 'new_claim_queue'
    section_name = 'new_claims'
    include_initial_comment = True


@method_decorator(in_group_required('dealer-admin', 'wrs-admin'), name='dispatch')
class RaClaimQueueListView(PaginatedClaimQueue):
    template_name = 'claim/ra_claim_queue.html'
    context_object_name = 'ra_claim_queue'
    section_name = 'ra_claims'
    include_line_ages = True


@method_decorator(in_group_required('dealer-admin', 'wrs-admin'), name='dispatch')
class PendingClaimQueueListView(PaginatedClaimQueue):
    template_name = 'claim/pending_claim_queue.html'
    context_object_name = 'pending_claim_queue'
    section_name = 'pending_claims'
    include_line_ages = True


@method_decorator(in_group_required('dealer-admin', 'wrs-admin'), name='dispatch')
class ReworkClaimQueueListView(PaginatedClaimQueue):
    template_name = 'claim/rework_claim_queue.html'
    context_object_name = 'rework_claim_queue'
    section_name = 'rework_claims'
    include_line_ages = True


@method_decorator(in_group_required('dealer-admin', 'wrs-admin'), name='dispatch') ##### NOT USED
class OpenRoQueueListView(ListView):
    model = Claim
    template_name = 'claim/open_ro_queue.html'
    context_object_name = 'open_ro_queue'
    bodyshop = False

    def get_queryset(self):
        dealership_id = self.request.GET.get('dealership_id')
        if not dealership_id:
            return Claim.objects.none()

        today = timezone.localdate()
        open_status = get_object_or_404(RoStatus, name='Open')

        dealership = get_object_or_404(accessible_dealerships(self.request.user), id=dealership_id)

        # Exclude claims with lines having excluded statuses
        excluded_statuses = ['New', 'Pending', 'Requires Attention', 'Rework']
        queryset = Claim.objects.filter(
            dealership_id=dealership.id,
            ro_status=open_status
        ).exclude(
            id__in=Claim.objects.filter(
                linetable__claim_status__name__in=excluded_statuses
            ).values_list('id', flat=True)
        )

        return queryset


    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        dealership_id = self.request.GET.get('dealership_id')
        dealership = get_object_or_404(accessible_dealerships(self.request.user), id=dealership_id)
        user = self.request.user

        # Add additional context
        context['user_groups'] = user.groups.all()
        context['dealership'] = dealership
        context['dealership_id'] = dealership_id
        context['open_ro_claims'] = self.get_queryset()

        return context

#####################################################################################
# FULL CLAIM VIEW
#####################################################################################

DEALER_RETURN_STATUSES = {'rejected', 'no warranty', 'not submitted'}


def dealer_status_choices(current):
    if current == 'requires attention':
        return {'rework', 'not submitted'}
    if current in DEALER_RETURN_STATUSES:
        return {current, 'rework'}
    if current == 'rework':
        return {'rework', 'no warranty', 'not submitted', 'rejected'}
    return set()


COMPLETION_DATE_REQUIRED_STATUSES = {'pending', 'requires attention'}


def line_update_error(request, line, message):
    """Keep entered values across validation redirects without persisting the line."""
    values = {key: request.POST[key] for key in (
        'line_num', 'claim_type', 'claim_status', 'claim_total', 'start_date', 'comment'
    ) if key in request.POST}
    if is_wrs_admin(request.user):
        values['compliant'] = request.POST.get('compliant') == 'on'
    request.session['line_edit_draft'] = {
        'claim_id': line.claim_id, 'line_id': line.pk, 'values': values,
    }
    messages.error(request, message)
    route = 'claim-update' if is_wrs_admin(request.user) else 'dealer-claim-update'
    url = reverse('claim:' + route, args=[line.claim_id, line.dealership_id])
    return redirect(url + f'#line_form_{line.pk}')


def line_edit_values(request, claim, queryset):
    draft = request.session.get('line_edit_draft', {})
    if draft.get('claim_id') == claim.pk:
        request.session.pop('line_edit_draft')
    else:
        draft = {}
    lines = list(queryset)
    for line in lines:
        line.edit_values = {
            'line_num': str(line.line_num or ''), 'claim_type': str(line.claim_type_id or ''),
            'claim_status': str(line.claim_status_id or ''),
            'claim_total': str(line.claim_total) if line.claim_total is not None else '',
            'start_date': datetime_input(line.start_date),
            'comment': '', 'compliant': bool(line.compliant),
        }
        if draft.get('line_id') == line.pk:
            line.edit_values.update(draft['values'])
    return lines


@method_decorator(in_group_required('wrs-admin'), name='dispatch')
class ClaimLineUpdateView(DealershipAccessMixin, UpdateView):
    model = Claim
    form_class = ClaimLineUpdateForm
    template_name = 'claim/claim_update.html'
    success_url = '/claim/claim-list/'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        claim = self.object
        user = self.request.user
        dealership_id = self.kwargs.get('dealership_id')
        dealership = get_object_or_404(accessible_dealerships(self.request.user), id=dealership_id)
        line_table = line_edit_values(self.request, claim,
            LineTable.objects.filter(claim=claim, dealership_id=dealership_id))
        reconciliation = LineTable.objects.filter(claim=claim, dealership_id=dealership_id, discrepancy__isnull=False).select_related('discrepancy')
        discrepancies = [line.discrepancy for line in reconciliation if line.discrepancy is not None]
        #journal = Journal.objects.filter(claim=claim)
        pdf_file = PdfFile.objects.filter(claim=claim)
        tags = claim.claim_tag.all()

        #######################################
        # Lets grab those events for the claim.
        #######################################
        audit_events = (
            AuditEvent.objects
            .filter(claim=claim)
            .select_related(
                'actor',
                'dealership',
                'claim',
                'line',
                'journal',
                'content_type',
            )
            .order_by('-occurred_at')
        )

        #journal = (
        #    Journal.objects
        #    .filter(claim=claim)
        #    .select_related('line')
        #    .order_by('line__line_num', 'created_date')
        #)

        #journal_by_line = defaultdict(list)

        #for entry in journal:
        #    if entry.line:
        #        journal_by_line[entry.line.line_num].append(entry)

        journal = (
            Journal.objects
            .filter(claim=claim)
            .select_related('line', 'user')
            .order_by('created_date', 'id')
        )

        journal_by_line = OrderedDict()
        journal_by_line['Claim Comment'] = []

        line_comments = defaultdict(list)

        for entry in journal:
            if entry.line and entry.line.line_num is not None:
                line_comments[entry.line.line_num].append(entry)
            else:
                journal_by_line['Claim Comment'].append(entry)

        for line_num in sorted(line_comments.keys()):
            journal_by_line[line_num] = line_comments[line_num]

        def calculate_line_total(discrepancy):
                """Calculate the total for a discrepancy by summing its fields that have data."""
                total = 0
                fields = ['labor', 'parts', 'maint', 'core', 'rental', 'sublet', 'other']
                for field in fields:
                    value = getattr(discrepancy, field, 0)  # Get the field value, default to 0 if None
                    if value:  # Only sum if the value is not None or 0
                        total += value
                return total

        for line in reconciliation:
            if line.discrepancy:
                line.total_discrepancy = calculate_line_total(line.discrepancy)




        context.update({
            'line_table': line_table,
            'journal': journal,
            'journal_by_line': dict(journal_by_line),
            'pdf_file': pdf_file,
            'audit_events': audit_events,
            'dealership': dealership,
            'created_date': claim.created_date,
            'claim_id': claim.id,
            'claim': claim,
            'discrepancy': reconciliation,
            'tags': tags,
            'start': timezone.localdate().strftime('%B %d, %Y'),
            'start_date': DateFormat(line_table[0].start_date).format('F d, Y') if line_table and line_table[0].start_date else None,
        })
        return context

    def form_valid(self, form):
        claim = form.save(commit=False)
        LineTableFormSet = inlineformset_factory(Claim, LineTable, form=LineUpdateForm, extra=0)
        formset = LineTableFormSet(self.request.POST, instance=claim)

        if form.is_valid() and formset.is_valid():
            # Update claim start_date
            start_date = self.request.POST.get('start_date')
            if start_date:
                claim.start_date = datetime.strptime(start_date, '%d %b, %Y').strftime('%Y-%m-%d')
            claim.save()

            # Save formset
            formset.save()

            # Update related models (Journal, PdfFile)
            journal_comment = form.cleaned_data.get('comment')
            pdf_name = form.cleaned_data.get('pdf_name')
            pdf_file = form.cleaned_data.get('pdf_file')

            journal = Journal.objects.filter(claim=claim).first()
            if journal and journal_comment:
                journal.comment = journal_comment
                journal.save()

            pdf_file_obj = PdfFile.objects.filter(claim=claim).first()
            if pdf_file_obj:
                pdf_file_obj.pdf_name = pdf_name
                pdf_file_obj.pdf_file = pdf_file
                pdf_file_obj.save()

            return HttpResponseRedirect(self.get_success_url())
        else:
            # Re-render the form with errors
            return self.render_to_response(self.get_context_data(form=form, formset=formset))

    def form_invalid(self, form):
        # Re-render the form with errors
        return self.render_to_response(self.get_context_data(form=form))

#####################################################################################
# Used to just update the claim. 'Edit Repair Order' from the Full claim view
#####################################################################################

@method_decorator(in_group_required('wrs-admin'), name='dispatch')
class UpdateClaim(UpdateView):
    model = Claim
    template_name = 'claim/update_claim.html'
    form_class = ClaimUpdateForm

    ClaimFormSet = modelformset_factory(Claim, form=ClaimForm, extra=0)

    def get_object(self, queryset=None):
        dealership = self.kwargs['dealership']
        repair_order = self.kwargs['repair_order']
        return get_object_or_404(claims_for_user(self.request.user), dealership__name=dealership, repair_order=repair_order)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        dealership = self.object.dealership
        context['dealership'] = dealership
        context['repair_order'] = self.object.repair_order
        tags = Tag.objects.all()
        context['tags'] = tags

        queryset = Claim.objects.filter(pk=self.object.pk)
        formset = self.ClaimFormSet(queryset=queryset)
        context['formset'] = formset

        return context

    def form_valid(self, form):
        return super().form_valid(form)

    def get_success_url(self):
        dealership_id = self.object.dealership_id
        return reverse('claim:claim-update', kwargs={'pk': self.object.pk, 'dealership_id': dealership_id})

#####################################################################################
# Delete claim from 'UpdateClaim' view.
#####################################################################################

@method_decorator(in_group_required('wrs-admin'), name='dispatch')
class DeleteClaim(View):

    def get(self, request, *args, **kwargs):
        claim = get_object_or_404(claims_for_user(request.user),
            dealership__name=kwargs['dealership'], repair_order=kwargs['repair_order'])
        return render(request, 'claim/confirm_delete.html', {
            'delete_label': f'Repair Order {claim.repair_order}',
            'delete_warning': 'This deletes the claim and its lines, comments, and attachments.',
            'cancel_url': reverse('claim:claim-update', args=[claim.pk, claim.dealership_id]),
        })

    def post(self, request, *args, **kwargs):
        redirect_url = '/dashboard/'
        dealership = kwargs['dealership']
        dealership = get_object_or_404(accessible_dealerships(self.request.user), name=dealership)
        repair_order = kwargs['repair_order']
        claim = get_object_or_404(claims_for_user(self.request.user), dealership__name=dealership, repair_order=repair_order)

        # Attempt to delete the claim
        try:
            claim.delete()
            messages.success(request, 'Claim has been deleted successfully.')
        except Exception as e:
            messages.error(request, f'Error deleting claim: {str(e)}')

        return redirect(redirect_url)
        #return redirect('dashboard:dealer_admin_dashboard')

#####################################################################################
# Update a Journal entry from Full Claim view 'UpdateClaim'
#####################################################################################

@method_decorator(in_group_required('wrs-admin'), name='dispatch')
class UpdateJournal(UpdateView):
    model = Journal
    template_name = 'claim/update_journal.html'
    form_class = JournalForm

    def get_object(self, queryset=None):
        journal_id = self.kwargs['journal_id']
        #print("This is the journal ID", journal_id)
        return get_object_or_404(Journal, id=journal_id)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        claim = self.object.claim
        context['repair_order'] = claim.repair_order
        context['dealership_id'] = claim.dealership_id
        return context

    def get_success_url(self):
        dealership_id = self.object.claim.dealership_id
        claim_id = self.object.claim.id
        return reverse('claim:claim-update', kwargs={'pk': claim_id, 'dealership_id': dealership_id})

#####################################################################################
# Delete a Journal entry. from UpdateJournal view
#####################################################################################

@method_decorator(in_group_required('wrs-admin'), name='dispatch')
class DeleteJournal(DeleteView):
    model = Journal
    template_name = 'claim/delete_journal.html'

    def get_object(self, queryset=None):
        return get_object_or_404(Journal, id=self.kwargs['journal_id'])

    def get_success_url(self):
        dealership_id = self.object.claim.dealership_id
        claim_id = self.object.claim.id

        messages.success(self.request, "Journal entry deleted successfully.")

        return reverse(
            'claim:claim-update',
            kwargs={
                'pk': claim_id,
                'dealership_id': dealership_id
            }
        )

@method_decorator(in_group_required('wrs-admin'), name='dispatch')
class UpdateDiscrepancy(UpdateView):
    model = Discrepancy
    template_name = 'claim/discrepancy_update.html'
    #Here is the URL for the HTML line: {% url 'claim:delete-discrepancy' form.instance.id line_id %}
    form_class = DiscrepancyForm

    def dispatch(self, request, *args, **kwargs):
        self.line = get_object_or_404(lines_for_user(self.request.user), id=self.kwargs['line_id'])
        return super().dispatch(request, *args, **kwargs)

    def get_object(self, queryset=None):
        discrepancy_id = self.kwargs['discrepancy_id']
        return get_object_or_404(Discrepancy, id=discrepancy_id)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        claim = self.line.claim  # Access claim via the line
        context['line_id'] = self.line.id
        context['line_num'] = self.line.line_num
        context['repair_order'] = claim.repair_order
        context['dealership_id'] = claim.dealership_id
        return context

    def get_success_url(self):
        claim = self.line.claim
        return reverse('claim:claim-update', kwargs={'pk': claim.id, 'dealership_id': claim.dealership_id})

@method_decorator(in_group_required('wrs-admin'), name='dispatch')
class DeleteDiscrepancy(DeleteView):
    model = Discrepancy
    template_name = 'claim/confirm_delete_discrepancy.html'

    def dispatch(self, request, *args, **kwargs):
        self.line = get_object_or_404(lines_for_user(self.request.user), id=self.kwargs['line_id'])
        self.discrepancy = get_object_or_404(
            Discrepancy,
            id=self.kwargs['discrepancy_id']
        )

        if self.line.discrepancy_id != self.discrepancy.id:
            raise Http404("Discrepancy does not match the LineTable entry.")

        return super().dispatch(request, *args, **kwargs)

    def get_object(self, queryset=None):
        return self.discrepancy

    def form_valid(self, form):
        self.line.discrepancy = None
        self.line.save(update_fields=["discrepancy"])
        return super().form_valid(form)

    def get_success_url(self):
        claim = self.line.claim
        return reverse(
            'claim:claim-update',
            kwargs={
                'pk': claim.id,
                'dealership_id': claim.dealership_id
            }
        )

@method_decorator(in_group_required('wrs-admin'), name='dispatch')
class DiscrepancyCreate(CreateView):
    model = Discrepancy
    form_class = DiscrepancyForm
    template_name = 'claim/discrepancy_form.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        line_id = self.kwargs.get('line_id')
        line = get_object_or_404(lines_for_user(self.request.user), id=line_id)
        claim = line.claim  # Access claim via the line
        context['line_num'] = line.line_num
        context['repair_order'] = claim.repair_order
        context['dealership_id'] = claim.dealership_id
        context['line_id'] = line_id
        return context

    def form_valid(self, form):
        line_id = self.kwargs.get('line_id')
        line = get_object_or_404(lines_for_user(self.request.user), id=line_id)
        form.instance.line = line
        response = super().form_valid(form)

        line.discrepancy = form.instance
        line.save()

        return response

    def get_success_url(self):
        line_id = self.kwargs.get('line_id')
        line = get_object_or_404(lines_for_user(self.request.user), id=line_id)
        claim_id = line.claim.id
        dealership_id = line.dealership.id
        return reverse('claim:claim-update', kwargs={'pk': claim_id, 'dealership_id': dealership_id})

#####################################################################################
# This is the Dealer view for updating a claim. Limited to journal and a few clami types: 'rework'..
#####################################################################################

@method_decorator(in_group_required('dealer-admin', 'wrs-admin'), name='dispatch')
class DealerClaimLineUpdateView(DealershipAccessMixin, UpdateView):
    http_method_names = ['get', 'head', 'options']

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        users = CustomUser.objects.filter(dealership=self.authorized_dealership).distinct()
        for field in ('service_writer', 'technician'):
            if field in form.fields:
                form.fields[field].queryset = users
        return form

    model = Claim
    form_class = ClaimLineUpdateForm
    template_name = 'claim/dealer_claim_update_view.html'
    success_url = '/claim/claim-list/'  # URL to redirect after successful update

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        claim = self.object
        dealership_id = self.kwargs.get('dealership_id')
        dealership = get_object_or_404(accessible_dealerships(self.request.user), id=dealership_id)
        line_table = line_edit_values(self.request, claim,
            LineTable.objects.filter(claim=claim, dealership_id=dealership_id).select_related('claim_status', 'claim_type'))
        statuses = list(Status.objects.all())
        for line in line_table:
            current = line.claim_status.name.strip().lower() if line.claim_status else ''
            allowed = dealer_status_choices(current)
            line.dealer_status_options = [
                {'id': str(status.pk), 'name': status.name,
                 'requires_comment': current in DEALER_RETURN_STATUSES and status.name.strip().lower() == 'rework'}
                for status in statuses if status.name.strip().lower() in allowed
            ]
            selected = line.edit_values['claim_status']
            if selected not in {option['id'] for option in line.dealer_status_options}:
                selected = next((option['id'] for option in line.dealer_status_options
                    if option['name'].strip().lower() == 'rework'), '')
            line.dealer_status_selected = selected
        reconciliation = LineTable.objects.filter(claim=claim, dealership_id=dealership_id, discrepancy__isnull=False).select_related('discrepancy')
        journal = Journal.objects.filter(claim=claim)
        pdf_file = PdfFile.objects.filter(claim=claim)
        tags = claim.claim_tag.all()
        #for entry in journal:
            #print(entry.comment)
            #print(entry.user.email)
            #print(entry.user.first_name)
        context['line_table'] = line_table
        context['journal'] = journal
        context['pdf_file'] = pdf_file
        context['dealership'] = dealership
        context['created_date'] = claim.created_date
        context['claim_id'] = claim.id
        context['claim'] = claim
        context['discrepancy'] = reconciliation
        context['tags'] = tags
        current_date = timezone.localdate()
        context['start'] = current_date.strftime('%B %d, %Y')

        if line_table and line_table[0].start_date:
            start_date = line_table[0].start_date
            formatted_date = DateFormat(start_date).format('F d, Y')
            context['start_date'] = formatted_date
        else:
            context['start_date'] = None

        return context

    def form_valid(self, form):
        claim = form.save(commit=False)
        LineTableFormSet = inlineformset_factory(Claim, LineTable, form=LineUpdateForm, extra=1)
        formset = LineTableFormSet(self.request.POST, instance=claim)

        if formset.is_valid():

            start_date = self.request.POST.get('start_date')
            if start_date:
                claim.start_date = datetime.strptime(start_date, '%d %b, %Y').strftime('%Y-%m-%d')

            self.object = form.save()
            formset.save()

            # Update related models (Journal, PdfFile)
            journal_comment = form.cleaned_data['journal_comment']
            pdf_name = form.cleaned_data['pdf_name']
            pdf_file = form.cleaned_data['pdf_file']

            journal = Journal.objects.filter(claim=claim).first()
            if journal:
                journal.comment = journal_comment
                journal.save()

            pdf_file_obj = PdfFile.objects.filter(claim=claim).first()
            if pdf_file_obj:
                pdf_file_obj.pdf_name = pdf_name
                pdf_file_obj.pdf_file = pdf_file
                pdf_file_obj.save()

            return HttpResponseRedirect(self.get_success_url())
        else:
            return self.form_invalid(form, formset)

@method_decorator(in_group_required('dealer-admin', 'wrs-admin'), name='dispatch')
class ComplianceView(DealershipAccessMixin, TemplateView):
    template_name = 'claim/compliance.html'
    context_object_name = 'compliance'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Get the 'Dealership' id from the URL
        dealership_id = self.kwargs.get('dealership_id')

        # Count the total number of 'Paid' entries
        total_paid = LineTable.objects.filter(claim_status__name='Paid', dealership__id=dealership_id).count()

        # Count the number of 'Paid' entries with 'compliant' set to 'False'
        non_compliant_paid = LineTable.objects.filter(claim_status__name='Paid', compliant=False, dealership__id=dealership_id).count()

        # Calculate the percentage
        percentage = 0
        if total_paid > 0:
            percentage = (non_compliant_paid / total_paid) * 100

        context['total_paid'] = total_paid
        context['non_compliant_paid'] = non_compliant_paid
        context['compliance_percentage'] = percentage

        return context


## EVENT SYSTEMS ################################################################################################################

@method_decorator(in_group_required('wrs-admin'), name='dispatch')
class EventViewer(ListView):
    model = Event
    context_object_name = 'events'
    template_name = 'claim/events_view.html'
    ordering = ['-created_date', 'line']


## CLAIM LINE FUNCTIONS ###############################################   FUNCTIONS    ###########################################

@in_group_required('dealer-admin','wrs-admin')
@require_POST
def upload_pdf(request):
    if request.method == 'POST' and request.FILES.get('pdf_file'):
        pdf_file = request.FILES['pdf_file']
        try:
            validate_claim_file(pdf_file)
        except ValidationError as error:
            return HttpResponseBadRequest(' '.join(error.messages))
        claim_id = positive_id(request.POST.get('claim_id'))

        claim = get_object_or_404(claims_for_user(request.user), id=claim_id)

        # Create a new PdfFile instance
        if pdf_file:
                now = datetime.now()
                timestamp = now.strftime("%Y%m%d%H%M%S")
                pdf_filename = f"{pdf_file.name}_{timestamp}"

                #pdf_name = pdf_file.name
                PdfFile.objects.create(
                    pdf_name=pdf_filename,
                    pdf_file=pdf_file,
                    claim=claim
                )

        # Get the success URL
        forwarding_url = safe_return_url(request)

        # Return the success URL as JSON response
        return redirect(forwarding_url)

    # Invalid request or missing data
    return JsonResponse({'success': False, 'error': 'Invalid request or missing data'})

@in_group_required('dealer-admin','wrs-admin')
@require_POST
def global_comment(request):
    if request.method == 'POST':
        global_comment_text = request.POST.get('comment')
        claim_id = positive_id(request.POST.get('claim_id'))
        user_id = request.user.id
        claim = get_object_or_404(claims_for_user(request.user), id=claim_id)

        # Create a new PdfFile instance
        if global_comment_text and global_comment_text.strip():
                Journal.objects.create(
                    comment=global_comment_text,
                    claim=claim,
                    user_id=user_id
                )

        # Get the success URL
        forwarding_url = safe_return_url(request)

        # Return the success URL as JSON response
        return redirect(forwarding_url)

    # Invalid request or missing data
    return JsonResponse({'success': False, 'error': 'Invalid request or missing data'})

#####################################################################
#
# This is the claim line function
#
#####################################################################

COMMENT_REQUIRED_STATUSES = {
    'not submitted',
    'rejected',
    'requires attention',
}

@in_group_required('dealer-admin', 'wrs-admin')
@require_POST
@transaction.atomic
def line_update(request):
    forwarding_url = safe_return_url(request)

    line_id = positive_id(request.POST.get('line_id'))
    line = get_object_or_404(lines_for_user(request.user).select_for_update().select_related('claim', 'claim_status', 'claim_type'), id=line_id)

    if not is_wrs_admin(request.user):
        immutable = {
            'line_num': str(line.line_num or ''),
            'claim_type': str(line.claim_type_id or ''),
            'start_date': datetime_input(line.start_date),
        }
        if any(request.POST.get(key, value) != value for key, value in immutable.items()):
            raise PermissionDenied
        submitted_total = request.POST.get('claim_total')
        if submitted_total:
            try:
                if Decimal(submitted_total) != line.claim_total:
                    raise PermissionDenied
            except InvalidOperation:
                return HttpResponseBadRequest('Invalid claim total.')

    updated = False

    # Normalize submitted comment.
    comment = request.POST.get('comment', '').strip()

    # ---------------------------------------------------------
    # DEBUG
    # ---------------------------------------------------------


    # ---------------------------------------------------------
    # CLAIM STATUS VALIDATION
    # ---------------------------------------------------------

    claim_status_id = request.POST.get('claim_status') or line.claim_status_id

    if not claim_status_id:
        return line_update_error(request, line, 'A claim status must be selected.')

    try:
        new_claim_status_id = int(claim_status_id)
    except (TypeError, ValueError):
        return line_update_error(request, line, 'Invalid claim status.')

    new_claim_status = get_object_or_404(
        Status,
        id=new_claim_status_id
    )

    if not is_wrs_admin(request.user) and new_claim_status.pk != line.claim_status_id:
        current = line.claim_status.name.strip().lower() if line.claim_status else ''
        if new_claim_status.name.strip().lower() not in dealer_status_choices(current):
            raise PermissionDenied

    # Determine whether the status actually changed.
    status_changed = (
        new_claim_status_id != line.claim_status_id
    )

    # Normalize the new status name for comparison.
    new_status_name = new_claim_status.name.strip().lower()

    # Require a comment only when:
    #
    # 1. The status actually changed.
    # 2. The NEW status is one of the statuses requiring a comment.
    # 3. No comment was supplied.
    if (
        status_changed
        and (new_status_name in COMMENT_REQUIRED_STATUSES or (
            not is_wrs_admin(request.user) and new_status_name == 'rework'
            and line.claim_status and line.claim_status.name.strip().lower() in DEALER_RETURN_STATUSES))
        and not comment
    ):
        return line_update_error(request, line,
            f'A comment is required when changing line {line.line_num} from '
            f'{line.claim_status.name if line.claim_status else "Unset"} to {new_claim_status.name}.')
    # ---------------------------------------------------------
    # LINE NUMBER
    # ---------------------------------------------------------

    new_line_num = request.POST.get('line_num', '').strip()


    # Compare as strings because POST values are strings.
    if new_line_num and new_line_num != str(line.line_num):
        line.line_num = new_line_num
        updated = True

    # ---------------------------------------------------------
    # COMPLETION DATE
    # ---------------------------------------------------------

    new_start_date = request.POST.get('start_date',
        datetime_input(line.start_date)).strip()

    if new_start_date:
        try:
            formatted_start_date = clean_datetime(new_start_date) if is_wrs_admin(request.user) else line.start_date

        except ValidationError:
            return line_update_error(request, line, 'Enter a valid completion date and time.')

        if formatted_start_date != line.start_date:
            line.start_date = formatted_start_date
            updated = True

    elif line.start_date is not None:
        line.start_date = None
        updated = True

    # ---------------------------------------------------------
    # CLAIM TYPE
    # ---------------------------------------------------------

    claim_type_id = request.POST.get('claim_type')

    if claim_type_id:
        new_claim_type = get_object_or_404(
            ClaimType,
            id=claim_type_id
        )

        if new_claim_type != line.claim_type:
            line.claim_type = new_claim_type
            updated = True

    # ---------------------------------------------------------
    # CLAIM TOTAL
    # ---------------------------------------------------------

    new_claim_total = request.POST.get(
        'claim_total',
        ''
    ).strip()

    if new_claim_total:
        try:
            validated_claim_total = Decimal(
                new_claim_total
            )

        except InvalidOperation:
            return line_update_error(request, line, 'Claim Total must be a valid decimal number.')

        if not validated_claim_total.is_finite() or abs(validated_claim_total) >= Decimal('100000000') or validated_claim_total.as_tuple().exponent < -2:
            return HttpResponseBadRequest('Invalid claim total.')

        if validated_claim_total != line.claim_total:
            line.claim_total = validated_claim_total
            updated = True

    if new_status_name in COMPLETION_DATE_REQUIRED_STATUSES and line.start_date is None:
        return line_update_error(request, line,
            f'Completion Date is required when the claim status is {new_claim_status.name}.')

    # ---------------------------------------------------------
    # CLAIM STATUS
    # ---------------------------------------------------------

    if status_changed:
        line.claim_status = new_claim_status
        updated = True

        # Set paid_date when moving TO Paid.
        if new_claim_status.name.strip().lower() == 'paid':
            line.paid_date = timezone.now()

        # Clear paid_date when moving AWAY from Paid.
        else:
            line.paid_date = None

    # ---------------------------------------------------------
    # COMPLIANT
    # ---------------------------------------------------------

    compliant = request.POST.get('compliant') == 'on' if is_wrs_admin(request.user) else line.compliant

    if compliant != line.compliant:
        line.compliant = compliant
        updated = True

    # ---------------------------------------------------------
    # SAVE LINE
    # ---------------------------------------------------------

    if updated:
        line.save()

    # ---------------------------------------------------------
    # JOURNAL COMMENT
    # ---------------------------------------------------------

    # Comments are still allowed for any update.
    #
    # The validation above only determines when a comment
    # MUST be supplied.
    if comment:
        Journal.objects.create(
            comment=comment,
            line=line,
            claim=line.claim,
            user=request.user
        )

    # ---------------------------------------------------------
    # RESPONSE MESSAGE
    # ---------------------------------------------------------

    if updated or comment:
        messages.success(
            request,
            'Claim line updated successfully.'
        )
    else:
        messages.info(
            request,
            'No changes were detected.'
        )

    return redirect(forwarding_url)

@in_group_required('wrs-admin')
@require_POST
def add_line(request):
    if request.method == 'POST':

        dealership_name = request.POST.get('dealership')
        dealership = get_object_or_404(accessible_dealerships(request.user), name=dealership_name)

        claim_id = positive_id(request.POST.get('claim_id'))
        claim = get_object_or_404(claims_for_user(request.user), id=claim_id)

        if dealership.pk != claim.dealership_id:
            raise Http404

        LineTable.objects.create(
                claim_total=0.00,
                compliant=False, # This is NON Compliant
                dealership=dealership,
                claim=claim

                )
        # Get the success URL
        forwarding_url = safe_return_url(request)

        # Return the success URL as JSON response
        return redirect(forwarding_url)

    return HttpResponseBadRequest('Invalid request or missing data')

@in_group_required('wrs-admin')
@require_http_methods(['GET', 'POST'])
def delete_line(request, line_id):
    line = get_object_or_404(lines_for_user(request.user), id=line_id)

    if request.method == 'GET':
        return render(request, 'claim/confirm_delete.html', {
            'delete_label': f'Line {line.line_num} on Repair Order {line.claim.repair_order}',
            'delete_warning': 'This deletes the line and its associated comments.',
            'cancel_url': reverse('claim:claim-update', args=[line.claim_id, line.dealership_id]),
        })

    # Save redirect location before deleting
    forwarding_url = safe_return_url(request)

    line.delete()

    return redirect(forwarding_url)

@in_group_required('wrs-admin')
@require_POST
@transaction.atomic
def add_start_date(request, line_id):
    start_date = request.POST.get('start_date')

    line = get_object_or_404(lines_for_user(request.user).select_for_update(), id=line_id)
    from django import forms
    try:
        line.start_date = clean_datetime(start_date)
    except ValidationError:
        return HttpResponseBadRequest('Invalid completion date.')
    if line.claim_status and line.claim_status.name.strip().lower() in COMPLETION_DATE_REQUIRED_STATUSES and line.start_date is None:
        return HttpResponseBadRequest('Completion Date is required for Pending and Requires Attention claims.')
    line.save()

    # Get the success URL
    forwarding_url = safe_return_url(request)

    # Return the success URL as redirect response
    return redirect(forwarding_url)

@in_group_required('dealer-admin','wrs-admin')
@require_POST
def update_ro_status(request):
    if request.method == 'POST':
        ro_status_post = request.POST.get('ro_status')
        claim_id_post = positive_id(request.POST.get('claim_id'))
        user_id = request.user.id

        ro_status = get_object_or_404(RoStatus, id=ro_status_post)

        claim = get_object_or_404(claims_for_user(request.user), id=claim_id_post)
        claim.ro_status = ro_status
        claim.save()

        update_event = event_log(claim_id_post, line=None, user=user_id, comment=f"user set the repair order status to {claim.ro_status.name} ")

        # Get the success URL
        forwarding_url = safe_return_url(request)

        # Return the success URL as JSON response
        return redirect(forwarding_url)

    return HttpResponseBadRequest('Invalid request or missing data')

def get_claim_status_totals(dealership_id, start_date, end_date):
    line_tables = LineTable.objects.filter(dealership_id=dealership_id, modified_date__date__range=(start_date, end_date))

    claim_status_totals = {
        'Paid': 0,
        'Requires_Attention': 0,
        'Pending': 0,
        'Rejected': 0,
        'Not_Submitted': 0,
    }

    for line in line_tables:
        claim_status_name = line.claim_status.name

        # Skip records with a claim_status of 'New'
        if claim_status_name in ('New', 'No Warranty', 'Rework'):
            continue

        # Update the claim_status totals
        #claim_status_totals[claim_status_name] += line.claim_total

        claim_status_totals[claim_status_name.replace(' ', '_')] += line.claim_total

    # Format the claim status totals as dollar values
    for key, value in claim_status_totals.items():
        claim_status_totals[key] = "${:,.2f}".format(value)

    return claim_status_totals

@login_required
@require_GET
def search_repair_order(request):
    from django.core.paginator import Paginator

    dealership = get_dealership(request.user, request.GET.get('dealership_id'))
    repair_order = request.GET.get('repair_order', '').strip()
    claims = claims_for_user(request.user).filter(dealership=dealership)
    claims = claims.filter(repair_order__icontains=repair_order) if repair_order else claims.none()
    claims = claims.select_related('ro_status').prefetch_related(
        'claim_tag',
        Prefetch('linetable_set', queryset=lines_for_user(request.user).filter(
            dealership=dealership).select_related(
                'claim_type', 'claim_status', 'discrepancy'),
            to_attr='search_lines'),
    ).order_by('repair_order', 'id')
    page = Paginator(claims, 10).get_page(request.GET.get('page'))
    for claim in page:
        claim.search_total = sum((line.claim_total or Decimal('0') for line in claim.search_lines), Decimal('0'))
        for line in claim.search_lines:
            line.search_discrepancy = sum((getattr(line.discrepancy, field) or Decimal('0')
                for field in ('labor', 'parts', 'maint', 'core', 'rental', 'sublet', 'other')), Decimal('0')) if line.discrepancy else None
    return render(request, 'claim/search_list.html', {
        'repair_orders': page, 'page_obj': page, 'dealership': dealership,
        'dealership_id': dealership.pk, 'repair_order': repair_order,
        'can_edit_claim': is_wrs_admin(request.user) or request.user.groups.filter(name='dealer-admin').exists(),
        'claim_edit_route': 'claim:claim-update' if is_wrs_admin(request.user) else 'claim:dealer-claim-update',
    })

def monthly_revenue_by_claim_type(request):
    pass

def event_log(claim, line, user, comment=None):
    claim = Claim.objects.get(id=claim)
    user = CustomUser.objects.get(id=user)
    #print(user.email, "will be used")
    # Create and save the Event instance
    event = Event(
        claim=claim,
        line=line,
        user=user,
        comment=comment,
    )
    event.save()

    return event

@require_GET
@login_required
@require_GET
def get_compliance(request, dealership_id):
    # Get the 'Dealership' id from the URL
    dealership = get_object_or_404(accessible_dealerships(request.user), id=dealership_id)

    # Count the total number of 'Paid' entries
    totals = LineTable.objects.filter(claim_status__name='Paid', dealership=dealership).aggregate(total=Count('pk'), non_compliant=Count('pk', filter=Q(compliant=False)))
    total_paid = totals['total']
    non_compliant_paid = totals['non_compliant']

    # Calculate the percentage
    percentage = 0
    if total_paid > 0:
        percentage = ((total_paid - non_compliant_paid) / total_paid) * 100
    else:
        percentage = 100

    data = {
        'compliance_percentage': percentage
    }

    return JsonResponse(data)

## VIEWS RELATE TO DASHBOARDS #########################################   DASHBOARDS   ###########################################

@method_decorator(in_group_required('wrs-admin'), name='dispatch')
class AdminDashboardView(TemplateView): # This is the WRS admin dashboard
    model = Claim
    template_name = 'dashboard/admin-dashboard.html'
    context_object_name = 'admindashboard'

    def get_queryset(self):
        queryset = super().get_queryset()
        claimstatus = self.kwargs.get('claimstatus')
        dealership = self.kwargs.get('dealership')

        claim_status_id = Status.objects.get(name=claimstatus).id
        queryset = queryset.filter(claim_status=claim_status_id, dealership=dealership)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        return context

class DealerDashboardView(TemplateView):
    model = Claim
    template_name = 'dashboard/dealer-dashboard.html'
    context_object_name = 'dealerdashboard'

    def get_queryset(self):
        queryset = super().get_queryset()
        claimstatus = self.kwargs.get('claimstatus')
        dealership = self.kwargs.get('dealership')

        claim_status_id = Status.objects.get(name=claimstatus).id
        queryset = queryset.filter(claim_status=claim_status_id, dealership=dealership)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        return context

## VIEWS RELATE TO REPORTS ############################################  REPORTS  ###################################################

class DailyReportView(View): #------------------------NOT IN USE-----------
    template_name = 'claim/daily_report.html'

    def get_report_data(self, dealership):
        # Get the current date
        today = datetime.now().date()

        # Define the start and end times of the day
        start_time = datetime.min.time()
        end_time = datetime.max.time().replace(hour=23, minute=59, second=59)

        # Construct the start and end datetime objects for the day
        start_datetime = datetime.combine(today, start_time)
        end_datetime = datetime.combine(today, end_time)

        # Filter claims based on the dealership and created date within the day
        claims = Claim.objects.filter(dealership__name=dealership)

        report = []
        for claim in claims:
            # Get the associated journal entries for each claim within the day
            journal_entries = Journal.objects.filter(claim=claim, created_date__range=(start_datetime, end_datetime))
            line_entries = LineTable.object.filter(claim=claim, created_date__range=(start_datetime, end_datetime))

            comments = [entry.comment for entry in journal_entries]

            if comments:
                report.append({
                    'repair_order': claim.repair_order,
                    'comments': comments,
                    'line_nums': line_entries
                })

        return report

    def get(self, request, dealership):
        report = self.get_report_data(dealership)
        context = {'report': report, 'dealership': dealership}
        return render(request, self.template_name, context)


def export_to_pdf(request):
    # Get the data for the report
    view = ReportsViewForm()
    dealership = request.GET.get('dealership')
    dealership_obj = get_object_or_404(accessible_dealerships(request.user), name=dealership)
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    report_type = request.GET.get('report_type')

    #start_date = datetime.strptime(start_date_str, '%B %d, %Y').date()
    #end_date = datetime.strptime(end_date_str, '%B %d, %Y').date()

    start_date = datetime.strptime(start_date_str, '%d %b, %Y').date()
    end_date = datetime.strptime(end_date_str, '%d %b, %Y').date()

    report = view.generate_report(dealership_obj.id, report_type, start_date, end_date)
    claim_status_totals = get_claim_status_totals(dealership_obj.id, start_date, end_date)

    current_date = timezone.localdate()

    context = {
        'report': report,
        'dealership': dealership,
        'report_type': report_type,
        'claim_status_totals': claim_status_totals,
        'start_date': start_date_str,
        'end_date': end_date_str,
    }

    # Render the template to a string
    content = render_to_string('reports/report_pdf.html', context)

    # Create a file-like buffer to receive PDF data
    buffer = BytesIO()

    # Generate the PDF using the rendered HTML
    pisa_status = pisa.CreatePDF(content, dest=buffer)

    # If PDF generation failed, return an error
    if pisa_status.err:
        return HttpResponse('PDF generation failed.')

    # Set the appropriate PDF headers for download
    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="daily_report_{dealership}.pdf"'

    return response


class ReportsView(TemplateView):

    template_name = 'reports/reports.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        dealership_id = self.kwargs['dealership_id']
        dealership = get_object_or_404(accessible_dealerships(self.request.user), id=dealership_id)
        context['dealership'] = dealership.name
        context['dealerships'] = Dealership.objects.all()
        user = self.request.user
        is_superuser = user.is_superuser
        context['is_superuser'] = is_superuser
        #context['reports'] = ['Daily Report', 'Discrepancy', 'Open RO Report']
        context['reports'] = ['Daily Report']
        context['report_type'] = 'Daily Report'
        current_date = timezone.localdate()
        context['start'] = current_date.strftime('%d %b, %Y')
        context['end'] = current_date.strftime('%d %b, %Y')
        #context['start'] = '01 Jan, 2023'
        #context['end'] = '31 Dec, 2023'

        form = ReportsForm(initial={
                'dealership': context['dealership'],
                'report_type': context['report_type'],
                'start': context['start'],
                'end': context['end'],
            })

        context['form'] = form
        return context

class ReportsViewForm(View):
    template_name = 'reports/reportsview.html'

    def get_context_data(self, **kwargs):
        context = {}
        user = self.request.user
        is_superuser = user.is_superuser
        report_type = self.kwargs['report_type']
        #print("This is the report type", report_type)
        context['is_superuser'] = is_superuser
        context['dealership'] = self.kwargs['dealership']
        context['dealerships'] = Dealership.objects.all()
        context['report_type'] = report_type
        return context

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        return render(request, self.template_name, context)

    def daily_report(self, dealership, start, end): ## -------------THIS IS NOT USED
        claims = Claim.objects.filter(dealership__name=dealership)

        report = []
        for claim in claims:
            # Get the associated journal entries for each claim within the day
            #journal_entries = Journal.objects.filter(claim=claim, created_date__range=(start, end))
            if start == end:
                journal_entries = Journal.objects.filter(claim=claim, created_date__startswith=start)
            else:
                journal_entries = Journal.objects.filter(claim=claim, created_date__range=(start, end))

            comments = [entry.comment for entry in journal_entries]

            if comments:
                report.append({
                    'repair_order': claim.repair_order,
                    'comments': comments
                })

        return report

    def generate_report(self, dealership_id, report_type, start, end):

        if report_type == "Daily Report":
            # WE NEED TO ADD FILTER TO INCLUDE ONLY WRS ADMIN COMMENTS
            line_tables = LineTable.objects.filter(dealership_id=dealership_id, modified_date__date__range=(start, end)).order_by('claim__repair_order')


            report = []

            paid_claim_total = 0
            requires_attention_claim_total = 0
            pending_claim_total = 0
            rejected_claim_total = 0
            not_submitted_claim_total = 0

            for line in line_tables:
                repair_order = line.claim.repair_order
                claim_status_name = line.claim_status.name

                # Skip records with a claim_status of 'New' or 'Rework'
                if claim_status_name in ('New', 'Rework'):
                    continue


                # Check if a report item with the same repair_order already exists
                existing_item = next((item for item in report if item['repair_order'] == repair_order), None)

                if existing_item:
                    # Update the existing item with claim_total based on claim_status
                    if claim_status_name == 'Paid':
                        existing_item['paid_claim_total'] += line.claim_total
                    elif claim_status_name == 'Requires Attention':
                        existing_item['requires_attention_claim_total'] += line.claim_total
                    elif claim_status_name == 'Pending':
                        existing_item['pending_claim_total'] += line.claim_total
                    elif claim_status_name == 'Rejected':
                        report_item['rejected_claim_total'] += line.claim_total
                    elif claim_status_name == 'Not Submitted':
                        report_item['not_submitted_claim_total'] += line.claim_total

                else:
                    # Create a new report item
                    report_item = {
                        'repair_order': repair_order,
                        'paid_claim_total': 0,
                        'requires_attention_claim_total': 0,
                        'pending_claim_total': 0,
                        'rejected_claim_total': 0,
                        'not_submitted_claim_total': 0,
                    }

                    # Update the new item's claim_total based on claim_status
                    if claim_status_name == 'Paid':
                        report_item['paid_claim_total'] += line.claim_total
                    elif claim_status_name == 'Requires Attention':
                        report_item['requires_attention_claim_total'] += line.claim_total
                    elif claim_status_name == 'Pending':
                        report_item['pending_claim_total'] += line.claim_total
                    elif claim_status_name == 'Rejected':
                        report_item['rejected_claim_total'] += line.claim_total
                    elif claim_status_name == 'Not Submitted':
                        report_item['not_submitted_claim_total'] += line.claim_total
                    # Fetch line data and comments here
                    lines = LineTable.objects.filter(claim__repair_order=repair_order, modified_date__date__range=(start, end)).distinct()
                    line_ids = lines.values_list('id', flat=True)


                    line_data = []

                    # This needs updating since it gets comments by a specific user ID. needs update
                    for line_id in line_ids:
                        line_comments = Journal.objects.filter(line_id=line_id, user_id='4', created_date__range=(start, end)).values_list('comment', flat=True)
                        comments = list(line_comments)
                        comment_count = len(comments)

                        line_data.append({
                            'line': LineTable.objects.get(id=line_id),
                            'comments': comments,
                            'comment_count': comment_count
                        })

                    report_item['line_data'] = line_data

                    report.append(report_item)

        return report


        if report_type == "Open RO Report":
            line_tables = LineTable.objects.filter(dealership_id=dealership_id, modified_date__date__range=(start, end), claim__ro_status__name='Open', claim_status__name='Paid').exclude(claim_status__name='New')

            report = {}
            for line in line_tables:
                repair_order = line.claim.repair_order

                if repair_order not in report:
                    report[repair_order] = {
                        'line_nums': [],
                        'claim_totals': [],
                        'claim_statuses': [],
                        'ro_statuses': [],
                    }

                report[repair_order]['line_nums'].append(line.line_num)
                report[repair_order]['claim_totals'].append(line.claim_total)
                report[repair_order]['claim_statuses'].append(line.claim_status)
                report[repair_order]['ro_statuses'].append(line.claim.ro_status)

            return report

        if report_type == "Discrepancy Report":
            pass

    def post(self, request, *args, **kwargs):
        form = ReportsForm(request.POST)

        if form.is_valid():
            dealership_name = form.cleaned_data['dealership']
            dealership = get_object_or_404(accessible_dealerships(self.request.user), name=dealership_name)
            dealership_id = dealership.id

            report_type = form.cleaned_data['report_type']
            start_date_str = form.cleaned_data['start']
            end_date_str = form.cleaned_data['end']


            start_date = datetime.strptime(start_date_str, '%d %b, %Y').date()
            end_date = datetime.strptime(end_date_str, '%d %b, %Y').date()


            report = self.generate_report(dealership_id, report_type, start_date, end_date)

            context = {
                'report': report,
                'dealership': dealership_name,
                'report_type': report_type,
                'start_date': start_date_str,
                'end_date': end_date_str
            }

            return render(request, self.template_name, context)

        #print(form.data)
        #print(form.errors)
        return HttpResponse("Invalid form data")

@login_required
def global_search(request):
    query = request.GET.get("q", "").strip()
    claims = Claim.objects.none()

    if query:
        if query.isdigit():
            claims = (
                claims_for_user(request.user)
                .select_related("dealership", "ro_status")
                .filter(repair_order=int(query))
                .order_by("dealership__name", "-modified_date")[:100]
            )

    return render(request, "claim/global_search_results.html", {
        "query": query,
        "claims": claims,
    })

## OLD VIEWS NOT USED BUT FUNCTIONAL ########################################  OLD CODE  #################################################

@method_decorator(in_group_required('Dealer Admin', 'wrs-admin'), name='dispatch')
class xClaimUpdateView(UpdateView):
    model = Claim
    form_class = ClaimUpdateForm
    template_name = 'claim/claim_update.html'
    success_url = '/claim/claim-list/'  # URL to redirect after successful update

class xUpdateClaimLine(UpdateView):
    model = LineTable
    template_name = 'claim/update_claim_line.html'
    form_class = LineUpdateForm

    def get_object(self, queryset=None):
        line_id = self.kwargs['line_id']
        return get_object_or_404(lines_for_user(self.request.user), id=line_id)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        claim = self.object.claim
        line_id = self.object.id
        #print("This is the line ID", line_id)
        context['repair_order'] = claim.repair_order
        context['dealership_id'] = claim.dealership.id
        context['line_id'] = line_id

        # Check if a discrepancy exists for the line and include it in the context
        discrepancy = self.object.discrepancy
        if not discrepancy:
            discrepancy = Discrepancy.objects.create()
            self.object.discrepancy = discrepancy
            self.object.save()
        context['discrepancy'] = discrepancy

        return context

    def form_valid(self, form):
        # Save the form for the LineTable model
        response = super().form_valid(form)

        # Get the discrepancy object for the line
        discrepancy = Discrepancy.objects.get(line=self.object)

        # Update the discrepancy fields based on the form data
        discrepancy.labor = form.cleaned_data['labor']
        discrepancy.parts = form.cleaned_data['parts']
        discrepancy.maint = form.cleaned_data['maint']
        discrepancy.other = form.cleaned_data['other']
        discrepancy.save()

        return response

    def get_success_url(self):
        claim_id = self.object.claim.id
        dealership_id = self.object.dealership.id
        return reverse('claim:claim-update', kwargs={'pk': claim_id, 'dealership_id': dealership_id})

## OLD VIEWS NOT USED FROM OLD CODE #####################################################

class xClaimListView(ListView):

    model = Claim
    template_name = 'claim/claim-list.html'
    context_object_name = 'claimlist'
    paginate_by = 10

    def get_queryset(self):
        queryset = super().get_queryset()
        claimstatus = self.kwargs.get('claimstatus')
        dealership = self.kwargs.get('dealership')

        status = get_object_or_404(Status, name=claimstatus)


        line_tables = LineTable.objects.filter(
            claim_status=status,
            dealership=dealership
            #claim__claim_status=status,
            #claim__dealership__name=dealership
        )
        #print("Number of records found in line_tables:", line_tables.count())
        repair_orders = line_tables.values_list('claim__repair_order', flat=True).distinct()
        queryset = queryset.filter(repair_order__in=repair_orders)

        #print("Number of records found:", queryset.count())
        #claim_status_id = Status.objects.get(name=claimstatus).id
        #queryset = queryset.filter(claim_status=claim_status_id, dealership=dealership)

        return queryset


    # This might get removed.
    def paginate_queryset(self, queryset, page_size):
        # Set the desired pagination limit
        return super().paginate_queryset(queryset, self.paginate_by)

    def get_paginate_by(self, queryset):
        # Disable default pagination by returning None
        return None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        is_superuser = user.is_superuser
        context['is_superuser'] = is_superuser
        filter_type = self.kwargs.get('claimstatus')
        context['status_name'] = filter_type
        dealership = self.kwargs.get('dealership')
        context['dealership'] = dealership
        context['dealerships'] = Dealership.objects.all()
        claimlists = context[self.context_object_name]
        paginator = Paginator(claimlists, self.paginate_by)
        page_number = self.request.GET.get('page')
        page_obj = paginator.get_page(page_number)
        #print(page_obj.paginator.num_pages)
        context['page_obj'] = page_obj

        return context



@login_required
@require_GET
def download_pdf(request, pdf_id):
    pdf = get_object_or_404(PdfFile.objects.select_related('claim'), pk=pdf_id, claim__in=claims_for_user(request.user))
    # Existing database paths are relative to the deployment directory.
    root = Path(settings.BASE_DIR).resolve()
    path = (root / pdf.pdf_file.name).resolve()
    upload_root = (root / 'static' / 'upload').resolve()
    if not path.is_relative_to(upload_root) or not path.is_file():
        raise Http404
    response = FileResponse(path.open('rb'), as_attachment=True, filename=path.name,
        content_type=ATTACHMENT_CONTENT_TYPES.get(path.suffix.lower(), 'application/octet-stream'))
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
