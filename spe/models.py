from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Avg, Sum
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone  # ✅ ADD THIS IMPORT


class SPEPeriod(models.Model):
    name = models.CharField(max_length=150)
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=False)
    is_locked = models.BooleanField(
        default=False, help_text="Lock to prevent further edits"
    )

    # Workflow phase control
    TARGET_SUBMISSION_PHASE = "target_submission"
    EVALUATION_PHASE = "evaluation"
    COMPLETED_PHASE = "completed"

    PHASE_CHOICES = [
        (TARGET_SUBMISSION_PHASE, "Target Submission Phase"),
        (EVALUATION_PHASE, "Evaluation Phase"),
        (COMPLETED_PHASE, "Completed"),
    ]

    current_phase = models.CharField(
        max_length=20, choices=PHASE_CHOICES, default=TARGET_SUBMISSION_PHASE
    )

    # Phase timing control
    target_submission_start = models.DateTimeField(null=True, blank=True)
    target_submission_end = models.DateTimeField(null=True, blank=True)
    evaluation_start = models.DateTimeField(null=True, blank=True)
    evaluation_end = models.DateTimeField(null=True, blank=True)

    # ✅ SIMPLIFIED: Replace these two fields with one supervisor-controlled field
    # forms_visible_to_staff = models.BooleanField(default=False)
    # forms_approved_by_admin = models.BooleanField(default=False)

    # ✅ NEW: Simple supervisor-controlled status
    FORMS_STATUS_CHOICES = [
        ("draft", "Draft - Supervisors Working"),
        ("ready", "Ready for Staff"),
        ("closed", "Closed - Evaluation Complete"),
    ]
    forms_status = models.CharField(
        max_length=20, choices=FORMS_STATUS_CHOICES, default="draft"
    )

    def __str__(self):
        return f"{self.name} ({self.start_date} - {self.end_date})"

    def clean(self):
        """Ensure only one active period exists"""
        if self.is_active:
            active_periods = SPEPeriod.objects.filter(is_active=True).exclude(
                pk=self.pk
            )
            if active_periods.exists():
                raise ValidationError(
                    "Only one period can be active at a time"
                )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    # ✅ UPDATED: Phase checking methods
    @property
    def is_target_submission_open(self):
        """Check if staff can submit targets"""
        if self.forms_status != "ready":  # ✅ SIMPLIFIED
            return False

        now = timezone.now()
        if self.target_submission_start and self.target_submission_end:
            return (
                self.target_submission_start
                <= now
                <= self.target_submission_end
            )
        return self.current_phase == self.TARGET_SUBMISSION_PHASE

    @property
    def is_evaluation_open(self):
        """Check if supervisors can evaluate"""
        now = timezone.now()
        if self.evaluation_start and self.evaluation_end:
            return self.evaluation_start <= now <= self.evaluation_end
        return self.current_phase == self.EVALUATION_PHASE

    # ✅ NEW: Simple property for template use
    @property
    def are_forms_ready_for_staff(self):
        return self.forms_status == "ready"


class SPEAttribute(models.Model):
    name = models.CharField(max_length=150)
    period = models.ForeignKey(
        SPEPeriod, on_delete=models.CASCADE, related_name="attributes"
    )

    # ✅ CHANGE: Make department optional for global forms
    department = models.ForeignKey(
        "users.Department",
        on_delete=models.CASCADE,
        null=True,  # ✅ ADD THIS
        blank=True,  # ✅ ADD THIS
        help_text="Department this attribute belongs to (leave empty for global forms)",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="User who created this attribute",
    )

    staff_type = models.CharField(
        max_length=20,
        choices=[("teaching", "Teaching"), ("non_teaching", "Non-Teaching")],
        default="teaching",
    )

    class Meta:
        unique_together = [
            "name",
            "period",
            "department",
        ]  # ✅ This still works with NULL

    def __str__(self):
        dept_name = self.department.name if self.department else "Global"
        return f"{self.name} ({self.period.name} - {dept_name})"

    def clean(self):
        """Validate department-staff_type consistency"""
        if self.department and self.department.staff_type != self.staff_type:
            raise ValidationError(
                f"Attribute staff type '{self.get_staff_type_display()}' "
                f"does not match department type '{self.department.get_staff_type_display()}'"
            )
        # ✅ Allow global forms (no department) to have any staff_type

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


# ================================================================
# Indicator (actual evaluable item)
# ================================================================
class SPEIndicator(models.Model):
    attribute = models.ForeignKey(
        SPEAttribute, on_delete=models.CASCADE, related_name="indicators"
    )
    description = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.description} ({self.attribute.name})"


