import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from dashboards.services.target_approval_service import TargetApprovalService
from spe.models import (
    NonTeachingStaffEvaluation,
    SPEPeriod,
    SupervisorEvaluation,
    TeachingStaffEvaluation,
)
from users.forms import StaffAppraisalForm, StaffProfileForm
from users.models import (
    CustomUser,
    PerformanceTarget,
    StaffAppraisal,
    StaffProfile,
)

logger = logging.getLogger(__name__)


@login_required
def non_teaching_dashboard(request):
    if request.user.role != "non_teaching":
        return redirect("role_based_redirect")

    # ✅ IMPORT EXISTING SERVICES
    from dashboards.services.performance_calculations import (
        StaffPerformanceCalculator,
    )

    profile, _ = StaffProfile.objects.get_or_create(user=request.user)

    # Active evaluation period
    period = SPEPeriod.objects.filter(is_active=True).first()

    # Get all appraisals for this user
    all_appraisals = (
        StaffAppraisal.objects.filter(profile=profile)
        .select_related("period")
        .order_by("-period__start_date")
    )

    # Get current period appraisal
    current_appraisal = StaffAppraisal.objects.filter(
        profile=profile, period=period
    ).first()

    # Count appraisals by status
    submitted_count = all_appraisals.filter(status__iexact="submitted").count()
    draft_count = all_appraisals.filter(status__iexact="draft").count()
    reviewed_count = all_appraisals.filter(status__iexact="reviewed").count()

    # ✅ USE SERVICE: Calculate average rating using (self_rating + supervisor_rating) / 2
    avg_rating = None
    efficiency_score = None

    if reviewed_count > 0:
        # Get the most recent reviewed appraisal for current calculations
        latest_reviewed = all_appraisals.filter(status="reviewed").first()
        if latest_reviewed:
            score_data = (
                StaffPerformanceCalculator.calculate_combined_evaluation_score(
                    request.user, latest_reviewed.period
                )
            )
            avg_rating = score_data["avg_score"]
            efficiency_score = score_data["percentage_score"]

    # FIXED: Calculate years of service safely (keep this in view since it's simple)
    years_service = 0
    try:
        from datetime import date

        today = date.today()

        # Use user's account creation date since StaffProfile doesn't have date_of_appointment
        appointment_date = request.user.date_joined.date()

        years_service = today.year - appointment_date.year
        if today.month < appointment_date.month or (
            today.month == appointment_date.month
            and today.day < appointment_date.day
        ):
            years_service -= 1

    except (AttributeError, ValueError):
        # If any error occurs, default to 0
        years_service = 0

    # FIXED: Time-based progress calculation for current period (keep this in view since it's simple)
    completion_percentage = 0
    completed_sections = 0
    total_sections = 0

    if period:
        from datetime import date

        today = date.today()
        start_date = period.start_date
        end_date = period.end_date

        # Calculate time-based progress
        total_days = (end_date - start_date).days
        if total_days > 0:
            days_passed = (today - start_date).days
            # Ensure percentage is between 0-100
            completion_percentage = max(
                0, min(100, (days_passed / total_days) * 100)
            )

            # For display purposes - show days info
            completed_sections = days_passed
            total_sections = total_days
    else:
        # No active period
        completion_percentage = 0
        completed_sections = 0
        total_sections = 1  # Avoid division by zero

    # ✅ USE SERVICE: Performance history for graphs
    performance_history = (
        StaffPerformanceCalculator.calculate_performance_history(request.user)
    )

    context = {
        "profile": profile,
        "appraisals": all_appraisals,
        "all_appraisals": all_appraisals,
        "current_appraisal": current_appraisal,
        "latest_appraisal": all_appraisals.first(),
        "submitted_count": submitted_count,
        "draft_count": draft_count,
        "years_service": years_service,
        "avg_rating": avg_rating,
        "efficiency_score": efficiency_score,
        "active_period": period,
        "completion_percentage": completion_percentage,
        "completed_sections": completed_sections,
        "total_sections": total_sections,
        "performance_history": performance_history,
    }

    return render(request, "dashboards/non_teaching.html", context)


@login_required
def teaching_dashboard(request):
    if request.user.role != "teaching":
        return redirect("role_based_redirect")

    # ✅ IMPORT EXISTING SERVICES
    from dashboards.services.performance_calculations import (
        StaffPerformanceCalculator,
    )

    profile, _ = StaffProfile.objects.get_or_create(user=request.user)

    # Active evaluation period
    period = SPEPeriod.objects.filter(is_active=True).first()

    # Get all appraisals for this user
    all_appraisals = (
        StaffAppraisal.objects.filter(profile=profile)
        .select_related("period")
        .order_by("-period__start_date")
    )

    # Get current period appraisal
    current_appraisal = StaffAppraisal.objects.filter(
        profile=profile, period=period
    ).first()

    # Count appraisals by status
    submitted_count = all_appraisals.filter(status__iexact="submitted").count()
    draft_count = all_appraisals.filter(status__iexact="draft").count()
    reviewed_count = all_appraisals.filter(status__iexact="reviewed").count()

    # ✅ USE SERVICE: Performance Targets Data
    target_stats = StaffPerformanceCalculator.calculate_target_statistics(
        request.user, period
    )

    targets_count = target_stats["targets_count"]
    approved_targets_count = target_stats["approved_targets_count"]
    pending_targets_count = target_stats["pending_targets_count"]
    completed_targets_count = target_stats["completed_targets_count"]
    rejected_targets_count = target_stats["rejected_targets_count"]
    current_targets = None

    if period:
        from users.models import PerformanceTarget

        current_targets = PerformanceTarget.objects.filter(
            staff=request.user, period=period
        )

        # ✅ DEBUG: Print target information to console
        print(f"=== TEACHING DASHBOARD DEBUG ===")
        print(f"User: {request.user.email}")
        print(f"Active Period: {period.name if period else 'None'}")
        print(f"Total Targets: {targets_count}")
        print(f"Approved Targets: {approved_targets_count}")
        print(f"Pending Targets: {pending_targets_count}")
        print(f"Completed Targets: {completed_targets_count}")
        print(f"Rejected Targets: {rejected_targets_count}")

        # Print individual target details
        for target in current_targets:
            print(
                f"  Target {target.target_number}: '{target.description[:30]}...' - Status: {target.status}"
            )
        print("=== END DEBUG ===")

    # ✅ USE SERVICE: Calculate average rating using (self_rating + supervisor_rating) / 2
    avg_rating = None
    efficiency_score = None

    if reviewed_count > 0:
        # Get the most recent reviewed appraisal for current calculations
        latest_reviewed = all_appraisals.filter(status="reviewed").first()
        if latest_reviewed:
            score_data = (
                StaffPerformanceCalculator.calculate_combined_evaluation_score(
                    request.user, latest_reviewed.period
                )
            )
            avg_rating = score_data["avg_score"]
            efficiency_score = score_data["percentage_score"]

    # Calculate years of service safely (keep this in view since it's simple)
    years_service = 0
    try:
        from datetime import date

        today = date.today()

        # Use user's account creation date since StaffProfile doesn't have date_of_appointment
        appointment_date = request.user.date_joined.date()

        years_service = today.year - appointment_date.year
        if today.month < appointment_date.month or (
            today.month == appointment_date.month
            and today.day < appointment_date.day
        ):
            years_service -= 1

    except (AttributeError, ValueError):
        # If any error occurs, default to 0
        years_service = 0

    # Appraisal progress calculation (simplified) - keep this in view
    completion_percentage = 0
    completed_sections = 0
    total_sections = 5  # Assuming 5 sections in appraisal form

    if current_appraisal:
        # Simple progress calculation - adjust based on your needs
        if current_appraisal.status == "submitted":
            completion_percentage = 100
            completed_sections = total_sections
        elif current_appraisal.status == "draft":
            completion_percentage = 50  # Half completed for drafts
            completed_sections = total_sections // 2

    # ✅ USE SERVICE: Performance history for graphs
    performance_history = (
        StaffPerformanceCalculator.calculate_performance_history(request.user)
    )

    context = {
        "profile": profile,
        "appraisals": all_appraisals,
        "all_appraisals": all_appraisals,
        "current_appraisal": current_appraisal,
        "latest_appraisal": all_appraisals.first(),
        "submitted_count": submitted_count,
        "draft_count": draft_count,
        "years_service": years_service,
        "avg_rating": avg_rating,
        "efficiency_score": efficiency_score,
        "active_period": period,
        "completion_percentage": completion_percentage,
        "completed_sections": completed_sections,
        "total_sections": total_sections,
        "performance_history": performance_history,
        # ✅ ADDED: Performance Targets Data
        "targets_count": targets_count,
        "approved_targets_count": approved_targets_count,
        "pending_targets_count": pending_targets_count,
        "completed_targets_count": completed_targets_count,
        "rejected_targets_count": rejected_targets_count,
        "current_targets": current_targets,
        # ✅ ADDED: Additional context for template debugging
        "has_approved_targets": approved_targets_count > 0,
        "has_pending_targets": pending_targets_count > 0,
        "has_targets": targets_count > 0,
        "debug_user": request.user.email,  # For template debugging
    }

    return render(request, "dashboards/teaching.html", context)


# ========================
# Profile Details
# ========================


@login_required
def profile_details(request):
    """
    Display and edit the logged-in user's staff profile.
    """
    profile, _ = StaffProfile.objects.get_or_create(user=request.user)
    form = StaffProfileForm(
        request.POST or None, request.FILES or None, instance=profile
    )

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profile updated successfully!")
        return redirect("dashboards:profile_details")  # Fixed: added namespace

    return render(
        request,
        "dashboards/profile_details.html",
        {
            "user": request.user,
            "profile": profile,
            "form": form,
        },
    )


from django.db.models import Q  # Add this import at the top


