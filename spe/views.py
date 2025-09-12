from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import (
    SPEPeriod, 
    SPEAttribute, 
    SPEIndicator, 
    NonTeachingStaffEvaluation,
    TeachingStaffEvaluation
)
from users.models import (
    NonTeachingStaffProfile, 
    TeachingStaffProfile, 
    TeachingStaffAppraisal
)
from .forms import (
    SPEPeriodForm, 
    SPEAttributeForm,
    SPEIndicatorForm,
    NonTeachingStaffEvaluationForm,
    TeachingStaffEvaluationForm,
)


# ============================
# NON-TEACHING Evaluation
# ============================
@login_required
def evaluation_form(request):
    """Non-Teaching Evaluation"""
    if request.user.role != 'non_teaching':
        return redirect('teaching_dashboard')

    try:
        period = SPEPeriod.objects.get(is_active=True)
    except SPEPeriod.DoesNotExist:
        messages.error(request, "No active evaluation period found. Please contact the supervisor/admin.")
        return redirect("role_based_redirect")

    attributes = SPEAttribute.objects.filter(period=period).prefetch_related("indicators")

    if request.method == 'POST':
        for indicator in SPEIndicator.objects.filter(attribute__period=period):
            rating = request.POST.get(f"rating_{indicator.id}")
            remarks = request.POST.get(f"remarks_{indicator.id}")

            if rating:
                NonTeachingStaffEvaluation.objects.create(
                    staff=request.user,
                    period=period,
                    attribute=indicator.attribute,
                    indicator=indicator,
                    rating=rating,
                    remarks=remarks or ""
                )

        messages.success(request, "Your evaluation was submitted successfully.")
        return redirect('non_teaching_dashboard')

    return render(request, 'spe/evaluation_form.html', {
        'period': period,
        'attributes': attributes,
    })


# ============================
# TEACHING Evaluation
# ============================
@login_required
def teaching_evaluation_form(request):
    """Teaching Evaluation"""
    if request.user.role != 'teaching':
        return redirect('non_teaching_dashboard')

    try:
        period = SPEPeriod.objects.get(is_active=True)
    except SPEPeriod.DoesNotExist:
        messages.error(request, "No active evaluation period found. Please contact the supervisor/admin.")
        return redirect("role_based_redirect")

    attributes = SPEAttribute.objects.filter(period=period).prefetch_related("indicators")

    if request.method == 'POST':
        for indicator in SPEIndicator.objects.filter(attribute__period=period):
            rating = request.POST.get(f"rating_{indicator.id}")
            remarks = request.POST.get(f"remarks_{indicator.id}")

            if rating:
                TeachingStaffEvaluation.objects.create(
                    staff=request.user,
                    period=period,
                    attribute=indicator.attribute,
                    indicator=indicator,
                    rating=rating,
                    remarks=remarks or ""
                )

        messages.success(request, "Your evaluation was submitted successfully.")
        return redirect('teaching_dashboard')

    return render(request, 'spe/teaching_evaluation_form.html', {
        'period': period,
        'attributes': attributes,
    })


# ============================
# SUPERVISOR: Add Periods, Attributes & Indicators
# ============================
@login_required
def add_new_evaluation(request):
    if request.user.role != 'supervisor':
        return redirect('role_based_redirect')

    # Initialize forms
    period_form = SPEPeriodForm()
    attribute_form = SPEAttributeForm()
    indicator_form = SPEIndicatorForm()

    # Handle submissions
    if request.method == 'POST':
        if 'add_period' in request.POST:
            period_form = SPEPeriodForm(request.POST)
            if period_form.is_valid():
                period_form.save()
                return redirect('spe:add_new_evaluation')

        elif 'add_attribute' in request.POST:
            attribute_form = SPEAttributeForm(request.POST)
            if attribute_form.is_valid():
                attribute_form.save()
                return redirect('spe:add_new_evaluation')

        elif 'add_indicator' in request.POST:
            indicator_form = SPEIndicatorForm(request.POST)
            if indicator_form.is_valid():
                indicator_form.save()
                return redirect('spe:add_new_evaluation')

    # Fetch existing data for display
    periods = SPEPeriod.objects.all()
    attributes = SPEAttribute.objects.all()
    indicators = SPEIndicator.objects.select_related('attribute').all()

    return render(request, 'spe/add_new_evaluation.html', {
        'period_form': period_form,
        'attribute_form': attribute_form,
        'indicator_form': indicator_form,
        'periods': periods,
        'attributes': attributes,
        'indicators': indicators,
    })


