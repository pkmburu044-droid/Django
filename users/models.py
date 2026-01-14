from django.conf import settings
from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone


class Department(models.Model):
    name = models.CharField(max_length=150, unique=True)
    code = models.CharField(max_length=10, unique=True, blank=True, null=True)

    STAFF_TYPE_CHOICES = [
        ("teaching", "Teaching"),
        ("non_teaching", "Non-Teaching"),
        ("supervisor", "Supervisor"),
        ("hr", "HR"),  # ✅ ADD HR DEPARTMENT TYPE
    ]
    staff_type = models.CharField(max_length=20, choices=STAFF_TYPE_CHOICES)

    def __str__(self):
        return f"{self.name} ({self.get_staff_type_display()})"


# --------------------------------
# Custom User Manager
# --------------------------------
class CustomUserManager(BaseUserManager):
    def create_user(self, pf_number, email, password=None, **extra_fields):
        if not pf_number:
            raise ValueError("PF Number must be set")
        if not email:
            raise ValueError("Email must be set")

        email = self.normalize_email(email)
        user = self.model(pf_number=pf_number, email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(
        self, pf_number, email, password=None, **extra_fields
    ):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", "supervisor")

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(pf_number, email, password, **extra_fields)


class CustomUser(AbstractBaseUser, PermissionsMixin):
    pf_number = models.CharField(max_length=20, unique=True)
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)

    ROLE_CHOICES = [
        ("teaching", "Teaching Staff"),
        ("non_teaching", "Non-Teaching Staff"),
        ("supervisor", "Supervisor"),
        ("hr", "HR Staff"),
        ("vc", "Vice Chancellor"),  # ADD VC ROLE
    ]
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)

    EMPLOYMENT_TYPE_CHOICES = [
        ("permanent", "Permanent"),
        ("contract", "Contract"),
    ]
    employment_type = models.CharField(
        max_length=20, choices=EMPLOYMENT_TYPE_CHOICES, default="permanent"
    )

    # Department is optional - especially for VC
    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="users",
    )

    # ✅ ADD HR FLAG FOR QUICK PERMISSION CHECKS
    is_hr = models.BooleanField(default=False)

    # ✅ ADD VC FLAG FOR QUICK PERMISSION CHECKS
    is_vc = models.BooleanField(default=False)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects = CustomUserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = [
        "pf_number",
        "first_name",
        "last_name",
        "role",
        "employment_type",
    ]

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def __str__(self):
        return f"{self.get_full_name()} ({self.role})"

    # ✅ ADD HELPER PROPERTY FOR HR PERMISSIONS
    @property
    def is_hr_staff(self):
        return self.is_hr or self.role == "hr"

    # ✅ ADD HELPER PROPERTY FOR VC PERMISSIONS
    @property
    def is_vc_staff(self):
        return self.is_vc or self.role == "vc"

    # ✅ ADD METHOD TO GET ALL DEPARTMENTS (for VC)
    def get_all_departments(self):
        """VC can access all departments"""
        if self.is_vc_staff:
            return Department.objects.all()
        return Department.objects.none()