@login_required
def create_appraisal(request):
    """
    Create appraisal with STRICT validation - requires complete profile, approved targets AND basic details
    """
    if request.user.role not in ["teaching", "non_teaching"]:
        messages.error(
            request,
            "❌ Access denied. This section is for teaching and non-teaching staff only.",
        )
        return redirect("users:role_based_redirect")

    profile = get_object_or_404(StaffProfile, user=request.user)
    period = SPEPeriod.objects.filter(is_active=True).first()

    # ✅ STRICT: Check basic profile completion FIRST
    if not profile.department or not profile.designation:
        messages.error(
            request,
            "📋 Your basic profile is incomplete. "
            "Please complete your profile with department and designation before starting appraisal.",
        )
        return redirect("dashboards:profile_details")

    # ✅ STRICT: Check if user has any appraisal with employment history data
    has_employment_history = (
        StaffAppraisal.objects.filter(profile=profile)
        .filter(
            Q(date_of_appointment__isnull=False)
            | Q(years_experience_kyu__isnull=False)
            | Q(years_experience_elsewhere__isnull=False)
            | Q(length_of_service__isnull=False)
        )
        .exists()
    )

    if not has_employment_history:
        messages.error(
            request,
            "📋 Your employment history is incomplete. "
            "Please complete your employment history in your profile before starting appraisal.",
        )
        return redirect("dashboards:profile_details")

    if not period:
        messages.warning(
            request, "📅 No active evaluation period is available."
        )
        return redirect("dashboards:profile_details")

    # ✅ FORMS STATUS CHECK
    if period.forms_status != "ready":
        if period.forms_status == "draft":
            messages.error(
                request,
                "📝 Appraisal forms are not yet published. Please check back later.",
            )
        elif period.forms_status == "closed":
            messages.error(
                request,
                "⏰ The appraisal period has ended. Forms are no longer accepting submissions.",
            )
        else:
            messages.error(
                request, "❌ Appraisal forms are not currently available."
            )
        dashboard = (
            "dashboards:teaching_dashboard"
            if request.user.role == "teaching"
            else "dashboards:non_teaching_dashboard"
        )
        return redirect(dashboard)

    # ✅ STRICT: Check for performance targets status
    performance_targets = PerformanceTarget.objects.filter(
        staff=request.user, period=period
    )

    has_targets = performance_targets.exists()
    approved_targets = performance_targets.filter(status="approved")
    has_approved_targets = approved_targets.exists()
    pending_targets = performance_targets.filter(status="pending")
    has_pending_targets = pending_targets.exists()

    # ✅ STRICT: Check for existing non-draft appraisals
    existing_submitted = (
        StaffAppraisal.objects.filter(profile=profile, period=period)
        .exclude(status="draft")
        .first()
    )

    if existing_submitted:
        status_display = existing_submitted.get_status_display()
        messages.info(
            request,
            f"📄 You have already {status_display.lower()} your appraisal for this period.",
        )
        dashboard = (
            "dashboards:teaching_dashboard"
            if request.user.role == "teaching"
            else "dashboards:non_teaching_dashboard"
        )
        return redirect(dashboard)

    # ✅ STRICT: Check for existing DRAFT appraisal (basic details completed)
    existing_draft = StaffAppraisal.objects.filter(
        profile=profile, period=period, status="draft"
    ).first()
    has_completed_basic_details = existing_draft is not None

    # 🚀 STRICT ENFORCEMENT: Check prerequisites in sequence
    if not has_approved_targets:
        if not has_targets:
            messages.error(
                request,
                "🎯 You must set performance targets before starting appraisal. "
                "Please set your targets first.",
            )
            return redirect("users:set_performance_targets")
        elif has_pending_targets:
            messages.error(
                request,
                "⏳ Your performance targets are awaiting supervisor approval. "
                "Please wait for approval before starting appraisal.",
            )
            return redirect("users:view_performance_targets")
        else:
            messages.error(
                request,
                "❌ You need approved performance targets to start appraisal.",
            )
            return redirect("users:set_performance_targets")

    # 🚀 STRICT ENFORCEMENT: If user has approved targets but no basic details, show form
    if has_approved_targets and not has_completed_basic_details:
        # Handle form submission for basic details
        if request.method == "POST":
            form = StaffAppraisalForm(request.POST)
            if form.is_valid():
                try:
                    appraisal = form.save(commit=False)
                    appraisal.profile = profile
                    appraisal.period = period
                    appraisal.supervisor_name = (
                        profile.department.head.get_full_name()
                        if profile.department and profile.department.head
                        else "Department Head"
                    )
                    appraisal.supervisor_designation = "Supervisor"
                    appraisal.appraisal_date = timezone.now().date()
                    appraisal.status = "draft"
                    appraisal.save()

                    messages.success(
                        request,
                        "✅ Basic details saved successfully! "
                        "Now complete your performance self-assessment.",
                    )

                    return redirect("spe:start_self_assessment")

                except Exception as e:
                    logger.error(
                        f"Error creating appraisal for {request.user.email}: {str(e)}"
                    )
                    messages.error(
                        request,
                        "❌ Error saving your details. Please try again or contact support.",
                    )
        else:
            # Pre-fill form with available data
            initial_data = {}
            if profile.department and profile.department.head:
                initial_data["supervisor_name"] = (
                    profile.department.head.get_full_name()
                )
                initial_data["supervisor_designation"] = "Supervisor"

            form = StaffAppraisalForm(initial=initial_data)

        context = {
            "form": form,
            "active_period": period,
            "appraisal": existing_draft,
            "is_new": True,
            # Target status information
            "has_performance_targets": has_targets,
            "has_approved_targets": has_approved_targets,
            "has_pending_targets": has_pending_targets,
            "targets_count": performance_targets.count(),
            "approved_targets_count": approved_targets.count(),
            "pending_targets_count": pending_targets.count(),
            "has_completed_basic_details": has_completed_basic_details,
            "can_proceed": has_approved_targets
            and has_completed_basic_details,
        }
        return render(request, "dashboards/create_appraisal.html", context)

    # 🚀 STRICT ENFORCEMENT: If user has both approved targets AND completed basic details, redirect to self-assessment
    if has_approved_targets and has_completed_basic_details:
        messages.success(
            request,
            "✅ All prerequisites completed. Continuing to performance self-assessment.",
        )
        return redirect("spe:start_self_assessment")

    # Fallback - should not reach here with proper validation
    messages.error(
        request,
        "❌ Unable to determine appraisal status. Please contact administrator.",
    )
    return redirect("users:role_based_redirect")


@login_required
def appraisal_redirect(request):
    """
    PROPER WORKFLOW ENFORCEMENT: Staff must complete ALL prerequisites BEFORE self-assessment
    """
    if request.user.role not in ["teaching", "non_teaching"]:
        return redirect("users:role_based_redirect")

    profile = get_object_or_404(StaffProfile, user=request.user)
    period = SPEPeriod.objects.filter(is_active=True).first()

    # ✅ STRICT: Check basic profile completion FIRST
    if not profile.department or not profile.designation:
        messages.error(
            request,
            "📋 Your basic profile is incomplete. "
            "Please complete your profile with department and designation before starting appraisal.",
        )
        return redirect("dashboards:profile_details")

    # ✅ STRICT: Check if user has any appraisal with employment history data
    has_employment_history = (
        StaffAppraisal.objects.filter(profile=profile)
        .filter(
            Q(date_of_appointment__isnull=False)
            | Q(years_experience_kyu__isnull=False)
            | Q(years_experience_elsewhere__isnull=False)
            | Q(length_of_service__isnull=False)
        )
        .exists()
    )

    if not has_employment_history:
        messages.error(
            request,
            "📋 Your employment history is incomplete. "
            "Please complete your employment history in your profile before starting appraisal.",
        )
        return redirect("dashboards:profile_details")

    if not period:
        messages.warning(
            request, "📅 No active evaluation period is available."
        )
        return redirect("dashboards:profile_details")

    # ✅ FORMS STATUS CHECK
    if period.forms_status != "ready":
        if period.forms_status == "draft":
            messages.error(
                request,
                "📝 Appraisal forms are not yet published. Please check back later.",
            )
        elif period.forms_status == "closed":
            messages.error(
                request,
                "⏰ The appraisal period has ended. Forms are no longer accepting submissions.",
            )
        else:
            messages.error(
                request, "❌ Appraisal forms are not currently available."
            )
        dashboard = (
            "dashboards:teaching_dashboard"
            if request.user.role == "teaching"
            else "dashboards:non_teaching_dashboard"
        )
        return redirect(dashboard)

    # ✅ STRICT: Check for performance targets status
    performance_targets = PerformanceTarget.objects.filter(
        staff=request.user, period=period
    )

    has_approved_targets = performance_targets.filter(
        status="approved"
    ).exists()
    has_pending_targets = performance_targets.filter(status="pending").exists()

    # ✅ STRICT: Check for existing non-draft appraisals
    existing_submitted = (
        StaffAppraisal.objects.filter(profile=profile, period=period)
        .exclude(status="draft")
        .first()
    )

    if existing_submitted:
        status_display = existing_submitted.get_status_display()
        messages.info(
            request,
            f"📄 You have already {status_display.lower()} your appraisal for this period.",
        )
        dashboard = (
            "dashboards:teaching_dashboard"
            if request.user.role == "teaching"
            else "dashboards:non_teaching_dashboard"
        )
        return redirect(dashboard)

    # ✅ STRICT: Check for existing DRAFT appraisal (basic details completed)
    existing_draft = StaffAppraisal.objects.filter(
        profile=profile, period=period, status="draft"
    ).first()
    has_completed_basic_details = existing_draft is not None

    # 🚀 STRICT ENFORCEMENT: Apply same validation as create_appraisal
    if not has_approved_targets:
        if has_pending_targets:
            messages.error(
                request,
                "⏳ Your performance targets are awaiting supervisor approval. "
                "Please wait for approval before continuing.",
            )
            return redirect("users:view_performance_targets")
        else:
            messages.error(
                request,
                "🎯 You must set and get performance targets approved before starting appraisal.",
            )
            return redirect("users:set_performance_targets")

    # 🚀 STRICT ENFORCEMENT: Check current status and redirect appropriately
    if has_approved_targets and not has_completed_basic_details:
        # User has approved targets but no basic details - redirect to create_appraisal
        messages.info(
            request, "📝 Please complete your basic appraisal details first."
        )
        return redirect("dashboards:create_appraisal")

    elif has_approved_targets and has_completed_basic_details:
        # User has both approved targets AND completed basic details - redirect to self-assessment
        messages.success(
            request, "✅ Continuing to performance self-assessment."
        )
        return redirect("spe:start_self_assessment")

    else:
        # Fallback - redirect to create_appraisal for proper validation
        return redirect("dashboards:create_appraisal")


