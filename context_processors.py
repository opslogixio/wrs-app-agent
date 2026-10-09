from accounts.models import Dealership

def user_dealerships(request):
    context = {}

    if request.user.is_authenticated:
        # Get associated dealerships
        dealerships = Dealership.objects.filter(users=request.user)
        context['user_dealerships'] = dealerships
        # Get redirect URL from session
        redirect_url = request.session.get('redirect_url')
        #print("This is the redirect URL:", redirect_url)
        context['redirect_url'] = redirect_url
        #print("This is how many dealerships assigned", dealerships.count())
        # Check the number of dealerships the user is assigned to
        if dealerships.count() > 1:
            context['user_stat'] = 'multi_user'
        else:
            context['user_stat'] = 'single_user'

    #return {'user_dealerships': dealerships}
    return context
