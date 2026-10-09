from django.urls import path
from .views import audit_event_list

app_name = "auditlog"

urlpatterns = [
    path("events/", audit_event_list, name="event_list"),
]
