from django import forms

from users.models import SelfAssessment, StaffProfile, SupervisorEvaluation

from .models import SPEAttribute, SPEIndicator, SPEPeriod


# ============================
# 1. Non-Teaching Staff Self-Assessment Form
# ============================
class NonTeachingSelfAssessmentForm(forms.ModelForm):
    class Meta:
        model = SelfAssessment
        fields = ["attribute", "indicator", "self_rating", "remarks"]
        widgets = {
            "attribute": forms.Select(attrs={"class": "form-select"}),
            "indicator": forms.Select(attrs={"class": "form-select"}),
            "self_rating": forms.NumberInput(
                attrs={"class": "form-control", "min": 1, "max": 5}
            ),
            "remarks": forms.Textarea(
                attrs={"class": "form-control", "rows": 3}
            ),
        }

    def __init__(self, *args, **kwargs):
        appraisal = kwargs.pop("appraisal", None)
        department = kwargs.pop("department", None)  # New argument
        super().__init__(*args, **kwargs)
        self.appraisal = appraisal

        # Limit attributes to non-teaching and the staff's department
        self.fields["attribute"].queryset = SPEAttribute.objects.filter(
            staff_type="non_teaching",
            period=appraisal.period,
            department=department,  # Ensure department filtering
        )

        # Limit indicators dynamically
        self.fields["indicator"].queryset = SPEIndicator.objects.none()
        if "attribute" in self.data:
            try:
                attribute_id = int(self.data.get("attribute"))
                self.fields["indicator"].queryset = (
                    SPEIndicator.objects.filter(attribute_id=attribute_id)
                )
            except (ValueError, TypeError):
                pass
        elif self.instance.pk:
            self.fields["indicator"].queryset = (
                self.instance.attribute.indicators
            )

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.appraisal = self.appraisal
        if commit:
            instance.save()
        return instance


# ============================
# 2. Teaching Staff Self-Assessment Form
# ============================
class TeachingSelfAssessmentForm(forms.ModelForm):
    class Meta:
        model = SelfAssessment
        fields = ["attribute", "indicator", "self_rating", "remarks"]
        widgets = {
            "attribute": forms.Select(attrs={"class": "form-select"}),
            "indicator": forms.Select(attrs={"class": "form-select"}),
            "self_rating": forms.NumberInput(
                attrs={"class": "form-control", "min": 1, "max": 5}
            ),
            "remarks": forms.Textarea(
                attrs={"class": "form-control", "rows": 3}
            ),
        }

    def __init__(self, *args, **kwargs):
        appraisal = kwargs.pop("appraisal", None)
        department = kwargs.pop("department", None)  # New argument
        super().__init__(*args, **kwargs)
        self.appraisal = appraisal

        # Limit attributes to teaching and the staff's department
        self.fields["attribute"].queryset = SPEAttribute.objects.filter(
            staff_type="teaching",
            period=appraisal.period,
            department=department,  # Ensure department filtering
        )

        # Limit indicators dynamically
        self.fields["indicator"].queryset = SPEIndicator.objects.none()
        if "attribute" in self.data:
            try:
                attribute_id = int(self.data.get("attribute"))
                self.fields["indicator"].queryset = (
                    SPEIndicator.objects.filter(attribute_id=attribute_id)
                )
            except (ValueError, TypeError):
                pass
        elif self.instance.pk:
            self.fields["indicator"].queryset = (
                self.instance.attribute.indicators
            )

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.appraisal = self.appraisal
        if commit:
            instance.save()
        return instance


# ============================
# Teaching Staff Multi Form
# ============================
class TeachingSelfAssessmentMultiForm(forms.Form):
    def __init__(self, *args, **kwargs):
        appraisal = kwargs.pop("appraisal", None)
        department = kwargs.pop("department", None)
        super().__init__(*args, **kwargs)
        self.appraisal = appraisal

        # Get TEACHING attributes only
        attributes = SPEAttribute.objects.filter(
            staff_type="teaching",  # ← Different filter
            period=appraisal.period,
            department=department,
        ).prefetch_related("speindicator_set")

        for attribute in attributes:
            for indicator in attribute.speindicator_set.all():
                self.fields[f"rating_{indicator.id}"] = forms.IntegerField(
                    min_value=1,
                    max_value=5,
                    widget=forms.NumberInput(
                        attrs={
                            "class": "form-control rating-input",
                            "min": 1,
                            "max": 5,
                            "required": True,
                        }
                    ),
                    label=indicator.description,
                    help_text=f"Attribute: {attribute.name}",
                )

                self.fields[f"remarks_{indicator.id}"] = forms.CharField(
                    required=False,
                    widget=forms.Textarea(
                        attrs={
                            "class": "form-control remarks-input",
                            "rows": 2,
                            "placeholder": "Remarks (optional)",
                        }
                    ),
                    label=f"Remarks for {indicator.description}",
                )

    def save(self):
        for field_name, value in self.cleaned_data.items():
            if field_name.startswith("rating_"):
                indicator_id = field_name.replace("rating_", "")
                remarks = self.cleaned_data.get(f"remarks_{indicator_id}", "")

                try:
                    indicator = SPEIndicator.objects.get(id=indicator_id)
                    SelfAssessment.objects.update_or_create(
                        appraisal=self.appraisal,
                        indicator=indicator,
                        defaults={
                            "attribute": indicator.attribute,
                            "self_rating": value,
                            "remarks": remarks,
                        },
                    )
                except SPEIndicator.DoesNotExist:
                    continue


