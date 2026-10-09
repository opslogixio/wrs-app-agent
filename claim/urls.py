from django.urls import path
from django.contrib.auth.decorators import login_required
from django.views.generic.base import TemplateView
from .views import ClaimFormView, ClaimListView, ClaimQueueListView, RaClaimQueueListView, PendingClaimQueueListView, ReworkClaimQueueListView, NewClaimQueueListView, ClaimDetailView, xClaimUpdateView, ClaimLineUpdateView, UpdateClaim, DeleteClaim, xUpdateClaimLine, UpdateJournal, DeleteJournal, DiscrepancyCreate, DealerClaimLineUpdateView, EventViewer, ComplianceView, UpdateDiscrepancy, DeleteDiscrepancy, upload_pdf, global_comment, line_update, add_line, delete_line, add_start_date, update_ro_status, search_repair_order, get_compliance, global_search

app_name = 'claim'

urlpatterns = [
    path('claim-form/<int:dealership_id>/', login_required(ClaimFormView.as_view()), name='claim-form'),
    path('queue/<str:filter_request>', login_required(ClaimQueueListView.as_view()), name='claim-queue'),
    path('ra_queue/<str:filter_request>', login_required(RaClaimQueueListView.as_view()), name='ra-claim-queue'),
    path('pending_queue/<str:filter_request>', login_required(PendingClaimQueueListView.as_view()), name='pending-claim-queue'),
    path('rework_queue/<str:filter_request>', login_required(ReworkClaimQueueListView.as_view()), name='rework-claim-queue'),
    path('new_queue/<str:filter_request>', login_required(NewClaimQueueListView.as_view()), name='new-claim-queue'),
    path('not-authorized/', TemplateView.as_view(template_name='claim/not-authorized.html'), name='not-authorized'),
    # This path is for Super Admin to make claim updates
    path('update/<int:pk>/<int:dealership_id>/', ClaimLineUpdateView.as_view(), name='claim-update'),
    # This path is for the dealer to make smaller updates
    path('dealer_update/<int:pk>/<int:dealership_id>/', DealerClaimLineUpdateView.as_view(), name='dealer-claim-update'),
    path('update_claim/<str:dealership>/<int:repair_order>/', UpdateClaim.as_view(), name='update-claim'),
    path('delete_claim/<str:dealership>/<int:repair_order>/', DeleteClaim.as_view(), name='delete-claim'),
    path('update_journal/<int:journal_id>', UpdateJournal.as_view(), name='update-journal'),
    path('journal/delete/<int:journal_id>/',DeleteJournal.as_view(),name='delete-journal'),
    path('update_discrepancy/<int:discrepancy_id>/<int:line_id>', UpdateDiscrepancy.as_view(), name='update-discrepancy'),
    path('delete_discrepancy/<int:discrepancy_id>/<int:line_id>/', DeleteDiscrepancy.as_view(), name='delete-discrepancy'),
    path('discrepancy/<int:line_id>/', DiscrepancyCreate.as_view(), name='discrepancy'),
    #path('update_claim_line/<int:line_id>/', UpdateClaimLine.as_view(), name='update-claim-line'),
    path('events/', EventViewer.as_view(), name='events'),
    path('compliance/<int:dealership_id>/', ComplianceView.as_view(), name='compliance'),
    

    #### functions  ####### 
    path('upload_pdf/', upload_pdf, name='upload-pdf'),
    path('global_comment/', global_comment, name='global-comment'),
    path('line_updates/', line_update, name='line-updates'),
    path('add_line/', add_line, name='add-line'),
    path('delete_line/<int:line_id>/', delete_line, name='delete-line'),
    path('add_dec/<int:line_id>/', delete_line, name='delete-line'),
    path('start_date/<int:line_id>/', add_start_date, name='start-date'),
    path('ro_status/', update_ro_status, name='ro-status'),
    path('search_ro/', search_repair_order, name='search-ro'),
    path("global-search/", global_search, name="global-search"),
    path('compliance_percentage/<int:dealership_id>/', get_compliance, name='compliance_percentage'),

    # retired links
    # path('claim-list/<int:dealership_id>/', login_required(ClaimListView.as_view()), name='claim-list'),
    # path('detail/<int:pk>/', ClaimDetailView.as_view(), name='claim-detail'),
]
