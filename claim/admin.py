from django.contrib import admin
from .models import ClaimType, Status, RoStatus, Dealership, Tag

# Register your models here.

admin.site.register(ClaimType)
admin.site.register(Status)
admin.site.register(RoStatus)
admin.site.register(Dealership)
admin.site.register(Tag)

