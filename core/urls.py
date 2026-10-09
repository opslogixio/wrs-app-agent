"""core URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/3.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.contrib.auth.decorators import login_required
from django.contrib.auth import views as auth_views
from accounts import views
from django.views.generic import RedirectView
from dashboard import views as dashboard_views
from accounts.views import CustomLoginView, CustomPasswordChangeView
from claim.views import ReportsView, export_to_pdf
from claim.views import ReportsViewForm

urlpatterns = [
    path('admin/', admin.site.urls),
    path('claim/', include('claim.urls')),
    path('auditlog/', include('auditlog.urls')),
    path('accounts/login/', views.CustomLoginView.as_view(), name='login'),
    path('accounts/change_password/', views.CustomPasswordChangeView.as_view(), name='change-password'),
    #path('accounts/login/', CustomLoginView.as_view(template_name='login.html'), name='login'),
    path('accounts/', include('django.contrib.auth.urls')),  # Include authentication URLs
    #path('service-writers/', views.service_writers_view, name='service_writers'),
    #path('error/', views.error_view, name='error'),
    path('', RedirectView.as_view(pattern_name='dashboard:dashboard', permanent=False)),
    path('dashboard/', include('dashboard.urls')),

    ### REPORTS ###
    path('reports/', include('reports.urls')),
    #path('reports_view/', ReportsViewForm.as_view(), name='reports-view'),
    #path('<int:dealership_id>/reports/', ReportsView.as_view(), name='reports'),
    #path('export_pdf/', export_to_pdf, name='export_pdf'),
]
