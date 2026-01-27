# hr/views.py
import io

import openpyxl
from django.apps import apps
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Max, Min, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from openpyxl.styles import Alignment, Font
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# Import models from spe app
from spe.models import (
    NonTeachingStaffEvaluation,
    SelfAssessment,
    SPEPeriod,
    SupervisorEvaluation as SpeSupervisorEvaluation,  # Aliased to avoid conflict
    SupervisorRating,
    TeachingStaffEvaluation,
)

# Import models from users app
from users.models import (
    CustomUser,
    Department,
    PerformanceTarget,
    StaffAppraisal,
    StaffProfile,
)

# Import models from hr app
from .models import (
    SupervisorAppraisal,
    SupervisorAttribute,
    SupervisorEvaluation as HrSupervisorEvaluation,  # Aliased to avoid conflict
    SupervisorIndicator,
    SupervisorPerformanceTarget,
)

# Import services if available
try:
    from vc.services import VCSupervisorService
except ImportError:
    VCSupervisorService = None  # Handle gracefully if VC app not available


def is_hr_user(user):
    """Check if user is HR staff"""
    return user.is_authenticated and user.is_hr_staff


User = get_user_model()


@login_required
def hr_dashboard(request):
    """HR Dashboard - Staff-focused only (Supervisor management moved to VC)"""
    if not request.user.is_hr_staff:
        messages.error(request, "Only HR staff can access this page.")
        return redirect("users:role_based_redirect")

    # Get actual statistics from your models - STAFF ONLY
    total_staff = CustomUser.objects.filter(
        role__in=["teaching", "non_teaching"]
    ).count()

    # Staff Appraisals statistics
    staff_appraisals = StaffAppraisal.objects.all()
    total_appraisals = staff_appraisals.count()
    submitted_count = staff_appraisals.filter(status="submitted").count()
    reviewed_count = staff_appraisals.filter(status="reviewed").count()
    finalized_count = staff_appraisals.filter(status="finalized").count()

    # Performance Targets statistics (STAFF ONLY)
    performance_targets = PerformanceTarget.objects.all()
    pending_targets = performance_targets.filter(status="submitted").count()
    approved_targets_count = performance_targets.filter(
        status="approved"
    ).count()

    # Department statistics
    total_departments = Department.objects.count()

    # Recent activity - Staff appraisals only
    recent_appraisals = StaffAppraisal.objects.select_related(
        "profile__user", "period", "profile__user__department"
    ).order_by("-updated_at")[:10]

    # Performance statistics (STAFF ONLY)
    avg_score = (
        staff_appraisals.filter(overall_score__isnull=False).aggregate(
            avg=Avg("overall_score")
        )["avg"]
        or 0
    )

    highest_score = (
        staff_appraisals.filter(overall_score__isnull=False).aggregate(
            max=Max("overall_score")
        )["max"]
        or 0
    )

    lowest_score = (
        staff_appraisals.filter(overall_score__isnull=False).aggregate(
            min=Min("overall_score")
        )["min"]
        or 0
    )

    # Department stats (STAFF ONLY)
    dept_stats = (
        StaffAppraisal.objects.filter(overall_score__isnull=False)
        .values("profile__user__department__name")
        .annotate(count=Count("id"), avg_score=Avg("overall_score"))
        .order_by("-avg_score")
    )

    # Enhanced department data for the overview (STAFF ONLY)
    departments = Department.objects.annotate(
        staff_count=Count(
            "users", filter=Q(users__role__in=["teaching", "non_teaching"])
        ),
        appraisal_count=Count(
            "users__staffprofile__appraisals",
            filter=Q(users__staffprofile__appraisals__isnull=False),
        ),
    )

    context = {
        # Statistics (STAFF ONLY)
        "total_staff": total_staff,
        "total_appraisals": total_appraisals,
        "submitted_count": submitted_count,
        "reviewed_count": reviewed_count,
        "finalized_count": finalized_count,
        "pending_targets": pending_targets,
        "approved_targets_count": approved_targets_count,
        "total_departments": total_departments,
        # Performance data (STAFF ONLY)
        "avg_score": avg_score,
        "highest_score": highest_score,
        "lowest_score": lowest_score,
        "dept_stats": dept_stats,
        # Lists (STAFF ONLY)
        "recent_appraisals": recent_appraisals,
        "departments": departments,
    }

    return render(request, "hr/hr_dashboard.html", context)


@login_required
def hr_department_appraisals(request):
    """HR view of all department appraisals - Counts COMPLETE appraisals with all components"""
    if not request.user.is_hr_staff:
        messages.error(request, "Only HR staff can access this page.")
        return redirect("users:role_based_redirect")

    # Get active period
    active_period = SPEPeriod.objects.filter(is_active=True).first()

    # Get all departments
    departments = Department.objects.all().order_by("name")

    # Calculate statistics for each department
    department_data = []
    for dept in departments:
        # Count ALL staff in this department (teaching + non_teaching + supervisors)
        staff_count = CustomUser.objects.filter(
            department=dept,
            role__in=["teaching", "non_teaching", "supervisor"],
        ).count()

        # Get ALL staff in this department
        dept_staff = CustomUser.objects.filter(
            department=dept,
            role__in=["teaching", "non_teaching", "supervisor"],
        )

        # Count COMPLETE appraisals for current period
        current_appraisals = 0
        if active_period:
            # Manual check for each staff member to ensure complete appraisals
            for staff in dept_staff:
                is_complete = False

                if staff.role in ["teaching", "non_teaching"]:
                    # REGULAR STAFF: Check PerformanceTarget + SelfAssessment + SupervisorEvaluation
                    has_targets = PerformanceTarget.objects.filter(
                        staff=staff, period=active_period
                    ).exists()

                    has_self_assessments = SelfAssessment.objects.filter(
                        staff=staff, period=active_period
                    ).exists()

                    # Check supervisor evaluations
                    staff_self_assessments = SelfAssessment.objects.filter(
                        staff=staff, period=active_period
                    )

                    has_supervisor_evals = False
                    for self_assessment in staff_self_assessments:
                        if hasattr(
                            self_assessment, "spe_supervisor_evaluation"
                        ):
                            has_supervisor_evals = True
                            break

                    is_complete = (
                        has_targets
                        and has_self_assessments
                        and has_supervisor_evals
                    )

                elif staff.role == "supervisor":
                    # SUPERVISORS: Check SupervisorPerformanceTarget + SupervisorRating (VC ratings)
                    has_targets = SupervisorPerformanceTarget.objects.filter(
                        supervisor=staff, period=active_period
                    ).exists()

                    has_vc_ratings = SupervisorRating.objects.filter(
                        supervisor=staff, period=active_period
                    ).exists()

                    is_complete = has_targets and has_vc_ratings

                if is_complete:
                    current_appraisals += 1

        # Count total historical appraisals (simplified)
        staff_with_any_appraisal = (
            StaffAppraisal.objects.filter(profile__user__in=dept_staff)
            .values("profile__user")
            .distinct()
            .count()
        )

        supervisors_with_any_rating = (
            SupervisorRating.objects.filter(
                supervisor__in=dept_staff.filter(role="supervisor")
            )
            .values("supervisor")
            .distinct()
            .count()
        )

        appraisal_count = (
            staff_with_any_appraisal + supervisors_with_any_rating
        )

        # Calculate completion rate (should be 0-100%)
        completion_rate = (
            (current_appraisals / staff_count * 100) if staff_count > 0 else 0
        )

        # Add calculated fields to department object
        dept.staff_count = staff_count
        dept.appraisal_count = appraisal_count
        dept.current_period_appraisals = current_appraisals
        dept.completion_rate = completion_rate

        department_data.append(dept)

    # Get department performance statistics from StaffAppraisal model
    dept_stats = (
        StaffAppraisal.objects.filter(overall_score__isnull=False)
        .select_related("profile__user__department")
        .values("profile__user__department__name")
        .annotate(
            count=Count("id", distinct=True), avg_score=Avg("overall_score")
        )
    )

    # Calculate overall statistics
    total_departments = len(department_data)
    total_staff = sum(dept.staff_count for dept in department_data)
    total_appraisals = sum(dept.appraisal_count for dept in department_data)
    current_period_appraisals = sum(
        dept.current_period_appraisals for dept in department_data
    )

    # Calculate overall average score
    overall_avg_result = StaffAppraisal.objects.filter(
        overall_score__isnull=False
    ).aggregate(avg_score=Avg("overall_score"))
    overall_avg_score = round(float(overall_avg_result["avg_score"] or 0), 1)

    context = {
        "departments": department_data,
        "dept_stats": dept_stats,
        "total_departments": total_departments,
        "total_staff": total_staff,
        "total_appraisals": total_appraisals,
        "current_period_appraisals": current_period_appraisals,
        "overall_avg_score": overall_avg_score,
        "active_period": active_period,
    }

    # DEBUG: Print counts to verify
    print(f"DEBUG - Total departments: {total_departments}")
    print(f"DEBUG - Total staff: {total_staff}")
    print(
        f"DEBUG - Current period complete appraisals: {current_period_appraisals}"
    )

    return render(request, "hr/department_appraisals.html", context)


