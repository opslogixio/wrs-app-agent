"""Keep calendar-day selection and stored timestamps in the application's time zone."""
from datetime import date, datetime, time

from django import forms
from django.utils import timezone


def as_date(value):
    if isinstance(value, datetime):
        return timezone.localdate(value) if timezone.is_aware(value) else value.date()
    return date.fromisoformat(value) if isinstance(value, str) else value


def as_datetime(value):
    if value is None:
        return None
    if not isinstance(value, datetime):
        value = datetime.combine(as_date(value), time.min)
    return timezone.make_aware(value) if timezone.is_naive(value) else value


def datetime_input(value):
    return timezone.localtime(as_datetime(value)).strftime('%Y-%m-%dT%H:%M:%S') if value else ''


def clean_datetime(value):
    return forms.DateTimeField(required=False, input_formats=[
        '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M', '%Y-%m-%d', '%B %d, %Y',
    ]).clean(value)
