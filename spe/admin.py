from django.contrib import admin
from .models import SPEPeriod, SPEAttribute, SPEIndicator, NonTeachingStaffEvaluation, TeachingStaffEvaluation


@admin.register(SPEPeriod)
class SPEPeriodAdmin(admin.ModelAdmin):
    list_display = ("name", "start_date", "end_date", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)

    def save_model(self, request, obj, form, change):
        if obj.is_active:
            # ensure only one active period at a time
            SPEPeriod.objects.exclude(pk=obj.pk).update(is_active=False)
        super().save_model(request, obj, form, change)


@admin.register(SPEAttribute)
class SPEAttributeAdmin(admin.ModelAdmin):
    list_display = ("name", "period")
    list_filter = ("period",)
    search_fields = ("name",)


@admin.register(SPEIndicator)
class SPEIndicatorAdmin(admin.ModelAdmin):
    list_display = ("description", "attribute")
    list_filter = ("attribute",)
    search_fields = ("description", "attribute__name")


@admin.register(TeachingStaffEvaluation)
class TeachingStaffEvaluationAdmin(admin.ModelAdmin):
    list_display = ("staff", "period", "attribute", "indicator", "rating", "remarks")
    list_filter = ("period", "attribute", "staff")
    search_fields = ("staff__email", "indicator__description", "attribute__name")


@admin.register(NonTeachingStaffEvaluation)
class NonTeachingStaffEvaluationAdmin(admin.ModelAdmin):
    list_display = ("staff", "period", "attribute", "indicator", "rating", "remarks")
    list_filter = ("period", "attribute", "staff")
    search_fields = ("staff__email", "indicator__description", "attribute__name")