@login_required
def hr_manage_attributes(request):
    """HR management of supervisor evaluation criteria"""
    if not request.user.is_hr_staff:
        messages.error(request, "Only HR staff can access this page.")
        return redirect("users:role_based_redirect")

    # Get all supervisor attributes with indicators
    attributes = (
        SupervisorAttribute.objects.all()
        .prefetch_related("indicators")
        .order_by("name")
    )

    # ADD PERIOD DATA
    active_period = SPEPeriod.objects.filter(is_active=True).first()
    all_periods = SPEPeriod.objects.all().order_by("-start_date")

    if request.method == "POST":
        action = request.POST.get("action", "").strip()

        try:
            # CREATE ATTRIBUTE - SIMPLIFIED (no category)
            if action == "create_attribute":
                name = request.POST.get("name").strip()
                description = request.POST.get("description", "").strip()

                if name:
                    # Check for duplicates
                    if SupervisorAttribute.objects.filter(name=name).exists():
                        messages.error(
                            request,
                            f'❌ Supervisor attribute "{name}" already exists.',
                        )
                    else:
                        attribute = SupervisorAttribute.objects.create(
                            name=name,
                            description=description,
                            is_active=True,
                            created_by=request.user,
                        )
                        messages.success(
                            request,
                            f'✅ Supervisor attribute "{name}" created successfully.',
                        )
                else:
                    messages.error(request, "❌ Attribute name is required.")

            # UPDATE ATTRIBUTE - SIMPLIFIED (no category)
            elif action == "update_attribute":
                attribute_id = request.POST.get("attribute_id")
                attribute = get_object_or_404(
                    SupervisorAttribute, id=attribute_id
                )

                new_name = request.POST.get("name").strip()

                # ✅ CHECK FOR DUPLICATES (excluding current attribute)
                if new_name != attribute.name:
                    existing_attribute = (
                        SupervisorAttribute.objects.filter(name=new_name)
                        .exclude(id=attribute_id)
                        .first()
                    )

                    if existing_attribute:
                        messages.error(
                            request,
                            f'❌ Supervisor attribute "{new_name}" already exists.',
                        )
                    else:
                        attribute.name = new_name
                        attribute.description = request.POST.get(
                            "description", ""
                        ).strip()
                        attribute.is_active = (
                            request.POST.get("is_active") == "on"
                        )
                        attribute.save()
                        messages.success(
                            request,
                            f'✅ Supervisor attribute "{attribute.name}" updated successfully.',
                        )
                else:
                    # Same name, just update other fields
                    attribute.description = request.POST.get(
                        "description", ""
                    ).strip()
                    attribute.is_active = request.POST.get("is_active") == "on"
                    attribute.save()
                    messages.success(
                        request,
                        f'✅ Supervisor attribute "{attribute.name}" updated successfully.',
                    )

            # DELETE ATTRIBUTE - ADD THIS MISSING ACTION
            elif action == "delete_attribute":
                attribute_id = request.POST.get("attribute_id")
                print(f"DEBUG: Deleting attribute with ID: {attribute_id}")
                attribute = get_object_or_404(
                    SupervisorAttribute, id=attribute_id
                )
                attribute_name = attribute.name
                attribute.delete()
                messages.warning(
                    request,
                    f'🗑️ Attribute "{attribute_name}" deleted successfully.',
                )

            # CREATE INDICATOR
            elif action == "create_indicator":
                attribute_id = request.POST.get("attribute_id")
                description = request.POST.get("description").strip()

                if description:
                    attribute = get_object_or_404(
                        SupervisorAttribute, id=attribute_id
                    )
                    SupervisorIndicator.objects.create(
                        attribute=attribute,
                        description=description,
                        is_active=True,
                    )
                    messages.success(
                        request,
                        f'✅ Indicator added to "{attribute.name}" successfully.',
                    )
                else:
                    messages.error(
                        request, "❌ Indicator description is required."
                    )

            # UPDATE INDICATOR
            elif action == "update_indicator":
                indicator_id = request.POST.get("indicator_id")
                indicator = get_object_or_404(
                    SupervisorIndicator, id=indicator_id
                )

                indicator.description = request.POST.get("description").strip()
                indicator.is_active = request.POST.get("is_active") == "on"
                indicator.save()

                messages.success(request, "✅ Indicator updated successfully.")

            # DELETE INDICATOR
            elif action == "delete_indicator":
                indicator_id = request.POST.get("indicator_id")
                print(f"DEBUG: Deleting indicator with ID: {indicator_id}")
                indicator = get_object_or_404(
                    SupervisorIndicator, id=indicator_id
                )
                attribute_name = indicator.attribute.name
                indicator.delete()
                messages.warning(
                    request, f'🗑️ Indicator deleted from "{attribute_name}".'
                )

            # BULK INDICATOR CREATION
            elif action == "bulk_add_indicators":
                attribute_id = request.POST.get("attribute_id")
                bulk_indicators = request.POST.get(
                    "bulk_indicators", ""
                ).strip()

                if bulk_indicators:
                    attribute = get_object_or_404(
                        SupervisorAttribute, id=attribute_id
                    )
                    indicators_added = 0

                    for indicator_desc in bulk_indicators.split("\n"):
                        indicator_desc = indicator_desc.strip()
                        if indicator_desc:
                            SupervisorIndicator.objects.create(
                                attribute=attribute,
                                description=indicator_desc,
                                is_active=True,
                            )
                            indicators_added += 1

                    messages.success(
                        request,
                        f'✅ Added {indicators_added} indicators to "{attribute.name}"!',
                    )
                else:
                    messages.error(request, "❌ No indicators provided.")

            # ✅ INTERACTIVE CRITERIA BUILDER - SIMPLIFIED (no category)
            elif action == "save_criteria":
                attribute_name = request.POST.get("attribute_name").strip()

                if attribute_name:
                    # ✅ CHECK FOR EXISTING ATTRIBUTE FIRST
                    existing_attribute = SupervisorAttribute.objects.filter(
                        name=attribute_name
                    ).first()

                    if existing_attribute:
                        messages.error(
                            request,
                            f"❌ Supervisor attribute '{attribute_name}' already exists.",
                        )
                    else:
                        # Create attribute
                        attribute = SupervisorAttribute.objects.create(
                            name=attribute_name,
                            description=request.POST.get(
                                "attribute_description", ""
                            ).strip(),
                            is_active=True,
                            created_by=request.user,
                        )

                        # Create indicators from multiple fields
                        indicators_created = 0
                        indicator_index = 0

                        while True:
                            indicator_field = f"indicator_{indicator_index}"
                            indicator_desc = request.POST.get(
                                indicator_field, ""
                            ).strip()

                            if not indicator_desc:
                                # Check if we have more indicators to process
                                indicator_index += 1
                                next_indicator = request.POST.get(
                                    f"indicator_{indicator_index}", ""
                                ).strip()
                                if not next_indicator:
                                    break  # No more indicators
                                continue

                            # Create the indicator
                            SupervisorIndicator.objects.create(
                                attribute=attribute,
                                description=indicator_desc,
                                is_active=True,
                            )
                            indicators_created += 1
                            indicator_index += 1

                        messages.success(
                            request,
                            f"✅ Created supervisor attribute '{attribute_name}' with {indicators_created} indicators!",
                        )
                else:
                    messages.error(request, "❌ Please enter attribute name")

        except Exception as e:
            messages.error(request, f"⚠️ Error processing request: {str(e)}")

        return redirect("hr:hr_manage_attributes")

    context = {
        "attributes": attributes,
        "active_period": active_period,  # ADDED
        "periods": all_periods,  # ADDED
    }
    return render(request, "hr/hr_manage_attributes.html", context)


