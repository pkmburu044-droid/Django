from django.urls import path
from . import views 

app_name = 'spe'  


urlpatterns = [
    path('evaluation/', views.evaluation_form, name='evaluation_form'),
    path('teaching/evaluation/', views.teaching_evaluation_form, name='teaching_evaluation_form'),
    path('evaluation/add/', views.add_new_evaluation, name='add_new_evaluation'),
    path('teaching/appraisal/', views.teaching_appraisal, name='teaching_appraisal'),
    path('teaching/appraisal/<int:pk>/', views.teaching_appraisal_detail, name='teaching_appraisal_detail'),
    path('supervisor/teaching/<int:staff_id>/evaluate/', views.teaching_evaluate_staff, name='teaching_evaluate_staff'),
    path('supervisor/nonteaching/<int:staff_id>/evaluate/', views.nonteaching_evaluate_staff, name='nonteaching_evaluate_staff'),
]
