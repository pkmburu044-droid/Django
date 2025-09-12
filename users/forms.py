from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import CustomUser, NonTeachingStaffProfile, NonTeachingAppraisal, TeachingStaffProfile, TeachingStaffAppraisal

# -------------------------------
# Custom User Form
# -------------------------------
class CustomUserCreationForm(UserCreationForm):
    role = forms.ChoiceField(
        choices=CustomUser.ROLE_CHOICES,
        required=True,
        label="Role",
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    class Meta:
        model = CustomUser
        fields = ('pf_number', 'role', 'password1', 'password2')
        widgets = {
            'pf_number': forms.TextInput(attrs={'class': 'form-control'}),
            'password1': forms.PasswordInput(attrs={'class': 'form-control'}),
            'password2': forms.PasswordInput(attrs={'class': 'form-control'}),
        }

# -------------------------------
# Non-Teaching Staff Form
# -------------------------------
class NonTeachingStaffProfileForm(forms.ModelForm):
    terms_of_service = forms.ChoiceField(
        choices=CustomUser.TERMS_OF_SERVICE_CHOICES,  # updated
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    class Meta:
        model = NonTeachingStaffProfile
        fields = ['designation', 'department', 'terms_of_service']
        widgets = {
            'designation': forms.TextInput(attrs={'class': 'form-control'}),
            'department': forms.TextInput(attrs={'class': 'form-control'}),
        }

# -------------------------------
# Non-Teaching Appraisal Form
# -------------------------------
class NonTeachingAppraisalForm(forms.ModelForm):
    class Meta:
        model = NonTeachingAppraisal
        fields = [
            'period_under_review',
            'length_of_service',
            'years_in_equivalent_position',
            'supervisor_name',
            'appraisal_date',
            'acting_or_special_duty',
        ]
        widgets = {
            'period_under_review': forms.TextInput(attrs={'class': 'form-control'}),
            'length_of_service': forms.TextInput(attrs={'class': 'form-control'}),
            'years_in_equivalent_position': forms.TextInput(attrs={'class': 'form-control'}),
            'supervisor_name': forms.TextInput(attrs={'class': 'form-control'}),
            'appraisal_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'acting_or_special_duty': forms.TextInput(attrs={'class': 'form-control'}),
        }

# -------------------------------
# Teaching Staff Form
# -------------------------------
class TeachingStaffProfileForm(forms.ModelForm):
    terms_of_service = forms.ChoiceField(
        choices=CustomUser.TERMS_OF_SERVICE_CHOICES,  # updated
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    class Meta:
        model = TeachingStaffProfile
        fields = ['designation', 'department', 'terms_of_service']
        widgets = {
            'designation': forms.TextInput(attrs={'class': 'form-control'}),
            'department': forms.TextInput(attrs={'class': 'form-control'}),
        }

# -------------------------------
# Teaching Staff Appraisal Form
# -------------------------------
class TeachingStaffAppraisalForm(forms.ModelForm):
    class Meta:
        model = TeachingStaffAppraisal
        fields = [
            'date_of_appointment',
            'acting_appointment',
            'years_experience_kyu',
            'years_experience_elsewhere',
            'supervisor_name',
            'supervisor_designation',
        ]
        widgets = {
            'date_of_appointment': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'acting_appointment': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
            'years_experience_kyu': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'years_experience_elsewhere': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'supervisor_name': forms.TextInput(attrs={'class': 'form-control'}),
            'supervisor_designation': forms.TextInput(attrs={'class': 'form-control'}),
        }
