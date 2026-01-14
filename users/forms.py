from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import CustomUser, Department, StaffAppraisal, StaffProfile


# -------------------------------
# 1. PF Number Login Form
# -------------------------------
class PFNumberLoginForm(AuthenticationForm):
    username = forms.CharField(
        label="PF Number",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Enter your PF Number",
                "autofocus": True,
            }
        ),
    )
    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "placeholder": "Enter your password",
            }
        ),
    )

    def clean_username(self):
        username = self.cleaned_data.get("username")
        if username:
            username = username.upper().strip()  # Ensure consistent format
        return username


# -------------------------------
# 2. Custom User Creation Form
# -------------------------------
class CustomUserCreationForm(UserCreationForm):
    role = forms.ChoiceField(
        choices=CustomUser.ROLE_CHOICES,
        required=True,
        label="Role",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    employment_type = forms.ChoiceField(
        choices=CustomUser.EMPLOYMENT_TYPE_CHOICES,
        required=True,
        label="Terms of Service",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    department = forms.ModelChoiceField(
        queryset=Department.objects.all().order_by("name"),
        required=False,  # Changed to False to make it optional
        label="Department",
        widget=forms.Select(attrs={"class": "form-select"}),
        empty_label="Select Department (Optional for VC)",  # Add empty label
    )

    class Meta:
        model = CustomUser
        fields = (
            "pf_number",
            "email",
            "first_name",
            "last_name",
            "role",
            "department",
            "employment_type",
            "password1",
            "password2",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make PF Number field more prominent
        self.fields["pf_number"].widget.attrs.update(
            {"class": "form-control", "placeholder": "e.g., PF/12345"}
        )
        self.fields["pf_number"].label = "PF Number"

        # Add help text for department field
        self.fields["department"].help_text = (
            "Required for all roles except Vice Chancellor"
        )

    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get("role")
        department = cleaned_data.get("department")

        # VC users don't need a department
        if role == "vc":
            cleaned_data["department"] = None
        # For other roles, department is required
        elif (
            role in ["teaching", "non_teaching", "supervisor", "hr"]
            and not department
        ):
            self.add_error(
                "department", "Department is required for this role."
            )

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        # Ensure PF number is in consistent format
        user.pf_number = user.pf_number.upper().strip()

        # Handle department based on role
        role = self.cleaned_data.get("role")
        if role == "vc":
            user.department = None

        if commit:
            user.save()
            # Ensure StaffProfile is created
            StaffProfile.objects.get_or_create(
                user=user,
                defaults={
                    "designation": self.get_default_designation(role),
                    "department": user.department,
                },
            )

        return user

    def get_default_designation(self, role):
        """Get default designation based on role"""
        designation_map = {
            "teaching": "Lecturer",
            "non_teaching": "Administrative Staff",
            "supervisor": "Supervisor",
            "hr": "HR Officer",
            "vc": "Vice Chancellor",
        }
        return designation_map.get(role, "Staff Member")


# -------------------------------
# 3. Staff Profile Form
# -------------------------------
class StaffProfileForm(forms.ModelForm):
    # Add fields from StaffAppraisal model
    date_of_appointment = forms.DateField(
        required=False,
        widget=forms.DateInput(
            attrs={"class": "form-control", "type": "date"}
        ),
        label="Date of Appointment",
    )

    years_experience_kyu = forms.IntegerField(
        required=False,
        min_value=0,
        max_value=50,
        widget=forms.NumberInput(
            attrs={"class": "form-control", "placeholder": "0"}
        ),
        label="KYU Experience (Years)",
    )

    years_experience_elsewhere = forms.IntegerField(
        required=False,
        min_value=0,
        max_value=50,
        widget=forms.NumberInput(
            attrs={"class": "form-control", "placeholder": "0"}
        ),
        label="Other Institution Experience (Years)",
    )

    length_of_service = forms.CharField(
        required=False,
        max_length=50,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "e.g., 5 years 3 months",
            }
        ),
        label="Length of Service",
    )

    years_in_equivalent_position = forms.CharField(
        required=False,
        max_length=50,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "e.g., 3 years"}
        ),
        label="Years in Equivalent Position",
    )

    acting_or_special_duty = forms.CharField(
        required=False,
        max_length=255,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "e.g., Acting Department Head",
            }
        ),
        label="Acting or Special Duty",
    )

    class Meta:
        model = StaffProfile
        fields = ["designation"]
        widgets = {
            "designation": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "e.g., Senior Lecturer, Administrative Officer",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # SMART DATA: Get the most recent data from ANY appraisal (not just current)
        if self.instance and self.instance.user:
            latest_data = self.get_latest_appraisal_data(self.instance.user)
            if latest_data:
                for field_name, value in latest_data.items():
                    if field_name in self.fields and value not in [None, ""]:
                        self.fields[field_name].initial = value

    def get_latest_appraisal_data(self, user):
        """Get the most recent non-empty values from all appraisals"""
        from users.models import StaffAppraisal

        # Get all appraisals for this user, ordered by most recent
        appraisals = StaffAppraisal.objects.filter(
            profile__user=user
        ).order_by("-created_at")

        latest_data = {}

        for appraisal in appraisals:
            # Only take non-empty values that haven't been set yet
            fields_to_check = [
                "date_of_appointment",
                "years_experience_kyu",
                "years_experience_elsewhere",
                "length_of_service",
                "years_in_equivalent_position",
                "acting_or_special_duty",
            ]

            for field in fields_to_check:
                value = getattr(appraisal, field)
                if (
                    value not in [None, "", 0]
                    and field not in latest_data
                    and not (isinstance(value, int) and value == 0)
                ):
                    latest_data[field] = value

        return latest_data

    def save(self, commit=True):
        profile = super().save(commit=False)

        if commit:
            profile.save()
            # Save to current/latest appraisal
            self.save_to_appraisal(profile)

        return profile

    def save_to_appraisal(self, profile):
        """Save data to the current active period appraisal"""
        from spe.models import SPEPeriod

        # Get active period
        active_period = SPEPeriod.objects.filter(is_active=True).first()

        if active_period:
            # Get or create appraisal for current period
            appraisal, created = StaffAppraisal.objects.get_or_create(
                profile=profile,
                period=active_period,
                defaults={
                    "status": "draft",
                    "supervisor_name": "",
                    "supervisor_designation": "",
                },
            )

            # Update with form data - only update if value is provided
            if self.cleaned_data.get("date_of_appointment"):
                appraisal.date_of_appointment = self.cleaned_data[
                    "date_of_appointment"
                ]
            if self.cleaned_data.get("years_experience_kyu") is not None:
                appraisal.years_experience_kyu = self.cleaned_data[
                    "years_experience_kyu"
                ]
            if self.cleaned_data.get("years_experience_elsewhere") is not None:
                appraisal.years_experience_elsewhere = self.cleaned_data[
                    "years_experience_elsewhere"
                ]
            if self.cleaned_data.get("length_of_service"):
                appraisal.length_of_service = self.cleaned_data[
                    "length_of_service"
                ]
            if self.cleaned_data.get("years_in_equivalent_position"):
                appraisal.years_in_equivalent_position = self.cleaned_data[
                    "years_in_equivalent_position"
                ]
            if self.cleaned_data.get("acting_or_special_duty"):
                appraisal.acting_or_special_duty = self.cleaned_data[
                    "acting_or_special_duty"
                ]

            appraisal.save()

            # Update profile's current appraisal reference
            profile.current_appraisal = appraisal
            profile.save()


# -------------------------------
# 4. Staff Appraisal Form
# -------------------------------
class StaffAppraisalForm(forms.ModelForm):
    class Meta:
        model = StaffAppraisal
        exclude = [
            "profile",
            "overall_score",
            "status",
            "created_at",
            "updated_at",
            "supervisor_name",
            "supervisor_designation",
            "period",
            "appraisal_date",
        ]
        widgets = {
            "length_of_service": forms.TextInput(
                attrs={"class": "form-control"}
            ),
            "years_in_equivalent_position": forms.TextInput(
                attrs={"class": "form-control"}
            ),
            "acting_or_special_duty": forms.TextInput(
                attrs={"class": "form-control"}
            ),
            "date_of_appointment": forms.DateInput(
                attrs={"type": "date", "class": "form-control"}
            ),
            "acting_appointment": forms.TextInput(
                attrs={"class": "form-control"}
            ),
            "years_experience_kyu": forms.NumberInput(
                attrs={"class": "form-control"}
            ),
            "years_experience_elsewhere": forms.NumberInput(
                attrs={"class": "form-control"}
            ),
        }

    def __init__(self, *args, **kwargs):
        self.period = kwargs.pop("period", None)
        self.profile = kwargs.pop("profile", None)
        self.supervisor = kwargs.pop("supervisor", None)
        super().__init__(*args, **kwargs)

        # Remove supervisor, period, and appraisal_date fields from the form
        fields_to_remove = ["supervisor", "period", "appraisal_date"]
        for field in fields_to_remove:
            if field in self.fields:
                del self.fields[field]
