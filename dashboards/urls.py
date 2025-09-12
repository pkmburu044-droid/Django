from django.urls import path
from . import views
from django.shortcuts import redirect


urlpatterns = [
    path('', lambda request: redirect('login')), 
    path('teaching/', views.teaching_dashboard, name='teaching_dashboard'),
    path('non_teaching/', views.non_teaching_dashboard, name='non_teaching_dashboard'),
    path('supervisor/', views.supervisor_dashboard, name='supervisor_dashboard'),
    path("profile/", views.profile_details, name="profile_details"),
    path('non_teaching/appraisals/create/', views.create_non_teaching_appraisal, name='create_non_teaching_appraisal'),
    path('teaching/appraisal/', views.teaching_appraisal, name='teaching_appraisal'),
    path("profile/edit/", views.edit_profile, name="edit_profile"),
    path('appraisal/', views.appraisal_redirect, name='appraisal_redirect'),
]


