from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.conf import settings

# -------------------------------
# Custom User
# -------------------------------
class CustomUserManager(BaseUserManager):
    def create_user(self, pf_number, password=None, **extra_fields):
        if not pf_number:
            raise ValueError('PF Number must be set')
        pf_number = self.model.normalize_username(pf_number)
        user = self.model(pf_number=pf_number, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, pf_number, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', 'supervisor')  # Optional: superuser role

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(pf_number, password, **extra_fields)

class CustomUser(AbstractBaseUser, PermissionsMixin):
    pf_number = models.CharField(max_length=20, unique=True)
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    ROLE_CHOICES = [
        ('teaching', 'Teaching Staff'),
        ('non_teaching', 'Non-Teaching Staff'),
        ('supervisor', 'Supervisor'),
    ]
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)

    # Remove 'casual' from terms of service choices
    TERMS_OF_SERVICE_CHOICES = [
        ('permanent', 'Permanent'),
        ('contract', 'Contract'),
    ]
    terms_of_service = models.CharField(
        max_length=20,
        choices=TERMS_OF_SERVICE_CHOICES,
        default='permanent'
    )

    objects = CustomUserManager()

    USERNAME_FIELD = 'pf_number'
    REQUIRED_FIELDS = ['role', 'first_name', 'last_name', 'terms_of_service']

    def __str__(self):
        return f"{self.pf_number} ({self.get_role_display()})"

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}"

# -------------------------------
# Non-Teaching Staff
# -------------------------------
class TeachingStaffProfile(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)
    designation = models.CharField(max_length=100)
    department = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.pf_number} ({self.designation})"


class NonTeachingStaffProfile(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)
    designation = models.CharField(max_length=100)
    department = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.pf_number} ({self.designation})"



class NonTeachingAppraisal(models.Model):
    profile = models.ForeignKey(NonTeachingStaffProfile, on_delete=models.CASCADE, related_name='appraisals')
    period_under_review = models.CharField(max_length=100)
    length_of_service = models.CharField(max_length=50)
    years_in_equivalent_position = models.CharField(max_length=50)
    supervisor_name = models.CharField(max_length=100)
    appraisal_date = models.DateField()
    acting_or_special_duty = models.CharField(
        max_length=255,
        verbose_name="Acting/Special Duty (state duration)",
        help_text="E.g. 'Acting Librarian – 2 months' or 'None'"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return f"Appraisal for {self.profile.user.get_full_name()} – {self.period_under_review}"


# -------------------------------
# Teaching Staff
# -------------------------------
# users/models.py



class TeachingStaffAppraisal(models.Model):
    profile = models.ForeignKey(TeachingStaffProfile, on_delete=models.CASCADE, related_name='appraisals')  # NEW
    date_of_appointment = models.DateField()
    acting_appointment = models.TextField(blank=True, null=True)
    years_experience_kyu = models.PositiveIntegerField(default=0)  
    years_experience_elsewhere = models.PositiveIntegerField(default=0)
    supervisor_name = models.CharField(max_length=255)
    supervisor_designation = models.CharField(max_length=255)

    def __str__(self):
        return f"Appraisal by {self.supervisor_name}"
