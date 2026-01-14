from django.contrib.auth import views as auth_views
from django.shortcuts import redirect
from django.urls import path

from . import views
from .views import CustomLogoutView, complete_profile, signup_view

app_name = "users"

urlpatterns = [
    path("signup/", signup_view, name="signup"),
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="users/login.html"),
        name="login",
    ),
    path("complete-profile/", complete_profile, name="complete_profile"),
    path("logout/", CustomLogoutView.as_view(), name="logout"),
    path("profile/edit/", views.edit_profile, name="edit_profile"),
    path("redirect/", views.role_based_redirect, name="role_based_redirect"),
    path("", lambda request: redirect("users:login")),
    path(
        "targets/set/",
        views.set_performance_targets,
        name="set_performance_targets",
    ),
    path(
        "targets/view/",
        views.view_performance_targets,
        name="view_performance_targets",
    ),
    path(
        "targets/staff/", views.view_staff_targets, name="view_staff_targets"
    ),
    path(
        "supervisor/evaluate-targets/",
        views.evaluate_staff_targets,
        name="evaluate_staff_targets",
    ),
    path(
        "supervisor/evaluate-targets/<int:staff_id>/",
        views.evaluate_staff_targets,
        name="evaluate_staff_targets",
    ),
]
