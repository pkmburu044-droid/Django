# spe/models.py
from django.db import models
from django.conf import settings

# -----------------------------
# Evaluation Period
# -----------------------------
class SPEPeriod(models.Model):
    """Staff Performance Evaluation Period"""
    name = models.CharField(max_length=150)
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.start_date} - {self.end_date})"


# -----------------------------
# Attributes & Indicators
# -----------------------------
class SPEAttribute(models.Model):
    """High-level evaluation criteria (e.g., Work Efficiency)"""
    period = models.ForeignKey(SPEPeriod, on_delete=models.CASCADE, related_name='attributes')
    name = models.CharField(max_length=150)

    def __str__(self):
        return f"{self.name} ({self.period.name})"


class SPEIndicator(models.Model):
    """Measurable items under each attribute"""
    attribute = models.ForeignKey(SPEAttribute, on_delete=models.CASCADE, related_name='indicators')
    description = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.description} ({self.attribute.name})"


# spe/models.py
class NonTeachingStaffEvaluation(models.Model):
    staff = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        limit_choices_to={'role': 'non_teaching'}
    )
    period = models.ForeignKey(SPEPeriod, on_delete=models.CASCADE)
    attribute = models.ForeignKey(SPEAttribute, on_delete=models.CASCADE)
    indicator = models.ForeignKey(SPEIndicator, on_delete=models.CASCADE)
    rating = models.PositiveSmallIntegerField(default=0)
    remarks = models.TextField(blank=True, null=True)

    trs = models.FloatField(default=0)
    mrs = models.FloatField(default=0)
    percent_score = models.FloatField(default=0)
    
    # <-- New field
    is_submitted = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        self.rating = int(self.rating)
        ratings_qs = NonTeachingStaffEvaluation.objects.filter(
            staff=self.staff,
            period=self.period,
            attribute=self.attribute
        ).exclude(pk=self.pk)

        total_ratings = sum(int(r.rating) for r in ratings_qs) + self.rating
        num_indicators = ratings_qs.count() + 1

        self.trs = total_ratings
        self.mrs = total_ratings / num_indicators if num_indicators else self.rating
        self.percent_score = (self.mrs / 5) * 100

        super().save(*args, **kwargs)


class TeachingStaffEvaluation(models.Model):
    staff = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        limit_choices_to={'role': 'teaching'}
    )
    period = models.ForeignKey(SPEPeriod, on_delete=models.CASCADE)
    attribute = models.ForeignKey(SPEAttribute, on_delete=models.CASCADE)
    indicator = models.ForeignKey(SPEIndicator, on_delete=models.CASCADE)
    rating = models.PositiveSmallIntegerField(default=0)
    remarks = models.TextField(blank=True, null=True)

    trs = models.FloatField(default=0)
    mrs = models.FloatField(default=0)
    percent_score = models.FloatField(default=0)

    # <-- New field
    is_submitted = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        self.rating = int(self.rating)
        ratings_qs = TeachingStaffEvaluation.objects.filter(
            staff=self.staff,
            period=self.period,
            attribute=self.attribute
        ).exclude(pk=self.pk)

        total_ratings = sum(int(r.rating) for r in ratings_qs) + self.rating
        num_indicators = ratings_qs.count() + 1

        self.trs = total_ratings
        self.mrs = total_ratings / num_indicators if num_indicators else self.rating
        self.percent_score = (self.mrs / 5) * 100

        super().save(*args, **kwargs)