@login_required
def supervisor_dashboard(request):
    # Only supervisors allowed
    if request.user.role != "supervisor":
        logger.warning(
            f"Non-supervisor user {request.user.email} attempted to access supervisor dashboard"
        )

        # ✅ FIXED: Redirect to appropriate dashboard based on actual role
        if request.user.role == "teaching":
            return redirect("dashboards:teaching_dashboard")
        elif request.user.role == "non_teaching":
            return redirect("dashboards:non_teaching_dashboard")
        elif request.user.role == "hr":
            return redirect("hr:hr_dashboard")
        else:
            return redirect("users:login")  # Fallback to login

    supervisor_department = getattr(request.user, "department", None)

    # Ensure supervisor has a department
    if not supervisor_department:
        logger.error(
            f"Supervisor {request.user.email} has no department assigned"
        )
        messages.error(request, "You are not assigned to any department.")
        # ✅ FIXED: Redirect to profile page to update department
        return redirect("dashboards:profile_details")

    # Use email instead of username and safe department access
    department_name = getattr(
        supervisor_department, "name", "Unknown Department"
    )
    logger.info(
        f"Supervisor {request.user.email} accessing dashboard for department: {department_name}"
    )

    # Active evaluation period
    period = SPEPeriod.objects.filter(is_active=True).first()
    if period:
        logger.debug(f"Active period found: {period.name}")
    else:
        logger.warning("No active evaluation period found")

    # ✅ IMPORT EXISTING SERVICES
    from dashboards.services.performance_calculations import (
        SupervisorPerformanceCalculator,
    )

    # ✅ FIX: Use User model instead of StaffProfile for department filtering
    department_staff = CustomUser.objects.filter(
        department=supervisor_department
    ).exclude(id=request.user.id)
    total_staff = department_staff.count()
    logger.debug(f"Found {total_staff} staff members in department")

    # PERFORMANCE TARGETS DATA
    staff_with_targets = []
    targets_set_count = 0
    pending_approval_count = 0

    if period:
        for staff_user in department_staff:
            targets = PerformanceTarget.objects.filter(
                staff=staff_user, period=period
            )
            targets_count = targets.count()
            targets_set_count += targets_count

            # Count pending approvals
            pending_targets = targets.filter(status="pending")
            pending_approval_count += pending_targets.count()

            # Get latest target update time
            latest_update = targets.order_by("-updated_at").first()
            latest_update_time = (
                latest_update.updated_at if latest_update else None
            )

            # Get staff profile for display info
            try:
                staff_profile = StaffProfile.objects.get(user=staff_user)
                designation = staff_profile.designation
            except StaffProfile.DoesNotExist:
                designation = "Not specified"

            staff_with_targets.append(
                {
                    "profile": (
                        staff_profile if "staff_profile" in locals() else None
                    ),
                    "user": staff_user,
                    "designation": designation,
                    "targets_count": targets_count,
                    "latest_update": latest_update_time,
                    "has_targets": targets_count > 0,
                    "has_pending_approvals": pending_targets.exists(),
                    "has_approved_targets": targets.filter(
                        status="approved"
                    ).exists(),
                }
            )
    else:
        # Initialize empty data if no period
        for staff_user in department_staff:
            try:
                staff_profile = StaffProfile.objects.get(user=staff_user)
                designation = staff_profile.designation
            except StaffProfile.DoesNotExist:
                designation = "Not specified"

            staff_with_targets.append(
                {
                    "profile": (
                        staff_profile if "staff_profile" in locals() else None
                    ),
                    "user": staff_user,
                    "designation": designation,
                    "targets_count": 0,
                    "latest_update": None,
                    "has_targets": False,
                    "has_pending_approvals": False,
                    "has_approved_targets": False,
                }
            )

    # Sort staff: those with targets first, then by name
    staff_with_targets.sort(
        key=lambda x: (-x["targets_count"], x["user"].get_full_name())
    )

    # If no active period → show empty stats
    if not period:
        logger.info("No active period - returning empty dashboard stats")
        messages.warning(request, "No active evaluation period found.")
        context = {
            "total_staff": total_staff,
            "evaluations_submitted": 0,
            "evaluated_count": 0,
            "pending_evaluations": total_staff,
            "avg_department_score": 0,
            "staff_with_targets": staff_with_targets,
            "targets_set_count": targets_set_count,
            "total_possible_targets": total_staff * 5,
            "active_period": None,
            "pending_approval_count": pending_approval_count,
            "recent_evaluations": [],
            "recent_target_approvals": [],
        }
        return render(request, "dashboards/supervisor.html", context)

    # ✅ FIX: Update department filtering in queries to use User model
    # Count submitted appraisals
    submitted_qs = StaffAppraisal.objects.filter(
        profile__user__department=supervisor_department,  # Updated
        period=period,
        status__in=["submitted", "reviewed"],
    )
    evaluations_submitted = submitted_qs.count()

    # Count reviewed appraisals
    reviewed_qs = StaffAppraisal.objects.filter(
        profile__user__department=supervisor_department,  # Updated
        period=period,
        status="reviewed",
    )
    evaluated_count = reviewed_qs.count()

    # Get IDs of profiles who have submitted OR reviewed
    submitted_or_reviewed_profile_ids = list(
        submitted_qs.values_list("profile_id", flat=True)
    )

    # Pending staff (not yet submitted AND not reviewed)
    # ✅ FIX: Update to work with User model
    pending_users = department_staff.exclude(
        staffprofile__id__in=submitted_or_reviewed_profile_ids
    )
    pending_evaluations = pending_users.count()

    # ✅ USE SERVICE: Calculate average department score
    department_performance = (
        SupervisorPerformanceCalculator.calculate_department_performance(
            supervisor_department, period
        )
    )
    avg_department_score = department_performance["avg_department_score"]

    # Get recent evaluations for activity feed
    recent_evaluations = []
    try:
        # Get recent supervisor evaluations (last 5)
        recent_evaluations = (
            SupervisorEvaluation.objects.filter(
                self_assessment__appraisal__profile__user__department=supervisor_department,  # Updated
                period=period,
            )
            .select_related(
                "self_assessment__appraisal__profile__user",
                "self_assessment__attribute",
            )
            .order_by("-submitted_at")[:5]
        )

        logger.debug(f"Found {len(recent_evaluations)} recent evaluations")
    except Exception as e:
        logger.error(f"Error fetching recent evaluations: {e}")

    # Get recent target approvals for activity feed
    recent_target_approvals = []
    try:
        recent_target_approvals = (
            PerformanceTarget.objects.filter(
                staff__department=supervisor_department,  # Updated
                period=period,
                status="approved",
            )
            .select_related("staff")
            .order_by("-approved_at")[:5]
        )

        logger.debug(
            f"Found {len(recent_target_approvals)} recent target approvals"
        )
    except Exception as e:
        logger.error(f"Error fetching recent target approvals: {e}")

    context = {
        "active_period": period,
        "pending_profiles": pending_users,  # Updated variable name
        "total_staff": total_staff,
        "evaluations_submitted": evaluations_submitted,
        "evaluated_count": evaluated_count,
        "pending_evaluations": pending_evaluations,
        "avg_department_score": avg_department_score,
        "staff_with_targets": staff_with_targets,
        "targets_set_count": targets_set_count,
        "total_possible_targets": total_staff * 5,
        "pending_approval_count": pending_approval_count,
        "recent_evaluations": recent_evaluations,
        "recent_target_approvals": recent_target_approvals,
    }

    logger.info(
        f"Dashboard loaded successfully for {request.user.email}: "
        f"{total_staff} staff, {evaluations_submitted} submitted, "
        f"{evaluated_count} reviewed, {pending_approval_count} pending approvals"
    )

    return render(request, "dashboards/supervisor.html", context)


