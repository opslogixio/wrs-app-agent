from django.urls import path
from reports.views import download_report, Reports, DailyReportsView, ArchiveDailyReportsView, OpenClaimsReportView, DiscrepancyReportView, RaReportView, update_ro_status, export_to_pdf, historical_claim_view, historical_linetable_view, historical_journal_view, list_report_files
from django.contrib.auth.decorators import login_required

app_name = 'reports'

urlpatterns = [
    path('download/<path:relative_path>', download_report, name='download-report'),
    path('<int:dealership_id>', Reports.as_view(), name='reports'),
    path('daily_reports_view/<int:dealership_id>', DailyReportsView.as_view(), name='daily-reports-view'),
    path('archive_daily_reports_view', ArchiveDailyReportsView.as_view(), name='archive-daily-reports-view'),
    path('open_reports_view/<int:dealership_id>', OpenClaimsReportView.as_view(), name='open-reports-view'),
    path('discrepancy_report/', DiscrepancyReportView.as_view(), name='discrepancy-report'),
    path('ra_report/<str:filter_request>', RaReportView.as_view(), name='ra-report'),
    path('ro_status', update_ro_status, name='ro-status'),
    path('report_export/', export_to_pdf, name='report-export'),
    #path('historical_data/', historical_data_view, name='historical-data'),

    # HISTORICAL
    path('historicalclaim/', historical_claim_view, name='historicalclaim-list'),
    path('historicallinetable/', historical_linetable_view, name='historicallinetable-list'),
    path('historicaljournal/', historical_journal_view, name='historicaljournal-list'),

    path('report-files/', list_report_files, name='report_file_browser'),

    #path('historicalclaim/', HistoricalClaimListView.as_view(), name='historicalclaim-list'),
    #path('historicalclaim/update/<int:pk>/', HistoricalClaimUpdateView.as_view(), name='historicalclaim-update'),
    #path('historicalclaim/delete/<int:pk>/', HistoricalClaimDeleteView.as_view(), name='historicalclaim-delete'),

    # HistoricalLineTable URLs
    #path('historicallinetable/', HistoricalLineTableListView.as_view(), name='historicallinetable-list'),
    #path('historicallinetable/update/<int:pk>/', HistoricalLineTableUpdateView.as_view(), name='historicallinetable-update'),
    #path('historicallinetable/delete/<int:pk>/', HistoricalLineTableDeleteView.as_view(), name='historicallinetable-delete'),

    # HistoricalJournal URLs
    #path('historicaljournal/', HistoricalJournalListView.as_view(), name='historicaljournal-list'),
    #path('historicaljournal/update/<int:pk>/', HistoricalJournalUpdateView.as_view(), name='historicaljournal-update'),
    #path('historicaljournal/delete/<int:pk>/', HistoricalJournalDeleteView.as_view(), name='historicaljournal-delete'),
]