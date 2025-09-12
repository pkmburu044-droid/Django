from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from users.models import NonTeachingStaffProfile, TeachingStaffProfile 
from spe.models import NonTeachingStaffEvaluation, TeachingStaffEvaluation, SPEPeriod
from django.db.models import Sum, Avg, F, FloatField
from users.forms import NonTeachingAppraisalForm,TeachingStaffProfileForm,TeachingStaffAppraisalForm, NonTeachingStaffProfileForm
from django.contrib import messages


# ========================
# Dashboards
# ========================

@login_required
def teaching_dashboard(request):
    if request.user.role != "teaching":
        return redirect("role_based_redirect")
    return render(request, "dashboards/teaching.html")


@login_required
def non_teaching_dashboard(request):
    if request.user.role != "non_teaching":
        return redirect("role_based_redirect")
    return render(request, "dashboards/non_teaching.html")



# ========================
# Profile Details
# ========================
@login_required
def profile_details(request):
    template_name = "dashboards/profile_details.html"

    if request.user.role == "non_teaching":
        profile_attr = "nonteachingstaffprofile"
        form_class = NonTeachingStaffProfileForm
    elif request.user.role == "teaching":
        profile_attr = "teachingstaffprofile"  # ✅ corrected name (not teaching_profile)
        form_class = TeachingStaffProfileForm
    else:
        return redirect("role_based_redirect")

    # Get or initialize profile
    profile = getattr(request.user, profile_attr, None)

    if request.method == "POST":
        form = form_class(request.POST, request.FILES, instance=profile)  # ✅ use instance
        if form.is_valid():
            new_profile = form.save(commit=False)
            new_profile.user = request.user
            new_profile.save()
            messages.success(request, "Profile updated successfully!")
            return redirect("profile_details")
    else:
        form = form_class(instance=profile)

    return render(request, template_name, {
        "user": request.user,
        "profile": profile,
        "form": form,
    })



# ========================
# Appraisals
# ========================

@login_required
def create_non_teaching_appraisal(request):
    """
    Create appraisal for non-teaching staff.
    After saving, redirect to the performance evaluation page.
    """
    if request.user.role != "non_teaching":
        return redirect("role_based_redirect")

    profile = get_object_or_404(NonTeachingStaffProfile, user=request.user)

    if request.method == "POST":
        form = NonTeachingAppraisalForm(request.POST)
        if form.is_valid():
            appraisal = form.save(commit=False)
            appraisal.profile = profile
            appraisal.save()
            # Redirect to evaluation start
            return redirect("start_performance_evaluation", appraisal_id=appraisal.id)
    else:
        form = NonTeachingAppraisalForm()

    return render(request, "dashboards/create_non_teaching_appraisal.html", {"form": form})

@login_required
def teaching_appraisal(request):
    """
    Create appraisal for teaching staff.
    """
    if request.user.role != "teaching":
        return redirect("role_based_redirect")

    # Get the logged-in user's teaching staff profile
    try:
        profile = request.user.teachingstaffprofile
    except TeachingStaffProfile.DoesNotExist:
        # Redirect to a page to create profile first
        return redirect("create_teaching_profile")  # <- you need this URL/view

    if request.method == "POST":
        form = TeachingStaffAppraisalForm(request.POST)
        if form.is_valid():
            appraisal = form.save(commit=False)
            appraisal.profile = profile  # assign the profile
            appraisal.save()
            return redirect("teaching_dashboard")
    else:
        form = TeachingStaffAppraisalForm()

    return render(request, "dashboards/TeachingStaffAppraisal.html", {"form": form})

@login_required
def appraisal_redirect(request):
    """
    Redirect user to the correct appraisal form (new or existing) based on role and profile.
    """
    if request.user.role == "teaching":
        # Teaching staff
        try:
            profile = request.user.teachingstaffprofile
        except TeachingStaffProfile.DoesNotExist:
            return redirect("create_teaching_profile")

        appraisal = getattr(profile, 'teachingstaffappraisal', None)
        if appraisal:
            return redirect('teaching_appraisal_detail', pk=appraisal.pk)
        else:
            return redirect('teaching_appraisal')  # new form

    elif request.user.role == "non_teaching":
        # Non-teaching staff
        try:
            profile = request.user.nonteachingstaffprofile
        except NonTeachingStaffProfile.DoesNotExist:
            return redirect("create_non_teaching_profile")

        appraisal = getattr(profile, 'nonteachingstaffappraisal', None)
        if appraisal:
            return redirect('nonteaching_appraisal_detail', pk=appraisal.pk)
        else:
            return redirect('nonteaching_appraisal')  # new form

    else:
        return redirect("role_based_redirect")  # fallback for other roles
    