# ============================
# Non-Teaching Staff Multi Form
# ============================
class NonTeachingSelfAssessmentMultiForm(forms.Form):
    def __init__(self, *args, **kwargs):
        appraisal = kwargs.pop("appraisal", None)
        department = kwargs.pop("department", None)
        super().__init__(*args, **kwargs)
        self.appraisal = appraisal

        # Get NON-TEACHING attributes only
        attributes = SPEAttribute.objects.filter(
            staff_type="non_teaching",  # ← Different filter
            period=appraisal.period,
            department=department,
        ).prefetch_related("speindicator_set")

        for attribute in attributes:
            for indicator in attribute.speindicator_set.all():
                self.fields[f"rating_{indicator.id}"] = forms.IntegerField(
                    min_value=1,
                    max_value=5,
                    widget=forms.NumberInput(
                        attrs={
                            "class": "form-control rating-input",
                            "min": 1,
                            "max": 5,
                            "required": True,
                        }
                    ),
                    label=indicator.description,
                    help_text=f"Attribute: {attribute.name}",
                )

                self.fields[f"remarks_{indicator.id}"] = forms.CharField(
                    required=False,
                    widget=forms.Textarea(
                        attrs={
                            "class": "form-control remarks-input",
                            "rows": 2,
                            "placeholder": "Remarks (optional)",
                        }
                    ),
                    label=f"Remarks for {indicator.description}",
                )

    def save(self):
        # Same save logic but for non-teaching data
        for field_name, value in self.cleaned_data.items():
            if field_name.startswith("rating_"):
                indicator_id = field_name.replace("rating_", "")
                remarks = self.cleaned_data.get(f"remarks_{indicator_id}", "")

                try:
                    indicator = SPEIndicator.objects.get(id=indicator_id)
                    SelfAssessment.objects.update_or_create(
                        appraisal=self.appraisal,
                        indicator=indicator,
                        defaults={
                            "attribute": indicator.attribute,
                            "self_rating": value,
                            "remarks": remarks,
                        },
                    )
                except SPEIndicator.DoesNotExist:
                    continue


# ============================
# 3. Supervisor Evaluation Form
# ============================
class SupervisorEvaluationForm(forms.ModelForm):
    class Meta:
        model = SupervisorEvaluation
        fields = ["supervisor_rating", "remarks"]
        widgets = {
            "supervisor_rating": forms.NumberInput(
                attrs={"class": "form-control", "min": 1, "max": 5}
            ),
            "remarks": forms.Textarea(
                attrs={"class": "form-control", "rows": 3}
            ),
        }

    def __init__(self, *args, **kwargs):
        self.self_assessment = kwargs.pop("self_assessment", None)
        super().__init__(*args, **kwargs)

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.self_assessment = self.self_assessment
        if commit:
            instance.save()
        return instance


# ============================
# 4. Supervisor Setup Forms
# ============================
class SPEPeriodForm(forms.ModelForm):
    class Meta:
        model = SPEPeriod
        fields = ["name", "start_date", "end_date", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "start_date": forms.DateInput(
                attrs={"type": "date", "class": "form-control"}
            ),
            "end_date": forms.DateInput(
                attrs={"type": "date", "class": "form-control"}
            ),
            "is_active": forms.CheckboxInput(
                attrs={"class": "form-check-input"}
            ),
        }


class SPEAttributeForm(forms.ModelForm):
    class Meta:
        model = SPEAttribute
        fields = ["period", "name", "staff_type"]
        widgets = {
            "period": forms.Select(attrs={"class": "form-select"}),
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "staff_type": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["period"].queryset = SPEPeriod.objects.filter(
            is_active=True
        )


class SPEIndicatorForm(forms.ModelForm):
    class Meta:
        model = SPEIndicator
        fields = ["attribute", "description"]  # REMOVE 'weight' from this list
        widgets = {
            "attribute": forms.Select(attrs={"class": "form-select"}),
            "description": forms.TextInput(attrs={"class": "form-control"}),
            # REMOVE the 'weight' widget entirely
        }


# ============================
# 5. Unified Staff Profile Form (without staff_type field)
# ============================
class StaffProfileForm(forms.ModelForm):
    class Meta:
        model = StaffProfile
        fields = ["designation"]  # REMOVE DEPARTMENT - it's admin-assigned!
        widgets = {
            "designation": forms.TextInput(attrs={"class": "form-control"}),
            # REMOVE department widget
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        # Remove all department-related logic
        # Department is set by admin, not by user

        # Make designation required
        self.fields["designation"].required = True

    # Remove the clean_department method entirely
    # Department validation is not needed since user doesn't choose it
