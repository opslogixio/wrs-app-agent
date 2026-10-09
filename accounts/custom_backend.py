from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.http import HttpResponseRedirect

class CustomBackend(ModelBackend):
    
    def user_can_access_admin_dashboard(self, user):
        #print("Admin Dashboard check: ", user)
        #return user.is_superuser
        return user.groups.filter(name='wrs-admin').exists()

    def user_can_access_dealer_dashboard(self, user):
        #print("Dealer Admin Check: ", user)
        return user.groups.filter(name='dealer-admin').exists()

    def get_user_dashboard_redirect_url(self, user):
        print("Determining dashboard for: ", user)
        if self.user_can_access_admin_dashboard(user):
            #print("Admin DASH")
            return reverse('dashboard:admin_dashboard')
        elif self.user_can_access_dealer_dashboard(user):
            #print("We are dealer")
            return reverse('dashboard:dealer_admin_dashboard') #changed to dealer_admin_dashboard from dealer_dashboard
        else:
            #print("We are just a user")
            return reverse('dashboard:user_dashboard')

    def get_user_redirect_url(self, user):       
        #print("Getting User redirect URL")
        #print(user)
        if hasattr(user, 'redirect_url'):
            return user.redirect_url
        else:
            return self.get_user_dashboard_redirect_url(user)

    def get_redirect_url(self, user):
        #print("We are getting redirect URL")
        #user_attributes = vars(user)
        #print(user_attributes)
        #print("This is the request HERE: ", request)
        #user = request.user
        return self.get_user_redirect_url(user)
    
    def authenticate(self, request, username=None, password=None, **kwargs):
        #print(username)
        #print("We are Authenticating")
        #print("Request: ", request)
        #print("Request User: ", request.user)
        user = super().authenticate(request, username=username, password=password, **kwargs)
        if user is not None and user.is_active and user.is_authenticated:
            #print("We are authenticated")
            #print("User Group:", user.groups.first().name if user.groups.exists() else "None")
            #if user.groups.filter(name='Dealer Admin').exists():
                #user.redirect_url = reverse('dashboard:dealer_dashboard')
                #print(user.login_redirect_url)
                #if user is not None:
            user.redirect_url = self.get_redirect_url(user)
            request.session['redirect_url'] = self.get_redirect_url(user)
  
                #print("Redirect URL:", user.redirect_url)
            user_attributes = vars(user)
            print("Here are all the attributes: ", user_attributes)
            return user