@login_required
def hr_view_reports(request):
    """HR view showing ALL staff with their evaluation status - Fixed calculations"""
    if not request.user.is_hr_staff:
        messages.error(request, "Only HR staff can access this page.")
        return redirect("users:role_based_redirect")

    # Get active period
    active_period = SPEPeriod.objects.filter(is_active=True).first()

    # Get ALL staff (teaching, non-teaching, supervisors)
    all_staff = (
        CustomUser.objects.filter(
            role__in=["teaching", "non_teaching", "supervisor"], is_active=True
        )
        .select_related("department")
        .order_by("department__name", "first_name")
    )

    # Filter options
    department_filter = request.GET.get("department")
    role_filter = request.GET.get("role")
    status_filter = request.GET.get("status")

    if department_filter:
        all_staff = all_staff.filter(department__name=department_filter)

    if role_filter:
        all_staff = all_staff.filter(role=role_filter)

    # Get available periods and departments for filters
    periods = SPEPeriod.objects.all().order_by("-start_date")
    departments = Department.objects.all()

    # Enhanced staff data with appraisal status
    staff_data = []
    for staff in all_staff:
        # Initialize variables
        current_appraisal = None
        overall_score = None
        last_activity = None
        pf_number = staff.pf_number if hasattr(staff, "pf_number") else None

        # Try to get StaffAppraisal first (most accurate) - for regular staff
        if staff.role in ["teaching", "non_teaching"]:
            try:
                staff_profile = StaffProfile.objects.get(user=staff)
                current_appraisal = StaffAppraisal.objects.filter(
                    profile=staff_profile, period=active_period
                ).first()

                if current_appraisal and current_appraisal.overall_score:
                    # Use appraisal overall score if available
                    overall_score = float(current_appraisal.overall_score)
                    last_activity = current_appraisal.updated_at

            except StaffProfile.DoesNotExist:
                pass

        # If no appraisal score for regular staff, calculate from components
        if (
            not overall_score
            and staff.role in ["teaching", "non_teaching"]
            and active_period
        ):
            # Get all evaluation components
            targets = PerformanceTarget.objects.filter(
                staff=staff,
                period=active_period,
                performance_rating__isnull=False,
            )

            # Get supervisor evaluations for attributes/indicators
            # Use SpeSupervisorEvaluation (from spe) for staff evaluations
            supervisor_evaluations = SpeSupervisorEvaluation.objects.filter(
                self_assessment__staff=staff,
                self_assessment__period=active_period,
            )

            # Initialize scores
            targets_score = None
            attributes_score = None

            # Calculate targets average (already in percentage)
            if targets.exists():
                targets_avg_result = targets.aggregate(
                    avg=Avg("performance_rating")
                )
                targets_score = (
                    float(targets_avg_result["avg"])
                    if targets_avg_result["avg"]
                    else None
                )

            # Calculate attributes/indicators average from supervisor ratings
            if supervisor_evaluations.exists():
                supervisor_avg_result = supervisor_evaluations.aggregate(
                    avg=Avg("supervisor_rating")
                )
                supervisor_avg = (
                    float(supervisor_avg_result["avg"])
                    if supervisor_avg_result["avg"]
                    else None
                )
                if supervisor_avg:
                    # Convert 1-5 scale to percentage
                    attributes_score = (supervisor_avg / 5) * 100

            # Calculate overall score as average of targets and attributes scores
            # ONLY if both have supervisor ratings
            if targets_score is not None and attributes_score is not None:
                # Both targets and attributes have supervisor ratings
                overall_score = (targets_score + attributes_score) / 2
            elif targets_score is not None:
                # Only targets have supervisor ratings
                overall_score = targets_score
            elif attributes_score is not None:
                # Only attributes have supervisor ratings (targets not rated yet)
                overall_score = attributes_score

            # Update last activity
            activities = []
            if targets.exists():
                activities.append(targets.latest("updated_at").updated_at)
            if supervisor_evaluations.exists():
                activities.append(
                    supervisor_evaluations.latest("submitted_at").submitted_at
                )

            if activities:
                last_activity = max(activities)

        elif staff.role == "supervisor" and active_period:
            # SUPERVISORS: Get SupervisorAppraisal for the most accurate score
            supervisor_appraisal = SupervisorAppraisal.objects.filter(
                supervisor=staff, period=active_period
            ).first()

            if supervisor_appraisal and supervisor_appraisal.overall_score:
                # Use appraisal overall score if available
                overall_score = float(supervisor_appraisal.overall_score)
                last_activity = supervisor_appraisal.evaluated_at
            else:
                # Calculate from components if no appraisal exists
                # Get VC evaluations (from HrSupervisorEvaluation model in hr app)
                vc_evaluations = HrSupervisorEvaluation.objects.filter(
                    supervisor=staff, period=active_period
                )

                # Get supervisor performance targets
                supervisor_targets = (
                    SupervisorPerformanceTarget.objects.filter(
                        supervisor=staff, period=active_period
                    )
                )

                # Initialize scores
                criteria_score = None
                targets_score = None

                # Calculate criteria score from VC evaluations (1-5 scale converted to %)
                if vc_evaluations.exists():
                    criteria_avg_result = vc_evaluations.aggregate(
                        avg=Avg("rating")
                    )
                    criteria_avg = (
                        float(criteria_avg_result["avg"])
                        if criteria_avg_result["avg"]
                        else 0
                    )
                    criteria_score = round(
                        (criteria_avg / 5) * 100, 2
                    )  # Convert to percentage

                # Calculate targets score from SupervisorPerformanceTarget (already in percentage)
                rated_targets = supervisor_targets.filter(
                    performance_rating__isnull=False
                )
                if rated_targets.exists():
                    targets_avg_result = rated_targets.aggregate(
                        avg=Avg("performance_rating")
                    )
                    if targets_avg_result["avg"]:
                        targets_avg = float(targets_avg_result["avg"])
                        # Convert 1-5 scale to percentage for supervisor targets
                        targets_score = round((targets_avg / 5) * 100, 2)

                # Calculate overall score: (criteria_score + targets_score) / 2
                if criteria_score is not None and targets_score is not None:
                    # Both criteria and targets have VC ratings
                    overall_score = round(
                        (criteria_score + targets_score) / 2, 2
                    )
                elif criteria_score is not None:
                    # Only criteria have VC ratings
                    overall_score = criteria_score
                elif targets_score is not None:
                    # Only targets have VC ratings
                    overall_score = targets_score

                # Update last activity
                activities = []
                if vc_evaluations.exists():
                    latest_vc_eval = vc_evaluations.order_by(
                        "-submitted_at"
                    ).first()
                    if latest_vc_eval:
                        activities.append(latest_vc_eval.submitted_at)

                if supervisor_targets.exists():
                    latest_target = supervisor_targets.order_by(
                        "-updated_at"
                    ).first()
                    if latest_target:
                        activities.append(latest_target.updated_at)

                if activities:
                    last_activity = max(activities)

        # Get performance targets status
        targets_status = "no_targets"
        targets_avg_score = None

        if staff.role == "supervisor":
            targets = (
                SupervisorPerformanceTarget.objects.filter(
                    supervisor=staff, period=active_period
                )
                if active_period
                else SupervisorPerformanceTarget.objects.none()
            )
        else:
            targets = (
                PerformanceTarget.objects.filter(
                    staff=staff, period=active_period
                )
                if active_period
                else PerformanceTarget.objects.none()
            )

        if targets.exists():
            approved_targets = targets.filter(status="approved").count()
            pending_targets = targets.filter(status="pending").count()
            if approved_targets > 0:
                targets_status = "approved"
            elif pending_targets > 0:
                targets_status = "pending"
            else:
                targets_status = "draft"

            # Calculate average target performance rating
            rated_targets = targets.filter(performance_rating__isnull=False)
            if rated_targets.exists():
                targets_avg_result = rated_targets.aggregate(
                    avg=Avg("performance_rating")
                )
                targets_avg_score = (
                    float(targets_avg_result["avg"])
                    if targets_avg_result["avg"]
                    else None
                )

        # Determine overall evaluation status
        evaluation_status = "not_started"

        if staff.role in ["teaching", "non_teaching"]:
            if current_appraisal:
                evaluation_status = current_appraisal.status
            elif overall_score is not None:
                # Has some evaluation scores
                if targets_status == "approved":
                    evaluation_status = "submitted"
                else:
                    evaluation_status = "in_progress"
            elif targets_status != "no_targets":
                # Has targets but no scores yet
                evaluation_status = "draft"

        elif staff.role == "supervisor":
            # Check for SupervisorAppraisal
            supervisor_appraisal = (
                SupervisorAppraisal.objects.filter(
                    supervisor=staff, period=active_period
                ).first()
                if active_period
                else None
            )

            if supervisor_appraisal:
                evaluation_status = supervisor_appraisal.status
            elif overall_score is not None:
                # Has evaluation scores
                evaluation_status = "completed"
            elif targets_status == "approved":
                # Has approved targets but no VC evaluation yet
                evaluation_status = "submitted"
            elif targets_status != "no_targets":
                # Has targets but not approved
                evaluation_status = "draft"

        staff_data.append(
            {
                "staff": staff,
                "pf_number": pf_number,
                "current_appraisal": current_appraisal,
                "supervisor_appraisal": (
                    supervisor_appraisal
                    if staff.role == "supervisor"
                    else None
                ),
                "targets_status": targets_status,
                "targets_avg_score": targets_avg_score,
                "evaluation_status": evaluation_status,
                "overall_score": overall_score,
                "last_activity": last_activity,
                "department": staff.department,
            }
        )

    # Apply status filter after building staff data
    if status_filter:
        staff_data = [
            data
            for data in staff_data
            if data["evaluation_status"] == status_filter
        ]

    # Enhanced Statistics
    total_staff = len(staff_data)
    teaching_count = len(
        [data for data in staff_data if data["staff"].role == "teaching"]
    )
    non_teaching_count = len(
        [data for data in staff_data if data["staff"].role == "non_teaching"]
    )
    supervisor_count = len(
        [data for data in staff_data if data["staff"].role == "supervisor"]
    )

    # Calculate average scores
    staff_with_scores = [
        data for data in staff_data if data["overall_score"] is not None
    ]
    if staff_with_scores:
        total_score = sum(
            float(data["overall_score"]) for data in staff_with_scores
        )
        avg_overall_score = round(total_score / len(staff_with_scores), 2)
    else:
        avg_overall_score = 0

    # Status distribution
    status_counts = {
        "not_started": len(
            [
                data
                for data in staff_data
                if data["evaluation_status"] == "not_started"
            ]
        ),
        "draft": len(
            [
                data
                for data in staff_data
                if data["evaluation_status"] == "draft"
            ]
        ),
        "in_progress": len(
            [
                data
                for data in staff_data
                if data["evaluation_status"] == "in_progress"
            ]
        ),
        "submitted": len(
            [
                data
                for data in staff_data
                if data["evaluation_status"] == "submitted"
            ]
        ),
        "reviewed": len(
            [
                data
                for data in staff_data
                if data["evaluation_status"] == "reviewed"
            ]
        ),
        "completed": len(
            [
                data
                for data in staff_data
                if data["evaluation_status"] == "completed"
            ]
        ),
    }

    # Component completion stats
    staff_with_targets = len(
        [data for data in staff_data if data["targets_status"] != "no_targets"]
    )
    staff_with_scores_count = len(staff_with_scores)

    paginator = Paginator(staff_data, 20)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "total_staff": total_staff,
        "teaching_count": teaching_count,
        "non_teaching_count": non_teaching_count,
        "supervisor_count": supervisor_count,
        "status_counts": status_counts,
        "avg_overall_score": avg_overall_score,
        "staff_with_targets": staff_with_targets,
        "staff_with_scores_count": staff_with_scores_count,
        "periods": periods,
        "departments": departments,
        "department_filter": department_filter,
        "role_filter": role_filter,
        "status_filter": status_filter,
        "active_period": active_period,
    }

    return render(request, "hr/hr_view_reports.html", context)


