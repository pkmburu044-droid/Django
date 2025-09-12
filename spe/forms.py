from django import forms
from .models import (
    NonTeachingStaffEvaluation,
    SPEPeriod,
    SPEAttribute,
    SPEIndicator,
    TeachingStaffEvaluation,
)

# ============================
# 1. Non-Teaching Staff Form
# ============================
class NonTeachingStaffEvaluationForm(forms.ModelForm):
    """
    Filled by non-teaching staff.
    Allows them to select period, attribute, indicator,
    rate themselves, and add remarks.
    """
    class Meta:
        model = NonTeachingStaffEvaluation
        fields = ['period', 'attribute', 'indicator', 'rating', 'remarks']
        widgets = {
            'period': forms.Select(attrs={'class': 'form-select'}),
            'attribute': forms.Select(attrs={'class': 'form-select'}),
            'indicator': forms.Select(attrs={'class': 'form-select'}),
            'rating': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 5}),
            'remarks': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

class TeachingStaffEvaluationForm(forms.ModelForm):
    class Meta:
        model = TeachingStaffEvaluation
        fields = ['period', 'attribute', 'indicator', 'rating', 'remarks']
        widgets = {
            'period': forms.Select(attrs={'class': 'form-select'}),
            'attribute': forms.Select(attrs={'class': 'form-select'}),
            'indicator': forms.Select(attrs={'class': 'form-select'}),
            'rating': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 5}),
            'remarks': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


# ============================
# 2. Supervisor Forms
# ============================
class SPEPeriodForm(forms.ModelForm):
    """Supervisor creates evaluation periods (e.g., Mid-Year 2025)."""
    class Meta:
        model = SPEPeriod
        fields = ['name', 'start_date', 'end_date', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'start_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'end_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class SPEAttributeForm(forms.ModelForm):
    """Supervisor defines evaluation attributes (e.g., Teamwork, Discipline)."""
    class Meta:
        model = SPEAttribute
        fields = ['period', 'name']
        widgets = {
            'period': forms.Select(attrs={'class': 'form-select'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
        }


class SPEIndicatorForm(forms.ModelForm):
    """Supervisor defines evaluation indicators under each attribute."""
    class Meta:
        model = SPEIndicator
        fields = ['attribute', 'description']
        widgets = {
            'attribute': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.TextInput(attrs={'class': 'form-control'}),
        }