# ================================================================
# Abstract Base Evaluation
# ================================================================
class BaseEvaluation(models.Model):
    staff = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE
    )
    period = models.ForeignKey(SPEPeriod, on_delete=models.CASCADE)
    attribute = models.ForeignKey(SPEAttribute, on_delete=models.CASCADE)
    indicator = models.ForeignKey(SPEIndicator, on_delete=models.CASCADE)
    # REMOVED: department field - delegate to staff.department

    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    remarks = models.TextField(blank=True, null=True)

    # Computed fields
    total_raw_score = models.FloatField(default=0)
    mean_raw_score = models.FloatField(default=0)
    percent_score = models.FloatField(default=0)

    is_submitted = models.BooleanField(default=False)
    status = models.CharField(
        max_length=20,
        choices=[
            ("draft", "Draft"),
            ("submitted", "Submitted"),
            ("reviewed", "Reviewed"),
            ("finalized", "Finalized"),
        ],
        default="draft",
    )

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="%(class)s_reviewed_evaluations",
        limit_choices_to={"role": "supervisor"},
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ["-period", "staff"]
        unique_together = ("staff", "period", "indicator")

    def calculate_scores(self, previous_ratings_qs):
        """Recalculate raw score, mean, and percent score for an attribute."""
        agg = previous_ratings_qs.aggregate(
            total=Sum("rating"), count=models.Count("id")
        )
        total_ratings = (agg["total"] or 0) + self.rating
        num_indicators = (agg["count"] or 0) + 1

        self.total_raw_score = total_ratings
        self.mean_raw_score = (
            total_ratings / num_indicators if num_indicators else self.rating
        )
        self.percent_score = (self.mean_raw_score / 5) * 100

    def __str__(self):
        return f"{self.staff} - {self.period.name} ({self.attribute.name})"

    @property
    def department(self):
        """Delegate to staff's department"""
        return self.staff.department


# ================================================================
# Non-Teaching Staff Evaluation
# ================================================================
class NonTeachingStaffEvaluation(BaseEvaluation):
    staff = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        limit_choices_to={"role": "non_teaching"},
        related_name="non_teaching_evaluations",
    )

    class Meta(BaseEvaluation.Meta):
        verbose_name = "Non-Teaching Staff Evaluation"
        verbose_name_plural = "Non-Teaching Staff Evaluations"

    def save(self, *args, **kwargs):
        qs = NonTeachingStaffEvaluation.objects.filter(
            staff=self.staff, period=self.period, attribute=self.attribute
        ).exclude(pk=self.pk)
        self.calculate_scores(qs)
        super().save(*args, **kwargs)


# ================================================================
# Teaching Staff Evaluation
# ================================================================
class TeachingStaffEvaluation(BaseEvaluation):
    staff = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        limit_choices_to={"role": "teaching"},
        related_name="teaching_evaluations",
    )

    class Meta(BaseEvaluation.Meta):
        verbose_name = "Teaching Staff Evaluation"
        verbose_name_plural = "Teaching Staff Evaluations"

    def save(self, *args, **kwargs):
        qs = TeachingStaffEvaluation.objects.filter(
            staff=self.staff, period=self.period, attribute=self.attribute
        ).exclude(pk=self.pk)
        self.calculate_scores(qs)
        super().save(*args, **kwargs)


# ================================================================
# Staff Overall Result
# ================================================================
class StaffResult(models.Model):
    staff = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="staff_results",
    )
    period = models.ForeignKey(SPEPeriod, on_delete=models.CASCADE)
    # REMOVED: department field - delegate to staff.department
    overall_score = models.FloatField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("staff", "period")
        ordering = ["-overall_score"]

    def update_overall_score(self):
        """Aggregate all evaluations into an overall score."""
        if self.staff.role == "teaching":
            evaluations = TeachingStaffEvaluation.objects.filter(
                staff=self.staff, period=self.period
            )
        else:
            evaluations = NonTeachingStaffEvaluation.objects.filter(
                staff=self.staff, period=self.period
            )

        if evaluations.exists():
            self.overall_score = (
                evaluations.aggregate(avg=Avg("percent_score"))["avg"] or 0
            )
            self.save()

    def __str__(self):
        return f"{self.staff} - {self.period.name}: {self.overall_score:.2f}%"

    @property
    def department(self):
        """Delegate to staff's department"""
        return self.staff.department


