from django.urls import path, include
from django.contrib.auth import views as auth_views  
from .views import signup_view, role_based_redirect, complete_profile

urlpatterns = [
    path('signup/', signup_view, name='signup'),
    path('login/', auth_views.LoginView.as_view(template_name='users/login.html'), name='login'),
    path('complete-profile/', complete_profile, name='complete_profile'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    path('dashboard/', role_based_redirect, name='role_based_redirect'),
   
]
