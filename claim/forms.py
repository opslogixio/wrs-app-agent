from .validators import validate_pdf
from django import forms
from django.core.exceptions import ValidationError
from decimal import Decimal, InvalidOperation
from .models import Claim, Journal, PdfFile, RoStatus, Dealership, LineTable, ClaimType, Discrepancy, CustomUser, Status, Tag

class ClaimForm(forms.ModelForm):
    dealership = forms.ModelChoiceField(queryset=Dealership.objects.all())
    claim_tag = forms.ModelMultipleChoiceField(queryset=Tag.objects.all(), widget=forms.CheckboxSelectMultiple(), required=True)

    class Meta:
        model = Claim
        fields = ['dealership','repair_order', 'claim_tag']
        widgets = {
            'repair_order': forms.TextInput(attrs={'placeholder': 'Enter Repair Order Number'}),
            #'claim_tag': forms.TextInput(attrs={'placeholder': 'Enter Claim Tag'}),
        }
    #def __init__(self, *args, **kwargs):
    #    super().__init__(*args, **kwargs)
    #    self.fields['claim_tag'].widget = forms.CheckboxSelectMultiple()
    #    self.fields['claim_tag'].queryset = Tag.objects.all()

    def clean_repair_order(self):
        repair_order = self.cleaned_data.get('repair_order')
        dealership = self.cleaned_data.get('dealership')

        if Claim.objects.filter(dealership=dealership, repair_order=repair_order).exists():
            raise forms.ValidationError("A claim with this repair order number already exists.")
        return repair_order

class JournalForm(forms.ModelForm):
    class Meta:
        model = Journal
        fields = ['comment']
        widgets = {
            'comment': forms.Textarea(attrs={'placeholder': 'Enter Comment'}),
        }

class PdfFileForm(forms.ModelForm):
    pdf_file = forms.FileField(label='Upload PDF File', required=False, validators=[validate_pdf])

    class Meta:
        model = PdfFile
        fields = ['pdf_file']

class ClaimUpdateForm(forms.ModelForm):
    claim_tag = forms.ModelMultipleChoiceField(
        queryset=Tag.objects.all(),
        required=False,
        widget=forms.CheckboxSelectMultiple
    )

    class Meta:
        model = Claim
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['ro_status'].empty_label = None

        self.fields['dealership'].widget = forms.Select(choices=Dealership.objects.all().values_list('id', 'name'))
        self.fields['ro_status'].widget = forms.Select(choices=RoStatus.objects.all().values_list('id', 'name'))

class LineUpdateForm(forms.ModelForm):
    service_writer = forms.ModelChoiceField(queryset=CustomUser.objects.all())
    technician = forms.ModelChoiceField(queryset=CustomUser.objects.all())

    class Meta:
        model = LineTable
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['claim_type'].widget = forms.Select(choices=ClaimType.objects.all().values_list('id', 'name'))
        self.fields['discrepancy'].widget = forms.Select(choices=Discrepancy.objects.all().values_list('id'))

    def clean_start_date(self):
        start_date = self.cleaned_data.get('start_date')
        if not start_date:
            return None
        return start_date

class ClaimLineUpdateForm(forms.ModelForm):
    class Meta:
        model = Claim
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['dealership'].widget = forms.Select(choices=Dealership.objects.all().values_list('id', 'name'))
        self.fields['ro_status'].widget = forms.Select(choices=RoStatus.objects.all().values_list('id', 'name'))
        self.line_form = LineUpdateForm(*args, **kwargs)

    def is_valid(self):
        return super().is_valid() and self.line_form.is_valid()

    def save(self, commit=True):
        claim = super().save(commit=commit)
        line = self.line_form.save(commit=False)
        line.claim = claim
        if commit:
            line.save()
        return claim