@login_required
def vc_supervisor_management(request):
    """VC view to manage all supervisors with enhanced data using services"""
    if not request.user.is_vc_staff:
        messages.error(request, "Only Vice Chancellor can access this page.")
        return redirect("users:role_based_redirect")

    # Check if VCSupervisorService is available
    if VCSupervisorService is None:
        messages.error(
            request, "Supervisor management service is not available."
        )
        return redirect("users:role_based_redirect")

    # Get filters from request
    filters = {
        "department": request.GET.get("department"),
        "search": request.GET.get("search"),
        "status": request.GET.get("status", "active"),
    }

    # Get all supervisor data using service
    supervisor_data = VCSupervisorService.get_supervisors_with_stats(filters)

    # Ensure total_stats and avg_rating always exist
    if "total_stats" not in supervisor_data:
        supervisor_data["total_stats"] = {
            "pending_targets": 0,
            "approved_without_rating": 0,
            "rated_targets": 0,
        }

    if "avg_rating" not in supervisor_data:
        supervisor_data["avg_rating"] = None

    paginator = Paginator(supervisor_data["supervisors"], 25)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "departments": supervisor_data["departments"],
        "department_filter": filters["department"],
        "search_query": filters["search"],
        "status_filter": filters["status"],
        "current_period": supervisor_data["current_period"],
        "total_stats": supervisor_data["total_stats"],
        "avg_rating": supervisor_data["avg_rating"],
    }
    return render(request, "vc/vc_supervisor_management.html", context)


@login_required
@user_passes_test(is_hr_user)
def download_evaluation_pdf(request, appraisal_id):
    """Generate proper PDF report for staff evaluation - REQUIRES BOTH TARGETS AND SELF-ASSESSMENTS"""
    try:
        appraisal = get_object_or_404(
            StaffAppraisal.objects.select_related(
                "profile__user", "period", "profile__user__department"
            ),
            id=appraisal_id,
        )

        staff_user = appraisal.profile.user
        period = appraisal.period

        # Get all evaluation data
        performance_targets = PerformanceTarget.objects.filter(
            staff=staff_user, period=period
        )

        self_assessments = SelfAssessment.objects.filter(
            staff=staff_user, period=period
        )

        supervisor_evaluations = SpeSupervisorEvaluation.objects.filter(
            supervisor__department=staff_user.department, period=period
        )

        if staff_user.role == "teaching":
            formal_evaluations = TeachingStaffEvaluation.objects.filter(
                staff=staff_user, period=period
            )
        else:
            formal_evaluations = NonTeachingStaffEvaluation.objects.filter(
                staff=staff_user, period=period
            )

        # Check if staff has BOTH targets AND self-assessments
        has_both_evaluations = (
            performance_targets.exists() and self_assessments.exists()
        )
        if not has_both_evaluations:
            missing_items = []
            if not performance_targets.exists():
                missing_items.append("performance targets")
            if not self_assessments.exists():
                missing_items.append("self-assessments")

            messages.error(
                request,
                f"Cannot generate report: Missing {', '.join(missing_items)} for {staff_user.get_full_name()}",
            )
            return redirect(
                "hr:hr_staff_evaluation_detail", appraisal_id=appraisal_id
            )

        # Create PDF buffer
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            topMargin=0.5 * inch,
            bottomMargin=0.5 * inch,
            leftMargin=0.5 * inch,
            rightMargin=0.5 * inch,
        )
        story = []
        styles = getSampleStyleSheet()

        # Title - Smaller and cleaner
        title_style = ParagraphStyle(
            "CustomTitle",
            parent=styles["Heading1"],
            fontSize=14,
            spaceAfter=20,
            alignment=1,
            textColor=colors.HexColor("#2c5aa0"),
        )
        title = Paragraph(f"STAFF EVALUATION REPORT", title_style)
        story.append(title)

        # Subtitle
        subtitle_style = ParagraphStyle(
            "Subtitle",
            parent=styles["Normal"],
            fontSize=12,
            spaceAfter=20,
            alignment=1,
            textColor=colors.HexColor("#666666"),
        )
        subtitle = Paragraph(
            f"{staff_user.get_full_name()} - {period.name}", subtitle_style
        )
        story.append(subtitle)
        story.append(Spacer(1, 0.2 * inch))

        # Basic Information - SIMPLIFIED TABLE
        story.append(Paragraph("Basic Information", styles["Heading2"]))

        info_data = [
            ["Staff Name:", staff_user.get_full_name()],
            [
                "Department:",
                staff_user.department.name if staff_user.department else "N/A",
            ],
            ["Role:", staff_user.get_role_display()],
            ["Period:", period.name],
            [
                "Overall Score:",
                (
                    f"{appraisal.overall_score}%"
                    if appraisal.overall_score
                    else "Not Scored"
                ),
            ],
        ]

        info_table = Table(info_data, colWidths=[1.5 * inch, 3 * inch])
        info_table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(info_table)
        story.append(Spacer(1, 0.3 * inch))

        # Performance Targets Section - SIMPLIFIED
        if performance_targets.exists():
            story.append(Paragraph("Performance Targets", styles["Heading2"]))

            target_data = [["#", "Description", "Status", "Rating"]]
            for target in performance_targets:
                target_data.append(
                    [
                        str(target.target_number),
                        Paragraph(
                            (
                                target.description[:40] + "..."
                                if len(target.description) > 40
                                else target.description
                            ),
                            styles["Normal"],
                        ),
                        target.get_status_display(),
                        (
                            f"{target.performance_rating}%"
                            if target.performance_rating
                            else "N/A"
                        ),
                    ]
                )

            target_table = Table(
                target_data,
                colWidths=[0.4 * inch, 2.5 * inch, 1 * inch, 0.8 * inch],
            )
            target_table.setStyle(
                TableStyle(
                    [
                        (
                            "BACKGROUND",
                            (0, 0),
                            (-1, 0),
                            colors.HexColor("#2c5aa0"),
                        ),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                        (
                            "ALIGN",
                            (3, 1),
                            (3, -1),
                            "CENTER",
                        ),  # Center align ratings
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, -1), 8),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ]
                )
            )
            story.append(target_table)
            story.append(Spacer(1, 0.2 * inch))

        # Self-Assessments Section - SIMPLIFIED
        if self_assessments.exists():
            story.append(Paragraph("Self-Assessments", styles["Heading2"]))

            self_data = [["Attribute", "Rating", "Indicator"]]
            for assessment in self_assessments:
                self_data.append(
                    [
                        assessment.attribute.name,
                        f"{assessment.self_rating}/5",
                        Paragraph(
                            (
                                assessment.indicator.description[:50] + "..."
                                if len(assessment.indicator.description) > 50
                                else assessment.indicator.description
                            ),
                            styles["Normal"],
                        ),
                    ]
                )

            self_table = Table(
                self_data, colWidths=[1.5 * inch, 0.6 * inch, 2.6 * inch]
            )
            self_table.setStyle(
                TableStyle(
                    [
                        (
                            "BACKGROUND",
                            (0, 0),
                            (-1, 0),
                            colors.HexColor("#28a745"),
                        ),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                        (
                            "ALIGN",
                            (1, 1),
                            (1, -1),
                            "CENTER",
                        ),  # Center align ratings
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, -1), 8),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ]
                )
            )
            story.append(self_table)
            story.append(Spacer(1, 0.2 * inch))

        # Supervisor Evaluations Section - SIMPLIFIED
        if supervisor_evaluations.exists():
            story.append(
                Paragraph("Supervisor Evaluations", styles["Heading2"])
            )

            supervisor_data = [["Attribute", "Rating"]]
            for evaluation in supervisor_evaluations:
                supervisor_data.append(
                    [evaluation.attribute.name, f"{evaluation.rating}/5"]
                )

            supervisor_table = Table(
                supervisor_data, colWidths=[3 * inch, 0.8 * inch]
            )
            supervisor_table.setStyle(
                TableStyle(
                    [
                        (
                            "BACKGROUND",
                            (0, 0),
                            (-1, 0),
                            colors.HexColor("#dc3545"),
                        ),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                        (
                            "ALIGN",
                            (1, 1),
                            (1, -1),
                            "CENTER",
                        ),  # Center align ratings
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, -1), 8),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ]
                )
            )
            story.append(supervisor_table)
            story.append(Spacer(1, 0.2 * inch))

        # Summary Statistics - CLEANER
        story.append(Paragraph("Summary", styles["Heading2"]))

        summary_data = [
            ["Evaluation Type", "Count", "Avg Rating"],
            [
                "Targets",
                str(performance_targets.count()),
                f"{performance_targets.aggregate(avg=Avg('performance_rating'))['avg'] or 0:.1f}%",
            ],
            [
                "Self-Assessments",
                str(self_assessments.count()),
                f"{self_assessments.aggregate(avg=Avg('self_rating'))['avg'] or 0:.1f}/5",
            ],
            [
                "Supervisor Evals",
                str(supervisor_evaluations.count()),
                f"{supervisor_evaluations.aggregate(avg=Avg('rating'))['avg'] or 0:.1f}/5",
            ],
        ]

        summary_table = Table(
            summary_data, colWidths=[2 * inch, 1 * inch, 1 * inch]
        )
        summary_table.setStyle(
            TableStyle(
                [
                    (
                        "BACKGROUND",
                        (0, 0),
                        (-1, 0),
                        colors.HexColor("#6c757d"),
                    ),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    (
                        "ALIGN",
                        (1, 1),
                        (2, -1),
                        "CENTER",
                    ),  # Center align numbers
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ]
            )
        )
        story.append(summary_table)

        # Footer
        story.append(Spacer(1, 0.3 * inch))
        footer_style = ParagraphStyle(
            "Footer",
            parent=styles["Normal"],
            fontSize=8,
            alignment=1,
            textColor=colors.HexColor("#666666"),
        )
        footer = Paragraph(
            f"Generated on {timezone.now().strftime('%Y-%m-%d at %H:%M')} - KyU HR System",
            footer_style,
        )
        story.append(footer)

        # Build PDF
        doc.build(story)

        # Get PDF value from buffer
        pdf = buffer.getvalue()
        buffer.close()

        # Create response
        response = HttpResponse(content_type="application/pdf")
        filename = f"evaluation_{staff_user.get_full_name().replace(' ', '_')}_{period.name}.pdf"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response.write(pdf)

        return response

    except Exception as e:
        messages.error(request, f"Error generating PDF: {str(e)}")
        import traceback
        traceback.print_exc()
        return redirect(
            "hr:hr_staff_evaluation_detail", appraisal_id=appraisal_id
        )