# ============================
# TEACHING APPRAISALS
# ============================
@login_required
def teaching_appraisal(request):
    if request.user.role != 'teaching':
        return redirect('non_teaching_dashboard')  # block wrong users
    
    try:
        period = SPEPeriod.objects.get(is_active=True)
    except SPEPeriod.DoesNotExist:
        messages.error(request, "No active appraisal period found. Please contact the supervisor/admin.")
        return redirect("role_based_redirect")

    attributes = SPEAttribute.objects.filter(period=period).prefetch_related('indicators')

    if request.method == 'POST':
        for indicator in SPEIndicator.objects.filter(attribute__period=period):
            rating = request.POST.get(f"rating_{indicator.id}")
            remarks = request.POST.get(f"remarks_{indicator.id}")

            if rating:  # only save if rating is provided
                TeachingStaffEvaluation.objects.create(
                    staff=request.user,
                    period=period,
                    attribute=indicator.attribute,
                    indicator=indicator,
                    rating=rating,
                    remarks=remarks or ""
                )

        messages.success(request, "Appraisal submitted successfully.")
        return redirect('spe:teaching_appraisal')  # refresh after submission

    return render(request, 'spe/teaching_evaluation_form.html', {
        'period': period,
        'attributes': attributes,
    })


@login_required
def teaching_appraisal_detail(request, pk):
    appraisal = get_object_or_404(TeachingStaffAppraisal, pk=pk, staff=request.user)
    return render(request, "spe/teaching_appraisal_detail.html", {"appraisal": appraisal})

# -----------------------------
@login_required
def nonteaching_evaluate_staff(request, staff_id):
    if request.user.role != "supervisor":
        return redirect("role_based_redirect")

    staff_profile = get_object_or_404(NonTeachingStaffProfile, id=staff_id)
    if not staff_profile.user:
        messages.error(request, "Staff user not found!")
        return redirect("supervisor_dashboard")

    active_period = SPEPeriod.objects.filter(is_active=True).first()
    if not active_period:
        messages.error(request, "No active evaluation period.")
        return redirect("spe:add_new_evaluation")

    attributes = SPEAttribute.objects.filter(period=active_period).prefetch_related("indicators")

    # Fetch existing evaluations to pre-fill and convert ratings to string
    saved_ratings = NonTeachingStaffEvaluation.objects.filter(
        staff=staff_profile.user,
        period=active_period
    )
    self_ratings_dict = {ev.indicator.id: str(ev.rating) for ev in saved_ratings}  # cast to str

    if request.method == "POST":
        complete_submission = request.POST.get("complete", "no") == "yes"

        for attribute in attributes:
            for indicator in attribute.indicators.all():
                rating = request.POST.get(f"rating_{indicator.id}")
                rating = int(rating) if rating else 0  # convert or default

                remarks = request.POST.get(f"remarks_{indicator.id}", "")

                NonTeachingStaffEvaluation.objects.update_or_create(
                    staff=staff_profile.user,
                    period=active_period,
                    attribute=attribute,
                    indicator=indicator,
                    defaults={
                        "rating": rating,
                        "remarks": remarks
                    }
                )

        if complete_submission:
            # ✅ Call the method to get staff full name
            messages.success(request, f"{staff_profile.user.get_full_name()} evaluation submitted.")
            return redirect("supervisor_dashboard")
        else:
            messages.info(request, "Your progress has been saved. You can continue later.")
            return redirect(request.path)

    return render(request, "spe/nonteaching_evaluate_staff.html", {
        "staff": staff_profile,
        "period": active_period,
        "attributes": attributes,
        "self_ratings_dict": self_ratings_dict,  # matches template now
    })