@login_required
def view_department_staff(request):
    supervisor = request.user
    department = getattr(supervisor, "department", None)

    if not department:
        return render(
            request,
            "dashboards/no_department.html",
            {"message": "You are not assigned to any department."},
        )

    # ✅ IMPORT EXISTING SERVICES
    from dashboards.services.performance_calculations import (
        StaffPerformanceCalculator,
    )

    # Get active period
    period = SPEPeriod.objects.filter(is_active=True).first()

    # Get all staff in this department except the supervisor
    staff_members = CustomUser.objects.filter(
        department=department, role__in=["teaching", "non_teaching"]
    ).exclude(id=supervisor.id)

    staff_data = []
    scored_staff = []

    for staff in staff_members:
        # Find their current appraisal for this period
        current_appraisal = StaffAppraisal.objects.filter(
            profile__user=staff, period=period
        ).first()

        # ✅ CORRECTED: Get ANY appraisal (including current) for records link
        any_appraisal = (
            StaffAppraisal.objects.filter(profile__user=staff)
            .order_by("created_at")
            .first()
        )

        # ✅ USE SERVICE: Calculate average score using (self_rating + supervisor_rating) / 2
        avg_score = None
        if current_appraisal and current_appraisal.status.lower() in [
            "reviewed",
            "finalized",
        ]:
            score_data = (
                StaffPerformanceCalculator.calculate_combined_evaluation_score(
                    staff, period
                )
            )
            if score_data["total_evaluations"] > 0:
                avg_score = score_data["percentage_score"]

            if avg_score:
                scored_staff.append(avg_score)

        # ✅ CORRECTED: Check if staff has ANY appraisals (including current)
        has_any_appraisals = StaffAppraisal.objects.filter(
            profile__user=staff
        ).exists()

        # Determine status and labels
        if current_appraisal:
            status_label = current_appraisal.get_status_display()
            status_lower = (
                (getattr(current_appraisal, "status", "") or "")
                .strip()
                .lower()
            )
            is_submitted = status_lower in [
                "submitted",
                "reviewed",
                "finalized",
            ]
        else:
            status_label = "Awaiting Submission"
            status_lower = "awaiting"
            is_submitted = False

        staff_data.append(
            {
                "id": staff.id,
                "name": f"{staff.first_name} {staff.last_name}",
                "email": staff.email,
                "role": staff.get_role_display(),
                "appraisal": current_appraisal,
                "appraisal_status": status_label,
                "status_lower": status_lower,
                "period": period.name if period else "—",
                "can_evaluate": is_submitted,
                "avg_score": avg_score,
                "has_any_appraisals": has_any_appraisals,  # ✅ CHANGED: From has_previous_appraisals
                "any_appraisal_id": (
                    any_appraisal.id if any_appraisal else None
                ),  # ✅ CHANGED: From first_appraisal_id
                "score_class": (
                    "success"
                    if avg_score and avg_score >= 80
                    else (
                        "warning"
                        if avg_score and avg_score >= 60
                        else "danger" if avg_score else "secondary"
                    )
                ),
            }
        )

    # Sort by average score (highest first), then by name
    staff_data.sort(
        key=lambda x: (x["avg_score"] or 0, x["name"]), reverse=True
    )

    # Calculate statistics
    total_staff = len(staff_data)
    evaluated_count = len(
        [s for s in staff_data if s["avg_score"] is not None]
    )
    top_score = max(scored_staff) if scored_staff else None
    lowest_score = min(scored_staff) if scored_staff else None

    context = {
        "department": department,
        "staff_data": staff_data,
        "period": period,
        "total_staff": total_staff,
        "evaluated_count": evaluated_count,
        "top_score": top_score,
        "lowest_score": lowest_score,
    }

    return render(request, "dashboards/view_department_staff.html", context)


@login_required
def view_staff_evaluations(request):
    if request.user.role != "supervisor":
        messages.error(request, "Only supervisors can access this page.")
        return redirect("role_based_redirect")

    department = getattr(request.user, "department", None)
    if not department:
        return render(
            request,
            "dashboards/no_department.html",
            {"message": "You are not assigned to any department."},
        )

    # ✅ FIXED: Remove supervisor filtering since supervisor field was removed
    # Active evaluation period (any active period)
    active_period = SPEPeriod.objects.filter(is_active=True).first()

    # Get all staff in the supervisor's department
    staff_members = CustomUser.objects.filter(
        department=department, role__in=["teaching", "non_teaching"]
    ).exclude(id=request.user.id)

    staff_data = []
    for staff in staff_members:
        # Find that staff member's appraisal for the active period
        appraisal = StaffAppraisal.objects.filter(
            profile__user=staff, period=active_period
        ).first()

        # Prepare status
        if appraisal:
            status_label = appraisal.get_status_display()
            can_evaluate = (
                getattr(appraisal, "status", "") or ""
            ).strip().lower() == "submitted"
        else:
            status_label = "No Record"
            can_evaluate = False

        staff_data.append(
            {
                "staff": staff,
                "appraisal": appraisal,
                "status": status_label,
                "can_evaluate": can_evaluate,
            }
        )

    context = {
        "department": department,
        "active_period": active_period,
        "staff_data": staff_data,
    }

    return render(request, "dashboards/staff_evaluations.html", context)


@login_required
def evaluate_staff(request, appraisal_id):
    pass

    from dashboards.services.performance_calculations import (
        StaffPerformanceCalculator,
    )
    from spe.models import SelfAssessment

    appraisal = get_object_or_404(StaffAppraisal, id=appraisal_id)
    print(
        f"🔍 VIEW STARTED - Method: {request.method}, Appraisal ID: {appraisal_id}"
    )

    # Permission checks
    if request.user.role != "supervisor":
        messages.error(request, "Only supervisors can evaluate staff.")
        return redirect("dashboards:view_staff_evaluations")

    supervisor_dept = getattr(request.user, "department", None)
    profile_dept = getattr(appraisal.profile, "department", None)

    if (
        supervisor_dept is None
        or profile_dept is None
        or supervisor_dept != profile_dept
    ):
        messages.error(
            request, "You are not authorized to evaluate this staff."
        )
        return redirect("dashboards:view_staff_evaluations")

    if (getattr(appraisal, "status", "") or "").strip().lower() != "submitted":
        messages.error(
            request, "This appraisal must be submitted before evaluation."
        )
        return redirect("dashboards:view_staff_evaluations")

    # Get self assessments
    self_assessments_qs = SelfAssessment.objects.filter(
        staff=appraisal.profile.user, period=appraisal.period
    ).select_related("attribute", "indicator")

    self_assessments = list(self_assessments_qs)

    if request.method == "POST":
        print("✅ POST REQUEST RECEIVED!")

        try:
            with transaction.atomic():
                print("✅ INSIDE TRANSACTION")
                appraisal.refresh_from_db()

                if appraisal.status.lower() != "submitted":
                    messages.error(
                        request, "This appraisal status has changed."
                    )
                    return redirect("dashboards:view_staff_evaluations")

                saved_evaluations = []
                saved_count = 0

                # FIRST PASS: Save all individual evaluations
                for sa in self_assessments:
                    rating_key = f"supervisor_rating_{sa.id}"
                    remark_key = f"supervisor_remark_{sa.id}"

                    rating_value = request.POST.get(rating_key)

                    if rating_value:
                        try:
                            supervisor_rating = int(rating_value)
                            if 1 <= supervisor_rating <= 5:
                                remark = (
                                    request.POST.get(remark_key, "").strip()
                                    or None
                                )

                                # Save SupervisorEvaluation
                                sup_eval, created = (
                                    SupervisorEvaluation.objects.update_or_create(
                                        self_assessment=sa,
                                        supervisor=request.user,
                                        defaults={
                                            "supervisor_rating": supervisor_rating,
                                            "remarks": remark,
                                        },
                                    )
                                )

                                # Save to SPE models (without computation fields first)
                                staff_user = appraisal.profile.user
                                if staff_user.role == "teaching":
                                    eval_obj, created = (
                                        TeachingStaffEvaluation.objects.update_or_create(
                                            staff=staff_user,
                                            period=appraisal.period,
                                            attribute=sa.attribute,
                                            indicator=sa.indicator,
                                            defaults={
                                                "rating": supervisor_rating,
                                                "remarks": remark,
                                                "is_submitted": True,
                                                "status": "reviewed",
                                                "reviewed_by": request.user,
                                                "reviewed_at": timezone.now(),
                                            },
                                        )
                                    )
                                else:
                                    eval_obj, created = (
                                        NonTeachingStaffEvaluation.objects.update_or_create(
                                            staff=staff_user,
                                            period=appraisal.period,
                                            attribute=sa.attribute,
                                            indicator=sa.indicator,
                                            defaults={
                                                "rating": supervisor_rating,
                                                "remarks": remark,
                                                "is_submitted": True,
                                                "status": "reviewed",
                                                "reviewed_by": request.user,
                                                "reviewed_at": timezone.now(),
                                            },
                                        )
                                    )

                                saved_evaluations.append(eval_obj)
                                saved_count += 1

                                print(
                                    f"✅ Saved evaluation: {eval_obj.id}, Rating: {supervisor_rating}"
                                )

                        except (ValueError, TypeError) as e:
                            print(f"❌ Rating conversion error: {e}")
                            continue

                # ✅ Use service class to calculate combined scores
                if saved_count > 0:
                    print("🔄 Calculating combined scores using service...")

                    # Calculate overall combined score using service
                    score_data = StaffPerformanceCalculator.calculate_combined_evaluation_score(
                        staff_user=appraisal.profile.user,
                        period=appraisal.period,
                    )

                    # Update individual evaluation records with computed scores
                    for eval_obj in saved_evaluations:
                        try:
                            # Get corresponding self-assessment
                            self_assessment = SelfAssessment.objects.get(
                                staff=eval_obj.staff,
                                period=eval_obj.period,
                                attribute=eval_obj.attribute,
                                indicator=eval_obj.indicator,
                            )
                            # Calculate combined score for this specific evaluation
                            combined_score = (
                                self_assessment.self_rating + eval_obj.rating
                            ) / 2

                            # Update the evaluation with combined score data
                            if staff_user.role == "teaching":
                                TeachingStaffEvaluation.objects.filter(
                                    id=eval_obj.id
                                ).update(
                                    total_raw_score=combined_score,
                                    mean_raw_score=combined_score,
                                    percent_score=(combined_score / 5) * 100,
                                )
                            else:
                                NonTeachingStaffEvaluation.objects.filter(
                                    id=eval_obj.id
                                ).update(
                                    total_raw_score=combined_score,
                                    mean_raw_score=combined_score,
                                    percent_score=(combined_score / 5) * 100,
                                )

                            print(
                                f"📊 Combined score for {eval_obj.attribute.name}: {combined_score:.2f}"
                            )

                        except SelfAssessment.DoesNotExist:
                            # If no self-assessment, use supervisor rating only
                            if staff_user.role == "teaching":
                                TeachingStaffEvaluation.objects.filter(
                                    id=eval_obj.id
                                ).update(
                                    total_raw_score=eval_obj.rating,
                                    mean_raw_score=eval_obj.rating,
                                    percent_score=(eval_obj.rating / 5) * 100,
                                )
                            else:
                                NonTeachingStaffEvaluation.objects.filter(
                                    id=eval_obj.id
                                ).update(
                                    total_raw_score=eval_obj.rating,
                                    mean_raw_score=eval_obj.rating,
                                    percent_score=(eval_obj.rating / 5) * 100,
                                )

                            print(
                                f"📊 Supervisor-only score for {eval_obj.attribute.name}: {eval_obj.rating:.2f}"
                            )

                    print(f"✅ SAVED {saved_count} EVALUATIONS")

                    # Update appraisal status and overall score
                    appraisal.status = "reviewed"
                    appraisal.overall_score = score_data[
                        "percentage_score"
                    ]  # Use service-calculated percentage
                    appraisal.save()

                    # Store computed scores in session
                    request.session["evaluation_results"] = {
                        "staff_name": f"{appraisal.profile.user.first_name} {appraisal.profile.user.last_name}",
                        "period": appraisal.period.name,
                        "total_indicators": saved_count,
                        "avg_score": score_data["avg_score"],
                        "percentage_score": score_data["percentage_score"],
                        "appraisal_id": appraisal.id,
                    }

                    request.session.modified = True

                    print(
                        f"📊 FINAL SCORES - Overall Avg: {score_data['avg_score']:.2f}, Overall Percent: {score_data['percentage_score']:.2f}%"
                    )

                    messages.success(
                        request,
                        f"Evaluation completed successfully! {saved_count} indicators evaluated.",
                    )
                    return redirect("dashboards:view_staff_evaluations")

                else:
                    print("❌ NO EVALUATIONS SAVED - no ratings selected")
                    messages.warning(
                        request,
                        "Please select at least one rating before submitting.",
                    )

        except Exception as e:
            print(f"❌ EXCEPTION: {str(e)}")
            import traceback

            print(f"❌ TRACEBACK: {traceback.format_exc()}")
            messages.error(request, f"Error saving evaluation: {str(e)}")

    print("🔄 RENDERING TEMPLATE (GET request or POST failed)")

    # Prepare context for template
    existing_evals = SupervisorEvaluation.objects.filter(
        self_assessment__in=[sa.id for sa in self_assessments]
    )
    existing_evals_dict = {
        eval.self_assessment_id: eval for eval in existing_evals
    }

    rating_choices = [(i, f"{i}") for i in range(1, 6)]

    context = {
        "appraisal": appraisal,
        "self_assessments": self_assessments,
        "existing_evals": existing_evals_dict,
        "rating_choices": rating_choices,
    }

    return render(request, "dashboards/evaluate_staff.html", context)


