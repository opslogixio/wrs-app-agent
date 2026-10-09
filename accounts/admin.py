from django.contrib import admin
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin
from accounts.models import CustomUser, Dealership


class CustomUserAdmin(UserAdmin):
    model = CustomUser
    ordering = ['email']
    fieldsets = (
        (None, {
            'fields': ('email', 'password', 'dealership')
            }),
        ('Personal Info', {
            'fields': ('first_name', 'last_name')
            }),
        ('Daily Report Settings', {
            'fields': ('receive_daily_report', 'daily_report_email')
        }),
        ('Permissions', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'
                       )}),
        ('Important dates', {
            'fields': ('last_login', 'date_joined')
            }),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'password1', 'password2', 'receive_daily_report', 'daily_report_email'),
        }),
    )
    list_display = ['email', 'first_name', 'last_name', 'is_staff']
    search_fields = ['email', 'first_name', 'last_name']
    ordering = ['email']

admin.site.register(CustomUser, CustomUserAdmin)