# ================================================================
# Department Summary (for dashboard analytics)
# ================================================================
class DepartmentSummary(models.Model):
    period = models.ForeignKey(SPEPeriod, on_delete=models.CASCADE)
    department = models.ForeignKey(
        "users.Department", on_delete=models.CASCADE
    )
    avg_score = models.FloatField(default=0)
    num_staff = models.PositiveIntegerField(default=0)
    rank = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("period", "department")
        ordering = ["rank"]

    def __str__(self):
        return f"{self.department.name} ({self.period.name}) - Avg: {self.avg_score:.2f}%"


# ================================================================
# Self-Assessment (by staff)
# ================================================================
class SelfAssessment(models.Model):
    staff = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="spe_self_assessments",
    )
    period = models.ForeignKey(SPEPeriod, on_delete=models.CASCADE)
    attribute = models.ForeignKey(
        SPEAttribute,
        on_delete=models.CASCADE,
        related_name="spe_self_assessments",
    )
    indicator = models.ForeignKey(
        SPEIndicator,
        on_delete=models.CASCADE,
        related_name="spe_self_assessments",
    )
    # REMOVED: department field - delegate to staff.department

    self_rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    remarks = models.TextField(blank=True, null=True)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("staff", "period", "indicator")
        ordering = ["-period", "staff"]

    def __str__(self):
        return f"{self.staff} - {self.indicator.description} (Self: {self.self_rating})"

    @property
    def department(self):
        """Delegate to staff's department"""
        return self.staff.department

    # ✅ REMOVED: clean() method - No department validation needed for global forms workflow

    def save(self, *args, **kwargs):
        # ✅ REMOVED: self.clean() call
        super().save(*args, **kwargs)


# ================================================================
# Supervisor Evaluation (per indicator) - WITH DEPARTMENT ENFORCEMENT
# ================================================================
class SupervisorEvaluation(models.Model):
    supervisor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="spe_supervisor_evaluations",
        limit_choices_to={"role": "supervisor"},
    )
    self_assessment = models.ForeignKey(
        SelfAssessment,
        on_delete=models.CASCADE,
        related_name="spe_supervisor_evaluation",
    )

    supervisor_rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    remarks = models.TextField(blank=True, null=True)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("supervisor", "self_assessment")
        ordering = ["-submitted_at"]

    def __str__(self):
        return f"{self.supervisor} → {self.self_assessment.staff} ({self.supervisor_rating})"

    def clean(self):
        """Validate supervisor can only evaluate staff in their department"""
        if (
            self.supervisor.department
            and self.self_assessment.department != self.supervisor.department
        ):
            raise ValidationError(
                "Supervisor can only evaluate staff in their own department"
            )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


# ================================================================
# Evaluation Comments (Generic - supports both evaluation types)
# ================================================================
class EvaluationComment(models.Model):
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    evaluation = GenericForeignKey("content_type", "object_id")

    commenter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="spe_comments",
    )
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Comment by {self.commenter} on {self.evaluation}"


# ================================================================
# Signals: Auto-update StaffResult
# ================================================================
def _update_staff_result(instance):
    staff = instance.staff
    period = instance.period

    result, _ = StaffResult.objects.get_or_create(staff=staff, period=period)
    result.update_overall_score()


@receiver(post_save, sender=TeachingStaffEvaluation)
def update_teaching_result(sender, instance, **kwargs):
    _update_staff_result(instance)


@receiver(post_save, sender=NonTeachingStaffEvaluation)
def update_non_teaching_result(sender, instance, **kwargs):
    _update_staff_result(instance)


from django.conf import settings
from django.db import models


class SupervisorRating(models.Model):
    RATING_CHOICES = [
        (1, "1 - Poor"),
        (2, "2 - Fair"),
        (3, "3 - Good"),
        (4, "4 - Very Good"),
        (5, "5 - Excellent"),
    ]

    supervisor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,  # Use this instead of User
    )
    period = models.ForeignKey("SPEPeriod", on_delete=models.CASCADE)
    attribute = models.ForeignKey(
        "hr.SupervisorAttribute", on_delete=models.CASCADE
    )
    indicator = models.ForeignKey(
        "hr.SupervisorIndicator", on_delete=models.CASCADE
    )
    rating = models.IntegerField(choices=RATING_CHOICES)
    comments = models.TextField(blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ["supervisor", "period", "indicator"]

    def __str__(self):
        return f"{self.supervisor} - {self.indicator} - {self.rating}"
