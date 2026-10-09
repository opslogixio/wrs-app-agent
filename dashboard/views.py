from decorators.access import in_group_required, get_dealership, safe_return_url
from django.db.models.functions import ExtractMonth
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.db import models
from django.http import HttpResponseRedirect, HttpResponse, HttpResponseBadRequest, JsonResponse, HttpResponseNotAllowed
from django.db.models import Sum, Case, When, Value, F, IntegerField, DecimalField, Count, Func, CharField
from django.db.models.functions import Coalesce
from datetime import datetime, date, timedelta
from collections import defaultdict
from django.utils.timezone import now
from django.views.decorators.http import require_GET
from django.contrib.auth.models import Group
from claim.models import Claim, Status, LineTable, ClaimType, RoStatus
from accounts.models import Dealership
from decorators.dealeraccess import user_has_dealership_access

@login_required
def dashboard_view(request):
    from accounts.custom_backend import CustomBackend
    redirect_url = CustomBackend().get_redirect_url(request.user)
    if request.user.is_authenticated and redirect_url:
        return redirect(redirect_url)  # Redirect to the user's login URL
    else:
        return render(request, 'dashboard/dashboard.html')


def build_dealer_dashboard(request, dealership_id):

    current_month = now().month
    current_year = now().year

    def format_total(total_amount):
        formatted_total_amount = "{:,.2f}".format(total_amount)
        return formatted_total_amount

    # Calculate previous month
    previous_month = current_month - 1
    if previous_month == 0:
        previous_month = 12
        current_year -= 1

    ninety_days_ago = date.today() - timedelta(days=90)

    dashboard_data = []

    agg_new_claims_count = 0
    agg_open_ro_count = 0
    agg_pending_claims_count = 0
    agg_requires_attention_claims_count = 0
    agg_rework_claims_count = 0
    agg_paid_claims_nc_count = 0
    agg_requires_attention_expire_count = 0
    
    agg_pending_claims_total = 0
    agg_requires_attention_total = 0
    agg_rework_totals = 0
    agg_paid_claims_nc_total = 0
    agg_requires_attention_expire_total = 0
    agg_in_queue_total = 0
    agg_yearly_total = 0

    try:
        dealership_obj = Dealership.objects.get(dealership_id=dealership_id)
        open_status = get_object_or_404(RoStatus, name='Open')

        ## claim counts and totals
        new_claims_count = LineTable.objects.filter(claim_status__name='New', dealership_id=dealership_obj.pk).count()

        pending_claims_info = LineTable.objects.filter(claim_status__name='Pending', dealership_id=dealership_obj.pk).aggregate(
            pending_claims_count=Count('id'),
            pending_claims_total=Sum('claim_total')
        )

        pending_claims_count = pending_claims_info['pending_claims_count']
        pending_claims_total = pending_claims_info['pending_claims_total'] or 0

        requires_attention_claims_info = LineTable.objects.filter(claim_status__name='Requires Attention', dealership_id=dealership_obj.pk).aggregate(
            requires_attention_claims_count=Count('id'),
            requires_attention_claims_total=Sum('claim_total')
        )
        requires_attention_claims_count = requires_attention_claims_info['requires_attention_claims_count']
        requires_attention_claims_total = requires_attention_claims_info['requires_attention_claims_total'] or 0

        rework_claims_info = LineTable.objects.filter(claim_status__name='rework', dealership_id=dealership_obj.pk).aggregate(
            rework_claims_count=Count('id'),
            rework_claims_total=Sum('claim_total')
        )
        rework_claims_count = rework_claims_info['rework_claims_count']
        rework_claims_total = rework_claims_info['rework_claims_total']

        paid_claims_nc_info = LineTable.objects.filter(claim_status__name='Paid', dealership_id=dealership_obj.pk, compliant=True).aggregate(
            paid_claims_nc_count=Count('id'),
            paid_claims_nc_total=Sum('claim_total')
        )
        paid_claims_nc_count = paid_claims_nc_info['paid_claims_nc_count']
        paid_claims_nc_total = paid_claims_nc_info['paid_claims_nc_total']
    
        in_queue_total = LineTable.objects.filter().exclude(claim_status__name__in=['Paid', 'New'], dealership_id=dealership_obj.pk).aggregate(total_amount=Sum('claim_total'))['total_amount'] or 0

        open_ro_count_info = Claim.objects.filter(dealership_id=dealership_obj.pk, ro_status=open_status).aaggregate(
            open_ro_count=Count('id') 
        )

        open_ro_count = open_ro_count_info['open_ro_count']
        pass

        # Filter the LineTable to get the count of 'Paid' claims that are 90 days or more old
        requires_attention_expire_info = LineTable.objects.filter(claim_status__name='Requires Attention', dealership_id=dealership_obj.pk, start_date__lte=ninety_days_ago).aggregate(
            requires_attention_expire_count=Count('id'),
            requires_attention_expire_total=Sum('claim_total')
        )
        requires_attention_expire_count = requires_attention_expire_info['requires_attention_expire_count']
        requires_attention_expire_total = requires_attention_expire_info['requires_attention_expire_total']

        paid_claims_monthly_total = LineTable.objects.filter(
            claim_status__name='Paid',
            paid_date__month=current_month,
            paid_date__year=current_year,
            dealership_id=dealership_obj.pk
        ).aggregate(total_amount=Sum('claim_total'))['total_amount'] or 0

        paid_claims_yearly_total = LineTable.objects.filter(
            claim_status__name='Paid',
            paid_date__year=current_year,
            dealership_id=dealership_obj.pk
        ).aggregate(total_amount=Sum('claim_total'))['total_amount'] or 0
            
        # Lets get totals for all dealerships
        agg_new_claims_count += new_claims_count
        agg_pending_claims_count += pending_claims_count
        agg_requires_attention_claims_count += requires_attention_claims_count
        agg_rework_claims_count += rework_claims_count
        agg_paid_claims_nc_count += paid_claims_nc_count
        agg_requires_attention_expire_count += requires_attention_expire_count
        agg_open_ro_count += open_ro_count

        agg_pending_claims_total += pending_claims_total
        agg_requires_attention_total += requires_attention_claims_total
        agg_rework_totals += rework_claims_total
        agg_paid_claims_nc_total += paid_claims_nc_total
        agg_requires_attention_expire_total += requires_attention_expire_total
        agg_in_queue_total += in_queue_total
           
        context = {
            'new_claims_count': new_claims_count,
            'pending_claims_count': pending_claims_count,
            'pending_claims_total': format_total(pending_claims_total),
            'requires_attention_claims_count': requires_attention_claims_count,
            'requires_attention_claims_total': format_total(requires_attention_claims_total),
            'rework_claims_count': rework_claims_count,
            'rework_claims_total': format_total(rework_claims_total),
            'paid_claims_nc_count': paid_claims_nc_count,
            'paid_claims_nc_total': format_total(paid_claims_nc_total),
            'requires_attention_expire_count': requires_attention_expire_count,
            'requires_attention_expire_total': format_total(requires_attention_expire_total),
            'open_ro_count': open_ro_count,
            'in_queue_total': format_total(in_queue_total),
            'paid_claims_monthly_total': format_total(paid_claims_monthly_total),
            'paid_claims_yearly_total': format_total(paid_claims_yearly_total),
        }

        dashboard_data.append(context)
            
    except ObjectDoesNotExist:
        pass

    aggregate_context = {
        'agg_pending_claims_total': format_total(agg_pending_claims_total),
        'agg_requires_attention_total': format_total(agg_requires_attention_total),
        'agg_rework_totals': format_total(agg_rework_totals),
        'agg_paid_claims_nc_total': format_total(agg_paid_claims_nc_total),
        'agg_requires_attention_expire_total': format_total(agg_requires_attention_expire_total),
        'agg_in_queue_total': format_total(agg_in_queue_total),
        'agg_new_claims_count': agg_new_claims_count,
        'agg_pending_claims_count': agg_pending_claims_count,
        'agg_requires_attention_claims_count': agg_requires_attention_claims_count,
        'agg_rework_claims_count': agg_rework_claims_count,
        'agg_paid_claims_nc_count': agg_paid_claims_nc_count,
        'agg_requires_attention_expire_count': agg_requires_attention_expire_count,
        'agg_open_ro_count': agg_open_ro_count

    }
    return dashboard_data, aggregate_context


