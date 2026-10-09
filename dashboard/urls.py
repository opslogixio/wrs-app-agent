from django.urls import path
from . import views
from .views import get_charts_data, get_compliance

app_name = 'dashboard'

urlpatterns = [
    # ...
    path('', views.dashboard_view, name='dashboard'),
    path('admin/', views.admin_dashboard_view, name='admin_dashboard'),
    path('dealer-admin/', views.dealer_admin_dashboard_view, name='dealer_admin_dashboard'),
    path('dealer/<int:pk>', views.dealer_dashboard_view, name='dealer_dashboard'),
    path('user/', views.user_dashboard_view, name='user_dashboard'),
    path('get-charts-data/<int:dealership_id>/', get_charts_data, name='get_charts_data'),


    # ...
]