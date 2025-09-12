from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser
from .forms import CustomUserCreationForm, NonTeachingStaffProfile


class CustomUserAdmin(UserAdmin):
    add_form = CustomUserCreationForm
    model = CustomUser

    list_display = ("pf_number", "role", "is_staff", "is_active")
    list_filter = ("role", "is_staff", "is_active")

    fieldsets = (
        (None, {"fields": ("pf_number", "password")}),
        ("Personal info", {"fields": ("role",)}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login",)}),
    )

    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("pf_number", "role", "password1", "password2", "is_staff", "is_active")}
        ),
    )

    search_fields = ("pf_number",)
    ordering = ("pf_number",)

admin.site.register(CustomUser, CustomUserAdmin)
