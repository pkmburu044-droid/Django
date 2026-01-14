# hr/models.py
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse

from spe.models import SPEPeriod
from users.models import Department

User = get_user_model()


class SupervisorAttribute(models.Model):
    """HR-managed attributes for evaluating supervisors"""

    CATEGORY_CHOICES = [
        ("leadership", "Leadership & Team Management"),
        ("strategic", "Strategic & Planning"),
        ("operational", "Operational Excellence"),
        ("development", "Staff Development & Mentoring"),
        ("communication", "Communication & Collaboration"),
    ]

    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES)
    name = models.CharField(max_length=200)
    description = models.TextField(
        help_text="Detailed description of this attribute"
    )
    weight = models.IntegerField(
        help_text="Weight in percentage (e.g., 15 for 15%)",
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={"is_staff": True},
        related_name="created_supervisor_attributes",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category", "weight", "name"]
        verbose_name = "Supervisor Attribute"
        verbose_name_plural = "Supervisor Attributes"

    def __str__(self):
        return f"{self.name} ({self.get_category_display()})"

    def get_absolute_url(self):
        return reverse("hr:edit_attribute", kwargs={"attribute_id": self.id})

    @property
    def active_indicators(self):
        return self.indicators.filter(is_active=True)


class SupervisorIndicator(models.Model):
    """Specific indicators/behaviors for supervisor attributes"""

    attribute = models.ForeignKey(
        SupervisorAttribute,
        on_delete=models.CASCADE,
        related_name="indicators",
    )
    description = models.TextField(
        help_text="Specific behavior or competency to evaluate"
    )
    example = models.TextField(
        blank=True, help_text="Example of what this looks like in practice"
    )
    is_active = models.BooleanField(default=True)
    order = models.IntegerField(default=0, help_text="Display order")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["attribute", "order", "id"]
        verbose_name = "Supervisor Indicator"
        verbose_name_plural = "Supervisor Indicators"

    def __str__(self):
        return f"{self.attribute.name} - {self.description[:50]}..."


# ================================================================
# SUPERVISOR EVALUATION MODELS (UPDATED TO USE HR ATTRIBUTES)
# ================================================================


class SupervisorAssessment(models.Model):
    """Assessment criteria for evaluating supervisors (uses HR supervisor attributes)"""

    period = models.ForeignKey("spe.SPEPeriod", on_delete=models.CASCADE)
    attribute = models.ForeignKey(
        "SupervisorAttribute", on_delete=models.CASCADE
    )  # Changed to SupervisorAttribute
    indicator = models.ForeignKey(
        "SupervisorIndicator", on_delete=models.CASCADE
    )  # Changed to SupervisorIndicator
    weight = models.FloatField(default=1.0)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ["period", "attribute", "indicator"]
        verbose_name = "Supervisor Assessment"
        verbose_name_plural = "Supervisor Assessments"

    def __str__(self):
        return f"{self.attribute.name} - {self.indicator.description} ({self.period.name})"


class SupervisorEvaluationByStaff(models.Model):
    """Evaluation of supervisors by their staff members"""

    supervisor_assessment = models.ForeignKey(
        "SupervisorAssessment", on_delete=models.CASCADE
    )
    staff = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="staff_given_supervisor_evaluations",
    )
    supervisor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="staff_received_supervisor_evaluations",
    )
    period = models.ForeignKey("spe.SPEPeriod", on_delete=models.CASCADE)
    staff_rating = models.IntegerField(choices=[(i, i) for i in range(1, 6)])
    staff_remarks = models.TextField(blank=True, null=True)
    evaluated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [
            "supervisor_assessment",
            "staff",
            "supervisor",
            "period",
        ]
        verbose_name = "Staff Supervisor Evaluation"
        verbose_name_plural = "Staff Supervisor Evaluations"

    def __str__(self):
        return f"{self.staff.get_full_name()} -> {self.supervisor.get_full_name()}"