@login_required
@user_passes_test(is_hr_user)
def hr_staff_evaluation_detail(request, appraisal_id):
    """HR view for detailed staff evaluation report - handles ALL staff types"""
    try:
        # Get the existing StaffAppraisal
        appraisal = get_object_or_404(
            StaffAppraisal.objects.select_related(
                "profile__user", "period", "profile__user__department"
            ),
            id=appraisal_id,
        )

        staff_user = appraisal.profile.user
        period = appraisal.period
        staff_role = staff_user.role

        # ============================================
        # HANDLE DIFFERENT STAFF TYPES
        # ============================================

        matched_evaluations = []
        indicator_scores_pct = []  # Store (Self+Supervisor)/2 converted to %
        performance_targets = None
        supervisor_targets = None
        supervisor_ratings = None
        self_assessments = None
        supervisor_evaluations = None

        if staff_role in ["teaching", "non_teaching"]:
            # ============================================
            # REGULAR STAFF (Teaching & Non-Teaching)
            # ============================================

            # Get performance targets
            performance_targets = (
                PerformanceTarget.objects.filter(
                    staff=staff_user, period=period
                )
                .select_related("approved_by", "evaluated_by")
                .order_by("target_number")
            )

            # Get self-assessments
            self_assessments = SelfAssessment.objects.filter(
                staff=staff_user, period=period
            ).select_related("attribute", "indicator")

            # Check if staff has BOTH targets AND self-assessments
            has_both_evaluations = (
                performance_targets.exists() and self_assessments.exists()
            )

            if not has_both_evaluations:
                missing_items = []
                if not performance_targets.exists():
                    missing_items.append("performance targets")
                if not self_assessments.exists():
                    missing_items.append("self-assessments")

                messages.warning(
                    request,
                    f"Cannot view report: {staff_user.get_full_name()} is missing {', '.join(missing_items)} for this period.",
                )
                return redirect("hr:hr_view_reports")

            # Get SupervisorEvaluation for these self-assessments
            if self_assessments.exists():
                self_assessment_ids = list(
                    self_assessments.values_list("id", flat=True)
                )
                supervisor_evaluations = (
                    SpeSupervisorEvaluation.objects.filter(
                        self_assessment__in=self_assessment_ids
                    ).select_related(
                        "self_assessment",
                        "self_assessment__attribute",
                        "self_assessment__indicator",
                        "supervisor",
                    )
                )

                # Create a dictionary for easy lookup
                supervisor_eval_dict = {}
                for sup_eval in supervisor_evaluations:
                    supervisor_eval_dict[sup_eval.self_assessment_id] = (
                        sup_eval
                    )

                # Calculate scores for each indicator
                for self_assessment in self_assessments:
                    supervisor_evaluation = supervisor_eval_dict.get(
                        self_assessment.id
                    )

                    # Get self-rating
                    self_rating = (
                        float(self_assessment.self_rating)
                        if self_assessment.self_rating
                        else 0
                    )

                    # Get supervisor rating
                    supervisor_rating = 0
                    if (
                        supervisor_evaluation
                        and supervisor_evaluation.supervisor_rating
                    ):
                        supervisor_rating = float(
                            supervisor_evaluation.supervisor_rating
                        )

                    # Calculate indicator score: (Self Rating + Supervisor Rating) ÷ 2
                    indicator_score_1_5 = 0
                    if self_rating > 0 and supervisor_rating > 0:
                        # Both ratings exist
                        indicator_score_1_5 = (
                            self_rating + supervisor_rating
                        ) / 2
                    elif self_rating > 0:
                        # Only self-rating exists
                        indicator_score_1_5 = self_rating
                    elif supervisor_rating > 0:
                        # Only supervisor rating exists
                        indicator_score_1_5 = supervisor_rating

                    # Convert to percentage
                    indicator_pct = (
                        round((indicator_score_1_5 / 5) * 100, 2)
                        if indicator_score_1_5 > 0
                        else 0
                    )

                    if indicator_pct > 0:
                        indicator_scores_pct.append(indicator_pct)

                    # For template display
                    self_rating_pct = (
                        round((self_rating / 5) * 100, 2)
                        if self_rating > 0
                        else 0
                    )
                    supervisor_rating_pct = (
                        round((supervisor_rating / 5) * 100, 2)
                        if supervisor_rating > 0
                        else 0
                    )

                    matched_evaluations.append(
                        {
                            "self_assessment": self_assessment,
                            "supervisor_evaluation": supervisor_evaluation,
                            "self_rating": self_rating,
                            "self_rating_pct": self_rating_pct,
                            "supervisor_rating": supervisor_rating,
                            "supervisor_rating_pct": supervisor_rating_pct,
                            "indicator_score_1_5": round(
                                indicator_score_1_5, 1
                            ),
                            "indicator_pct": indicator_pct,
                            "evaluation_type": "staff",
                        }
                    )

        elif staff_role == "supervisor":
            # ============================================
            # SUPERVISOR STAFF
            # ============================================

            # Get supervisor performance targets
            supervisor_targets = (
                SupervisorPerformanceTarget.objects.filter(
                    supervisor=staff_user, period=period
                )
                .select_related("approved_by", "rated_by")
                .order_by("target_number")
            )

            # Get supervisor ratings (VC ratings) - using SupervisorRating from spe.models
            supervisor_ratings = SupervisorRating.objects.filter(
                supervisor=staff_user, period=period
            ).select_related("attribute", "indicator")

            # Check if supervisor has BOTH targets AND ratings
            has_both_evaluations = (
                supervisor_targets.exists() and supervisor_ratings.exists()
            )

            if not has_both_evaluations:
                missing_items = []
                if not supervisor_targets.exists():
                    missing_items.append("performance targets")
                if not supervisor_ratings.exists():
                    missing_items.append("supervisor ratings")

                messages.warning(
                    request,
                    f"Cannot view report: {staff_user.get_full_name()} is missing {', '.join(missing_items)} for this period.",
                )
                return redirect("hr:hr_view_reports")

            # For supervisors, we use SupervisorRating directly
            # Create a dictionary to organize ratings by attribute
            ratings_by_attribute = {}
            for rating in supervisor_ratings:
                attr_id = rating.attribute_id
                if attr_id not in ratings_by_attribute:
                    ratings_by_attribute[attr_id] = {
                        "attribute": rating.attribute,
                        "ratings": [],
                    }
                ratings_by_attribute[attr_id]["ratings"].append(rating)

            # Calculate scores for supervisor indicators
            for attr_id, attr_data in ratings_by_attribute.items():
                attribute = attr_data["attribute"]
                ratings = attr_data["ratings"]

                # Get average rating for this attribute
                ratings_list = [float(r.rating) for r in ratings]
                if ratings_list:
                    avg_rating = sum(ratings_list) / len(ratings_list)

                    # Convert to percentage
                    indicator_pct = round((avg_rating / 5) * 100, 2)
                    indicator_scores_pct.append(indicator_pct)

                    # For template display
                    matched_evaluations.append(
                        {
                            "attribute": attribute,
                            "ratings": ratings,
                            "avg_rating": round(avg_rating, 1),
                            "indicator_pct": indicator_pct,
                            "evaluation_type": "supervisor",
                        }
                    )

        # ============================================
        # CALCULATE OVERALL SCORES
        # ============================================

        # For REGULAR STAFF: Calculate targets average
        targets_avg_score = 0
        if staff_role in ["teaching", "non_teaching"] and performance_targets:
            rated_targets = performance_targets.filter(
                performance_rating__isnull=False
            )
            if rated_targets.exists():
                targets_avg_result = rated_targets.aggregate(
                    avg=Avg("performance_rating")
                )
                if targets_avg_result["avg"]:
                    targets_avg_score = float(
                        round(targets_avg_result["avg"], 2)
                    )

        # For SUPERVISORS: Calculate targets average (SupervisorPerformanceTarget)
        elif staff_role == "supervisor" and supervisor_targets:
            rated_targets = supervisor_targets.filter(
                performance_rating__isnull=False
            )
            if rated_targets.exists():
                # Supervisor targets use 1-5 scale, convert to percentage
                targets_avg_result = rated_targets.aggregate(
                    avg=Avg("performance_rating")
                )
                if targets_avg_result["avg"]:
                    targets_avg_score = round(
                        (float(targets_avg_result["avg"]) / 5) * 100, 2
                    )

        # Calculate indicators average score
        indicators_avg_score = 0
        if indicator_scores_pct:
            indicators_avg_score = round(
                sum(indicator_scores_pct) / len(indicator_scores_pct), 2
            )

        # Calculate final overall score
        overall_score = None

        if staff_role in ["teaching", "non_teaching"]:
            # Regular staff: (Targets Average + Indicators Score) ÷ 2
            if targets_avg_score > 0 and indicators_avg_score > 0:
                overall_score = round(
                    (targets_avg_score + indicators_avg_score) / 2, 2
                )
            elif targets_avg_score > 0:
                overall_score = targets_avg_score
            elif indicators_avg_score > 0:
                overall_score = indicators_avg_score

        elif staff_role == "supervisor":
            # Supervisors: (Targets Average + Indicators Score) ÷ 2 (same formula)
            if targets_avg_score > 0 and indicators_avg_score > 0:
                overall_score = round(
                    (targets_avg_score + indicators_avg_score) / 2, 2
                )
            elif targets_avg_score > 0:
                overall_score = targets_avg_score
            elif indicators_avg_score > 0:
                overall_score = indicators_avg_score

        # ============================================
        # UPDATE STAFF APPRAISAL
        # ============================================

        if overall_score is not None:
            # Determine status based on staff type
            has_supervisor_ratings = False
            has_rated_targets = False

            if staff_role in ["teaching", "non_teaching"]:
                has_supervisor_ratings = (
                    supervisor_evaluations.exists()
                    if supervisor_evaluations
                    else False
                )
                has_rated_targets = (
                    performance_targets.filter(
                        performance_rating__isnull=False
                    ).exists()
                    if performance_targets
                    else False
                )

            elif staff_role == "supervisor":
                has_supervisor_ratings = (
                    supervisor_ratings.exists()
                    if supervisor_ratings
                    else False
                )
                has_rated_targets = (
                    supervisor_targets.filter(
                        performance_rating__isnull=False
                    ).exists()
                    if supervisor_targets
                    else False
                )

            if has_supervisor_ratings and has_rated_targets:
                status = "reviewed"
                messages.success(
                    request,
                    f"✅ Appraisal updated: Overall score = {overall_score}%",
                )
            else:
                status = "in_progress"
                message = f"⚠️ Appraisal in progress: Current score = {overall_score}%"
                if not has_supervisor_ratings:
                    message += " (Awaiting supervisor/VC ratings)"
                if not has_rated_targets:
                    message += " (Awaiting target evaluations)"
                messages.info(request, message)

            # Update the StaffAppraisal
            appraisal.overall_score = overall_score
            appraisal.status = status
            if status == "reviewed":
                appraisal.reviewed_by = request.user
                appraisal.reviewed_at = timezone.now()
            appraisal.save()

        # ============================================
        # CALCULATE ADDITIONAL STATISTICS
        # ============================================

        # For REGULAR STAFF: Self-assessments and supervisor evaluations averages
        self_assessments_avg = 0
        supervisor_evaluations_avg = 0

        if staff_role in ["teaching", "non_teaching"]:
            if self_assessments and self_assessments.exists():
                self_avg_result = self_assessments.aggregate(
                    avg=Avg("self_rating")
                )
                if self_avg_result["avg"]:
                    self_assessments_avg = float(
                        round(self_avg_result["avg"], 1)
                    )

            if supervisor_evaluations and supervisor_evaluations.exists():
                sup_avg_result = supervisor_evaluations.aggregate(
                    avg=Avg("supervisor_rating")
                )
                if sup_avg_result["avg"]:
                    supervisor_evaluations_avg = float(
                        round(sup_avg_result["avg"], 1)
                    )

        # For SUPERVISORS: Calculate supervisor ratings average
        elif staff_role == "supervisor" and supervisor_ratings:
            sup_avg_result = supervisor_ratings.aggregate(avg=Avg("rating"))
            if sup_avg_result["avg"]:
                supervisor_evaluations_avg = float(
                    round(sup_avg_result["avg"], 1)
                )

        # Supervisor indicators average score (percentage)
        supervisor_indicators_avg_score = (
            round((supervisor_evaluations_avg / 5) * 100, 2)
            if supervisor_evaluations_avg > 0
            else 0
        )

        # Additional statistics
        rated_targets_count = 0
        rated_indicators_count = len(indicator_scores_pct)
        completion_percentage = 0
        total_indicators_count = 0

        if staff_role in ["teaching", "non_teaching"]:
            if performance_targets:
                rated_targets_count = performance_targets.filter(
                    performance_rating__isnull=False
                ).count()
            if self_assessments:
                total_indicators_count = self_assessments.count()

        elif staff_role == "supervisor":
            if supervisor_targets:
                rated_targets_count = supervisor_targets.filter(
                    performance_rating__isnull=False
                ).count()
            if supervisor_ratings:
                total_indicators_count = supervisor_ratings.count()

        if total_indicators_count > 0:
            completion_percentage = round(
                (rated_indicators_count / total_indicators_count) * 100, 1
            )

        # DEBUG: Print for verification
        print(f"=== DEBUG CALCULATIONS ===")
        print(f"Staff: {staff_user.get_full_name()} ({staff_role})")
        print(f"Targets avg score: {targets_avg_score}%")
        print(f"Indicators avg score: {indicators_avg_score}%")
        print(f"Overall score: {overall_score}%")
        print(
            f"Formula: ({targets_avg_score} + {indicators_avg_score}) / 2 = {((targets_avg_score + indicators_avg_score) / 2) if targets_avg_score > 0 and indicators_avg_score > 0 else 'N/A'}"
        )
        print(f"=== END DEBUG ===")

        # Build context based on staff type
        context = {
            "appraisal": appraisal,
            "staff_role": staff_role,
            # MAIN SCORES
            "targets_avg_score": targets_avg_score,
            "indicators_avg_score": indicators_avg_score,
            "calculated_overall_score": overall_score,
            # AVERAGE RATINGS
            "self_assessments_avg": self_assessments_avg,
            "supervisor_evaluations_avg": supervisor_evaluations_avg,
            "supervisor_indicators_avg_score": supervisor_indicators_avg_score,
            # COUNTS
            "rated_targets_count": rated_targets_count,
            "rated_indicators_count": rated_indicators_count,
            "total_indicators_count": total_indicators_count,
            "completion_percentage": completion_percentage,
            "page_title": f"Evaluation - {staff_user.get_full_name()}",
        }

        # Add type-specific data
        if staff_role in ["teaching", "non_teaching"]:
            context.update(
                {
                    "performance_targets": performance_targets,
                    "self_assessments": self_assessments,
                    "matched_evaluations": matched_evaluations,
                    "has_both_evaluations": has_both_evaluations,
                }
            )
        elif staff_role == "supervisor":
            context.update(
                {
                    "supervisor_targets": supervisor_targets,
                    "supervisor_ratings": supervisor_ratings,
                    "matched_evaluations": matched_evaluations,
                    "has_both_evaluations": has_both_evaluations,
                }
            )

        return render(request, "hr/hr_staff_evaluation_detail.html", context)

    except Exception as e:
        messages.error(request, f"Error loading evaluation: {str(e)}")
        import traceback
        traceback.print_exc()
        return redirect("hr:hr_view_reports")


