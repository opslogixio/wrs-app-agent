from django.shortcuts import render, redirect
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, PasswordChangeView
from django.urls import reverse_lazy
from django.contrib.auth.decorators import login_required
from django.contrib.auth import views as auth_views
from django.contrib.auth.forms import PasswordChangeForm
from accounts.forms import CustomAuthenticationForm
from accounts.custom_backend import CustomBackend

    
class CustomLoginView(auth_views.LoginView):
    authentication_form = CustomAuthenticationForm
    template_name = 'auth/login.html'

    def get_success_url(self):
        #redirect_url = CustomBackend().get_redirect_url(self.request)
        redirect_url = CustomBackend().get_redirect_url(self.request.user)
        if redirect_url:
            return redirect_url
        return super().get_success_url()

    #def form_valid(self, form):
     #   redirect_url = self.get_success_url()
        #if redirect_url != self.request.path:
        #     #Check if the user is authenticated and has a redirect_url attribute
        #    if self.request.user.is_authenticated and hasattr(self.request.user, 'redirect_url'):
        #        redirect_url = CustomBackend().get_redirect_url(self.request.user)
        #    return redirect(redirect_url)
      #  return super().form_valid(form)

class CustomPasswordChangeView(LoginRequiredMixin, PasswordChangeView):
    template_name = 'auth/change_password.html'
    success_url = reverse_lazy('logout')
