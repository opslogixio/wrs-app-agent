from django import forms
from datetime import datetime
from accounts.models import Dealership, CustomUser

class ReportsForm(forms.Form):
    dealership = forms.ModelChoiceField(queryset=Dealership.objects.all(), empty_label=None, to_field_name='name')
    start = forms.CharField(max_length=20)

class ArchiveDailyReportsForm(forms.Form):
    dealership = forms.CharField(widget=forms.HiddenInput())
    report_type = forms.CharField(widget=forms.HiddenInput(), initial="archive-daily-reports-view")
    start = forms.DateField(required=True, label="Select a date")

class DiscrepancyReportsForm(forms.Form):
    dealership = forms.IntegerField(widget=forms.HiddenInput())  # Hidden input for dealership ID
    start_date = forms.DateField(required=True, label="Select a date")
    end_date = forms.DateField(required=True, label="Select a date")

class DiscrepancyReportsForms(forms.Form):
    dealership = forms.IntegerField(widget=forms.HiddenInput())  # Hidden input for dealership ID
    start_date = forms.CharField(widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Start Date'}))
    end_date = forms.CharField(widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'End Date'}))

    # Custom clean method to convert the CharField input to a date
    def clean_start_date(self):
        start_date = self.cleaned_data['start_date']
        try:
            return datetime.strptime(start_date, '%d %b, %Y').date()  # Convert 'dd M, yyyy' to a date object
        except ValueError:
            raise forms.ValidationError("Invalid start date format. Please use 'dd M, yyyy'.")

    def clean_end_date(self):
        end_date = self.cleaned_data['end_date']
        try:
            return datetime.strptime(end_date, '%d %b, %Y').date()  # Convert 'dd M, yyyy' to a date object
        except ValueError:
            raise forms.ValidationError("Invalid end date format. Please use 'dd M, yyyy'.")

