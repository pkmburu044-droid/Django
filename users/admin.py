from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .forms import CustomUserCreationForm
from .models import CustomUser, Department, StaffProfile


@admin.register(StaffProfile)
class StaffProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "designation",
        "department",
        "get_user_email",
        "get_user_role",
    )
    list_filter = ("department", "department__staff_type")
    search_fields = (
        "user__email",
        "user__first_name",
        "user__last_name",
        "designation",
    )
    raw_id_fields = ("user",)  # Better for performance with many users

    def get_user_email(self, obj):
        return obj.user.email

    get_user_email.short_description = "Email"

    def get_user_role(self, obj):
        return obj.user.role

    get_user_role.short_description = "User Role"


# -------------------------------
# Inline: Manage Users under a Department
# -------------------------------
class StaffInline(admin.TabularInline):
    model = CustomUser
    fields = (
        "email",
        "pf_number",
        "first_name",
        "last_name",
        "role",
        "employment_type",
        "is_active",
        "is_staff",
    )
    extra = 1
    show_change_link = True


# -------------------------------
# Department Admin
# -------------------------------
@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "staff_type", "code")
    search_fields = ("name", "code")
    inlines = [StaffInline]

    def get_inline_instances(self, request, obj=None):
        """
        Only show inline users when editing an existing Department.
        When adding a new Department, inlines are hidden until saved.
        """
        if obj is None:
            return []
        return super().get_inline_instances(request, obj)


# -------------------------------
# Custom User Admin
# -------------------------------
@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    add_form = CustomUserCreationForm
    model = CustomUser

    list_display = (
        "email",
        "pf_number",
        "first_name",
        "last_name",
        "role",
        "department",
        "employment_type",
        "is_staff",
        "is_active",
    )
    list_filter = (
        "role",
        "department",
        "employment_type",
        "is_staff",
        "is_active",
    )

    fieldsets = (
        (None, {"fields": ("email", "pf_number", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name")}),
        (
            "Role & Status",
            {
                "fields": (
                    "role",
                    "department",
                    "employment_type",
                    "is_active",
                    "is_staff",
                    "is_superuser",
                )
            },
        ),
        ("Permissions", {"fields": ("groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login",)}),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "pf_number",
                    "first_name",
                    "last_name",
                    "role",
                    "department",
                    "employment_type",
                    "password1",
                    "password2",
                    "is_active",
                    "is_staff",
                ),
            },
        ),
    )

    search_fields = (
        "email",
        "pf_number",
        "first_name",
        "last_name",
        "department__name",
    )
    ordering = ("email",)