@login_required
def hr_performance_analytics(request):
    """HR Performance Analytics Dashboard"""
    if not request.user.is_hr_staff:
        messages.error(request, "Only HR staff can access this page.")
        return redirect("users:role_based_redirect")

    try:
        # Get periods for filter
        periods = SPEPeriod.objects.all().order_by("-start_date")

        # Get filter parameters
        period_id = request.GET.get("period")
        department_filter = request.GET.get("department")

        # Base querysets
        staff_appraisals = StaffAppraisal.objects.select_related(
            "profile__user", "period", "profile__user__department"
        )

        performance_targets = PerformanceTarget.objects.select_related(
            "staff", "period"
        )

        # Apply filters
        if period_id:
            staff_appraisals = staff_appraisals.filter(period_id=period_id)
            performance_targets = performance_targets.filter(
                period_id=period_id
            )

        if department_filter:
            staff_appraisals = staff_appraisals.filter(
                profile__user__department__name=department_filter
            )

        # Overall Performance Statistics
        performance_stats = staff_appraisals.filter(
            overall_score__isnull=False
        ).aggregate(
            avg_score=Avg("overall_score"),
            max_score=Max("overall_score"),
            min_score=Min("overall_score"),
            total_count=Count("id"),
        )

        # Status Distribution
        status_distribution = (
            staff_appraisals.values("status")
            .annotate(count=Count("id"))
            .order_by("status")
        )

        # Department Performance
        department_performance = (
            staff_appraisals.filter(overall_score__isnull=False)
            .values("profile__user__department__name")
            .annotate(
                avg_score=Avg("overall_score"),
                staff_count=Count("profile__user", distinct=True),
                appraisal_count=Count("id"),
            )
            .order_by("-avg_score")
        )

        # Performance Targets Statistics
        target_stats = performance_targets.aggregate(
            total_targets=Count("id"),
            approved_targets=Count("id", filter=Q(status="approved")),
            evaluated_targets=Count("id", filter=Q(status="evaluated")),
            avg_rating=Avg("performance_rating"),
        )

        # Target Status Distribution
        target_status_distribution = (
            performance_targets.values("status")
            .annotate(count=Count("id"))
            .order_by("status")
        )

        # Score Distribution (for charts)
        score_distribution = (
            staff_appraisals.filter(overall_score__isnull=False)
            .extra(
                {
                    "score_range": "CASE \
                WHEN overall_score >= 90 THEN '90-100' \
                WHEN overall_score >= 80 THEN '80-89' \
                WHEN overall_score >= 70 THEN '70-79' \
                WHEN overall_score >= 60 THEN '60-69' \
                ELSE 'Below 60' END"
                }
            )
            .values("score_range")
            .annotate(count=Count("id"))
            .order_by("score_range")
        )

        # Monthly Performance Trend (if you have date data)
        monthly_trend = (
            staff_appraisals.filter(overall_score__isnull=False)
            .extra(
                {
                    "month": "EXTRACT(month FROM updated_at)",
                    "year": "EXTRACT(year FROM updated_at)",
                }
            )
            .values("year", "month")
            .annotate(avg_score=Avg("overall_score"), count=Count("id"))
            .order_by("year", "month")[:12]
        )  # Last 12 months

        # Get departments for filter
        departments = Department.objects.all()

        context = {
            # Filter options
            "periods": periods,
            "departments": departments,
            "selected_period": period_id,
            "selected_department": department_filter,
            # Performance Statistics
            "performance_stats": performance_stats,
            "status_distribution": status_distribution,
            "department_performance": department_performance,
            "target_stats": target_stats,
            "target_status_distribution": target_status_distribution,
            "score_distribution": score_distribution,
            "monthly_trend": monthly_trend,
            # For template display
            "total_appraisals": staff_appraisals.count(),
            "total_targets": performance_targets.count(),
        }

        return render(request, "hr/hr_performance_analytics.html", context)

    except Exception as e:
        messages.error(request, f"Error loading analytics: {str(e)}")
        import traceback
        traceback.print_exc()
        return redirect("hr:hr_dashboard")