# --------------------------------
# Unified Staff Profile
# --------------------------------
class StaffProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="staffprofile",
    )
    designation = models.CharField(max_length=100)

    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="staff_profiles",
    )

    # ✅ ADD THIS: Foreign key to current/latest appraisal
    current_appraisal = models.ForeignKey(
        "StaffAppraisal",  # Use string to avoid circular import
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="active_profile",
    )

    def clean(self):
        """Validate that department matches user role, but allow supervisors in any department"""
        if (
            self.department and self.user.role != "supervisor"
        ):  # Only validate for non-supervisors
            if self.user.role != self.department.staff_type:
                raise ValidationError(
                    f"Department '{self.department.name}' is for {self.department.get_staff_type_display()} staff, "
                    f"but user is {self.user.get_role_display()}."
                )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.get_full_name()} - {self.designation} ({self.user.get_role_display()})"

    @property
    def is_supervisor(self):
        """Check if this staff member is a supervisor"""
        return self.user.role == "supervisor"

    @property
    def supervised_staff(self):
        """Get staff members this supervisor oversees (for supervisors only)"""
        if not self.is_supervisor:
            return StaffProfile.objects.none()

        # Staff in the same department (for non-teaching supervisors)
        return StaffProfile.objects.filter(department=self.department).exclude(
            user=self.user
        )

    # ✅ ADD THESE PROPERTIES TO ACCESS APPRAISAL DATA
    @property
    def display_experience(self):
        """Get total experience from current appraisal"""
        if self.current_appraisal:
            kyu = self.current_appraisal.years_experience_kyu or 0
            elsewhere = self.current_appraisal.years_experience_elsewhere or 0
            return f"{kyu + elsewhere} years"
        return "Not specified"

    @property
    def display_date_of_appointment(self):
        """Get appointment date from current appraisal"""
        if (
            self.current_appraisal
            and self.current_appraisal.date_of_appointment
        ):
            return self.current_appraisal.date_of_appointment
        return None

    @property
    def display_length_of_service(self):
        """Get length of service from current appraisal"""
        if self.current_appraisal:
            return self.current_appraisal.length_of_service
        return None

    @property
    def display_acting_duty(self):
        """Get acting/special duty from current appraisal"""
        if self.current_appraisal:
            return (
                self.current_appraisal.acting_or_special_duty
                or self.current_appraisal.acting_appointment
            )
        return None


# --------------------------------
# Unified Staff Appraisal
# --------------------------------
class StaffAppraisal(models.Model):
    profile = models.ForeignKey(
        StaffProfile, on_delete=models.CASCADE, related_name="appraisals"
    )
    period = models.ForeignKey(
        "spe.SPEPeriod",
        on_delete=models.CASCADE,
        related_name="staff_appraisals",
        null=True,
        blank=True,
    )

    supervisor_name = models.CharField(max_length=255)
    supervisor_designation = models.CharField(max_length=255)

    # Teaching-specific
    date_of_appointment = models.DateField(null=True, blank=True)
    acting_appointment = models.TextField(blank=True, null=True)
    years_experience_kyu = models.PositiveIntegerField(default=0)
    years_experience_elsewhere = models.PositiveIntegerField(default=0)

    # Non-teaching-specific
    length_of_service = models.CharField(max_length=50, blank=True, null=True)
    years_in_equivalent_position = models.CharField(
        max_length=50, blank=True, null=True
    )
    acting_or_special_duty = models.CharField(
        max_length=255, blank=True, null=True
    )
    appraisal_date = models.DateField(null=True, blank=True)

    overall_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Calculated score out of 100%",
    )

    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("submitted", "Submitted"),
        ("reviewed", "Reviewed"),
        ("finalized", "Finalized"),
    ]
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="draft"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        period_name = self.period.name if self.period else "N/A"
        return f"{self.profile.user.get_full_name()} – {period_name}"


