from django.contrib.auth.backends import ModelBackend
from django.urls import reverse
from decorators.access import group_names, is_wrs_admin


class CustomBackend(ModelBackend):
    def get_user_dashboard_redirect_url(self, user):
        if is_wrs_admin(user):
            return reverse('dashboard:admin_dashboard')
        if 'dealer-admin' in group_names(user):
            return reverse('dashboard:dealer_admin_dashboard')
        return reverse('dashboard:user_dashboard')

    def get_user_redirect_url(self, user):
        return self.get_user_dashboard_redirect_url(user)

    def get_redirect_url(self, user):
        return self.get_user_redirect_url(user)

    def authenticate(self, request, username=None, password=None, **kwargs):
        user = super().authenticate(request, username=username, password=password, **kwargs)
        if user is not None:
            user.redirect_url = self.get_redirect_url(user)
            if request is not None:
                request.session['redirect_url'] = user.redirect_url
        return user
