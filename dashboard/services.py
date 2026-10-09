from core.dates import as_datetime
"""Dashboard totals in three queries, independent of dealership count."""
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, Exists, F, OuterRef, Q, Sum
from django.utils.timezone import localdate

from claim.models import Claim, LineTable


COUNT_TOTALS = {
    'agg_new_claims_count': 'new_claims_count',
    'agg_pending_claims_count': 'pending_claims_count',
    'agg_requires_attention_claims_count': 'requires_attention_claims_count',
    'agg_rework_claims_count': 'rework_claims_count',
    'agg_paid_claims_nc_count': 'paid_claims_nc_count',
    'agg_requires_attention_expire_count': 'requires_attention_expire_count',
    'agg_open_ro_count': 'open_ro_count',
}
MONEY_TOTALS = {
    'agg_pending_claims_total': 'pending_claims_total',
    'agg_requires_attention_total': 'requires_attention_claims_total',
    'agg_rework_totals': 'rework_claims_total',
    'agg_paid_claims_nc_total': 'paid_claims_nc_total',
    'agg_requires_attention_expire_total': 'requires_attention_expire_total',
    'agg_in_queue_total': 'in_queue_total',
    'agg_monthly_total': 'paid_claims_monthly_total',
    'agg_yearly_total': 'paid_claims_yearly_total',
}


def build_dashboard(dealerships):
    dealerships = list(dealerships)
    ids = [dealer.pk for dealer in dealerships]
    today = localdate()
    month_start = today.replace(day=1)
    previous_start = (month_start - timedelta(days=1)).replace(day=1)
    next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    year_start, year_end = date(today.year, 1, 1), date(today.year + 1, 1, 1)
    paid = Q(claim_status__name='Paid')
    attention = Q(claim_status__name='Requires Attention')
    filters = {
        'new_claims': Q(claim_status__name='New'),
        'pending_claims': Q(claim_status__name='Pending'),
        'requires_attention_claims': attention,
        'rework_claims': Q(claim_status__name='Rework'),
        # Retain the existing dashboard's compliant=True financial metric.
        'paid_claims_nc': paid & Q(compliant=True),
        'requires_attention_expire': attention & Q(start_date__date__lte=today - timedelta(days=90)),
    }
    annotations = {}
    for name, condition in filters.items():
        annotations[name + '_count'] = Count('pk', filter=condition)
        if name != 'new_claims':
            annotations[name + '_total'] = Sum('claim_total', filter=condition)
    annotations.update({
        'in_queue_total': Sum('claim_total', filter=Q(claim_status__name__in=['Pending', 'Rework', 'Requires Attention'])),
        'paid_claims_monthly_total': Sum('claim_total', filter=paid & Q(paid_date__gte=as_datetime(month_start), paid_date__lt=as_datetime(next_month))),
        'paid_claims_previous_total': Sum('claim_total', filter=paid & Q(paid_date__gte=as_datetime(previous_start), paid_date__lt=as_datetime(month_start))),
        'paid_claims_yearly_total': Sum('claim_total', filter=paid & Q(paid_date__gte=as_datetime(year_start), paid_date__lt=as_datetime(year_end))),
        'compliance_count': Count('pk', filter=paid & Q(created_date__gte=as_datetime(year_start), created_date__lt=as_datetime(year_end))),
        'noncompliance_count': Count('pk', filter=paid & Q(compliant=False, created_date__gte=as_datetime(year_start), created_date__lt=as_datetime(year_end))),
    })
    grouped = {row['dealership_id']: row for row in (
        LineTable.objects.filter(dealership_id__in=ids, dealership_id=F('claim__dealership_id'))
        .order_by().values('dealership_id').annotate(**annotations)
    )}
    blocked = LineTable.objects.filter(
        claim_id=OuterRef('pk'), claim_status__name__in=['New', 'Pending', 'Requires Attention', 'Rework'],
    )
    open_rows = {row['dealership_id']: row for row in (
        Claim.objects.filter(dealership_id__in=ids, ro_status__name='Open')
        .filter(~Exists(blocked)).order_by().values('dealership_id')
        .annotate(open_ro_count=Count('pk', distinct=True), open_ro_total=Sum('linetable__claim_total', filter=Q(linetable__dealership_id=F('dealership_id'))))
    )}
    totals = dict.fromkeys([*COUNT_TOTALS, *MONEY_TOTALS], 0)
    dashboard = []
    for dealer in dealerships:
        metrics = {name: grouped.get(dealer.pk, {}).get(name) or 0 for name in annotations}
        metrics.update(open_rows.get(dealer.pk, {'open_ro_count': 0, 'open_ro_total': 0}))
        metrics['open_ro_total'] = metrics['open_ro_total'] or 0
        paid_count = metrics.pop('compliance_count')
        noncompliant = metrics.pop('noncompliance_count')
        metrics['claim_compliance'] = (paid_count - noncompliant) / paid_count * 100 if paid_count else 100
        for key, metric in {**COUNT_TOTALS, **MONEY_TOTALS}.items():
            totals[key] += metrics[metric]
        for key in metrics:
            if key.endswith('_total'):
                metrics[key] = f'{Decimal(metrics[key]):,.2f}'
        metrics.update(dealership=dealer.name, dealership_id=dealer.pk, dealership_compliance=dealer.compliance_enable)
        dashboard.append(metrics)
    for key in MONEY_TOTALS:
        totals[key] = f'{Decimal(totals[key]):,.2f}'
    return dashboard, totals
