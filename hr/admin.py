# hr/admin.py
from django.contrib import admin

from .models import (
    SupervisorAppraisal,
    SupervisorAssessment,
    SupervisorEvaluationByStaff,
    SupervisorOverallEvaluation,
)

# ... your existing admin classes ...


@admin.register(SupervisorAppraisal)
class SupervisorAppraisalAdmin(admin.ModelAdmin):
    list_display = [
        "supervisor",
        "period",
        "overall_score",  # Changed from 'percentage_score' to 'overall_score'
        "status",
        "evaluated_by",
        "evaluated_at",
    ]
    list_filter = ["period", "status", "evaluated_at"]
    search_fields = [
        "supervisor__first_name",
        "supervisor__last_name",
        "supervisor__email",
    ]
    readonly_fields = ["evaluated_at"]
    date_hierarchy = "evaluated_at"

    fieldsets = (
        (
            "Basic Information",
            {"fields": ("supervisor", "period", "evaluated_by", "status")},
        ),
        (
            "Scores",
            {
                "fields": (
                    "total_score",
                    "average_score",
                    "overall_score",
                )  # Updated field names
            },
        ),
        ("Timestamps", {"fields": ("evaluated_at",)}),
    )


# Register other new models
@admin.register(SupervisorAssessment)
class SupervisorAssessmentAdmin(admin.ModelAdmin):
    list_display = ["period", "attribute", "indicator", "weight", "is_active"]
    list_filter = ["period", "is_active"]
    search_fields = ["attribute__name", "indicator__description"]


@admin.register(SupervisorEvaluationByStaff)
class SupervisorEvaluationByStaffAdmin(admin.ModelAdmin):
    list_display = [
        "staff",
        "supervisor",
        "period",
        "staff_rating",
        "evaluated_at",
    ]
    list_filter = ["period", "staff_rating"]
    search_fields = [
        "staff__first_name",
        "staff__last_name",
        "supervisor__first_name",
        "supervisor__last_name",
    ]


@admin.register(SupervisorOverallEvaluation)
class SupervisorOverallEvaluationAdmin(admin.ModelAdmin):
    list_display = [
        "supervisor",
        "period",
        "attribute",
        "rating",
        "status",
        "submitted_at",
    ]
    list_filter = ["period", "status", "rating"]
    search_fields = [
        "supervisor__first_name",
        "supervisor__last_name",
        "attribute__name",
    ]


# ... rest of your admin registrations ...