@login_required
def staff_evaluation_results(request, appraisal_id=None):
    """Combined staff evaluation results and performance targets report with form submission"""
    from dashboards.services.evaluation_calculations import (
        EvaluationCalculator,
    )
    from dashboards.services.performance_calculations import (
        StaffPerformanceCalculator,
    )

    if request.user.role not in ["teaching", "non_teaching"]:
        messages.error(request, "Only staff can access this page.")
        return redirect("users:role_based_redirect")

    # Handle form submissions FIRST
    if request.method == "POST":
        try:
            appraisal = StaffAppraisal.objects.get(id=appraisal_id)

            # Check permissions
            if appraisal.profile.user != request.user:
                messages.error(
                    request, "You can only submit your own evaluations."
                )
                return redirect("dashboards:staff_evaluation_results")

            # Handle feedback submission
            if "staff_feedback" in request.POST:
                feedback = request.POST.get("staff_feedback", "").strip()
                if feedback:
                    # Save feedback to appraisal
                    appraisal.staff_feedback = feedback
                    appraisal.feedback_submitted_at = timezone.now()
                    appraisal.save()
                    messages.success(
                        request,
                        "Your feedback has been submitted successfully!",
                    )
                else:
                    messages.error(
                        request, "Please provide feedback before submitting."
                    )

            # Handle acknowledgement submission
            elif "acknowledge_results" in request.POST:
                appraisal.results_acknowledged = True
                appraisal.acknowledged_at = timezone.now()
                appraisal.save()
                messages.success(request, "Results acknowledged successfully!")

            # Handle appeal submission
            elif "appeal_reason" in request.POST:
                appeal_reason = request.POST.get("appeal_reason", "").strip()
                if appeal_reason:
                    # Save appeal to appraisal
                    appraisal.appeal_reason = appeal_reason
                    appraisal.appeal_submitted_at = timezone.now()
                    appraisal.appeal_status = "pending"
                    appraisal.save()
                    messages.success(
                        request, "Your appeal has been submitted for review!"
                    )
                else:
                    messages.error(
                        request, "Please provide a reason for your appeal."
                    )

            else:
                messages.error(request, "Invalid submission type.")

            # Redirect back to the same appraisal page
            return redirect(
                "dashboards:staff_evaluation_results",
                appraisal_id=appraisal_id,
            )

        except StaffAppraisal.DoesNotExist:
            messages.error(request, "Appraisal not found.")
            return redirect("dashboards:staff_evaluation_results")
        except Exception as e:
            messages.error(request, f"Error submitting form: {str(e)}")
            return redirect(
                "dashboards:staff_evaluation_results",
                appraisal_id=appraisal_id,
            )

    # ORIGINAL FUNCTIONALITY - Display results
    if not appraisal_id:
        # Show list of all appraisals
        appraisals = (
            StaffAppraisal.objects.filter(profile__user=request.user)
            .select_related("period", "profile")
            .order_by("-created_at")
        )
        context = {"appraisals": appraisals}
        return render(
            request, "dashboards/staff_evaluation_results.html", context
        )

    # View specific appraisal
    try:
        appraisal = StaffAppraisal.objects.get(id=appraisal_id)
    except StaffAppraisal.DoesNotExist:
        messages.error(request, "Appraisal not found.")
        return redirect("dashboards:staff_evaluation_results")

    # Permission check
    if appraisal.profile.user != request.user:
        messages.error(
            request, "You can only view your own evaluation results."
        )
        return redirect("dashboards:staff_evaluation_results")

    # Check if appraisal is reviewed
    if appraisal.status.lower() != "reviewed":
        messages.warning(request, "This appraisal has not been reviewed yet.")
        return redirect("dashboards:staff_evaluation_results")

    # ✅ USE SERVICE CLASSES FOR ALL CALCULATIONS
    # Get self-assessment evaluation results
    evaluation_results = (
        EvaluationCalculator.calculate_staff_evaluation_results(appraisal)
    )

    # Get target evaluation results
    target_results = EvaluationCalculator.calculate_target_evaluation_results(
        staff_user=request.user, period=appraisal.period
    )

    # ✅ FIXED: Better self-assessment detection
    print(f"=== DEBUG: Score Calculation ===")
    print(
        f"Self-assessment percentage_score: {evaluation_results['summary']['percentage_score']}"
    )
    print(
        f"Self-assessment total_indicators: {evaluation_results['summary']['total_indicators']}"
    )
    print(
        f"Self-assessment avg_score: {evaluation_results['summary']['avg_score']}"
    )
    print(
        f"Target average_score: {target_results['overall_target_performance']['average_score']}"
    )
    print(f"Has evaluated targets: {target_results['has_evaluated_targets']}")

    # ✅ FIXED: Check if self-assessment has actual data (not just structure)
    has_self_assessment_data = (
        evaluation_results["summary"]["total_indicators"] > 0
        and evaluation_results["summary"]["percentage_score"] > 0
    )

    # Check if supervisor has completed evaluation
    has_supervisor_evaluation = False
    if evaluation_results.get("supervisor_evals"):
        # Check if any supervisor ratings exist
        for eval_data in evaluation_results["supervisor_evals"].values():
            if eval_data.get("supervisor_rating") is not None:
                has_supervisor_evaluation = True
                break

    print(f"Has self-assessment data: {has_self_assessment_data}")
    print(f"Has supervisor evaluation: {has_supervisor_evaluation}")

    # ✅ FIXED: Combined overall performance calculation
    combined_overall_score = 0
    has_self_assessment_evaluation = (
        has_self_assessment_data and has_supervisor_evaluation
    )
    has_evaluated_targets = target_results["has_evaluated_targets"]

    # Get individual scores
    self_assessment_percentage = (
        float(evaluation_results["summary"]["percentage_score"])
        if has_self_assessment_data
        else 0
    )
    target_percentage = (
        float(target_results["overall_target_performance"]["average_score"])
        if has_evaluated_targets
        else 0
    )

    print(f"Self-assessment percentage (float): {self_assessment_percentage}")
    print(f"Target percentage (float): {target_percentage}")

    # ✅ FIXED: Calculate combined score based on available data
    if has_self_assessment_evaluation and has_evaluated_targets:
        # Both scores available - use weighted average (50/50)
        combined_overall_score = (
            self_assessment_percentage + target_percentage
        ) / 2
        print(
            f"Using weighted average: ({self_assessment_percentage} + {target_percentage}) / 2 = {combined_overall_score}"
        )
    elif has_self_assessment_evaluation:
        # Only self-assessment available (with supervisor evaluation)
        combined_overall_score = self_assessment_percentage
        print(f"Using self-assessment only: {combined_overall_score}")
    elif has_evaluated_targets:
        # Only target evaluation available
        combined_overall_score = target_percentage
        print(f"Using target evaluation only: {combined_overall_score}")
    elif has_self_assessment_data:
        # Only self-assessment data available (no supervisor evaluation yet)
        combined_overall_score = 0
        print("Self-assessment data available but no supervisor evaluation")
    else:
        # No evaluations available
        combined_overall_score = 0
        print("No evaluation data available")

    print(f"Final combined score: {combined_overall_score}")

    # ✅ FIXED: Performance category for combined score
    combined_performance = "Not Evaluated"
    combined_performance_class = "secondary"

    if combined_overall_score > 0:
        if combined_overall_score >= 90:
            combined_performance = "Outstanding"
            combined_performance_class = "success"
        elif combined_overall_score >= 80:
            combined_performance = "Excellent"
            combined_performance_class = "success"
        elif combined_overall_score >= 70:
            combined_performance = "Good"
            combined_performance_class = "info"
        elif combined_overall_score >= 60:
            combined_performance = "Satisfactory"
            combined_performance_class = "info"
        elif combined_overall_score >= 50:
            combined_performance = "Meets Expectations"
            combined_performance_class = "warning"
        elif combined_overall_score >= 30:
            combined_performance = "Below Expectations"
            combined_performance_class = "warning"
        else:
            combined_performance = "Unsatisfactory"
            combined_performance_class = "danger"

    # ✅ ADDED: Get performance history for charts
    performance_history = (
        StaffPerformanceCalculator.calculate_performance_history(
            request.user, limit=6
        )
    )

    # ✅ ADDED: Get target statistics
    target_stats = StaffPerformanceCalculator.calculate_target_statistics(
        request.user, appraisal.period
    )

    context = {
        "appraisal": appraisal,
        # Self-assessment evaluation data from service
        "self_assessments": evaluation_results["self_assessments"],
        "supervisor_evals": evaluation_results["supervisor_evals"],
        "performance": evaluation_results["performance"],
        "performance_class": evaluation_results["performance_class"],
        # Performance targets data from service
        "performance_targets": target_results["performance_targets"],
        "target_evaluations": target_results["target_evaluations"],
        "target_stats": target_results["target_stats"],
        "target_status_counts": target_results["target_status_counts"],
        "overall_target_performance": target_results[
            "overall_target_performance"
        ],
        # Summary data
        "summary": {
            "total_indicators": evaluation_results["summary"][
                "total_indicators"
            ],
            "avg_score": evaluation_results["summary"]["avg_score"],
            "percentage_score": evaluation_results["summary"][
                "percentage_score"
            ],
            "supervisor_name": evaluation_results["summary"][
                "supervisor_name"
            ],
            "combined_overall_score": round(combined_overall_score, 1),
            "combined_performance": combined_performance,
            "combined_performance_class": combined_performance_class,
        },
        # Additional data
        "rating_choices": [(i, f"{i}") for i in range(1, 6)],
        "performance_history": performance_history,
        "target_statistics": target_stats,
        # ✅ ADDED: Flags for template logic
        "has_targets": target_results["has_targets"],
        "has_evaluated_targets": target_results["has_evaluated_targets"],
        "has_self_assessment_data": has_self_assessment_data,  # Has any self-assessment data
        "has_self_assessment_evaluation": has_self_assessment_evaluation,  # Has completed self-assessment with supervisor
        "has_supervisor_evaluation": has_supervisor_evaluation,  # Supervisor has rated
        "show_combined_score": has_self_assessment_evaluation
        and has_evaluated_targets,
        # ✅ ADDED: Individual scores for debugging
        "self_assessment_percentage": self_assessment_percentage,
        "target_percentage": target_percentage,
    }

    # ✅ FIXED: Handle PDF export AFTER context is built
    if "export" in request.GET and request.GET["export"] == "pdf":
        return generate_staff_evaluation_pdf(request, appraisal, context)

    return render(request, "dashboards/staff_evaluation_results.html", context)