def build_dashboard(dealerships):

    current_month = now().month
    current_year = now().year

    def format_total(total_amount):
        formatted_total_amount = "{:,.2f}".format(total_amount)
        return formatted_total_amount
    
    def get_previous_month_and_year(current_month, current_year):
        # Calculate previous month and year
        previous_month = current_month - 1
        if previous_month == 0:
            previous_month = 12
            previous_year = current_year - 1
        else:
            previous_year = current_year

        return previous_month, previous_year
    
    # Calculate previous month
    #previous_month = current_month - 1

    #if previous_month == 0:
    #    previous_month = 12
    #    current_year -= 1
    
    previous_month, previous_year = get_previous_month_and_year(current_month, current_year)

    ninety_days_ago = date.today() - timedelta(days=90)

    dashboard_data = []

    agg_new_claims_count = 0
    agg_open_ro_count = 0
    #print("this is outside the loop for new claims", agg_new_claims_count)
    agg_pending_claims_count = 0
    agg_requires_attention_claims_count = 0
    agg_rework_claims_count = 0
    agg_paid_claims_nc_count = 0
    agg_requires_attention_expire_count = 0
    
    agg_pending_claims_total = 0
    agg_requires_attention_total = 0
    agg_rework_totals = 0
    agg_paid_claims_nc_total = 0
    agg_requires_attention_expire_total = 0
    agg_in_queue_total = 0
    agg_yearly_total = 0
    agg_monthly_total = 0
    
    open_status = get_object_or_404(RoStatus, name='Open')
    for dealership in dealerships:
        try:
            dealership_obj = dealership
            pass
            ## claim counts and totals
            new_claims_count = LineTable.objects.filter(claim_status__name='New', dealership_id=dealership_obj.pk).count()

            pending_claims_info = LineTable.objects.filter(claim_status__name='Pending', dealership_id=dealership_obj.pk).aggregate(
                pending_claims_count=Count('id'),
                pending_claims_total=Sum('claim_total')
            )

            pending_claims_count = pending_claims_info['pending_claims_count']
            pending_claims_total = pending_claims_info['pending_claims_total'] or 0

            requires_attention_claims_info = LineTable.objects.filter(claim_status__name='Requires Attention', dealership_id=dealership_obj.pk).aggregate(
                requires_attention_claims_count=Count('id'),
                requires_attention_claims_total=Sum('claim_total')
            )
            requires_attention_claims_count = requires_attention_claims_info['requires_attention_claims_count']
            requires_attention_claims_total = requires_attention_claims_info['requires_attention_claims_total'] or 0

            rework_claims_info = LineTable.objects.filter(claim_status__name='rework', dealership_id=dealership_obj.pk).aggregate(
                rework_claims_count=Count('id'),
                rework_claims_total=Sum('claim_total')
            )
            rework_claims_count = rework_claims_info['rework_claims_count']
            rework_claims_total = rework_claims_info['rework_claims_total'] or 0

            paid_claims_nc_info = LineTable.objects.filter(claim_status__name='Paid', dealership_id=dealership_obj.pk, compliant=True).aggregate(
                paid_claims_nc_count=Count('id'),
                paid_claims_nc_total=Sum('claim_total')
            )
            paid_claims_nc_count = paid_claims_nc_info['paid_claims_nc_count']
            paid_claims_nc_total = paid_claims_nc_info['paid_claims_nc_total'] or 0

            paid_claims_info = LineTable.objects.filter(claim_status__name='Paid', dealership_id=dealership_obj.pk).aggregate(
                paid_claims_count=Count('id'),
                paid_claims_total=Sum('claim_total')
            )
            paid_claims_count = paid_claims_info['paid_claims_count']
            paid_claims_total = paid_claims_info['paid_claims_total'] or 0
    
            #in_queue_total = LineTable.objects.filter().exclude(claim_status__name__in=['Paid', 'New', 'No Warranty', 'Not Submitted', 'Rejected' ], dealership_id=dealership_obj.pk).aggregate(total_amount=Sum('claim_total'))['total_amount'] or 0
            in_queue_total = LineTable.objects.filter(claim_status__name__in=['Pending', 'Rework', 'Requires Attention'], dealership_id=dealership_obj.pk).aggregate(total_amount=Sum('claim_total'))['total_amount'] or 0

            # Filter the LineTable to get the count of 'Paid' claims that are 90 days or more old
            requires_attention_expire_info = LineTable.objects.filter(claim_status__name='Requires Attention', dealership_id=dealership_obj.pk, start_date__lte=ninety_days_ago).aggregate(
                requires_attention_expire_count=Count('id'),
                requires_attention_expire_total=Sum('claim_total')
            )
            requires_attention_expire_count = requires_attention_expire_info['requires_attention_expire_count']
            requires_attention_expire_total = requires_attention_expire_info['requires_attention_expire_total'] or 0

            paid_claims_monthly_total = LineTable.objects.filter(
                claim_status__name='Paid',
                paid_date__month=current_month,
                paid_date__year=current_year,
                dealership_id=dealership_obj.pk
            ).aggregate(total_amount=Sum('claim_total'))['total_amount'] or 0

            paid_claims_previous_total = LineTable.objects.filter(
            claim_status__name='Paid',
            paid_date__month=previous_month,
            paid_date__year=previous_year,
            claim__dealership=dealership
            ).aggregate(total_amount=Sum('claim_total'))['total_amount'] or 0
            
            pass
            pass
            pass

            paid_claims_yearly_total = LineTable.objects.filter(
                claim_status__name='Paid',
                paid_date__year=current_year,
                dealership_id=dealership_obj.pk
            ).aggregate(total_amount=Sum('claim_total'))['total_amount'] or 0
            
            #print("This is the yearly total", paid_claims_yearly_total, "for the current year", current_year)

            # Lets check how many open ROs we have that have been completed
            excluded_statuses = ['New', 'Pending', 'Requires Attention', 'Rework']

            # Exclude claims that have any line with one of the excluded statuses
            open_claims = Claim.objects.filter(
                dealership_id=dealership,
                ro_status=open_status
            ).exclude(
                id__in=Claim.objects.filter(
                    linetable__claim_status__name__in=excluded_statuses
                ).values('id')  # Get all claims that have lines with excluded statuses
            ).aggregate(
                open_ro_count=Count('id', distinct=True),  # Count only distinct claims
                open_ro_total=Sum('linetable__claim_total')  # Sum the total claim_total for valid claims
            )

            open_ro_count = open_claims['open_ro_count']
            open_ro_total = open_claims['open_ro_total'] or 0

            claim_compliance = get_compliance(dealership_obj.pk)
            # Lets get totals for all dealerships
            agg_new_claims_count += new_claims_count
            agg_pending_claims_count += pending_claims_count
            agg_requires_attention_claims_count += requires_attention_claims_count
            agg_rework_claims_count += rework_claims_count
            agg_paid_claims_nc_count += paid_claims_nc_count
            agg_requires_attention_expire_count += requires_attention_expire_count
            #agg_open_ro_count += open_ro_count

            agg_pending_claims_total += pending_claims_total
            agg_requires_attention_total += requires_attention_claims_total
            agg_rework_totals += rework_claims_total
            agg_paid_claims_nc_total += paid_claims_nc_total
            agg_requires_attention_expire_total += requires_attention_expire_total
            agg_in_queue_total += in_queue_total
            agg_monthly_total += paid_claims_monthly_total
            agg_yearly_total += paid_claims_yearly_total
           
            context = {
                'new_claims_count': new_claims_count,
                'pending_claims_count': pending_claims_count,
                'pending_claims_total': format_total(pending_claims_total),
                'requires_attention_claims_count': requires_attention_claims_count,
                'requires_attention_claims_total': format_total(requires_attention_claims_total),
                'rework_claims_count': rework_claims_count,
                'rework_claims_total': format_total(rework_claims_total),
                'paid_claims_nc_count': paid_claims_nc_count,
                'paid_claims_nc_total': format_total(paid_claims_nc_total),
                'requires_attention_expire_count': requires_attention_expire_count,
                'requires_attention_expire_total': format_total(requires_attention_expire_total),
                'in_queue_total': format_total(in_queue_total),
                'paid_claims_monthly_total': format_total(paid_claims_monthly_total),
                'paid_claims_previous_total': format_total(paid_claims_previous_total),
                'paid_claims_yearly_total': format_total(paid_claims_yearly_total),
                'open_ro_count': open_ro_count,
                'open_ro_total': format_total(open_ro_total),
                'dealership': dealership_obj.name,
                'dealership_id': dealership_obj.id,
                'dealership_compliance': dealership_obj.compliance_enable,
                'claim_compliance': claim_compliance,
            }

            dashboard_data.append(context)
            
        except ObjectDoesNotExist:
            pass

    aggregate_context = {
        'agg_pending_claims_total': format_total(agg_pending_claims_total),
        'agg_requires_attention_total': format_total(agg_requires_attention_total),
        'agg_rework_totals': format_total(agg_rework_totals),
        'agg_paid_claims_nc_total': format_total(agg_paid_claims_nc_total),
        'agg_requires_attention_expire_total': format_total(agg_requires_attention_expire_total),
        'agg_in_queue_total': format_total(agg_in_queue_total),
        'agg_new_claims_count': agg_new_claims_count,
        'agg_pending_claims_count': agg_pending_claims_count,
        'agg_requires_attention_claims_count': agg_requires_attention_claims_count,
        'agg_rework_claims_count': agg_rework_claims_count,
        'agg_paid_claims_nc_count': agg_paid_claims_nc_count,
        'agg_requires_attention_expire_count': agg_requires_attention_expire_count,
        'agg_open_ro_count': agg_open_ro_count,
        'agg_monthly_total': format_total(agg_monthly_total),
        'agg_yearly_total': format_total(agg_yearly_total)

    }
    return dashboard_data, aggregate_context


