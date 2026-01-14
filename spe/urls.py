from django.urls import path

from dashboards import views as dashboard_views
from users.views import role_based_redirect

from . import views

app_name = "spe"

urlpatterns = [
    # Add dashboard redirect at the top
    path("", role_based_redirect, name="dashboard_redirect"),
    # Your existing URLs
    path("start/", views.start_self_assessment, name="start_self_assessment"),
    path("evaluation/", views.start_self_assessment, name="evaluation_form"),
    path(
        "supervisor/teaching/<int:staff_id>/evaluate/",
        views.evaluate_self_assessment,
        name="teaching_evaluate_staff",
    ),
    path(
        "supervisor/nonteaching/<int:staff_id>/evaluate/",
        views.evaluate_self_assessment,
        name="nonteaching_evaluate_staff",
    ),
    path(
        "attributes/manage/", views.manage_attributes, name="manage_attributes"
    ),
    path(
        "period/<int:period_id>/edit/",
        views.edit_period_attributes,
        name="edit_period_attributes",
    ),
    path(
        "attribute/<int:attribute_id>/delete/",
        views.delete_attribute,
        name="delete_attribute",
    ),
    path(
        "indicator/<int:indicator_id>/delete/",
        views.delete_indicator,
        name="delete_indicator",
    ),
    path(
        "self-evaluation/",
        views.supervisor_evaluation_form,
        name="supervisor_evaluation_form",
    ),
    path("", role_based_redirect, name="dashboard_redirect"),
    path(
        "supervisor/dashboard/",
        dashboard_views.supervisor_dashboard,
        name="supervisor_dashboard",
    ),
    path(
        "supervisor-self-report/",
        views.supervisor_self_report,
        name="supervisor_self_report",
    ),
]