# --------------------------------
# Performance Target (FIXED - NOT NESTED)
# --------------------------------
class PerformanceTarget(models.Model):
    # ✅ REMOVE defaults - they cause data integrity issues
    staff = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="performance_targets",
    )
    period = models.ForeignKey(
        "spe.SPEPeriod",
        on_delete=models.CASCADE,
    )

    target_number = models.IntegerField(default=1)
    description = models.TextField(default="Performance target description")
    success_measures = models.TextField(blank=True, default="")

    # ✅ UPDATED: Clear workflow status
    STATUS_CHOICES = [
        ("draft", "Draft - Being Filled by Staff"),
        ("submitted", "Submitted for Approval"),
        ("approved", "Approved - Ready for Evaluation"),
        ("rejected", "Rejected - Needs Revision"),
        ("evaluated", "Evaluated - Completed"),
    ]
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="draft"
    )

    # Rejection fields
    rejection_reason = models.TextField(blank=True, default="")
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rejected_targets",
    )
    rejected_at = models.DateTimeField(null=True, blank=True)

    # Approval fields (NEW)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_targets",
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    # Evaluation fields
    performance_rating = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        verbose_name="Performance Rating (%)",
    )
    supervisor_comments = models.TextField(blank=True, default="")
    evaluated_at = models.DateTimeField(null=True, blank=True)
    evaluated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="evaluated_targets",
    )

    RATING_CHOICES = [
        (1, "1 - Unsatisfactory"),
        (2, "2 - Needs Improvement"),
        (3, "3 - Meets Expectations"),
        (4, "4 - Exceeds Expectations"),
        (5, "5 - Outstanding"),
    ]
    rating_scale = models.IntegerField(
        choices=RATING_CHOICES,
        null=True,
        blank=True,
        verbose_name="Performance Rating Scale",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ["staff", "period", "target_number"]
        ordering = ["staff", "period", "target_number"]

    def __str__(self):
        return f"{self.staff.email} - Target {self.target_number} ({self.period.name})"

    def save(self, *args, **kwargs):
        # Auto-calculate performance rating
        if self.rating_scale is not None:
            self.performance_rating = self.rating_scale * 20

        # Auto-set evaluation timestamp
        if self.rating_scale is not None and not self.evaluated_at:
            self.evaluated_at = timezone.now()

        super().save(*args, **kwargs)

    # ✅ NEW: Workflow helper methods
    def can_submit(self, period):
        """Check if target can be submitted based on period phase"""
        return period.is_target_submission_open

    def can_evaluate(self, period):
        """Check if target can be evaluated based on period phase"""
        return period.is_evaluation_open and self.status == "approved"

    def submit_for_approval(self):
        """Submit target for supervisor approval"""
        if self.status == "draft":
            self.status = "submitted"
            self.save()

    def approve_target(self, approved_by):
        """Approve target by supervisor"""
        if self.status == "submitted":
            self.status = "approved"
            self.approved_by = approved_by
            self.approved_at = timezone.now()
            self.save()

    def reject_target(self, rejected_by, reason):
        """Reject target by supervisor"""
        if self.status == "submitted":
            self.status = "rejected"
            self.rejected_by = rejected_by
            self.rejection_reason = reason
            self.rejected_at = timezone.now()
            self.save()


@receiver(post_save, sender=CustomUser)
def sync_user_department(sender, instance, **kwargs):
    """Sync department between CustomUser and StaffProfile when User is updated"""
    try:
        profile = StaffProfile.objects.get(user=instance)
        if profile.department != instance.department:
            print(
                f"SYNC: Updating StaffProfile department for {instance.email}"
            )
            profile.department = instance.department
            profile.save()
    except StaffProfile.DoesNotExist:
        # Create StaffProfile if it doesn't exist
        StaffProfile.objects.create(
            user=instance,
            designation="Staff Member",
            department=instance.department,
        )


# Add to users/models.py
class DepartmentAppraisal(models.Model):
    STATUS_CHOICES = (
        ("draft", "Draft"),
        ("submitted", "Submitted"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    )

    department = models.ForeignKey(Department, on_delete=models.CASCADE)
    appraisal_period = models.ForeignKey(
        "spe.SPEPeriod", on_delete=models.CASCADE
    )
    overall_score = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="draft"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Summary fields
    summary = models.TextField(blank=True)
    strengths = models.TextField(blank=True)
    areas_for_improvement = models.TextField(blank=True)
    recommendations = models.TextField(blank=True)

    class Meta:
        unique_together = ["department", "appraisal_period"]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.department.name} - {self.appraisal_period.name}"

    def calculate_overall_score(self):
        """Calculate overall score from individual staff appraisals"""
        from django.db.models import Avg

        # Get average of all reviewed staff appraisals in this department and period
        avg_score = StaffAppraisal.objects.filter(
            profile__department=self.department,
            period=self.appraisal_period,
            status="reviewed",
        ).aggregate(avg_score=Avg("overall_score"))["avg_score"]

        if avg_score:
            self.overall_score = round(avg_score, 2)
            self.save()
        return self.overall_score


class DepartmentAppraisalItem(models.Model):
    appraisal = models.ForeignKey(
        DepartmentAppraisal, on_delete=models.CASCADE, related_name="items"
    )
    metric = models.CharField(max_length=200)
    weight = models.DecimalField(max_digits=5, decimal_places=2)  # Percentage
    target = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    actual = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    score = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    comments = models.TextField(blank=True)

    def calculate_score(self):
        if self.target and self.actual:
            return (self.actual / self.target) * 100
        return 0

    def save(self, *args, **kwargs):
        if self.target and self.actual:
            self.score = self.calculate_score()
        super().save(*args, **kwargs)