@login_required
def supervisor_evaluation_results(request, appraisal_id=None):
    """Allow supervisors to view staff evaluation results - WITH COMBINED RESULTS like staff view"""
    from dashboards.services.evaluation_calculations import (
        EvaluationCalculator,
    )
    from dashboards.services.performance_calculations import (
        StaffPerformanceCalculator,
    )

    if request.user.role != "supervisor":
        messages.error(request, "Only supervisors can access this page.")
        return redirect("role_based_redirect")

    # Get supervisor's department
    supervisor_dept = getattr(request.user, "department", None)
    if not supervisor_dept:
        messages.error(request, "You are not assigned to any department.")
        return redirect("dashboards:supervisor_dashboard")

    if not appraisal_id:
        # Show list of all reviewed appraisals in supervisor's department
        reviewed_appraisals = (
            StaffAppraisal.objects.filter(
                profile__department=supervisor_dept,
                status__in=["reviewed", "finalized"],
            )
            .select_related("profile", "profile__user", "period")
            .order_by("-created_at")
        )

        context = {
            "appraisals": reviewed_appraisals,
            "department": supervisor_dept,
        }
        return render(
            request, "dashboards/supervisor_evaluation_results.html", context
        )

    # View specific appraisal
    try:
        appraisal = StaffAppraisal.objects.get(id=appraisal_id)
    except StaffAppraisal.DoesNotExist:
        messages.error(request, "Appraisal not found.")
        return redirect("dashboards:supervisor_evaluation_results")

    # Permission check - supervisor can only view staff in their department
    if appraisal.profile.department != supervisor_dept:
        messages.error(
            request,
            "You can only view evaluations for staff in your department.",
        )
        return redirect("dashboards:supervisor_evaluation_results")

    # Check if appraisal is reviewed
    if appraisal.status.lower() not in ["reviewed", "finalized"]:
        messages.warning(request, "This appraisal has not been reviewed yet.")
        return redirect("dashboards:view_staff_evaluations")

    # ✅ USE SERVICE CLASSES FOR ALL CALCULATIONS (SAME AS STAFF VIEW)
    # Get self-assessment evaluation results
    evaluation_results = (
        EvaluationCalculator.calculate_staff_evaluation_results(appraisal)
    )

    # Get target evaluation results
    target_results = EvaluationCalculator.calculate_target_evaluation_results(
        staff_user=appraisal.profile.user, period=appraisal.period
    )

    # ✅ FIXED: Combined overall performance calculation (SAME AS STAFF VIEW)
    combined_overall_score = 0
    has_self_assessment_evaluation = (
        evaluation_results["summary"]["total_indicators"] > 0
    )
    has_evaluated_targets = target_results["has_evaluated_targets"]

    if has_self_assessment_evaluation and has_evaluated_targets:
        # Convert to float and calculate weighted average (60% self-assessment, 40% targets)
        self_assessment_percentage = float(
            evaluation_results["summary"]["percentage_score"]
        )
        target_percentage = float(
            target_results["overall_target_performance"]["average_score"]
        )
        combined_overall_score = (self_assessment_percentage * 0.6) + (
            target_percentage * 0.4
        )
    elif has_self_assessment_evaluation:
        combined_overall_score = float(
            evaluation_results["summary"]["percentage_score"]
        )
    elif has_evaluated_targets:
        combined_overall_score = float(
            target_results["overall_target_performance"]["average_score"]
        )

    # ✅ ADDED: Performance category for combined score (SAME AS STAFF VIEW)
    combined_performance = "Not Evaluated"
    combined_performance_class = "secondary"

    if combined_overall_score > 0:
        if combined_overall_score >= 90:
            combined_performance = "Outstanding"
            combined_performance_class = "success"
        elif combined_overall_score >= 80:
            combined_performance = "Exceeds Expectations"
            combined_performance_class = "success"
        elif combined_overall_score >= 50:
            combined_performance = "Meets Expectations"
            combined_performance_class = "info"
        elif combined_overall_score >= 30:
            combined_performance = "Below Expectations"
            combined_performance_class = "warning"
        else:
            combined_performance = "Far Below Expectations"
            combined_performance_class = "danger"

    # ✅ ADDED: Get performance history for charts
    performance_history = (
        StaffPerformanceCalculator.calculate_performance_history(
            appraisal.profile.user, limit=6
        )
    )

    # ✅ ADDED: Get target statistics
    target_stats = StaffPerformanceCalculator.calculate_target_statistics(
        appraisal.profile.user, appraisal.period
    )

    # ✅ USE THE EXACT SAME CONTEXT STRUCTURE AS STAFF VIEW
    context = {
        "appraisal": appraisal,
        # Self-assessment evaluation data from service (SAME AS STAFF VIEW)
        "self_assessments": evaluation_results["self_assessments"],
        "supervisor_evals": evaluation_results["supervisor_evals"],
        "performance": evaluation_results["performance"],
        "performance_class": evaluation_results["performance_class"],
        # Performance targets data from service (SAME AS STAFF VIEW)
        "performance_targets": target_results["performance_targets"],
        "target_evaluations": target_results["target_evaluations"],
        "target_stats": target_results["target_stats"],
        "target_status_counts": target_results["target_status_counts"],
        "overall_target_performance": target_results[
            "overall_target_performance"
        ],
        # Summary data (SAME AS STAFF VIEW)
        "summary": {
            "total_indicators": evaluation_results["summary"][
                "total_indicators"
            ],
            "avg_score": evaluation_results["summary"]["avg_score"],
            "percentage_score": evaluation_results["summary"][
                "percentage_score"
            ],
            "supervisor_name": evaluation_results["summary"][
                "supervisor_name"
            ],
            "combined_overall_score": round(combined_overall_score, 1),
            "combined_performance": combined_performance,
            "combined_performance_class": combined_performance_class,
        },
        # Additional data (SAME AS STAFF VIEW)
        "rating_choices": [(i, f"{i}") for i in range(1, 6)],
        "performance_history": performance_history,
        "target_statistics": target_stats,
        # ✅ ADDED: Flags for template logic (SAME AS STAFF VIEW)
        "has_targets": target_results["has_targets"],
        "has_evaluated_targets": target_results["has_evaluated_targets"],
        "has_self_assessment_evaluation": has_self_assessment_evaluation,
        "show_combined_score": has_self_assessment_evaluation
        and has_evaluated_targets,
        # ✅ ADDED: Supervisor-specific context
        "is_supervisor_view": True,
        "staff_user": appraisal.profile.user,
        "staff_profile": appraisal.profile,
        "supervisor_dept": supervisor_dept,
    }

    # ✅ FIXED: Handle PDF export (SAME AS STAFF VIEW)
    if "export" in request.GET and request.GET["export"] == "pdf":
        return generate_staff_evaluation_pdf(request, appraisal, context)

    # ✅ CRITICAL: Use the SAME TEMPLATE as staff view for consistent display
    return render(request, "dashboards/staff_evaluation_results.html", context)


