from django.contrib import admin
from django.db.models import Avg, Count
from django.shortcuts import render
from django.utils.html import format_html

from .models import (
    NonTeachingStaffEvaluation,
    SelfAssessment,
    SPEAttribute,
    SPEIndicator,
    SPEPeriod,
    SupervisorEvaluation,
    TeachingStaffEvaluation,
)

# ================================================
# Inline Administrations for Indicators Only
# ================================================


class SPEIndicatorInline(admin.TabularInline):
    model = SPEIndicator
    extra = 1
    fields = ("description",)


# ================================================
# Main Admin Classes
# ================================================
@admin.register(SPEPeriod)
class SPEPeriodAdmin(admin.ModelAdmin):
    list_display = ("name", "start_date", "end_date", "is_active", "forms_status", "current_phase")
    list_editable = ("is_active", "forms_status")
    list_filter = ("is_active", "forms_status")
    search_fields = ("name",)
    
@admin.register(SPEAttribute)
class SPEAttributeAdmin(admin.ModelAdmin):
    list_display = ("name", "period", "department", "staff_type")
    list_filter = ("period", "staff_type", "department")
    search_fields = ("name", "department__name")
    inlines = [SPEIndicatorInline]


@admin.register(SPEIndicator)
class SPEIndicatorAdmin(admin.ModelAdmin):
    list_display = ("description", "attribute", "attribute_department")
    list_filter = ("attribute", "attribute__department")
    search_fields = ("description", "attribute__name")

    def attribute_department(self, obj):
        return obj.attribute.department.name

    attribute_department.short_description = "Department"


# ================================================
# Template-Based Evaluation Admins
# ================================================


@admin.register(TeachingStaffEvaluation)
class TeachingStaffEvaluationAdmin(admin.ModelAdmin):
    list_display = (
        "staff",
        "period",
        "attribute",
        "indicator",
        "rating",
        "percent_score",
        "status",
    )
    list_filter = ("period", "attribute", "staff", "status")
    search_fields = (
        "staff__email",
        "indicator__description",
        "attribute__name",
    )
    readonly_fields = (
        "total_raw_score",
        "mean_raw_score",
        "percent_score",
        "created_at",
        "updated_at",
    )

    def changelist_view(self, request, extra_context=None):
        # Check if we're filtering by specific staff and period
        staff_id = request.GET.get("staff__id__exact")
        period_id = request.GET.get("period__id__exact")

        # If specific filters are applied, show the normal Django admin list
        if staff_id and period_id:
            return super().changelist_view(request, extra_context)

        # Otherwise show our custom staff summary view
        staff_stats = (
            TeachingStaffEvaluation.objects.values(
                "staff__id",
                "staff__first_name",
                "staff__last_name",
                "staff__email",
                "period__id",
                "period__name",
            )
            .annotate(
                total_evaluations=Count("id"),
                avg_rating=Avg("rating"),
                avg_percent=Avg("percent_score"),
                statuses=Count("status", distinct=True),
            )
            .order_by("staff__first_name", "staff__last_name")
        )

        context = {
            "staff_stats": staff_stats,
            "opts": self.model._meta,
            "title": "Teaching Staff Evaluation Summary",
        }
        if extra_context:
            context.update(extra_context)

        return render(
            request, "admin/spe/staff_evaluation_summary.html", context
        )


@admin.register(NonTeachingStaffEvaluation)
class NonTeachingStaffEvaluationAdmin(admin.ModelAdmin):
    list_display = (
        "staff",
        "period",
        "attribute",
        "indicator",
        "rating",
        "percent_score",
        "status",
    )
    list_filter = ("period", "attribute", "staff", "status")
    search_fields = (
        "staff__email",
        "indicator__description",
        "attribute__name",
    )
    readonly_fields = (
        "total_raw_score",
        "mean_raw_score",
        "percent_score",
        "created_at",
        "updated_at",
    )

    def changelist_view(self, request, extra_context=None):
        # Check if we're filtering by specific staff and period
        staff_id = request.GET.get("staff__id__exact")
        period_id = request.GET.get("period__id__exact")

        # If specific filters are applied, show the normal Django admin list
        if staff_id and period_id:
            return super().changelist_view(request, extra_context)

        # Otherwise show our custom staff summary view
        staff_stats = (
            NonTeachingStaffEvaluation.objects.values(
                "staff__id",
                "staff__first_name",
                "staff__last_name",
                "staff__email",
                "period__id",
                "period__name",
            )
            .annotate(
                total_evaluations=Count("id"),
                avg_rating=Avg("rating"),
                avg_percent=Avg("percent_score"),
                statuses=Count("status", distinct=True),
            )
            .order_by("staff__first_name", "staff__last_name")
        )

        context = {
            "staff_stats": staff_stats,
            "opts": self.model._meta,
            "title": "Non-Teaching Staff Evaluation Summary",
        }
        if extra_context:
            context.update(extra_context)

        return render(
            request, "admin/spe/staff_evaluation_summary.html", context
        )


@admin.register(SelfAssessment)
class SelfAssessmentAdmin(admin.ModelAdmin):
    list_display = (
        "staff",
        "period",
        "attribute",
        "indicator",
        "self_rating",
        "submitted_at",
    )
    list_filter = ("period", "attribute", "staff")
    search_fields = ("staff__email", "indicator__description")


@admin.register(SupervisorEvaluation)
class SupervisorEvaluationAdmin(admin.ModelAdmin):
    list_display = (
        "supervisor",
        "self_assessment",
        "supervisor_rating",
        "submitted_at",
    )
    list_filter = ("supervisor", "submitted_at")
    search_fields = ("supervisor__email", "self_assessment__staff__email")