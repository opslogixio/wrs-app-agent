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
from django.views.decorators.http import require_POST, require_GET
from django.http import HttpResponseRedirect, HttpResponse, HttpResponseBadRequest, JsonResponse, HttpResponseNotAllowed, Http404
from django.db.models import Q, OuterRef, Subquery
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

def in_group_required(*group_names):
    def decorator(view_func):
        def wrapped_view(request, *args, **kwargs):
            if request.user.groups.filter(name__in=group_names).exists():
                return view_func(request, *args, **kwargs)
            else:
                return redirect('claim:not-authorized')  # Redirect to the not-authorized page
        return wrapped_view
    return decorator

def is_superuser(user):
    return user.is_superuser

## VIEWS RELATE TO CLAIMS ##################################################  CLAIMS  ##########################################

#####################################################################################
# THIS HANDLES THE INITIAL CLAIM INPUT
#####################################################################################

@method_decorator(in_group_required('dealer-admin', 'wrs-admin'), name='dispatch')
#@method_decorator(user_passes_test(is_superuser) or in_group_required('Dealer Admin'), name='dispatch')
class ClaimFormView(View): 
    claim_form_class = ClaimForm
    journal_form_class = JournalForm
    pdffile_form_class = PdfFileForm
    template_name = 'claim/claim_form.html'

    def get(self, request, dealership_id):
        claim_form = self.claim_form_class()
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
            'tags': tags
        })

    def post(self, request, dealership_id):
        claim_form = self.claim_form_class(request.POST)
        journal_form = self.journal_form_class(request.POST)
        pdffile_form = self.pdffile_form_class(request.POST, request.FILES)
        user = request.user

        if claim_form.is_valid() and journal_form.is_valid() and pdffile_form.is_valid():
            print("WE ARE A VALID CLAIM!")
            # Create a new Claim
            claim = claim_form.save(commit=False)
            dealership = claim_form.cleaned_data['dealership'].id
            claim.dealership_id = dealership
            

            # Update the claim_tag in the Claim
            #claim.claim_tag = claim_form.cleaned_data['claim_tag']
            claim.ro_status_id = 1 # this has not been tested yet. 
            claim.save()

            claim.claim_tag.set(claim_form.cleaned_data['claim_tag'])

            # Get the list of tags from the form cleaned_data
            tag_list = claim_form.cleaned_data['claim_tag']
            print("This is our tag list:", tag_list)
            # Find the tag with the highest 'id' from the list
            if tag_list:
                highest_id_tag = max(tag_list, key=lambda tag: tag.id)
                print("This is our highest tag:", highest_id_tag)
                # Pontential use if tags need to be None:
                # highest_id_tag = max(tag_list, default=None, key=lambda tag: tag.id) if tag_list else None
                initial_claim_type = highest_id_tag  # Set 'initial_type' to the tag with the highest 'id'
            else:
                initial_claim_type = None

            if initial_claim_type.name == 'Bodyshop':             
             initial_claim_type = get_object_or_404(ClaimType, name='Repair')
            print("This is our new tag if its bodyshop initially:", initial_claim_type)
            claim_type_init = get_object_or_404(ClaimType, name=initial_claim_type.name)
            print("This is the claim type init:", claim_type_init)
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
                claim_type=claim_type_init
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

            redirect_url = reverse('claim:claim-form', args=[dealership_id])
            return redirect(redirect_url)
        
        else:

            dealerships = Dealership.objects.filter(id=dealership_id)
            tags = Tag.objects.all()
            return render(request, self.template_name, {
                'claim_form': claim_form,
                'journal_form': journal_form,
                'pdffile_form': pdffile_form,
                'dealerships': dealerships,
                'tags': tags
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

@method_decorator(in_group_required('dealer-admin', 'wrs-admin'), name='dispatch')
class ClaimQueueListView(ListView):
    model = Claim
    template_name = 'claim/claim_queue.html'
    context_object_name = 'claim_queue'
    bodyshop = False
    

    def get_queryset(self):
        # Get the filter request from the URL parameter
        filter_request = self.kwargs.get('filter_request')
        dealership_id = self.request.GET.get('dealership_id')
        ninety_days_ago = date.today() - timedelta(days=90)

        try:
            dealership = get_object_or_404(Dealership, id=dealership_id)
            user = self.request.user
            #dealership_ids = user.dealership.values_list('id', flat=True)
            #queryset = Claim.objects.filter(
            #Q(linetable__claim_status_id=claim_status.id) & Q(dealership_id__in=dealership_ids)

            try:
                if filter_request == 'Aging':
                    #queryset = LineTable.objects.filter(claim_status__name='Requires Attention', dealership_id=dealership, start_date__gte=ninety_days_ago)
                    queryset = Claim.objects.filter(linetable__claim_status__name='Requires Attention', dealership=dealership, linetable__start_date__lte=ninety_days_ago)
                else:
                    claim_status_obj = Status.objects.get(name=filter_request)
                    queryset = Claim.objects.filter(linetable__claim_status_id=claim_status_obj.id, dealership=dealership)
            except Status.DoesNotExist:
                queryset = Claim.objects.filter(
                    dealership=dealership
                ).exclude(
                    Q(linetable__claim_status__name='New')
                )

        except Status.DoesNotExist:
            queryset = Claim.objects.none()

        if queryset.filter(claim_tag__name='Bodyshop').exists():
            self.bodyshop = True

        bodyshop_claims = queryset.filter(claim_tag__name='Bodyshop')
        other_claims = queryset.exclude(claim_tag__name='Bodyshop')

        # Update the bodyshop flag if there are any bodyshop claims
        if bodyshop_claims:
            self.bodyshop = True

        return {'bodyshop_claims': bodyshop_claims, 'other_claims': other_claims}
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        filter_request = self.kwargs.get('filter_request')
        dealership_id = self.request.GET.get('dealership_id')
        dealership = get_object_or_404(Dealership, id=dealership_id)
        user = self.request.user
        user_groups = user.groups.all()
        print("This is the group:", user_groups)
        filtered_claims = self.get_queryset()
        tags = Tag.objects.filter(claim__in=filtered_claims['bodyshop_claims'] | filtered_claims['other_claims'])
        #dealerships = user.dealership.all()
        #context['dealerships'] = dealerships
        context['claim_status'] = filter_request
        context['user_groups'] = user_groups
        context['dealership'] = dealership
        context['dealership_id'] = dealership_id
        context['tags'] = tags
        context['bodyshop'] = self.bodyshop
        context['bodyshop_claims'] = filtered_claims['bodyshop_claims']
        context['other_claims'] = filtered_claims['other_claims']
        
        return context

#####################################################################################
# New Claim Queue
#####################################################################################

@method_decorator(in_group_required('dealer-admin', 'wrs-admin'), name='dispatch')
class NewClaimQueueListView(ListView):
    model = Claim
    template_name = 'claim/new_claim_queue.html'
    context_object_name = 'new_claim_queue'
    bodyshop = False

    def get_queryset(self):
        filter_request = self.kwargs.get('filter_request')
        dealership_id = self.request.GET.get('dealership_id')

        print("===== NewClaimQueueListView DEBUG =====")
        print(f"filter_request={filter_request}")
        print(f"dealership_id={dealership_id}")

        try:
            dealership = get_object_or_404(Dealership, id=dealership_id)
            claim_status_obj = Status.objects.get(name=filter_request)

            print(f"dealership={dealership}")
            print(f"claim_status_obj={claim_status_obj} id={claim_status_obj.id}")

            new_line_comment = Journal.objects.filter(
                claim_id=OuterRef('pk'),
                line_id__isnull=True
            ).order_by('created_date').values('comment')[:1]

            queryset = Claim.objects.filter(
                linetable__claim_status=claim_status_obj,
                dealership=dealership
            ).annotate(
                new_comment=Subquery(new_line_comment)
            ).distinct().prefetch_related(
                'linetable_set__claim_status',
                'claim_tag'
            )

            print(f"Total New queryset count={queryset.count()}")

            for claim in queryset[:10]:
                print(
                    f"Claim ID={claim.id}, "
                    f"RO={claim.repair_order}, "
                    f"new_comment={repr(claim.new_comment)}"
                )

                journals = Journal.objects.filter(
                    claim_id=claim.id,
                    line_id__isnull=True
                ).values(
                    'id',
                    'claim_id',
                    'line_id',
                    'comment',
                    'created_date'
                )

                print(f"  Claim-level NULL line journals={list(journals)}")

        except (Status.DoesNotExist, Dealership.DoesNotExist) as e:
            print(f"NewClaimQueueListView ERROR: {e}")
            queryset = Claim.objects.none()

        bodyshop_claims = queryset.filter(claim_tag__name='Bodyshop')
        new_claims = queryset.exclude(claim_tag__name='Bodyshop')

        print(f"bodyshop_claims count={bodyshop_claims.count()}")
        print(f"new_claims count={new_claims.count()}")
        print("===== END NewClaimQueueListView DEBUG =====")

        if bodyshop_claims.exists():
            self.bodyshop = True

        return {
            'bodyshop_claims': bodyshop_claims,
            'new_claims': new_claims
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        filter_request = self.kwargs.get('filter_request')
        dealership_id = self.request.GET.get('dealership_id')
        dealership = get_object_or_404(Dealership, id=dealership_id)
        user = self.request.user

        filtered_claims = self.get_queryset()

        context['claim_status'] = filter_request
        context['user_groups'] = user.groups.all()
        context['dealership'] = dealership
        context['dealership_id'] = dealership_id
        context['bodyshop'] = self.bodyshop
        context['bodyshop_claims'] = filtered_claims['bodyshop_claims']
        context['new_claims'] = filtered_claims['new_claims']

        return context

#####################################################################################
# Requires Attention Queue
#####################################################################################
@method_decorator(in_group_required('dealer-admin', 'wrs-admin'), name='dispatch')
class RaClaimQueueListView(ListView):
    model = Claim
    template_name = 'claim/ra_claim_queue.html'
    context_object_name = 'ra_claim_queue'
    bodyshop = False

    def get_queryset(self):
        filter_request = self.kwargs.get('filter_request')
        dealership_id = self.request.GET.get('dealership_id')
        ninety_days_ago = date.today() - timedelta(days=90)
        today = date.today()

        try:
            dealership = get_object_or_404(
                Dealership,
                id=dealership_id
            )

            if filter_request == 'Aging':
                queryset = (
                    Claim.objects
                    .filter(
                        linetable__claim_status__name='Requires Attention',
                        dealership=dealership,
                        linetable__start_date__lte=ninety_days_ago
                    )
                    .distinct()
                    .prefetch_related(
                        'linetable_set__claim_status',
                        'claim_tag'
                    )
                )
            else:
                claim_status_obj = Status.objects.get(
                    name=filter_request
                )

                queryset = (
                    Claim.objects
                    .filter(
                        linetable__claim_status=claim_status_obj,
                        dealership=dealership
                    )
                    .distinct()
                    .prefetch_related(
                        'linetable_set__claim_status',
                        'claim_tag'
                    )
                )

        except (Status.DoesNotExist, Dealership.DoesNotExist):
            queryset = Claim.objects.none()

        claim_data = []

        for claim in queryset:
            claim_info = {
                'claim': claim,
                'lines': []
            }

            for line in claim.linetable_set.all():

                if line.start_date:
                    claim_age = (
                        today - line.start_date
                    ).days + 1
                else:
                    claim_age = None

                claim_info['lines'].append({
                    'line': line,
                    'claim_age': claim_age,
                })

            claim_data.append(claim_info)

        bodyshop_claims = []
        ra_claims = []

        for data in claim_data:
            is_bodyshop = any(
                tag.name == 'Bodyshop'
                for tag in data['claim'].claim_tag.all()
            )

            if is_bodyshop:
                bodyshop_claims.append(data)
            else:
                ra_claims.append(data)

        self.bodyshop = bool(bodyshop_claims)

        return {
            'bodyshop_claims': bodyshop_claims,
            'ra_claims': ra_claims
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        filter_request = self.kwargs.get('filter_request')
        dealership_id = self.request.GET.get('dealership_id')

        dealership = get_object_or_404(
            Dealership,
            id=dealership_id
        )

        user = self.request.user
        filtered_claims = self.get_queryset()

        context['claim_status'] = filter_request
        context['user_groups'] = user.groups.all()
        context['dealership'] = dealership
        context['dealership_id'] = dealership_id
        context['bodyshop'] = self.bodyshop
        context['bodyshop_claims'] = filtered_claims['bodyshop_claims']
        context['ra_claims'] = filtered_claims['ra_claims']

        return context

#####################################################################################
# Pending Queue
#####################################################################################
@method_decorator(in_group_required('dealer-admin', 'wrs-admin'), name='dispatch')
class PendingClaimQueueListView(ListView):
    model = Claim
    template_name = 'claim/pending_claim_queue.html'
    context_object_name = 'pending_claim_queue'
    bodyshop = False

    def get_queryset(self):
        filter_request = self.kwargs.get('filter_request')
        dealership_id = self.request.GET.get('dealership_id')
        today = date.today()

        try:
            dealership = get_object_or_404(
                Dealership,
                id=dealership_id
            )

            claim_status_obj = Status.objects.get(
                name=filter_request
            )

            queryset = (
                Claim.objects
                .filter(
                    linetable__claim_status=claim_status_obj,
                    dealership=dealership
                )
                .distinct()
                .prefetch_related(
                    'linetable_set__claim_status',
                    'claim_tag'
                )
            )

        except (Status.DoesNotExist, Dealership.DoesNotExist):
            queryset = Claim.objects.none()

        claim_data = []

        for claim in queryset:
            claim_info = {
                'claim': claim,
                'lines': []
            }

            for line in claim.linetable_set.all():

                if line.start_date:
                    claim_age = (
                        today - line.start_date
                    ).days + 1
                else:
                    claim_age = None

                claim_info['lines'].append({
                    'line': line,
                    'claim_age': claim_age,
                })

            claim_data.append(claim_info)

        bodyshop_claims = []
        pending_claims = []

        for data in claim_data:
            is_bodyshop = any(
                tag.name == 'Bodyshop'
                for tag in data['claim'].claim_tag.all()
            )

            if is_bodyshop:
                bodyshop_claims.append(data)
            else:
                pending_claims.append(data)

        self.bodyshop = bool(bodyshop_claims)

        return {
            'bodyshop_claims': bodyshop_claims,
            'pending_claims': pending_claims
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        filter_request = self.kwargs.get('filter_request')
        dealership_id = self.request.GET.get('dealership_id')

        dealership = get_object_or_404(
            Dealership,
            id=dealership_id
        )

        user = self.request.user
        filtered_claims = self.get_queryset()

        context['claim_status'] = filter_request
        context['user_groups'] = user.groups.all()
        context['dealership'] = dealership
        context['dealership_id'] = dealership_id
        context['bodyshop'] = self.bodyshop
        context['bodyshop_claims'] = filtered_claims['bodyshop_claims']
        context['pending_claims'] = filtered_claims['pending_claims']

        return context

#####################################################################################
# Rework Queue
#####################################################################################
@method_decorator(in_group_required('dealer-admin', 'wrs-admin'), name='dispatch')
class ReworkClaimQueueListView(ListView):
    model = Claim
    template_name = 'claim/rework_claim_queue.html'
    context_object_name = 'rework_claim_queue'
    bodyshop = False

    def get_queryset(self):
        filter_request = self.kwargs.get('filter_request')
        dealership_id = self.request.GET.get('dealership_id')
        today = date.today()

        try:
            dealership = get_object_or_404(
                Dealership,
                id=dealership_id
            )

            claim_status_obj = Status.objects.get(
                name=filter_request
            )

            queryset = (
                Claim.objects
                .filter(
                    linetable__claim_status=claim_status_obj,
                    dealership=dealership
                )
                .distinct()
                .prefetch_related(
                    'linetable_set__claim_status',
                    'claim_tag'
                )
            )

        except (Status.DoesNotExist, Dealership.DoesNotExist):
            queryset = Claim.objects.none()

        claim_data = []

        for claim in queryset:
            claim_info = {
                'claim': claim,
                'lines': []
            }

            for line in claim.linetable_set.all():

                if line.start_date:
                    claim_age = (
                        today - line.start_date
                    ).days + 1
                else:
                    claim_age = None

                claim_info['lines'].append({
                    'line': line,
                    'claim_age': claim_age,
                })

            claim_data.append(claim_info)

        bodyshop_claims = []
        rework_claims = []

        for data in claim_data:
            is_bodyshop = any(
                tag.name == 'Bodyshop'
                for tag in data['claim'].claim_tag.all()
            )

            if is_bodyshop:
                bodyshop_claims.append(data)
            else:
                rework_claims.append(data)

        self.bodyshop = bool(bodyshop_claims)

        return {
            'bodyshop_claims': bodyshop_claims,
            'rework_claims': rework_claims
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        filter_request = self.kwargs.get('filter_request')
        dealership_id = self.request.GET.get('dealership_id')

        dealership = get_object_or_404(
            Dealership,
            id=dealership_id
        )

        user = self.request.user
        filtered_claims = self.get_queryset()

        context['claim_status'] = filter_request
        context['user_groups'] = user.groups.all()
        context['dealership'] = dealership
        context['dealership_id'] = dealership_id
        context['bodyshop'] = self.bodyshop
        context['bodyshop_claims'] = filtered_claims['bodyshop_claims']
        context['rework_claims'] = filtered_claims['rework_claims']

        return context
    
#####################################################################################
# Open RO queue
#####################################################################################

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

        today = date.today()
        open_status = get_object_or_404(RoStatus, name='Open')

        dealership = get_object_or_404(Dealership, id=dealership_id)

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
        dealership = get_object_or_404(Dealership, id=dealership_id)
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
        
@method_decorator(in_group_required('wrs-admin'), name='dispatch')
class ClaimLineUpdateView(UpdateView):
    model = Claim
    form_class = ClaimLineUpdateForm
    template_name = 'claim/claim_update.html'
    success_url = '/claim/claim-list/'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        claim = self.object
        user = self.request.user
        dealership_id = self.kwargs.get('dealership_id')
        dealership = get_object_or_404(Dealership, id=dealership_id)
        line_table = LineTable.objects.filter(claim=claim, dealership_id=dealership_id)
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
        print(f"Audit events for claim {claim.id}: {audit_events.count()}")

        for event in audit_events:
            print(
                event.occurred_at,
                event.event_type,
                event.action,
                event.actor,
                event.line,
                event.journal,
                event.content_type,
                event.message,
                event.line_num,
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

       

        print("Log: ", date.today().strftime('%B %d, %Y'), user, dealership, claim.repair_order)

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
            'start': date.today().strftime('%B %d, %Y'),
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
        return get_object_or_404(Claim, dealership__name=dealership, repair_order=repair_order)
    
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
        # Save the formset
        formset = self.ClaimFormSet(self.request.POST)
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()

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
        redirect_url = request.session.get('redirect_url')
        dealership = kwargs['dealership']
        dealership = get_object_or_404(Dealership, name=dealership)
        repair_order = kwargs['repair_order']
        claim = get_object_or_404(Claim, dealership__name=dealership, repair_order=repair_order)
        
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
        self.line = get_object_or_404(LineTable, id=self.kwargs['line_id'])
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
        self.line = get_object_or_404(LineTable, id=self.kwargs['line_id'])
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
        line = get_object_or_404(LineTable, id=line_id)
        claim = line.claim  # Access claim via the line
        context['line_num'] = line.line_num
        context['repair_order'] = claim.repair_order
        context['dealership_id'] = claim.dealership_id
        context['line_id'] = line_id
        return context

    def form_valid(self, form):
        line_id = self.kwargs.get('line_id')
        line = get_object_or_404(LineTable, id=line_id)
        form.instance.line = line
        response = super().form_valid(form)
    
        line.discrepancy = form.instance
        line.save()

        return response

    def get_success_url(self):
        line_id = self.kwargs.get('line_id')
        line = get_object_or_404(LineTable, id=line_id)
        claim_id = line.claim.id
        dealership_id = line.dealership.id
        return reverse('claim:claim-update', kwargs={'pk': claim_id, 'dealership_id': dealership_id})

#####################################################################################
# This is the Dealer view for updating a claim. Limited to journal and a few clami types: 'rework'..
#####################################################################################

@method_decorator(in_group_required('dealer-admin', 'wrs-admin'), name='dispatch')    
class DealerClaimLineUpdateView(UpdateView):
    model = Claim
    form_class = ClaimLineUpdateForm
    template_name = 'claim/dealer_claim_update_view.html'
    success_url = '/claim/claim-list/'  # URL to redirect after successful update

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        claim = self.object
        dealership_id = self.kwargs.get('dealership_id')
        dealership = get_object_or_404(Dealership, id=dealership_id)
        line_table = LineTable.objects.filter(claim=claim, dealership_id=dealership_id)
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
        current_date = date.today()
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
class ComplianceView(TemplateView):
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
 
class EventViewer(ListView):
    model = Event
    context_object_name = 'events'
    template_name = 'claim/events_view.html'
    ordering = ['-created_date', 'line']


## CLAIM LINE FUNCTIONS ###############################################   FUNCTIONS    ###########################################

def upload_pdf(request):
    if request.method == 'POST' and request.FILES.get('pdf_file'):
        pdf_file = request.FILES['pdf_file']
        claim_id = int(request.POST.get('claim_id'))

        claim = get_object_or_404(Claim, id=claim_id)

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
        forwarding_url = request.META.get('HTTP_REFERER', '/default-url/')

        # Return the success URL as JSON response
        return redirect(forwarding_url)

    # Invalid request or missing data
    return JsonResponse({'success': False, 'error': 'Invalid request or missing data'})

def global_comment(request):
    if request.method == 'POST':
        global_comment_text = request.POST.get('comment')
        claim_id = int(request.POST.get('claim_id'))
        user_id = request.user.id
        claim = get_object_or_404(Claim, id=claim_id)

        # Create a new PdfFile instance
        if global_comment: 
                Journal.objects.create(
                    comment=global_comment_text,
                    claim=claim,
                    user_id=user_id
                )

        # Get the success URL
        forwarding_url = request.META.get('HTTP_REFERER', '/default-url/')

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

@require_POST
@transaction.atomic
def line_update(request):
    forwarding_url = request.META.get(
        'HTTP_REFERER',
        '/default-url/'
    )

    COMMENT_REQUIRED_STATUSES = {
        'requires attention',
        'not submitted',
        'no warranty',
        'rejected',
    }

    line_id = request.POST.get('line_id')
    line = get_object_or_404(LineTable, id=line_id)

    updated = False

    # Normalize submitted comment.
    comment = request.POST.get('comment', '').strip()

    # ---------------------------------------------------------
    # DEBUG
    # ---------------------------------------------------------

    print('========================================')
    print('LINE UPDATE')
    print('line_id:', line_id)
    print('POST:', request.POST)
    print('DATABASE STATUS ID:', line.claim_status_id)
    print('DATABASE STATUS:', line.claim_status.name)
    print('SUBMITTED STATUS:', request.POST.get('claim_status'))
    print('COMMENT:', repr(comment))
    print('========================================')

    # ---------------------------------------------------------
    # CLAIM STATUS VALIDATION
    # ---------------------------------------------------------

    claim_status_id = request.POST.get('claim_status')

    if not claim_status_id:
        messages.error(
            request,
            'A claim status must be selected.'
        )
        return redirect(forwarding_url)

    try:
        new_claim_status_id = int(claim_status_id)
    except (TypeError, ValueError):
        messages.error(
            request,
            'Invalid claim status.'
        )
        return redirect(forwarding_url)

    new_claim_status = get_object_or_404(
        Status,
        id=new_claim_status_id
    )

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
        and new_status_name in COMMENT_REQUIRED_STATUSES
        and not comment
    ):
        messages.error(
            request,
            (
                f'A comment is required when changing '
                f'line {line.line_num} from '
                f'{line.claim_status.name} to '
                f'{new_claim_status.name}.'
            )
        )
        return redirect(forwarding_url)
    # ---------------------------------------------------------
    # LINE NUMBER
    # ---------------------------------------------------------

    new_line_num = request.POST.get('line_num', '').strip()

    print(
        'This is the new line number:',
        new_line_num,
        'VS OLD NUM:',
        line.line_num
    )

    # Compare as strings because POST values are strings.
    if new_line_num and new_line_num != str(line.line_num):
        line.line_num = new_line_num
        updated = True

    # ---------------------------------------------------------
    # COMPLETION DATE
    # ---------------------------------------------------------

    new_start_date = request.POST.get('start_date', '').strip()

    if new_start_date:
        try:
            formatted_start_date = datetime.strptime(
                new_start_date,
                '%B %d, %Y'
            ).date()

        except ValueError:
            messages.error(
                request,
                'Completion Date must use the expected date format.'
            )
            return redirect(forwarding_url)

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
            messages.error(
                request,
                'Claim Total must be a valid decimal number.'
            )
            return redirect(forwarding_url)

        if validated_claim_total != line.claim_total:
            line.claim_total = validated_claim_total
            updated = True

    # ---------------------------------------------------------
    # CLAIM STATUS
    # ---------------------------------------------------------

    if status_changed:
        line.claim_status = new_claim_status
        updated = True

        # Set paid_date when moving TO Paid.
        if new_claim_status.name.strip().lower() == 'paid':
            line.paid_date = date.today()

        # Clear paid_date when moving AWAY from Paid.
        else:
            line.paid_date = None

    # ---------------------------------------------------------
    # COMPLIANT
    # ---------------------------------------------------------

    compliant = request.POST.get('compliant') == 'on'

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

def add_line(request):
    if request.method == 'POST':

        dealership_name = request.POST.get('dealership')
        dealership = get_object_or_404(Dealership, name=dealership_name)

        claim_id = int(request.POST.get('claim_id'))
        claim = get_object_or_404(Claim, id=claim_id)

        LineTable.objects.create(
                claim_total=0.00,
                compliant=False, # This is NON Compliant
                dealership=dealership,
                claim=claim

                )
        # Get the success URL
        forwarding_url = request.META.get('HTTP_REFERER', '/default-url/')

        # Return the success URL as JSON response
        return redirect(forwarding_url)
    
    return HttpResponseBadRequest('Invalid request or missing data')

@require_POST
def delete_line(request, line_id):
    line = get_object_or_404(LineTable, id=line_id)

    # Save redirect location before deleting
    forwarding_url = request.META.get('HTTP_REFERER', '/default-url/')

    line.delete()

    return redirect(forwarding_url)

def add_start_date(request):
    line_id = request.POST.get('line_id')
    start_date = request.POST.get('start_date')

    line = get_object_or_404(LineTable, id=line_id)
    line.start_date = start_date
    line.save()

    # Get the success URL
    forwarding_url = request.META.get('HTTP_REFERER', '/default-url/')

    # Return the success URL as redirect response
    return redirect(forwarding_url)

def update_ro_status(request):
    if request.method == 'POST':
        print("We in a POST for Status")
        ro_status_post = request.POST.get('ro_status')
        claim_id_post = int(request.POST.get('claim_id'))
        user_id = request.user.id
    
        ro_status = get_object_or_404(RoStatus, id=ro_status_post)

        claim = get_object_or_404(Claim, id=claim_id_post)
        claim.ro_status = ro_status
        claim.save()

        update_event = event_log(claim_id_post, line=None, user=user_id, comment=f"user set the repair order status to {claim.ro_status.name} ")

        # Get the success URL
        forwarding_url = request.META.get('HTTP_REFERER', '/default-url/')

        # Return the success URL as JSON response
        return redirect(forwarding_url)
    
    return HttpResponseBadRequest('Invalid request or missing data')

def get_claim_status_totals(dealership_id, start_date, end_date):
    line_tables = LineTable.objects.filter(dealership_id=dealership_id, modified_date__range=(start_date, end_date))

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

def search_repair_order(request):
    if request.method == 'GET':
        dealership_id = request.GET.get('dealership_id', '')
        repair_order = request.GET.get('repair_order', '')

        # Perform a case-insensitive search for repair order numbers within the specified dealership
        claims = Claim.objects.filter(dealership_id=dealership_id, repair_order__icontains=repair_order)

        # Create a list of dictionaries containing repair order number and ID
        repair_orders = [{'id': claim.id, 'repair_order_number': claim.repair_order} for claim in claims]
        print(repair_orders)

        context = {
            'repair_orders': claims,
            'dealership_id': dealership_id,
            'repair_order': repair_order,
        }

        return render(request, 'claim/search_list.html', context)

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
def get_compliance(request, dealership_id):
    # Get the 'Dealership' id from the URL
    dealership = get_object_or_404(Dealership, id=dealership_id)

    # Count the total number of 'Paid' entries
    total_paid = LineTable.objects.filter(claim_status__name='Paid', dealership=dealership).count()

    # Count the number of 'Paid' entries with 'compliant' set to 'False'
    non_compliant_paid = LineTable.objects.filter(claim_status__name='Paid', compliant=False, dealership=dealership).count()

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
    dealership_obj = get_object_or_404(Dealership, name=dealership)
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    report_type = request.GET.get('report_type')

    #start_date = datetime.strptime(start_date_str, '%B %d, %Y').date()
    #end_date = datetime.strptime(end_date_str, '%B %d, %Y').date()

    start_date = datetime.strptime(start_date_str, '%d %b, %Y').date()
    end_date = datetime.strptime(end_date_str, '%d %b, %Y').date()

    report = view.generate_report(dealership_obj.id, report_type, start_date, end_date)
    claim_status_totals = get_claim_status_totals(dealership_obj.id, start_date, end_date)

    current_date = date.today()

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
        dealership = get_object_or_404(Dealership, id=dealership_id)
        context['dealership'] = dealership.name
        context['dealerships'] = Dealership.objects.all()
        user = self.request.user
        is_superuser = user.is_superuser
        context['is_superuser'] = is_superuser
        #context['reports'] = ['Daily Report', 'Discrepancy', 'Open RO Report']
        context['reports'] = ['Daily Report']
        context['report_type'] = 'Daily Report'
        current_date = date.today()
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
            line_tables = LineTable.objects.filter(dealership_id=dealership_id, modified_date__range=(start, end)).order_by('claim__repair_order')
            print("Here are the tables lines \n")

            for line in line_tables:
                print(f"ID: {line.id}, Name: {line.claim_id}, LineNum: {line.line_num}")

            report = []

            paid_claim_total = 0
            requires_attention_claim_total = 0
            pending_claim_total = 0
            rejected_claim_total = 0
            not_submitted_claim_total = 0

            for line in line_tables:
                repair_order = line.claim.repair_order
                print("This is the repair order:", repair_order)
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
                    lines = LineTable.objects.filter(claim__repair_order=repair_order, modified_date__range=(start, end)).distinct()
                    line_ids = lines.values_list('id', flat=True)
                    

                    line_data = []

                    # This needs updating since it gets comments by a specific user ID. needs update
                    for line_id in line_ids:
                        print("Here is the line ID:", line_id)
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
            line_tables = LineTable.objects.filter(dealership_id=dealership_id, modified_date__range=(start, end), claim__ro_status__name='Open', claim_status__name='Paid').exclude(claim_status__name='New')

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
            dealership = get_object_or_404(Dealership, name=dealership_name)
            dealership_id = dealership.id

            report_type = form.cleaned_data['report_type']
            start_date_str = form.cleaned_data['start']
            end_date_str = form.cleaned_data['end']

            print(start_date_str)

            start_date = datetime.strptime(start_date_str, '%d %b, %Y').date()
            end_date = datetime.strptime(end_date_str, '%d %b, %Y').date()

            print("Reformatted Date", start_date)

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
    print(f"GLOBAL SEARCH QUERY: [{query}]")
    claims = Claim.objects.none()

    if query:
        if query.isdigit():
            claims = (
                Claim.objects
                .select_related("dealership", "ro_status")
                .filter(repair_order=int(query))
                .order_by("dealership__name", "-modified_date")
            )
            print(f"SQL QUERY: {claims.query}")
            print(f"RESULT COUNT: {claims.count()}")

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
        return get_object_or_404(LineTable, id=line_id)

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