@in_group_required('wrs-admin')
def admin_dashboard_view(request):
    dealerships = Dealership.objects.filter(users=request.user)

    dashboard_data, aggregate_context = build_dashboard(dealerships)

    return render(request, 'dashboard/admin-dashboard.html', {'dashboard_items': dashboard_data, **aggregate_context})

@in_group_required('dealer-admin', 'wrs-admin')
def dealer_admin_dashboard_view(request):
    dealerships = Dealership.objects.filter(users=request.user)

    dashboard_data, aggregate_context = build_dashboard(dealerships)

    return render(request, 'dashboard/dealer-admin-dashboard.html', {'dashboard_items': dashboard_data, **aggregate_context})

@login_required
@user_has_dealership_access
def dealer_dashboard_view(request, pk):
    dealerships = Dealership.objects.filter(id=pk)

    dashboard_data, aggregate_context = build_dashboard(dealerships)

    return render(request, 'dashboard/dealer-dashboard.html', {'dashboard_items': dashboard_data, **aggregate_context})

@login_required
def user_dashboard_view(request):
    # Logic for user dashboard view
    return render(request, 'dashboard/user-dashboard.html')

# usable code
#for key, value in request.session.items():
    #    print(f"Session attribute - {key}: {value}")
    #print(request.session.get('redirect_url'))
    # Logic for user dashboard view

