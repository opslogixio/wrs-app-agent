"""Shared role and dealership authorization for HTTP views."""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils.http import url_has_allowed_host_and_scheme

from accounts.models import Dealership


def group_names(user):
    if not hasattr(user, '_wrs_groups'):
        user._wrs_groups = set(user.groups.values_list('name', flat=True))
    return user._wrs_groups


def is_wrs_admin(user):
    return user.is_authenticated and (user.is_superuser or 'wrs-admin' in group_names(user))


def in_group_required(*names):
    def decorate(view):
        @login_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not is_wrs_admin(request.user) and not group_names(request.user).intersection(names):
                raise PermissionDenied
            return view(request, *args, **kwargs)
        return wrapped
    return decorate


def accessible_dealerships(user):
    if not user.is_authenticated:
        return Dealership.objects.none()
    if is_wrs_admin(user):
        return Dealership.objects.all()
    return user.dealership.all()


def positive_id(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise Http404
    if number <= 0:
        raise Http404
    return number


def get_dealership(user, value):
    return get_object_or_404(accessible_dealerships(user), pk=positive_id(value))


def claims_for_user(user):
    from claim.models import Claim
    if is_wrs_admin(user):
        return Claim.objects.all()
    return Claim.objects.filter(dealership__in=accessible_dealerships(user))


def lines_for_user(user):
    from django.db.models import F
    from claim.models import LineTable
    # Reject inconsistent legacy rows instead of trusting an unrelated dealership FK.
    return LineTable.objects.filter(claim__in=claims_for_user(user), dealership_id=F('claim__dealership_id'))


def safe_return_url(request):
    target = request.META.get('HTTP_REFERER', '')
    if url_has_allowed_host_and_scheme(target, {request.get_host()}, require_https=request.is_secure()):
        return target
    return '/dashboard/'


class DealershipAccessMixin:
    def dispatch(self, request, *args, **kwargs):
        dealership_id = kwargs.get('dealership_id') or request.GET.get('dealership_id')
        self.authorized_dealership = get_dealership(request.user, dealership_id)
        if 'pk' in kwargs:
            claim = get_object_or_404(claims_for_user(request.user), pk=kwargs['pk'])
            if dealership_id is not None and claim.dealership_id != self.authorized_dealership.pk:
                raise Http404
        return super().dispatch(request, *args, **kwargs)
