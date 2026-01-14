from django.contrib.auth.views import LogoutView
from django.urls import path

from users.views import (
    role_based_redirect,  # ✅ IMPORT FROM USERS
    view_staff_targets,
)

from . import views

app_name = "dashboards"

urlpatterns = [
    path("", role_based_redirect, name="dashboard_redirect"),
    path("teaching/", views.teaching_dashboard, name="teaching_dashboard"),
    path(
        "non-teaching/",
        views.non_teaching_dashboard,
        name="non_teaching_dashboard",
    ),
    path(
        "supervisor/", views.supervisor_dashboard, name="supervisor_dashboard"
    ),
    path(
        "supervisor/staff/",
        views.view_department_staff,
        name="view_department_staff",
    ),
    path(
        "supervisor/staff/evaluations/",
        views.view_staff_evaluations,
        name="view_staff_evaluations",
    ),
    path(
        "supervisor/staff-evaluations/",
        views.view_staff_evaluations,
        name="view_staff_evaluations",
    ),
    path(
        "supervisor/evaluate/<int:appraisal_id>/",
        views.evaluate_staff,
        name="evaluate_staff",
    ),
    path(
        "supervisor-evaluation-results/",
        views.supervisor_evaluation_results,
        name="supervisor_evaluation_results",
    ),
    path(
        "supervisor-evaluation-results/<int:appraisal_id>/",
        views.supervisor_evaluation_results,
        name="supervisor_evaluation_results_detail",
    ),
    # ✅ USE THE IMPORTED FUNCTION (no 'views.' prefix)
    path(
        "supervisor/targets/",
        view_staff_targets,
        name="supervisor_view_targets_list",
    ),
    path(
        "supervisor/targets/<int:staff_id>/",
        views.supervisor_view_targets,
        name="supervisor_view_targets",
    ),
    path(
        "staff/evaluation/results/",
        views.staff_evaluation_results,
        name="staff_evaluation_results",
    ),
    path(
        "staff/evaluation/results/<int:appraisal_id>/",
        views.staff_evaluation_results,
        name="staff_evaluation_detail",
    ),
    path("approve-targets/", views.approve_target, name="approve_target"),
    path(
        "targets/<int:target_id>/approve/",
        views.approve_target,
        name="approve_target",
    ),
    path(
        "targets/<int:target_id>/reject/",
        views.reject_target,
        name="reject_target",
    ),
    path("profile/", views.profile_details, name="profile_details"),
    path("appraisal/create/", views.create_appraisal, name="create_appraisal"),
    path("appraisal/", views.appraisal_redirect, name="appraisal_redirect"),
    path(
        "teaching/appraisal/",
        views.create_appraisal,
        name="teaching_appraisal",
    ),
    path(
        "non-teaching/appraisal/create/",
        views.create_appraisal,
        name="create_non_teaching_appraisal",
    ),
    path(
        "logout/", LogoutView.as_view(next_page="users:login"), name="logout"
    ),
]
