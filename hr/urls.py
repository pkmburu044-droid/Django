# hr/urls.py
from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "hr"

urlpatterns = [
    # Dashboard & Core Views
    path("dashboard/", views.hr_dashboard, name="hr_dashboard"),
    # Department Appraisal Management - ADD THESE LINES
    path(
        "department-appraisals/",
        views.hr_department_appraisals,
        name="hr_department_appraisals",
    ),
    path(
        "attributes/", views.hr_manage_attributes, name="hr_manage_attributes"
    ),
    # Reporting
    path(
        "reports/generate/",
        views.hr_generate_reports,
        name="hr_generate_reports",
    ),
    path("reports/view/", views.hr_view_reports, name="hr_view_reports"),
    path(
        "reports/staff-evaluation/<int:appraisal_id>/",
        views.hr_staff_evaluation_detail,
        name="hr_staff_evaluation_detail",
    ),
    path(
        "reports/download-pdf/<int:appraisal_id>/",
        views.download_evaluation_pdf,
        name="download_evaluation_pdf",
    ),
    # Analytics & API
    path(
        "analytics/",
        views.hr_performance_analytics,
        name="hr_performance_analytics",
    ),
    path(
        "api/performance-data/",
        views.hr_api_performance_data,
        name="hr_api_performance_data",
    ),
    path(
        "logout/", auth_views.LogoutView.as_view(next_page="/"), name="logout"
    ),
]