###################################################  FUNCTIONS  ##########################################

@login_required
@require_GET
def get_charts_data(request, dealership_id):
    dealership = get_dealership(request.user, dealership_id)
    current_year = now().year
    rows = (LineTable.objects.filter(
        dealership=dealership, claim_status__name='Paid',
        paid_date__gte=date(current_year, 1, 1), paid_date__lt=date(current_year + 1, 1, 1),
    ).order_by().annotate(month=ExtractMonth('paid_date'))
        .values('claim_type_id', 'month').annotate(total=Sum('claim_total')))
    totals = {(row['claim_type_id'], row['month']): row['total'] or 0 for row in rows}
    series = [
        {'name': claim_type.name, 'data': [totals.get((claim_type.pk, month), 0) for month in range(1, 13)]}
        for claim_type in ClaimType.objects.all()
    ]
    return JsonResponse({'series': series})


def get_compliance(dealership_id): ## NOT USED YET ###
    # Get the 'Dealership' id from the URL
    dealership = get_object_or_404(Dealership, id=dealership_id)

    current_year = now().year
    # Count the total number of 'Paid' entries
    total_paid = LineTable.objects.filter(claim_status__name='Paid', created_date__year=current_year, dealership=dealership).count()

    # Count the number of 'Paid' entries with 'compliant' set to 'False'
    non_compliant_paid = LineTable.objects.filter(claim_status__name='Paid', created_date__year=current_year, compliant=False, dealership=dealership).count()

    # Calculate the percentage
    percentage = 0
    if total_paid > 0:
        percentage = ((total_paid - non_compliant_paid) / total_paid) * 100
    else:
        percentage = 100

    data = {
        'compliance_percentage': percentage
    }

    return percentage