class SupervisorOverallEvaluation(models.Model):
    """Overall evaluation summary for supervisors"""

    supervisor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="overall_supervisor_evaluations",
    )
    period = models.ForeignKey("spe.SPEPeriod", on_delete=models.CASCADE)
    attribute = models.ForeignKey(
        "SupervisorAttribute", on_delete=models.CASCADE
    )  # Changed to SupervisorAttribute
    indicator = models.ForeignKey(
        "SupervisorIndicator", on_delete=models.CASCADE
    )  # Changed to SupervisorIndicator
    evaluated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE
    )
    rating = models.IntegerField(choices=[(i, i) for i in range(1, 6)])
    remarks = models.TextField(blank=True, null=True)
    is_submitted = models.BooleanField(default=False)
    status = models.CharField(max_length=20, default="draft")
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [
            "supervisor",
            "period",
            "attribute",
            "indicator",
            "evaluated_by",
        ]
        verbose_name = "Supervisor Overall Evaluation"
        verbose_name_plural = "Supervisor Overall Evaluations"

    def __str__(self):
        return f"{self.supervisor.get_full_name()} - {self.attribute.name}"


class SupervisorAppraisal(models.Model):
    """Overall appraisal summary for supervisors"""

    supervisor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="supervisor_appraisals_received",
    )
    period = models.ForeignKey(
        "spe.SPEPeriod",
        on_delete=models.CASCADE,
        related_name="supervisor_period_appraisals",
    )
    evaluated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="supervisor_appraisals_given",
    )
    total_score = models.FloatField(default=0.0)
    average_score = models.FloatField(default=0.0)
    overall_score = models.FloatField(default=0.0)

    # ADD THESE MISSING FIELDS:
    criteria_score = models.FloatField(
        null=True, blank=True, verbose_name="Criteria Score"
    )
    target_score = models.FloatField(
        null=True, blank=True, verbose_name="Target Score"
    )
    criteria_evaluated = models.IntegerField(
        default=0, verbose_name="Criteria Evaluated Count"
    )
    targets_evaluated = models.IntegerField(
        default=0, verbose_name="Targets Evaluated Count"
    )
    target_achievement_rate = models.FloatField(
        null=True, blank=True, verbose_name="Target Achievement Rate"
    )

    status = models.CharField(max_length=20, default="draft")
    evaluated_at = models.DateTimeField(
        auto_now_add=True
    )  # This field already exists

    class Meta:
        unique_together = ["supervisor", "period", "evaluated_by"]
        verbose_name = "Supervisor Appraisal"
        verbose_name_plural = "Supervisor Appraisals"

    def __str__(self):
        return f"{self.supervisor.get_full_name()} - {self.period.name}: {self.overall_score:.2f}%"


# ================================================================
# EXISTING HR EVALUATION MODELS
# ================================================================


class SupervisorEvaluation(models.Model):
    """HR's evaluation of supervisors during the SAME period as staff evaluations"""

    RATING_CHOICES = [
        (1, "1 - Poor Leadership"),
        (2, "2 - Developing"),
        (3, "3 - Competent"),
        (4, "4 - Strong Leader"),
        (5, "5 - Exceptional Leader"),
    ]

    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("pending", "Pending Approval"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ]

    supervisor = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        limit_choices_to={"role": "supervisor"},
        related_name="hr_evaluations_received",
    )
    hr_user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        limit_choices_to={"is_staff": True},
        related_name="hr_evaluations_given",
    )
    period = models.ForeignKey(
        SPEPeriod,
        on_delete=models.CASCADE,
        related_name="supervisor_evaluations",
    )
    attribute = models.ForeignKey(
        SupervisorAttribute, on_delete=models.CASCADE
    )
    indicator = models.ForeignKey(
        SupervisorIndicator, on_delete=models.CASCADE, null=True, blank=True
    )
    rating = models.IntegerField(choices=RATING_CHOICES)
    comments = models.TextField(
        blank=True, null=True, help_text="HR's comments on this rating"
    )

    # Approval workflow fields
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="draft"
    )
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_supervisor_evaluations",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rejected_supervisor_evaluations",
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, null=True)

    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [
            ["supervisor", "period", "attribute", "indicator", "hr_user"]
        ]
        ordering = ["supervisor", "attribute__category", "attribute__weight"]
        verbose_name = "Supervisor HR Evaluation"
        verbose_name_plural = "Supervisor HR Evaluations"

    def __str__(self):
        return f"{self.supervisor.get_full_name()} - {self.attribute.name} - {self.rating}/5"

    @property
    def weighted_score(self):
        """Calculate weighted score for this evaluation"""
        return (self.rating / 5) * self.attribute.weight