# -----------------------------
# Non-Teaching Staff Evaluation
# -----------------------------
@login_required
def nonteaching_evaluate_staff(request, staff_id):
    if request.user.role != "supervisor":
        return redirect("role_based_redirect")

    staff_profile = get_object_or_404(NonTeachingStaffProfile, id=staff_id)
    if not staff_profile.user:
        messages.error(request, "Staff user not found!")
        return redirect("supervisor_dashboard")

    active_period = SPEPeriod.objects.filter(is_active=True).first()
    if not active_period:
        messages.error(request, "No active evaluation period.")
        return redirect("spe:add_new_evaluation")

    attributes = SPEAttribute.objects.filter(period=active_period).prefetch_related("indicators")

    # Fetch existing evaluations to pre-fill and convert ratings to str
    saved_ratings = NonTeachingStaffEvaluation.objects.filter(
        staff=staff_profile.user,
        period=active_period
    )
    saved_dict = {ev.indicator.id: str(ev.rating) for ev in saved_ratings}

    if request.method == "POST":
        complete_submission = request.POST.get("complete", "no") == "yes"

        # Prevent re-submission if already submitted
        if complete_submission and NonTeachingStaffEvaluation.objects.filter(
            staff=staff_profile.user,
            period=active_period,
            is_submitted=True
        ).exists():
            messages.error(request, "Evaluation already submitted. Cannot submit again.")
            return redirect("supervisor_dashboard")

        for attribute in attributes:
            for indicator in attribute.indicators.all():
                rating = int(request.POST.get(f"rating_{indicator.id}") or 0)
                remarks = request.POST.get(f"remarks_{indicator.id}", "")

                NonTeachingStaffEvaluation.objects.update_or_create(
                    staff=staff_profile.user,
                    period=active_period,
                    attribute=attribute,
                    indicator=indicator,
                    defaults={
                        "rating": rating,
                        "remarks": remarks,
                        "is_submitted": complete_submission
                    }
                )

        if complete_submission:
            messages.success(request, f"{staff_profile.user.get_full_name()} evaluation submitted.")
            return redirect("supervisor_dashboard")
        else:
            messages.info(request, "Progress saved. You can continue later.")
            return redirect(request.path)

    return render(request, "spe/nonteaching_evaluate_staff.html", {
        "staff": staff_profile,
        "period": active_period,
        "attributes": attributes,
        "self_ratings_dict": saved_dict,
    })


# -----------------------------
# Teaching Staff Evaluation
# -----------------------------
@login_required
def teaching_evaluate_staff(request, staff_id):
    if request.user.role != "supervisor":
        return redirect("role_based_redirect")

    staff_profile = get_object_or_404(TeachingStaffProfile, id=staff_id)
    if not staff_profile.user:
        messages.error(request, "Staff user not found!")
        return redirect("supervisor_dashboard")

    active_period = SPEPeriod.objects.filter(is_active=True).first()
    if not active_period:
        messages.error(request, "No active evaluation period.")
        return redirect("spe:add_new_evaluation")

    attributes = SPEAttribute.objects.filter(period=active_period).prefetch_related("indicators")

    # Fetch existing evaluations to pre-fill and convert ratings to str
    saved_ratings = TeachingStaffEvaluation.objects.filter(
        staff=staff_profile.user,
        period=active_period
    )
    saved_dict = {ev.indicator.id: str(ev.rating) for ev in saved_ratings}

    if request.method == "POST":
        complete_submission = request.POST.get("complete", "no") == "yes"

        # Prevent re-submission if already submitted
        if complete_submission and TeachingStaffEvaluation.objects.filter(
            staff=staff_profile.user,
            period=active_period,
            is_submitted=True
        ).exists():
            messages.error(request, "Evaluation already submitted. Cannot submit again.")
            return redirect("supervisor_dashboard")

        for attribute in attributes:
            for indicator in attribute.indicators.all():
                rating = int(request.POST.get(f"rating_{indicator.id}") or 0)
                remarks = request.POST.get(f"remarks_{indicator.id}", "")

                TeachingStaffEvaluation.objects.update_or_create(
                    staff=staff_profile.user,
                    period=active_period,
                    attribute=attribute,
                    indicator=indicator,
                    defaults={
                        "rating": rating,
                        "remarks": remarks,
                        "is_submitted": complete_submission
                    }
                )

        if complete_submission:
            messages.success(request, f"{staff_profile.user.get_full_name()} evaluation submitted.")
            return redirect("supervisor_dashboard")
        else:
            messages.info(request, "Progress saved. You can continue later.")
            return redirect(request.path)

    return render(request, "spe/teaching_evaluate_staff.html", {
        "staff": staff_profile,
        "period": active_period,
        "attributes": attributes,
        "self_ratings_dict": saved_dict,
    })