@login_required
def supervisor_view_targets(request, staff_id):
    """Supervisor view of staff member's performance targets"""
    try:
        staff_user = get_object_or_404(CustomUser, id=staff_id)

        # Handle POST requests for approve/reject
        if request.method == "POST":
            return _handle_target_action(request, staff_id)

        # GET request - display targets
        try:
            # Get supervisor permission
            supervisor_profile = (
                TargetApprovalService.validate_supervisor_permission(
                    request.user
                )
            )

            # Validate access to staff
            TargetApprovalService.validate_staff_access(
                supervisor_profile, staff_user
            )

        except PermissionDenied as e:
            messages.error(request, str(e))
            return redirect("dashboards:supervisor_dashboard")

        # Get current period
        current_period = SPEPeriod.objects.filter(is_active=True).first()

        if not current_period:
            return _render_no_period_view(
                request, staff_user, supervisor_profile
            )

        # Get staff targets details using service
        target_details = TargetApprovalService.get_staff_targets_details(
            staff_user, current_period
        )

        # Get staff summary
        staff_summary = TargetApprovalService.get_staff_with_targets_summary(
            request.user, current_period
        )

        # Get performance insights
        performance_insights = TargetApprovalService.get_performance_insights(
            staff_user, current_period
        )

        context = {
            "staff_user": staff_user,
            "staff_profile": staff_user.staffprofile,
            "targets": target_details["targets"],
            "current_period": current_period,
            "active_period": current_period,
            "has_targets": target_details["has_targets"],
            # Target statistics
            "pending_count": target_details["stats"]["pending_targets_count"],
            "approved_count": target_details["stats"][
                "approved_targets_count"
            ],
            "rejected_count": target_details["stats"][
                "rejected_targets_count"
            ],
            "completed_count": target_details["stats"][
                "completed_targets_count"
            ],
            "total_targets": target_details["stats"]["targets_count"],
            # Performance metrics
            "target_completion_rate": target_details["completion_rate"],
            "average_target_rating": target_details["average_rating"],
            "target_status_distribution": target_details[
                "status_distribution"
            ],
            # Staff list
            "staff_list": staff_summary["staff_list"],
            "total_staff": staff_summary["total_staff"],
            "staff_with_targets_count": staff_summary[
                "staff_with_targets_count"
            ],
            "pending_approval_count": staff_summary["total_pending_count"],
            "supervisor_department": supervisor_profile.department,
            # Performance insights
            "performance_insights": performance_insights,
        }

        return render(
            request, "dashboards/supervisor_view_targets.html", context
        )

    except Exception as e:
        logger.error(
            f"Error in supervisor_view_targets: {str(e)}", exc_info=True
        )
        messages.error(request, f"An error occurred: {str(e)}")
        return redirect("dashboards:supervisor_dashboard")


@login_required
def approve_target(request, target_id=None):
    """
    Combined view that:
    - Shows approval dashboard (when no target_id)
    - Handles approval actions (when target_id provided via POST)
    """
    try:
        # Validate supervisor permission
        try:
            TargetApprovalService.validate_supervisor_permission(request.user)
        except PermissionDenied as e:
            messages.error(request, str(e))
            return redirect("dashboards:supervisor_dashboard")

        # Handle POST request for approval actions
        if request.method == "POST":
            return _handle_bulk_approval(request)

        # GET request - Show approval dashboard
        dashboard_data = TargetApprovalService.get_approval_dashboard_data(
            request.user
        )

        return render(
            request, "dashboards/approve_target.html", dashboard_data
        )

    except Exception as e:
        logger.error(f"Error in approve_target: {str(e)}", exc_info=True)
        messages.error(request, f"An error occurred: {str(e)}")
        return redirect("dashboards:supervisor_dashboard")


@login_required
def reject_target(request, target_id):
    """Handle individual target rejection"""
    try:
        if request.method == "POST":
            rejection_reason = request.POST.get("rejection_reason")

            if not rejection_reason:
                messages.error(
                    request, "Please provide a reason for rejection."
                )
                return redirect("dashboards:approve_targets")

            try:
                target = TargetApprovalService.reject_target(
                    target_id, request.user, rejection_reason
                )
                messages.warning(
                    request, f'Target "{target.description}" rejected.'
                )
            except (PermissionDenied, ValueError) as e:
                messages.error(request, str(e))

        return redirect("dashboards:approve_targets")

    except Exception as e:
        logger.error(f"Error in reject_target: {str(e)}", exc_info=True)
        messages.error(request, f"An error occurred: {str(e)}")
        return redirect("dashboards:approve_targets")


# Helper functions
def _handle_target_action(request, staff_id):
    """Handle individual target approve/reject actions"""
    target_id = request.POST.get("target_id")
    action = request.POST.get("action")
    rejection_reason = request.POST.get("rejection_reason", "")

    if not target_id or not action:
        messages.error(request, "Invalid request parameters.")
        return redirect(
            "dashboards:supervisor_view_targets", staff_id=staff_id
        )

    try:
        if action == "approve":
            target = TargetApprovalService.approve_target(
                target_id, request.user
            )
            messages.success(
                request,
                f'Target "{target.description}" approved successfully!',
            )
        elif action == "reject":
            if not rejection_reason:
                messages.error(
                    request, "Please provide a reason for rejection."
                )
                return redirect(
                    "dashboards:supervisor_view_targets", staff_id=staff_id
                )

            target = TargetApprovalService.reject_target(
                target_id, request.user, rejection_reason
            )
            messages.warning(
                request, f'Target "{target.description}" rejected.'
            )
    except (PermissionDenied, ValueError) as e:
        messages.error(request, str(e))

    return redirect("dashboards:supervisor_view_targets", staff_id=staff_id)


def _handle_bulk_approval(request):
    """Handle bulk approval actions"""
    try:
        target_ids = request.POST.getlist("target_ids")
        action = request.POST.get("action")
        staff_id = request.POST.get("staff_id")
        bulk_action = request.POST.get("bulk_action")
        rejection_reason = request.POST.get("rejection_reason", "")

        # Handle bulk approve for specific staff
        if bulk_action == "approve_staff" and staff_id:
            approved_count = (
                TargetApprovalService.approve_all_pending_for_staff(
                    staff_id, request.user
                )
            )

            staff_user = get_object_or_404(CustomUser, id=staff_id)
            if approved_count > 0:
                messages.success(
                    request,
                    f"Approved all {approved_count} pending targets for {staff_user.get_full_name()}",
                )
            else:
                messages.info(
                    request,
                    f"No pending targets found for {staff_user.get_full_name()}",
                )

            return redirect(
                "dashboards:supervisor_view_targets", staff_id=staff_id
            )

        # Handle bulk actions on selected targets
        elif target_ids and action:
            count, staff_list = TargetApprovalService.bulk_approve_targets(
                request.user, target_ids, action, rejection_reason
            )

            if count > 0:
                action_text = "approved" if action == "approve" else "rejected"
                messages.success(
                    request,
                    f"Successfully {action_text} {count} targets for {staff_list}",
                )
            else:
                messages.info(request, "No targets were processed.")

            # Redirect to individual staff page if only one staff involved
            if count > 0:
                try:
                    first_target = PerformanceTarget.objects.filter(
                        id__in=target_ids
                    ).first()
                    if first_target:
                        staff_id = first_target.staff.id
                        return redirect(
                            "dashboards:supervisor_view_targets",
                            staff_id=staff_id,
                        )
                except:
                    pass

            return redirect("dashboards:approve_targets")
        else:
            messages.error(request, "No targets selected or invalid action.")

    except (PermissionDenied, ValueError) as e:
        messages.error(request, str(e))
    except Exception as e:
        logger.error(
            f"Error processing bulk approval: {str(e)}", exc_info=True
        )
        messages.error(request, f"Error processing request: {str(e)}")

    return redirect("dashboards:approve_targets")


def _render_no_period_view(request, staff_user, supervisor_profile):
    """Render view when no active period exists"""
    staff_summary = TargetApprovalService.get_staff_with_targets_summary(
        request.user, None
    )

    context = {
        "staff_user": staff_user,
        "staff_profile": staff_user.staffprofile,
        "targets": [],
        "current_period": None,
        "has_targets": False,
        "staff_list": staff_summary["staff_list"],
        "total_staff": staff_summary["total_staff"],
        "pending_count": 0,
        "approved_count": 0,
        "rejected_count": 0,
        "total_targets": 0,
        "staff_with_targets_count": staff_summary["staff_with_targets_count"],
        "pending_approval_count": staff_summary["total_pending_count"],
        "target_completion_rate": 0,
        "average_target_rating": 0,
        "target_status_distribution": [],
        "supervisor_department": supervisor_profile.department,
    }

    messages.info(request, "No active evaluation period found.")
    return render(request, "dashboards/supervisor_view_targets.html", context)