@login_required
def hr_api_performance_data(request):
    """API endpoint for performance data (for charts)"""
    if not request.user.is_hr_staff:
        return JsonResponse({"error": "Unauthorized"}, status=403)

    data_type = request.GET.get("type", "overall")

    if data_type == "department_scores":
        data = list(
            SupervisorAppraisal.objects.filter(status="approved")
            .values("supervisor__staffprofile__department__name")
            .annotate(avg_score=Avg("overall_score"))
            .order_by("-avg_score")
        )

    elif data_type == "monthly_trends":
        data = list(
            SupervisorAppraisal.objects.filter(status="approved")
            .extra(select={"month": "TO_CHAR(created_at, 'YYYY-MM')"})
            .values("month")
            .annotate(avg_score=Avg("overall_score"))
            .order_by("month")
        )

    elif data_type == "attribute_scores":
        data = list(
            HrSupervisorEvaluation.objects.filter(
                appraisal__status="approved", rating__gt=0
            )
            .values("indicator__attribute__name")
            .annotate(avg_rating=Avg("rating"))
            .order_by("-avg_rating")
        )

    else:
        data = []

    return JsonResponse({"data": data})


@login_required
def hr_generate_reports(request):
    """HR reporting dashboard - Generate reports from existing data"""
    if not request.user.is_hr_staff:
        messages.error(request, "Only HR staff can access this page.")
        return redirect("users:role_based_redirect")

    # Get data for filters
    periods = SPEPeriod.objects.all().order_by("-start_date")
    departments = Department.objects.all().order_by("name")

    if request.method == "POST":
        report_type = request.POST.get("report_type")
        period_id = request.POST.get("report_period")
        department_id = request.POST.get("department")
        format_type = request.POST.get("format", "pdf")

        try:
            # Get selected period
            period = None
            if period_id:
                period = get_object_or_404(SPEPeriod, id=period_id)
            else:
                period = SPEPeriod.objects.filter(is_active=True).first()
                if not period:
                    messages.error(
                        request,
                        "No active period found. Please select a period.",
                    )
                    context = {
                        "periods": periods,
                        "departments": departments,
                    }
                    return render(
                        request, "hr/hr_generate_reports.html", context
                    )

            # Get selected department
            department = None
            if department_id:
                department = get_object_or_404(Department, id=department_id)

            # Generate report based on type and format
            if report_type == "performance_summary":
                return generate_performance_summary_report(
                    request, period, department, format_type
                )
            elif report_type == "department_analysis":
                return generate_department_analysis_report(
                    request, period, format_type
                )
            elif report_type == "supervisor_ranking":
                return generate_supervisor_ranking_report(
                    request, period, department, format_type
                )
            elif report_type == "comprehensive_analysis":
                return generate_comprehensive_analysis_report(
                    request, period, department, format_type
                )
            else:
                messages.error(request, "Please select a valid report type.")

        except Exception as e:
            messages.error(request, f"Error generating report: {str(e)}")
            import traceback
            traceback.print_exc()

    context = {
        "periods": periods,
        "departments": departments,
    }
    return render(request, "hr/hr_generate_reports.html", context)


def generate_performance_summary_report(
    request, period, department, format_type
):
    """Generate performance summary report"""
    # Get staff appraisals for the period
    staff_appraisals = StaffAppraisal.objects.filter(
        period=period
    ).select_related("profile__user", "profile__user__department")

    if department:
        staff_appraisals = staff_appraisals.filter(
            profile__user__department=department
        )

    # Calculate statistics
    total_staff = staff_appraisals.count()
    completed_appraisals = staff_appraisals.filter(
        status__in=["reviewed", "finalized"]
    )
    avg_score = (
        completed_appraisals.aggregate(avg=Avg("overall_score"))["avg"] or 0
    )
    max_score = (
        completed_appraisals.aggregate(max=Max("overall_score"))["max"] or 0
    )
    min_score = (
        completed_appraisals.aggregate(min=Min("overall_score"))["min"] or 0
    )

    # Status distribution
    status_counts = staff_appraisals.values("status").annotate(
        count=Count("id")
    )

    report_data = {
        "total_staff": total_staff,
        "completed_count": completed_appraisals.count(),
        "avg_score": round(avg_score, 1),
        "max_score": round(max_score, 1),
        "min_score": round(min_score, 1),
        "status_counts": list(status_counts),
        "staff_appraisals": completed_appraisals,
        "period": period,
        "department": department,
    }

    if format_type == "pdf":
        return generate_performance_summary_pdf(request, report_data)
    elif format_type == "excel":
        return generate_performance_summary_excel(request, report_data)
    else:
        # HTML format
        context = {"report_type": "Performance Summary", **report_data}
        return render(request, "hr/reports/performance_summary.html", context)


def generate_department_analysis_report(request, period, format_type):
    """Generate department analysis report"""
    # Get department-wise statistics
    dept_stats = (
        StaffAppraisal.objects.filter(
            period=period, overall_score__isnull=False
        )
        .values("profile__user__department__name")
        .annotate(
            staff_count=Count("profile__user", distinct=True),
            avg_score=Avg("overall_score"),
            appraisal_count=Count("id"),
            completed_count=Count(
                "id", filter=Q(status__in=["reviewed", "finalized"])
            ),
        )
        .order_by("-avg_score")
    )

    report_data = {
        "dept_stats": list(dept_stats),
        "period": period,
        "total_departments": dept_stats.count(),
        "overall_avg_score": dept_stats.aggregate(avg=Avg("avg_score"))["avg"]
        or 0,
    }

    if format_type == "pdf":
        return generate_department_analysis_pdf(request, report_data)
    elif format_type == "excel":
        return generate_department_analysis_excel(request, report_data)
    else:
        context = {"report_type": "Department Analysis", **report_data}
        return render(request, "hr/reports/department_analysis.html", context)


def generate_supervisor_ranking_report(
    request, period, department, format_type
):
    """Generate supervisor ranking report"""
    # Get supervisor evaluations
    supervisor_evaluations = SpeSupervisorEvaluation.objects.filter(
        period=period
    ).select_related("supervisor", "supervisor__department")

    if department:
        supervisor_evaluations = supervisor_evaluations.filter(
            supervisor__department=department
        )

    # Calculate average ratings per supervisor
    supervisor_stats = (
        supervisor_evaluations.values(
            "supervisor__id",
            "supervisor__username",
            "supervisor__first_name",
            "supervisor__last_name",
            "supervisor__department__name",
        )
        .annotate(
            avg_rating=Avg("rating"),
            evaluation_count=Count("id"),
            max_rating=Max("rating"),
            min_rating=Min("rating"),
        )
        .order_by("-avg_rating")
    )

    report_data = {
        "supervisor_stats": list(supervisor_stats),
        "period": period,
        "department": department,
        "total_supervisors": supervisor_stats.count(),
    }

    if format_type == "pdf":
        return generate_supervisor_ranking_pdf(request, report_data)
    elif format_type == "excel":
        return generate_supervisor_ranking_excel(request, report_data)
    else:
        context = {"report_type": "Supervisor Ranking", **report_data}
        return render(request, "hr/reports/supervisor_ranking.html", context)


def generate_comprehensive_analysis_report(
    request, period, department, format_type
):
    """Generate comprehensive analysis report"""
    # Get comprehensive data
    staff_appraisals = StaffAppraisal.objects.filter(period=period)
    performance_targets = PerformanceTarget.objects.filter(period=period)

    if department:
        staff_appraisals = staff_appraisals.filter(
            profile__user__department=department
        )
        performance_targets = performance_targets.filter(
            staff__department=department
        )

    # Comprehensive statistics
    completed_appraisals = staff_appraisals.filter(
        status__in=["reviewed", "finalized"]
    )
    evaluated_targets = performance_targets.filter(status="evaluated")

    stats = {
        "total_staff": staff_appraisals.count(),
        "completed_appraisals": completed_appraisals.count(),
        "total_targets": performance_targets.count(),
        "evaluated_targets": evaluated_targets.count(),
        "avg_appraisal_score": completed_appraisals.aggregate(
            avg=Avg("overall_score")
        )["avg"]
        or 0,
        "avg_target_rating": evaluated_targets.aggregate(
            avg=Avg("performance_rating")
        )["avg"]
        or 0,
        "completion_rate": (
            (completed_appraisals.count() / staff_appraisals.count() * 100)
            if staff_appraisals.count() > 0
            else 0
        ),
        "evaluation_rate": (
            (evaluated_targets.count() / performance_targets.count() * 100)
            if performance_targets.count() > 0
            else 0
        ),
    }

    report_data = {
        "stats": stats,
        "period": period,
        "department": department,
        "staff_appraisals": completed_appraisals,
        "performance_targets": evaluated_targets,
    }

    if format_type == "pdf":
        return generate_comprehensive_analysis_pdf(request, report_data)
    elif format_type == "excel":
        return generate_comprehensive_analysis_excel(request, report_data)
    else:
        context = {"report_type": "Comprehensive Analysis", **report_data}
        return render(
            request, "hr/reports/comprehensive_analysis.html", context
        )


