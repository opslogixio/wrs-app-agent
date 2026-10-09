from functools import wraps
from django.contrib.auth.decorators import login_required
from .access import get_dealership


def user_has_dealership_access(view_func):
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        get_dealership(request.user, kwargs.get('pk'))
        return view_func(request, *args, **kwargs)
    return wrapper