class ClaimLineUpdateForm(forms.ModelForm):
    line_num = forms.CharField(max_length=50)
    claim_type = forms.ModelChoiceField(queryset=ClaimType.objects.all())
    service_writer = forms.ModelChoiceField(queryset=CustomUser.objects.filter(groups__name='Service Writer'))
    technician = forms.ModelChoiceField(queryset=CustomUser.objects.filter(groups__name='Technician'))
    claim_total = forms.CharField(max_length=20, required=False)
    claim_status = forms.ModelChoiceField(queryset=Status.objects.all())
    compliant = forms.BooleanField(required=False)
    discrepancy_labor = forms.DecimalField(max_digits=10, decimal_places=2, required=False)
    discrepancy_parts = forms.DecimalField(max_digits=10, decimal_places=2, required=False)
    discrepancy_maint = forms.DecimalField(max_digits=10, decimal_places=2, required=False)
    discrepancy_other = forms.DecimalField(max_digits=10, decimal_places=2, required=False)
    comment = forms.CharField(widget=forms.Textarea, required=False)
    pdf_name = forms.CharField(max_length=100, required=False)
    pdf_file = forms.FileField(required=False, validators=[validate_pdf])

    class Meta:
        model = Claim
        fields = ['repair_order', 'ro_status', 'claim_tag']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['claim_status'].empty_label = None
        self.fields['ro_status'].empty_label = None

        instance = kwargs.get('instance')
        if instance:
            line_table = instance.linetable_set.first()
            if line_table:
                self.fields['line_num'].initial = line_table.line_num
                self.fields['claim_type'].initial = line_table.claim_type
                self.fields['service_writer'].initial = line_table.service_writer
                self.fields['technician'].initial = line_table.technician
                self.fields['claim_total'].initial = line_table.claim_total
                self.fields['claim_status'].initial = line_table.claim_status
                self.fields['compliant'].initial = line_table.compliant
                if line_table.discrepancy:
                    self.fields['discrepancy_labor'].initial = line_table.discrepancy.labor
                    self.fields['discrepancy_parts'].initial = line_table.discrepancy.parts
                    self.fields['discrepancy_maint'].initial = line_table.discrepancy.maint
                    self.fields['discrepancy_other'].initial = line_table.discrepancy.other
            journal = instance.journal_set.first()
            if journal:
                self.fields['comment'].initial = journal.comment
            pdf_file = instance.pdffile_set.first()
            if pdf_file:
                self.fields['pdf_name'].initial = pdf_file.pdf_name

    def save(self, commit=True):
        claim = super().save(commit)
        line_table = claim.linetable_set.first()
        if line_table:
            line_table.line_num = self.cleaned_data['line_num']
            line_table.claim_type = self.cleaned_data['claim_type']
            line_table.service_writer = self.cleaned_data['service_writer']
            line_table.technician = self.cleaned_data['technician']
            line_table.claim_total = self.cleaned_data['claim_total']
            line_table.claim_status = self.cleaned_data['claim_status']
            line_table.compliant = self.cleaned_data['compliant']
            if line_table.discrepancy:
                line_table.discrepancy.labor = self.cleaned_data['discrepancy_labor']
                line_table.discrepancy.parts = self.cleaned_data['discrepancy_parts']
                line_table.discrepancy.maint = self.cleaned_data['discrepancy_maint']
                line_table.discrepancy.other = self.cleaned_data['discrepancy_other']
                line_table.discrepancy.save()
            line_table.save()
        else:
            line_table = LineTable.objects.create(
                line_num=self.cleaned_data['line_num'],
                claim_type=self.cleaned_data['claim_type'],
                service_writer=self.cleaned_data['service_writer'],
                technician=self.cleaned_data['technician'],
                claim_total=self.cleaned_data['claim_total'],
                claim_status=self.cleaned_data['claim_status'],
                compliant=self.cleaned_data['compliant'],
                claim=claim
            )
            discrepancy = Discrepancy.objects.create(
                labor=self.cleaned_data['discrepancy_labor'],
                parts=self.cleaned_data['discrepancy_parts'],
                maint=self.cleaned_data['discrepancy_maint'],
                other=self.cleaned_data['discrepancy_other']
            )
            line_table.discrepancy = discrepancy
            line_table.save()

        journal = claim.journal_set.first()
        if journal:
            journal.comment = self.cleaned_data['comment']
            journal.save()
        else:
            Journal.objects.create(
                comment=self.cleaned_data['comment'],
                line=line_table,
                claim=claim
            )

        pdf_file = claim.pdffile_set.first()
        if pdf_file:
            pdf_file.pdf_name = self.cleaned_data['pdf_name']
            pdf_file.save()
        else:
            PdfFile.objects.create(
                pdf_name=self.cleaned_data['pdf_name'],
                pdf_file=self.cleaned_data['pdf_file'],
                claim=claim
            )

        return claim
    
class DiscrepancyForm(forms.ModelForm):
    class Meta:
        model = Discrepancy
        fields = ['labor', 'parts', 'maint', 'other', 'core', 'rental', 'sublet']

### REPORT FORMS ##############

class ReportsForm(forms.Form):
    dealership = forms.ModelChoiceField(queryset=Dealership.objects.all(), empty_label=None, to_field_name='name')
    report_type = forms.ChoiceField(choices=[('Daily Report', 'Daily Report'), ('Discrepancy', 'Discrepancy'), ('Open RO Report', 'Open RO Report')])
    start = forms.CharField(max_length=20)
    end = forms.CharField(max_length=20)

### LINE VIEW FORMS #############

class LinePdfFileForm(forms.ModelForm):
    pdf_file = forms.FileField(label='Upload PDF File')

    class Meta:
        model = PdfFile
        fields = ['pdf_file']