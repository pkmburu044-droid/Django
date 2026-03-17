from django.urls import path

from . import views

app_name = "vc"

urlpatterns = [
    path("dashboard/", views.vc_dashboard, name="vc_dashboard"),
    path(
        "departments/",
        views.vc_department_overview,
        name="vc_department_overview",
    ),
    path('staff-results/<int:staff_id>/', views.vc_view_staff_results, name='vc_view_staff_results'),
    path(
        "departments/<int:department_id>/",
        views.vc_department_staff,
        name="vc_department_staff",
    ),
    path(
        "evaluate/supervisors/",
        views.vc_evaluate_supervisor_list,
        name="vc_evaluate_supervisor_list",
    ),
    path(
        "evaluate/supervisor/<int:supervisor_id>/",
        views.vc_evaluate_supervisor,
        name="vc_evaluate_supervisor",
    ),
    path(
        "reports/supervisor/<int:supervisor_id>/",
        views.vc_download_supervisor_report,
        name="vc_download_supervisor_report",
    ),
    path(
        "reports/department/",
        views.vc_download_department_report,
        name="vc_download_department_report",
    ),
    path(
        "reports/department/<int:department_id>/",
        views.vc_download_department_report,
        name="vc_download_department_report",
    ),
    path(
        "api/department-stats/",
        views.vc_department_stats_api,
        name="vc_department_stats_api",
    ),
    path(
        "api/performance-trends/",
        views.vc_performance_trends_api,
        name="vc_performance_trends_api",
    ),
    path("search/", views.vc_search_staff, name="vc_search_staff"),
    path(
        "export/<str:data_type>/", views.vc_export_data, name="vc_export_data"
    ),
    
    # TARGET APPROVAL URLs
    path('targets/approval/', views.vc_targets_approval, name='vc_targets_approval'),
    
  
    # NEW: Supervisor targets view (for viewing all targets of a supervisor)
    path('targets/supervisor/<int:supervisor_id>/', views.vc_supervisor_targets, name='vc_supervisor_targets'),
    
    path('targets/approved/', views.vc_approved_targets, name='vc_approved_targets'),

]