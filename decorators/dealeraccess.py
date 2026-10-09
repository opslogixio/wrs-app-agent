from functools import wraps
from django.shortcuts import get_object_or_404, redirect
from django.http import HttpResponseForbidden
from accounts.models import Dealership 

def user_has_dealership_access(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        dealership_id = kwargs.get('pk')
        redirect_url = request.session.get('redirect_url')

        # Ensure the user has access to the requested dealership
        dealership = get_object_or_404(Dealership, id=dealership_id)

        #print("We have access to this dealership ", dealership)

        if dealership not in request.user.dealership.all():
            return redirect(request.META.get('HTTP_REFERER', redirect_url))

        return view_func(request, *args, **kwargs)

    return wrapper