def generate_staff_evaluation_pdf(request, appraisal, context):
    """Generate formal PDF version of staff evaluation results with performance targets"""
    import io

    from django.http import HttpResponse
    from django.utils import timezone
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    # Create PDF in memory
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
    )

    styles = getSampleStyleSheet()
    story = []

    # Title
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Heading1"],
        fontSize=16,
        spaceAfter=30,
        alignment=1,  # Center
        textColor=colors.HexColor("#2c3e50"),
    )
    story.append(
        Paragraph("KyU STAFF PERFORMANCE EVALUATION REPORT", title_style)
    )

    # Header Information Table
    header_data = [
        ["STAFF INFORMATION", "EVALUATION DETAILS"],
        [
            f"Name: {appraisal.profile.user.get_full_name()}",
            f"Period: {appraisal.period.name}",
        ],
        [
            f"Department: {appraisal.profile.department.name}",
            f"Evaluation Date: {appraisal.updated_at.strftime('%B %d, %Y')}",
        ],
        [
            f"Designation: {appraisal.profile.designation}",
            f"Evaluated By: {context['summary']['supervisor_name']}",
        ],
    ]

    header_table = Table(header_data, colWidths=[3 * inch, 3 * inch])
    header_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#34495e")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 12),
                ("FONTSIZE", (0, 1), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#f8f9fa")),
                ("GRID", (0, 0), (-1, -1), 1, colors.grey),
            ]
        )
    )
    story.append(header_table)
    story.append(Spacer(1, 0.3 * inch))

    # Comprehensive Performance Summary
    summary_style = ParagraphStyle(
        "SummaryStyle",
        parent=styles["Normal"],
        fontSize=12,
        spaceAfter=12,
        textColor=colors.HexColor("#2c3e50"),
    )

    story.append(Paragraph("COMPREHENSIVE PERFORMANCE SUMMARY", summary_style))

    # Enhanced summary data with targets
    summary_data = [
        ["Metric", "Self-Assessment", "Performance Targets", "Overall"],
        [
            "Score",
            f"{context['summary']['percentage_score']}%",
            (
                f"{context['overall_target_performance']['average_score']}%"
                if context["has_evaluated_targets"]
                else "N/A"
            ),
            (
                f"{context['summary']['combined_overall_score']}%"
                if context["show_combined_score"]
                else f"{context['summary']['percentage_score']}%"
            ),
        ],
        [
            "Rating",
            context["performance"],
            (
                context["overall_target_performance"]["overall_rating"]
                if context["has_evaluated_targets"]
                else "Not Evaluated"
            ),
            context["performance"],
        ],
        [
            "Items Count",
            str(context["summary"]["total_indicators"]),
            f"{context['overall_target_performance']['evaluated_count']}/{context['target_stats']['total_targets']}",
            "Combined",
        ],
    ]

    summary_table = Table(
        summary_data,
        colWidths=[1.5 * inch, 1.5 * inch, 1.8 * inch, 1.2 * inch],
    )
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3498db")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 10),
                ("FONTSIZE", (0, 1), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#ecf0f1")),
                ("GRID", (0, 0), (-1, -1), 1, colors.grey),
            ]
        )
    )
    story.append(summary_table)
    story.append(Spacer(1, 0.3 * inch))

    # Performance Targets Section
    if context["has_targets"]:
        story.append(Paragraph("PERFORMANCE TARGETS OVERVIEW", summary_style))

        targets_data = [
            ["Target Status", "Count", "Percentage"],
            [
                "Total Targets",
                str(context["target_stats"]["total_targets"]),
                "100%",
            ],
            [
                "Approved",
                str(context["target_stats"]["approved_targets"]),
                (
                    f"{(context['target_stats']['approved_targets']/context['target_stats']['total_targets']*100):.1f}%"
                    if context["target_stats"]["total_targets"] > 0
                    else "0%"
                ),
            ],
            [
                "Evaluated",
                str(context["target_stats"]["evaluated_targets"]),
                (
                    f"{(context['target_stats']['evaluated_targets']/context['target_stats']['total_targets']*100):.1f}%"
                    if context["target_stats"]["total_targets"] > 0
                    else "0%"
                ),
            ],
            [
                "Completed",
                str(context["target_stats"]["completed_targets"]),
                (
                    f"{(context['target_stats']['completed_targets']/context['target_stats']['total_targets']*100):.1f}%"
                    if context["target_stats"]["total_targets"] > 0
                    else "0%"
                ),
            ],
        ]

        targets_table = Table(
            targets_data, colWidths=[2 * inch, 1 * inch, 1 * inch]
        )
        targets_table.setStyle(
            TableStyle(
                [
                    (
                        "BACKGROUND",
                        (0, 0),
                        (-1, 0),
                        colors.HexColor("#27ae60"),
                    ),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 10),
                    ("FONTSIZE", (0, 1), (-1, -1), 9),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                    (
                        "BACKGROUND",
                        (0, 1),
                        (-1, -1),
                        colors.HexColor("#f8f9fa"),
                    ),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ]
            )
        )
        story.append(targets_table)
        story.append(Spacer(1, 0.3 * inch))

    # Detailed Evaluation Table
    story.append(Paragraph("DETAILED PERFORMANCE ASSESSMENT", summary_style))

    # Table headers
    evaluation_data = [
        [
            "Attribute",
            "Indicator",
            "Self Rating",
            "Supervisor",
            "Combined",
            "Remarks",
        ]
    ]

    # Add evaluation data
    for assessment in context["self_assessments"]:
        eval_data = context["supervisor_evals"].get(assessment.id, {})

        # Truncate long text for better formatting
        attribute = (
            assessment.attribute.name[:25] + "..."
            if len(assessment.attribute.name) > 25
            else assessment.attribute.name
        )
        indicator = (
            assessment.indicator.description[:35] + "..."
            if len(assessment.indicator.description) > 35
            else assessment.indicator.description
        )

        # Handle None remarks safely
        remarks_text = eval_data.get("remarks", "") or ""
        remarks = (
            remarks_text[:40] + "..."
            if len(remarks_text) > 40
            else remarks_text
        )

        evaluation_data.append(
            [
                attribute,
                indicator,
                str(assessment.self_rating),
                str(eval_data.get("supervisor_rating", "N/A")),
                f"{eval_data.get('combined_score', 0):.1f}",
                remarks or "-",
            ]
        )

    # Create evaluation table
    evaluation_table = Table(
        evaluation_data,
        colWidths=[
            1.2 * inch,
            1.8 * inch,
            0.7 * inch,
            0.7 * inch,
            0.7 * inch,
            1.2 * inch,
        ],
        repeatRows=1,
    )

    evaluation_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("ALIGN", (2, 1), (4, -1), "CENTER"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 9),
                ("FONTSIZE", (0, 1), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors.white, colors.HexColor("#f8f9fa")],
                ),
            ]
        )
    )

    story.append(evaluation_table)
    story.append(Spacer(1, 0.3 * inch))

    # Performance Targets Details (if evaluated targets exist)
    if context["has_evaluated_targets"]:
        story.append(
            Paragraph("PERFORMANCE TARGETS EVALUATION", summary_style)
        )

        targets_eval_data = [
            ["Target #", "Description", "Rating", "Performance", "Comments"]
        ]

        for target in context["target_evaluations"]:
            if target["is_evaluated"]:
                desc = (
                    target["description"][:50] + "..."
                    if len(target["description"]) > 50
                    else target["description"]
                )
                comments = (
                    target["supervisor_comments"][:30] + "..."
                    if target["supervisor_comments"]
                    and len(target["supervisor_comments"]) > 30
                    else (target["supervisor_comments"] or "-")
                )

                targets_eval_data.append(
                    [
                        str(target["target_number"]),
                        desc,
                        f"{target['performance_rating']}%",
                        target["performance_category"],
                        comments,
                    ]
                )

        if len(targets_eval_data) > 1:  # If we have data beyond headers
            targets_eval_table = Table(
                targets_eval_data,
                colWidths=[
                    0.6 * inch,
                    2.2 * inch,
                    0.8 * inch,
                    1.2 * inch,
                    1.2 * inch,
                ],
                repeatRows=1,
            )

            targets_eval_table.setStyle(
                TableStyle(
                    [
                        (
                            "BACKGROUND",
                            (0, 0),
                            (-1, 0),
                            colors.HexColor("#e67e22"),
                        ),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, 0), 9),
                        ("FONTSIZE", (0, 1), (-1, -1), 8),
                        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                        (
                            "BACKGROUND",
                            (0, 1),
                            (-1, -1),
                            colors.HexColor("#fef9e7"),
                        ),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ]
                )
            )
            story.append(targets_eval_table)
            story.append(Spacer(1, 0.3 * inch))

    # Performance Interpretation Guide
    story.append(Paragraph("PERFORMANCE INTERPRETATION GUIDE", summary_style))

    guide_data = [
        ["Score Range", "Performance Level", "Description"],
        [
            "90-100%",
            "Outstanding",
            "Exceptional performance exceeding all expectations",
        ],
        ["80-89%", "Excellent", "Performance consistently above requirements"],
        ["70-79%", "Good", "Solid performance meeting most requirements"],
        [
            "60-69%",
            "Satisfactory",
            "Adequate performance meeting basic requirements",
        ],
        ["50-59%", "Needs Improvement", "Performance requires development"],
        [
            "Below 50%",
            "Unsatisfactory",
            "Performance requires immediate attention",
        ],
    ]

    guide_table = Table(
        guide_data, colWidths=[1.5 * inch, 1.5 * inch, 3 * inch]
    )
    guide_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#27ae60")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("ALIGN", (0, 1), (-1, -1), "LEFT"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 9),
                ("FONTSIZE", (0, 1), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                ("BACKGROUND", (0, 1), (0, -1), colors.HexColor("#e8f5e8")),
                ("BACKGROUND", (1, 1), (1, -1), colors.HexColor("#f0f8ff")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ]
        )
    )

    story.append(guide_table)

    # Footer with signatures
    story.append(Spacer(1, 0.5 * inch))

    signature_data = [
        ["", ""],
        ["_________________________", "_________________________"],
        ["Employee Signature", "Supervisor Signature"],
        ["", ""],
        [
            f"Date: {timezone.now().strftime('%Y-%m-%d')}",
            f"Date: {appraisal.updated_at.strftime('%Y-%m-%d')}",
        ],
    ]

    signature_table = Table(signature_data, colWidths=[3 * inch, 3 * inch])
    signature_table.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
            ]
        )
    )

    story.append(signature_table)

    # Build PDF
    doc.build(story)

    # Prepare response
    buffer.seek(0)
    response = HttpResponse(buffer, content_type="application/pdf")
    filename = f"Performance_Evaluation_{appraisal.profile.user.get_full_name().replace(' ', '_')}_{appraisal.period.name}.pdf"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    return response