class InstitutionalReport(models.Model):
    """Generated institutional/bulk reports"""

    REPORT_TYPE_CHOICES = [
        ("department", "Department Performance Report"),
        ("supervisor", "Supervisor Effectiveness Report"),
        ("institutional", "Institutional Analytics Report"),
        ("comparative", "Comparative Analysis Report"),
    ]

    name = models.CharField(max_length=200)
    report_type = models.CharField(max_length=20, choices=REPORT_TYPE_CHOICES)
    period = models.ForeignKey(SPEPeriod, on_delete=models.CASCADE)
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="Leave blank for institutional-wide reports",
    )
    generated_by = models.ForeignKey(
        User, on_delete=models.CASCADE, limit_choices_to={"is_staff": True}
    )
    generated_at = models.DateTimeField(auto_now_add=True)
    file_path = models.FileField(
        upload_to="hr_reports/%Y/%m/",
        blank=True,
        help_text="Generated report file",
    )
    parameters = models.JSONField(
        default=dict, blank=True, help_text="Report generation parameters"
    )

    class Meta:
        ordering = ["-generated_at"]
        verbose_name = "Institutional Report"
        verbose_name_plural = "Institutional Reports"

    def __str__(self):
        return f"{self.name} - {self.get_report_type_display()}"

    def get_download_url(self):
        if self.file_path:
            return self.file_path.url
        return None


# ================================================================
# SUPERVISOR PERFORMANCE TARGETS MODEL
# ================================================================


class SupervisorPerformanceTarget(models.Model):
    """Performance targets for supervisors"""

    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("pending", "Pending Approval"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ]

    # Performance Rating Choices
    RATING_CHOICES = [
        (1, "1 - Poor"),
        (2, "2 - Fair"),
        (3, "3 - Good"),
        (4, "4 - Very Good"),
        (5, "5 - Excellent"),
    ]

    supervisor = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        limit_choices_to={"role": "supervisor"},
        related_name="supervisor_performance_targets",
    )
    period = models.ForeignKey(
        SPEPeriod,
        on_delete=models.CASCADE,
        related_name="supervisor_performance_targets",
    )
    target_number = models.IntegerField(
        help_text="Target number (1-5)",
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    description = models.TextField(
        help_text="Detailed description of the performance target"
    )

    # ADDED: Success Measures / KPIs field
    success_measures = models.TextField(
        blank=True,
        null=True,
        verbose_name="Success Measures / KPIs",
        help_text="Specific measures to evaluate success. Enter one per line.",
    )

    due_date = models.DateField(
        null=True, blank=True, help_text="Target completion date"
    )

    # Approval workflow fields
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="draft"
    )
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_supervisor_targets",
        limit_choices_to={"is_staff": True},
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rejected_supervisor_targets",
        limit_choices_to={"is_staff": True},
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(
        blank=True, null=True, help_text="Reason for rejection"
    )

    # PERFORMANCE RATING FIELDS
    performance_rating = models.IntegerField(
        choices=RATING_CHOICES,
        null=True,
        blank=True,
        verbose_name="Performance Rating",
    )
    performance_comments = models.TextField(
        blank=True, null=True, verbose_name="Performance Comments"
    )
    achievement_percentage = models.FloatField(
        null=True,
        blank=True,
        verbose_name="Achievement Percentage",
        help_text="Percentage of target achieved (0-100)",
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    rated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rated_targets",
        verbose_name="Rated By",
    )
    rated_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ["supervisor", "period", "target_number"]
        ordering = ["supervisor", "period", "target_number"]
        verbose_name = "Supervisor Performance Target"
        verbose_name_plural = "Supervisor Performance Targets"

    def __str__(self):
        return f"{self.supervisor.get_full_name()} - Target {self.target_number} - {self.period.name}"

    @property
    def is_pending_approval(self):
        return self.status == "pending"

    @property
    def is_approved(self):
        return self.status == "approved"

    @property
    def is_rejected(self):
        return self.status == "rejected"

    @property
    def is_rated(self):
        """Check if target has been performance rated"""
        return self.performance_rating is not None

    def can_be_approved(self):
        """Check if target can be approved"""
        return self.status in ["draft", "pending", "rejected"]

    def can_be_rejected(self):
        """Check if target can be rejected"""
        return self.status in ["draft", "pending"]

    def can_be_rated(self):
        """Check if target can be performance rated"""
        return self.status == "approved" and not self.is_rated

    def get_measures_list(self):
        """Convert measures text to list for display"""
        if self.success_measures:
            # Split by newlines and filter out empty lines
            measures = [
                line.strip()
                for line in self.success_measures.split("\n")
                if line.strip()
            ]
            return measures
        return []
