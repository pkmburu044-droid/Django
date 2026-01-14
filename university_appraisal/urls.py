from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from users.views import CustomLoginView

urlpatterns = [
    path("admin/", admin.site.urls),
    # ✅ FIXED: Remove duplicates and use proper include syntax
    path("", include("users.urls")),
    path("dashboard/", include("dashboards.urls")),
    path("spe/", include("spe.urls")),
    path("hr/", include("hr.urls")),
    path("login/", CustomLoginView.as_view(), name="login"),
    path(
        "logout/", auth_views.LogoutView.as_view(next_page="/"), name="logout"
    ),
    path("vc/", include("vc.urls")),
]