# PDF Generation Functions
def generate_performance_summary_pdf(request, data):
    """Generate PDF for performance summary"""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    story = []
    styles = getSampleStyleSheet()

    # Title
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Heading1"],
        fontSize=16,
        spaceAfter=30,
        alignment=1,
        textColor=colors.HexColor("#2c5aa0"),
    )

    title_text = f"Performance Summary Report"
    story.append(Paragraph(title_text, title_style))

    # Period and Department
    period_info = f"Period: {data['period'].name}"
    if data["department"]:
        period_info += f" | Department: {data['department'].name}"

    story.append(Paragraph(period_info, styles["Normal"]))
    story.append(Spacer(1, 0.2 * inch))

    # Key Statistics
    story.append(Paragraph("Key Statistics", styles["Heading2"]))

    stats_data = [
        ["Total Staff", str(data["total_staff"])],
        ["Completed Appraisals", str(data["completed_count"])],
        ["Average Score", f"{data['avg_score']}%"],
        ["Highest Score", f"{data['max_score']}%"],
        ["Lowest Score", f"{data['min_score']}%"],
    ]

    stats_table = Table(stats_data, colWidths=[2 * inch, 1.5 * inch])
    stats_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f8f9fa")),
            ]
        )
    )
    story.append(stats_table)
    story.append(Spacer(1, 0.3 * inch))

    # Status Distribution
    if data["status_counts"]:
        story.append(Paragraph("Status Distribution", styles["Heading2"]))
        status_data = [["Status", "Count"]]
        for status in data["status_counts"]:
            status_data.append(
                [status["status"].title(), str(status["count"])]
            )

        status_table = Table(status_data, colWidths=[1.5 * inch, 1 * inch])
        status_table.setStyle(
            TableStyle(
                [
                    (
                        "BACKGROUND",
                        (0, 0),
                        (-1, 0),
                        colors.HexColor("#2c5aa0"),
                    ),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ]
            )
        )
        story.append(status_table)

    # Footer
    story.append(Spacer(1, 0.3 * inch))
    footer_style = ParagraphStyle(
        "Footer",
        parent=styles["Normal"],
        fontSize=8,
        alignment=1,
        textColor=colors.HexColor("#666666"),
    )
    footer = Paragraph(
        f"Generated on {timezone.now().strftime('%Y-%m-%d at %H:%M')} - KyU HR System",
        footer_style,
    )
    story.append(footer)

    doc.build(story)
    pdf = buffer.getvalue()
    buffer.close()

    response = HttpResponse(content_type="application/pdf")
    filename = (
        f"performance_summary_{data['period'].name.replace(' ', '_')}.pdf"
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write(pdf)
    return response


def generate_performance_summary_excel(request, data):
    """Generate Excel for performance summary"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Performance Summary"

    # Title
    ws.merge_cells("A1:E1")
    ws["A1"] = "Performance Summary Report"
    ws["A1"].font = Font(size=16, bold=True)
    ws["A1"].alignment = Alignment(horizontal="center")

    # Period info
    ws["A2"] = f"Period: {data['period'].name}"
    if data["department"]:
        ws["A3"] = f"Department: {data['department'].name}"

    # Key Statistics
    ws["A5"] = "Key Statistics"
    ws["A5"].font = Font(bold=True)

    stats_data = [
        ["Total Staff", data["total_staff"]],
        ["Completed Appraisals", data["completed_count"]],
        ["Average Score", f"{data['avg_score']}%"],
        ["Highest Score", f"{data['max_score']}%"],
        ["Lowest Score", f"{data['min_score']}%"],
    ]

    for i, (label, value) in enumerate(stats_data, start=6):
        ws[f"A{i}"] = label
        ws[f"B{i}"] = value

    # Status Distribution
    if data["status_counts"]:
        ws["A12"] = "Status Distribution"
        ws["A12"].font = Font(bold=True)

        ws["A13"] = "Status"
        ws["B13"] = "Count"
        ws["A13"].font = ws["B13"].font = Font(bold=True)

        for i, status in enumerate(data["status_counts"], start=14):
            ws[f"A{i}"] = status["status"].title()
            ws[f"B{i}"] = status["count"]

    # Auto-adjust column widths
    for column in ws.columns:
        max_length = 0
        column_letter = column[0].column_letter
        for cell in column:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except:
                pass
        adjusted_width = max_length + 2
        ws.column_dimensions[column_letter].width = adjusted_width

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    filename = (
        f"performance_summary_{data['period'].name.replace(' ', '_')}.xlsx"
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    wb.save(response)
    return response


# Similar functions for other report types (simplified versions)
def generate_department_analysis_pdf(request, data):
    """Generate PDF for department analysis"""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    story = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Heading1"],
        fontSize=16,
        spaceAfter=30,
        alignment=1,
        textColor=colors.HexColor("#2c5aa0"),
    )

    story.append(Paragraph("Department Analysis Report", title_style))
    story.append(Paragraph(f"Period: {data['period'].name}", styles["Normal"]))
    story.append(Spacer(1, 0.2 * inch))

    # Department statistics table
    if data["dept_stats"]:
        story.append(Paragraph("Department Performance", styles["Heading2"]))

        dept_data = [["Department", "Staff Count", "Avg Score", "Appraisals"]]
        for dept in data["dept_stats"]:
            dept_data.append(
                [
                    dept["profile__user__department__name"] or "No Department",
                    str(dept["staff_count"]),
                    (
                        f"{dept['avg_score']:.1f}%"
                        if dept["avg_score"]
                        else "N/A"
                    ),
                    str(dept["appraisal_count"]),
                ]
            )

        dept_table = Table(
            dept_data, colWidths=[2 * inch, 1 * inch, 1 * inch, 1 * inch]
        )
        dept_table.setStyle(
            TableStyle(
                [
                    (
                        "BACKGROUND",
                        (0, 0),
                        (-1, 0),
                        colors.HexColor("#2c5aa0"),
                    ),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ]
            )
        )
        story.append(dept_table)

    doc.build(story)
    pdf = buffer.getvalue()
    buffer.close()

    response = HttpResponse(content_type="application/pdf")
    filename = (
        f"department_analysis_{data['period'].name.replace(' ', '_')}.pdf"
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write(pdf)
    return response


def generate_department_analysis_excel(request, data):
    """Generate Excel for department analysis"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Department Analysis"

    ws["A1"] = "Department Analysis Report"
    ws["A1"].font = Font(size=16, bold=True)
    ws["A2"] = f"Period: {data['period'].name}"

    if data["dept_stats"]:
        headers = ["Department", "Staff Count", "Average Score", "Appraisals"]
        for i, header in enumerate(headers, start=1):
            ws.cell(row=4, column=i).value = header
            ws.cell(row=4, column=i).font = Font(bold=True)

        for i, dept in enumerate(data["dept_stats"], start=5):
            ws.cell(row=i, column=1).value = (
                dept["profile__user__department__name"] or "No Department"
            )
            ws.cell(row=i, column=2).value = dept["staff_count"]
            ws.cell(row=i, column=3).value = dept["avg_score"] or 0
            ws.cell(row=i, column=4).value = dept["appraisal_count"]

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    filename = (
        f"department_analysis_{data['period'].name.replace(' ', '_')}.xlsx"
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    wb.save(response)
    return response


# Add similar functions for supervisor_ranking and comprehensive_analysis
def generate_supervisor_ranking_pdf(request, data):
    """Generate PDF for supervisor ranking"""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    story = []
    styles = getSampleStyleSheet()

    story.append(Paragraph("Supervisor Ranking Report", styles["Heading1"]))
    story.append(Paragraph(f"Period: {data['period'].name}", styles["Normal"]))

    if data["supervisor_stats"]:
        supervisor_data = [
            ["Rank", "Supervisor", "Department", "Avg Rating", "Evaluations"]
        ]
        for i, supervisor in enumerate(data["supervisor_stats"], start=1):
            supervisor_data.append(
                [
                    str(i),
                    f"{supervisor['supervisor__first_name']} {supervisor['supervisor__last_name']}",
                    supervisor["supervisor__department__name"],
                    f"{supervisor['avg_rating']:.1f}/5",
                    str(supervisor["evaluation_count"]),
                ]
            )

        supervisor_table = Table(
            supervisor_data,
            colWidths=[0.5 * inch, 1.5 * inch, 1.5 * inch, 1 * inch, 1 * inch],
        )
        story.append(supervisor_table)

    doc.build(story)
    pdf = buffer.getvalue()
    buffer.close()

    response = HttpResponse(content_type="application/pdf")
    filename = (
        f"supervisor_ranking_{data['period'].name.replace(' ', '_')}.pdf"
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write(pdf)
    return response


def generate_comprehensive_analysis_pdf(request, data):
    """Generate PDF for comprehensive analysis"""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    story = []
    styles = getSampleStyleSheet()

    story.append(
        Paragraph("Comprehensive Analysis Report", styles["Heading1"])
    )
    story.append(Paragraph(f"Period: {data['period'].name}", styles["Normal"]))

    # Add comprehensive statistics
    stats = data["stats"]
    stats_data = [
        ["Metric", "Value"],
        ["Total Staff", stats["total_staff"]],
        ["Completed Appraisals", stats["completed_appraisals"]],
        ["Appraisal Completion Rate", f"{stats['completion_rate']:.1f}%"],
        ["Average Appraisal Score", f"{stats['avg_appraisal_score']:.1f}%"],
        ["Total Performance Targets", stats["total_targets"]],
        ["Evaluated Targets", stats["evaluated_targets"]],
        ["Target Evaluation Rate", f"{stats['evaluation_rate']:.1f}%"],
        ["Average Target Rating", f"{stats['avg_target_rating']:.1f}%"],
    ]

    stats_table = Table(stats_data)
    story.append(stats_table)

    doc.build(story)
    pdf = buffer.getvalue()
    buffer.close()

    response = HttpResponse(content_type="application/pdf")
    filename = (
        f"comprehensive_analysis_{data['period'].name.replace(' ', '_')}.pdf"
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write(pdf)
    return response