@login_required
def edit_profile(request):
    user = request.user

    # Pick the correct profile & form depending on role
    if user.role == "teaching":
        profile = get_object_or_404(TeachingStaffProfile, user=user)
        form_class = TeachingStaffProfileForm
    elif user.role == "non_teaching":
        profile = get_object_or_404(NonTeachingStaffProfile, user=user)
        form_class = NonTeachingStaffProfileForm
    else:
        messages.error(request, "You cannot edit a profile for this role.")
        return redirect("role_based_redirect")

    if request.method == "POST":
        form = form_class(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated successfully ✅")
            return redirect("profile_details")
    else:
        form = form_class(instance=profile)

    return render(request, "dashboards/edit_profile.html", {"form": form})
@login_required
def supervisor_dashboard(request):
    if request.user.role != "supervisor":
        return redirect("role_based_redirect")

    # Active period
    active_period = SPEPeriod.objects.filter(is_active=True).first()

    if not active_period:
        messages.warning(request, "No active evaluation period. Create one in SPE > Periods.")
        teaching_evaluations = []
        non_teaching_evaluations = []
        pending_teaching_staff = TeachingStaffProfile.objects.all()
        pending_non_teaching_staff = NonTeachingStaffProfile.objects.all()
    else:
        # Aggregate teaching evaluations per staff
        teaching_evaluations = (
            TeachingStaffEvaluation.objects.filter(period=active_period, is_submitted=True)
            .values(
                'staff_id', 'staff__pf_number', 'staff__first_name', 'staff__last_name'
            )
            .annotate(
                trs=Sum('rating'),
                mrs=Avg('rating'),
                percent_score=Avg(F('rating') * 20 / 5, output_field=FloatField())
            )
        )

        # Aggregate non-teaching evaluations per staff
        non_teaching_evaluations = (
            NonTeachingStaffEvaluation.objects.filter(period=active_period, is_submitted=True)
            .values(
                'staff_id', 'staff__pf_number', 'staff__first_name', 'staff__last_name'
            )
            .annotate(
                trs=Sum('rating'),
                mrs=Avg('rating'),
                percent_score=Avg(F('rating') * 20 / 5, output_field=FloatField())
            )
        )

        # Pending staff
        evaluated_teaching_ids = TeachingStaffEvaluation.objects.filter(
            period=active_period, is_submitted=True
        ).values_list('staff_id', flat=True).distinct()
        evaluated_non_teaching_ids = NonTeachingStaffEvaluation.objects.filter(
            period=active_period, is_submitted=True
        ).values_list('staff_id', flat=True).distinct()

        pending_teaching_staff = TeachingStaffProfile.objects.exclude(id__in=evaluated_teaching_ids)
        pending_non_teaching_staff = NonTeachingStaffProfile.objects.exclude(id__in=evaluated_non_teaching_ids)

    # Stats
    total_staff = TeachingStaffProfile.objects.count() + NonTeachingStaffProfile.objects.count()
    evaluations_submitted = len(teaching_evaluations) + len(non_teaching_evaluations)
    pending_evaluations = pending_teaching_staff.count() + pending_non_teaching_staff.count()

    context = {
        "active_period": active_period,
        "teaching_evaluations": teaching_evaluations,
        "non_teaching_evaluations": non_teaching_evaluations,
        "total_staff": total_staff,
        "evaluations_submitted": evaluations_submitted,
        "pending_evaluations": pending_evaluations,
        "pending_teaching_staff": pending_teaching_staff,
        "pending_non_teaching_staff": pending_non_teaching_staff,
    }

    return render(request, "dashboards/supervisor.html", context)
