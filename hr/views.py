# hr/views.py - UPDATE THE IMPORTS SECTION
import io
# UPDATE THIS LINE:
from .services import BulkReportService, IndividualReportService  # Added IndividualReportService
import openpyxl
from django.apps import apps
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Max, Min, Q, Sum, Case, When, IntegerField
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
    """Simplified - overall = average of department stats"""
    if not request.user.is_hr_staff:
        messages.error(request, "Only HR staff can access this page.")
        return redirect("users:role_based_redirect")

    active_period = SPEPeriod.objects.filter(is_active=True).first()
    departments = Department.objects.all().order_by("name")
    
    department_data = []
    department_completion_rates = []
    department_avg_scores = []
    total_staff_all = 0
    total_evaluated_all = 0
    
    for dept in departments:
        staff_count = dept.staff_count
        total_staff_all += staff_count
        
        # Get final scores for staff in this department
        staff_scores = []
        
        if active_period:
            # Get all staff in department
            dept_staff = CustomUser.objects.filter(department=dept).exclude(is_superuser=True)
            
            for staff in dept_staff:
                score = None
                
                # Try to get final score based on role
                if staff.role in ["teaching", "non_teaching"]:
                    # Method 1: StaffAppraisal
                    try:
                        staff_profile = StaffProfile.objects.get(user=staff)
                        appraisal = StaffAppraisal.objects.filter(
                            profile=staff_profile,
                            period=active_period
                        ).first()
                        if appraisal and appraisal.overall_score:
                            score = float(appraisal.overall_score)
                    except:
                        pass
                    
                    # Method 2: Teaching/NonTeaching evaluation
                    if score is None:
                        if staff.role == "teaching":
                            eval_obj = TeachingStaffEvaluation.objects.filter(
                                staff=staff,
                                period=active_period
                            ).first()
                        else:
                            eval_obj = NonTeachingStaffEvaluation.objects.filter(
                                staff=staff,
                                period=active_period
                            ).first()
                        
                        if eval_obj and eval_obj.percent_score:
                            score = float(eval_obj.percent_score)
                
                elif staff.role == "supervisor":
                    # Method 1: SupervisorAppraisal
                    appraisal = SupervisorAppraisal.objects.filter(
                        supervisor=staff,
                        period=active_period
                    ).first()
                    if appraisal and appraisal.overall_score:
                        score = float(appraisal.overall_score)
                    else:
                        # Method 2: SupervisorRating average
                        ratings = SupervisorRating.objects.filter(
                            supervisor=staff,
                            period=active_period
                        )
                        if ratings.exists():
                            avg_result = ratings.aggregate(avg=Avg('rating'))
                            if avg_result['avg']:
                                score = (float(avg_result['avg']) / 5) * 100
                
                if score is not None:
                    staff_scores.append(score)
        
        # Calculate department stats
        dept_evaluated = len(staff_scores)
        total_evaluated_all += dept_evaluated
        
        dept_avg_score = sum(staff_scores) / len(staff_scores) if staff_scores else 0
        dept_completion_rate = (dept_evaluated / staff_count * 100) if staff_count > 0 else 0
        
        # Store department stats
        department_avg_scores.append(dept_avg_score)
        department_completion_rates.append(dept_completion_rate)
        
        dept_info = {
            "department": dept,
            "calculated_staff_count": staff_count,
            "current_appraisals": dept_evaluated,
            "completion_rate": round(dept_completion_rate, 1),
            "avg_score": round(dept_avg_score, 1),
            "pending_appraisals": max(0, staff_count - dept_evaluated),
            "total_evaluated": dept_evaluated,
        }
        
        department_data.append(dept_info)
    
    # ======================================================
    # CALCULATE OVERALL STATISTICS
    # ======================================================
    
    total_departments = len(departments)
    
    # Overall completion rate = Average of department completion rates
    overall_completion_rate = 0
    if department_completion_rates:
        # Filter out departments with 0% completion
        valid_completion_rates = [rate for rate in department_completion_rates if rate > 0]
        if valid_completion_rates:
            overall_completion_rate = sum(valid_completion_rates) / len(valid_completion_rates)
    
    # Overall average score = Average of department average scores
    overall_avg_score = 0
    if department_avg_scores:
        # Filter out departments with 0 average score
        valid_avg_scores = [score for score in department_avg_scores if score > 0]
        if valid_avg_scores:
            overall_avg_score = sum(valid_avg_scores) / len(valid_avg_scores)
    
    context = {
        "department_data": department_data,
        "total_departments": total_departments,
        "total_staff": total_staff_all,  # Sum of all department staff
        "total_current_appraisals": total_evaluated_all,  # Sum of all evaluated staff
        "overall_completion_rate": round(overall_completion_rate, 1),
        "overall_avg_score": round(overall_avg_score, 1),
        "active_period": active_period,
    }
    
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


# hr/views.py - Add this function
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
        scored_appraisals = staff_appraisals.filter(overall_score__isnull=False)
        performance_stats = scored_appraisals.aggregate(
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
        department_performance = []
        departments = Department.objects.all()
        
        for dept in departments:
            dept_appraisals = staff_appraisals.filter(
                profile__user__department=dept,
                overall_score__isnull=False
            )
            
            if dept_appraisals.exists():
                avg_score = dept_appraisals.aggregate(avg=Avg('overall_score'))['avg'] or 0
                staff_count = CustomUser.objects.filter(department=dept).count()
                appraisal_count = dept_appraisals.count()
                completed_count = dept_appraisals.filter(status__in=["reviewed", "finalized"]).count()
                
                department_performance.append({
                    'profile__user__department__name': dept.name,
                    'avg_score': avg_score,
                    'staff_count': staff_count,
                    'appraisal_count': appraisal_count,
                    'completed_count': completed_count,
                    'completion_percentage': (appraisal_count / staff_count * 100) if staff_count > 0 else 0
                })
        
        # Sort by average score
        department_performance = sorted(department_performance, key=lambda x: x['avg_score'], reverse=True)

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

        # Score Distribution - MANUAL CALCULATION
        score_distribution = []
        scored_appraisals_list = list(scored_appraisals.values_list('overall_score', flat=True))
        
        # Initialize score ranges
        score_ranges = {
            '90-100': 0,
            '80-89': 0,
            '50-79': 0,
            '30-49': 0,
            'Below 30': 0
        }
        
        # Count scores in each range
        for score in scored_appraisals_list:
            if score >= 90:
                score_ranges['90-100'] += 1
            elif score >= 80:
                score_ranges['80-89'] += 1
            elif score >= 50:
                score_ranges['50-79'] += 1
            elif score >= 30:
                score_ranges['30-49'] += 1
            else:
                score_ranges['Below 30'] += 1
        
        # Convert to list for template
        score_distribution = [
            {'score_range': '90-100', 'count': score_ranges['90-100']},
            {'score_range': '80-89', 'count': score_ranges['80-89']},
            {'score_range': '50-79', 'count': score_ranges['50-79']},
            {'score_range': '30-49', 'count': score_ranges['30-49']},
            {'score_range': 'Below 30', 'count': score_ranges['Below 30']},
        ]

        # Monthly Performance Trend - Simplified
        monthly_trend = []
        try:
            # Get last 12 months of data
            from datetime import datetime, timedelta
            from django.utils import timezone
            
            end_date = timezone.now()
            start_date = end_date - timedelta(days=365)
            
            monthly_data = {}
            for appraisal in scored_appraisals.filter(updated_at__range=[start_date, end_date]):
                month_year = appraisal.updated_at.strftime('%Y-%m')
                if month_year not in monthly_data:
                    monthly_data[month_year] = {'total': 0, 'count': 0}
                monthly_data[month_year]['total'] += float(appraisal.overall_score)
                monthly_data[month_year]['count'] += 1
            
            # Convert to list and sort
            for month_year, data in sorted(monthly_data.items(), reverse=True)[:12]:
                year, month = month_year.split('-')
                monthly_trend.append({
                    'year': int(year),
                    'month': int(month),
                    'avg_score': data['total'] / data['count'] if data['count'] > 0 else 0,
                    'count': data['count']
                })
        except Exception as e:
            print(f"Error calculating monthly trend: {e}")
            # Provide dummy data for testing
            monthly_trend = [
                {'year': 2024, 'month': 1, 'avg_score': 75.5, 'count': 10},
                {'year': 2024, 'month': 2, 'avg_score': 78.2, 'count': 12},
                {'year': 2024, 'month': 3, 'avg_score': 80.1, 'count': 15},
            ]

        # Get departments for filter
        departments = Department.objects.all()

        # Calculate performance level based on your scale
        avg_score = performance_stats['avg_score'] or 0
        performance_level = ""
        if avg_score >= 90:
            performance_level = "Outstanding"
        elif avg_score >= 80:
            performance_level = "Exceeds Expectations"
        elif avg_score >= 50:
            performance_level = "Meets Expectations"
        elif avg_score >= 30:
            performance_level = "Below Expectations"
        else:
            performance_level = "Far Below Expectations"

        # Ensure all stats have default values
        performance_stats = {
            'avg_score': performance_stats['avg_score'] or 0,
            'max_score': performance_stats['max_score'] or 0,
            'min_score': performance_stats['min_score'] or 0,
            'total_count': performance_stats['total_count'] or 0,
        }

        target_stats = {
            'total_targets': target_stats['total_targets'] or 0,
            'approved_targets': target_stats['approved_targets'] or 0,
            'evaluated_targets': target_stats['evaluated_targets'] or 0,
            'avg_rating': target_stats['avg_rating'] or 0,
        }

        context = {
            # Filter options
            "periods": periods,
            "departments": departments,
            "selected_period": period_id,
            "selected_department": department_filter,
            # Performance Statistics
            "performance_stats": performance_stats,
            "performance_level": performance_level,
            "department_performance": department_performance,
            "status_distribution": status_distribution,
            "target_stats": target_stats,
            "target_status_distribution": target_status_distribution,
            "score_distribution": score_distribution,
            "monthly_trend": monthly_trend,
            # For template display
            "total_appraisals": staff_appraisals.count(),
            "total_targets": performance_targets.count(),
            # Add active_period for header
            "active_period": SPEPeriod.objects.filter(is_active=True).first(),
        }

        return render(request, "hr/hr_performance_analytics.html", context)

    except Exception as e:
        messages.error(request, f"Error loading analytics: {str(e)}")
        import traceback
        traceback.print_exc()
        return redirect("hr:hr_dashboard")
# hr/views.py - FIXED hr_performance_analytics with proper type handling
@login_required
def hr_performance_analytics(request):
    """HR Performance Analytics Dashboard - Includes ALL staff types"""
    if not request.user.is_hr_staff:
        messages.error(request, "Only HR staff can access this page.")
        return redirect("users:role_based_redirect")

    try:
        # Get periods for filter
        periods = SPEPeriod.objects.all().order_by("-start_date")
        
        # Get active period or selected period
        period_id = request.GET.get("period")
        if period_id:
            current_period = get_object_or_404(SPEPeriod, id=period_id)
        else:
            current_period = SPEPeriod.objects.filter(is_active=True).first()

        # Get filter parameters
        department_filter = request.GET.get("department")

        # ============================================
        # GET ALL STAFF WITH THEIR SCORES (ALL ROLES)
        # ============================================
        all_staff_data = []
        
        # Get all active staff (teaching, non-teaching, supervisors)
        all_staff = CustomUser.objects.filter(
            is_active=True,
            role__in=['teaching', 'non_teaching', 'supervisor']
        ).select_related('department')

        if department_filter:
            all_staff = all_staff.filter(department__name=department_filter)

        for staff in all_staff:
            score = None
            appraisal_status = None
            appraisal_date = None
            
            if current_period:
                # ========================================
                # TEACHING & NON-TEACHING STAFF
                # ========================================
                if staff.role in ['teaching', 'non_teaching']:
                    # Try StaffAppraisal first (most accurate)
                    try:
                        staff_profile = StaffProfile.objects.get(user=staff)
                        appraisal = StaffAppraisal.objects.filter(
                            profile=staff_profile,
                            period=current_period
                        ).first()
                        
                        if appraisal:
                            # Convert Decimal to float
                            if appraisal.overall_score:
                                score = float(appraisal.overall_score)
                            appraisal_status = appraisal.status
                            appraisal_date = appraisal.updated_at
                    except StaffProfile.DoesNotExist:
                        pass
                    
                    # If no StaffAppraisal, calculate from components
                    if score is None:
                        # Get performance targets with ratings
                        targets = PerformanceTarget.objects.filter(
                            staff=staff,
                            period=current_period,
                            performance_rating__isnull=False
                        )
                        
                        # Get supervisor evaluations
                        supervisor_evals = SpeSupervisorEvaluation.objects.filter(
                            self_assessment__staff=staff,
                            self_assessment__period=current_period,
                            supervisor_rating__isnull=False
                        )
                        
                        targets_score = None
                        if targets.exists():
                            avg_target = targets.aggregate(avg=Avg('performance_rating'))['avg']
                            if avg_target:
                                targets_score = float(avg_target)
                        
                        supervisor_score = None
                        if supervisor_evals.exists():
                            avg_sup = supervisor_evals.aggregate(avg=Avg('supervisor_rating'))['avg']
                            if avg_sup:
                                supervisor_score = (float(avg_sup) / 5) * 100
                        
                        # Calculate overall score
                        if targets_score is not None and supervisor_score is not None:
                            score = (targets_score + supervisor_score) / 2
                        elif targets_score is not None:
                            score = targets_score
                        elif supervisor_score is not None:
                            score = supervisor_score
                
                # ========================================
                # SUPERVISORS
                # ========================================
                elif staff.role == 'supervisor':
                    # Try SupervisorAppraisal first
                    supervisor_appraisal = SupervisorAppraisal.objects.filter(
                        supervisor=staff,
                        period=current_period
                    ).first()
                    
                    if supervisor_appraisal and supervisor_appraisal.overall_score:
                        # Convert Decimal to float
                        score = float(supervisor_appraisal.overall_score)
                        appraisal_status = supervisor_appraisal.status
                        appraisal_date = supervisor_appraisal.evaluated_at
                    else:
                        # Get VC evaluations
                        vc_evaluations = HrSupervisorEvaluation.objects.filter(
                            supervisor=staff,
                            period=current_period,
                            rating__isnull=False
                        )
                        
                        # Get supervisor targets with ratings
                        supervisor_targets = SupervisorPerformanceTarget.objects.filter(
                            supervisor=staff,
                            period=current_period,
                            performance_rating__isnull=False
                        )
                        
                        vc_score = None
                        if vc_evaluations.exists():
                            avg_vc = vc_evaluations.aggregate(avg=Avg('rating'))['avg']
                            if avg_vc:
                                vc_score = (float(avg_vc) / 5) * 100
                        
                        targets_score = None
                        if supervisor_targets.exists():
                            avg_target = supervisor_targets.aggregate(avg=Avg('performance_rating'))['avg']
                            if avg_target:
                                targets_score = (float(avg_target) / 5) * 100
                        
                        # Calculate overall score
                        if vc_score is not None and targets_score is not None:
                            score = (vc_score + targets_score) / 2
                        elif vc_score is not None:
                            score = vc_score
                        elif targets_score is not None:
                            score = targets_score
            
            all_staff_data.append({
                'staff': staff,
                'score': score,  # Already float or None
                'status': appraisal_status,
                'date': appraisal_date,
                'department': staff.department
            })

        # ============================================
        # OVERALL PERFORMANCE STATISTICS
        # ============================================
        staff_with_scores = [s for s in all_staff_data if s['score'] is not None]
        
        if staff_with_scores:
            scores = [s['score'] for s in staff_with_scores]  # All are floats now
            performance_stats = {
                'avg_score': round(sum(scores) / len(scores), 1),
                'max_score': round(max(scores), 1),
                'min_score': round(min(scores), 1),
                'total_count': len(staff_with_scores),
                'total_staff': len(all_staff_data)
            }
            avg_score = performance_stats['avg_score']
        else:
            performance_stats = {
                'avg_score': 0,
                'max_score': 0,
                'min_score': 0,
                'total_count': 0,
                'total_staff': len(all_staff_data)
            }
            avg_score = 0

        # ============================================
        # STATUS DISTRIBUTION
        # ============================================
        status_counts = {
            'not_started': 0,
            'draft': 0,
            'in_progress': 0,
            'submitted': 0,
            'reviewed': 0,
            'finalized': 0,
            'completed': 0
        }
        
        for staff_data in all_staff_data:
            status = staff_data['status']
            if status:
                if status in status_counts:
                    status_counts[status] += 1
                else:
                    # Handle any other status values
                    status_counts['in_progress'] += 1
            else:
                if staff_data['score'] is not None:
                    status_counts['in_progress'] += 1
                else:
                    status_counts['not_started'] += 1
        
        status_distribution = [
            {'status': k.replace('_', ' ').title(), 'count': v} 
            for k, v in status_counts.items() if v > 0
        ]

        # ============================================
        # DEPARTMENT PERFORMANCE (INCLUDES ALL DEPARTMENTS)
        # ============================================
        department_performance = []
        departments = Department.objects.all().order_by('name')
        
        for dept in departments:
            # Get staff in this department
            dept_staff_data = [s for s in all_staff_data if s['department'] == dept]
            dept_staff_count = len(dept_staff_data)
            
            # Get staff with scores in this department
            dept_scored = [s for s in dept_staff_data if s['score'] is not None]
            dept_scored_count = len(dept_scored)
            
            # Calculate average score
            if dept_scored:
                dept_avg_score = round(sum(s['score'] for s in dept_scored) / dept_scored_count, 1)
            else:
                dept_avg_score = 0
            
            # Count completed appraisals
            dept_completed = len([s for s in dept_staff_data 
                                 if s['status'] in ['reviewed', 'finalized', 'completed']])
            
            # Calculate completion percentage
            completion_percentage = 0
            if dept_staff_count > 0:
                completion_percentage = round((dept_completed / dept_staff_count) * 100, 1)
            
            department_performance.append({
                'profile__user__department__name': dept.name,
                'avg_score': dept_avg_score,
                'staff_count': dept_staff_count,
                'appraisal_count': dept_scored_count,  # Staff with scores
                'completed_count': dept_completed,
                'completion_percentage': completion_percentage
            })
        
        # Sort by average score (highest first)
        department_performance = sorted(
            department_performance,
            key=lambda x: (x['avg_score'] == 0, -x['avg_score']),
            reverse=False
        )

        # ============================================
        # PERFORMANCE TARGETS STATISTICS
        # ============================================
        if current_period:
            # Staff targets
            staff_targets = PerformanceTarget.objects.filter(period=current_period)
            # Supervisor targets
            supervisor_targets = SupervisorPerformanceTarget.objects.filter(period=current_period)
            
            all_targets_count = staff_targets.count() + supervisor_targets.count()
            
            approved_targets = (
                staff_targets.filter(status='approved').count() +
                supervisor_targets.filter(status='approved').count()
            )
            
            evaluated_targets = (
                staff_targets.filter(performance_rating__isnull=False).count() +
                supervisor_targets.filter(performance_rating__isnull=False).count()
            )
            
            # Average rating (convert supervisor ratings from 1-5 to percentage)
            staff_avg_result = staff_targets.filter(
                performance_rating__isnull=False
            ).aggregate(avg=Avg('performance_rating'))
            staff_avg = float(staff_avg_result['avg']) if staff_avg_result['avg'] else 0
            
            supervisor_avg_result = supervisor_targets.filter(
                performance_rating__isnull=False
            ).aggregate(avg=Avg('performance_rating'))
            supervisor_avg = float(supervisor_avg_result['avg']) if supervisor_avg_result['avg'] else 0
            
            if supervisor_avg > 0:
                supervisor_avg_pct = (supervisor_avg / 5) * 100
            else:
                supervisor_avg_pct = 0
            
            # Overall average
            total_rated = (
                staff_targets.filter(performance_rating__isnull=False).count() +
                supervisor_targets.filter(performance_rating__isnull=False).count()
            )
            
            if total_rated > 0:
                staff_total_result = staff_targets.filter(
                    performance_rating__isnull=False
                ).aggregate(total=Sum('performance_rating'))
                staff_total = float(staff_total_result['total']) if staff_total_result['total'] else 0
                
                supervisor_total_result = supervisor_targets.filter(
                    performance_rating__isnull=False
                ).aggregate(total=Sum('performance_rating'))
                supervisor_total = float(supervisor_total_result['total']) if supervisor_total_result['total'] else 0
                
                # Convert supervisor scores from 1-5 to percentage
                supervisor_score_contrib = supervisor_total * 20  # Convert to percentage
                staff_score_contrib = staff_total
                
                avg_rating = (staff_score_contrib + supervisor_score_contrib) / total_rated
            else:
                avg_rating = 0
        else:
            all_targets_count = 0
            approved_targets = 0
            evaluated_targets = 0
            avg_rating = 0
            staff_targets = PerformanceTarget.objects.none()
            supervisor_targets = SupervisorPerformanceTarget.objects.none()

        target_stats = {
            'total_targets': all_targets_count,
            'approved_targets': approved_targets,
            'evaluated_targets': evaluated_targets,
            'avg_rating': round(avg_rating, 1),
        }

        # Target Status Distribution
        target_status_distribution = []
        if current_period:
            status_dict = {}
            
            # Staff targets
            for item in staff_targets.values('status').annotate(count=Count('id')):
                status = item['status']
                status_dict[status] = status_dict.get(status, 0) + item['count']
            
            # Supervisor targets
            for item in supervisor_targets.values('status').annotate(count=Count('id')):
                status = item['status']
                status_dict[status] = status_dict.get(status, 0) + item['count']
            
            target_status_distribution = [
                {'status': k.replace('_', ' ').title(), 'count': v} 
                for k, v in status_dict.items()
            ]

        # ============================================
        # SCORE DISTRIBUTION
        # ============================================
        score_ranges = {
            '90-100': 0,
            '80-89': 0,
            '50-79': 0,
            '30-49': 0,
            'Below 30': 0
        }
        
        for staff_data in staff_with_scores:
            score = staff_data['score']  # Already float
            if score >= 90:
                score_ranges['90-100'] += 1
            elif score >= 80:
                score_ranges['80-89'] += 1
            elif score >= 50:
                score_ranges['50-79'] += 1
            elif score >= 30:
                score_ranges['30-49'] += 1
            else:
                score_ranges['Below 30'] += 1
        
        score_distribution = [
            {'score_range': k, 'count': v} for k, v in score_ranges.items() if v > 0
        ]

        # ============================================
        # MONTHLY PERFORMANCE TREND
        # ============================================
        monthly_trend = []
        if current_period and staff_with_scores:
            try:
                from datetime import datetime, timedelta
                from django.utils import timezone
                
                end_date = timezone.now()
                start_date = end_date - timedelta(days=365)
                
                monthly_data = {}
                
                # Staff appraisals
                staff_appraisals = StaffAppraisal.objects.filter(
                    period=current_period,
                    overall_score__isnull=False,
                    updated_at__range=[start_date, end_date]
                )
                
                for appraisal in staff_appraisals:
                    month_key = appraisal.updated_at.strftime('%Y-%m')
                    score = float(appraisal.overall_score)
                    
                    if month_key not in monthly_data:
                        monthly_data[month_key] = {'total': 0, 'count': 0}
                    monthly_data[month_key]['total'] += score
                    monthly_data[month_key]['count'] += 1
                
                # Supervisor appraisals
                supervisor_appraisals = SupervisorAppraisal.objects.filter(
                    period=current_period,
                    overall_score__isnull=False,
                    evaluated_at__range=[start_date, end_date]
                )
                
                for appraisal in supervisor_appraisals:
                    month_key = appraisal.evaluated_at.strftime('%Y-%m')
                    score = float(appraisal.overall_score)
                    
                    if month_key not in monthly_data:
                        monthly_data[month_key] = {'total': 0, 'count': 0}
                    monthly_data[month_key]['total'] += score
                    monthly_data[month_key]['count'] += 1
                
                # Convert to list and sort
                for month_key, data in sorted(monthly_data.items(), reverse=True)[:12]:
                    year, month = month_key.split('-')
                    monthly_trend.append({
                        'year': int(year),
                        'month': int(month),
                        'avg_score': round(data['total'] / data['count'], 1) if data['count'] > 0 else 0,
                        'count': data['count']
                    })
                    
            except Exception as e:
                print(f"Error calculating monthly trend: {e}")

        # ============================================
        # PERFORMANCE LEVEL
        # ============================================
        if avg_score >= 90:
            performance_level = "Outstanding"
        elif avg_score >= 80:
            performance_level = "Exceeds Expectations"
        elif avg_score >= 50:
            performance_level = "Meets Expectations"
        elif avg_score >= 30:
            performance_level = "Below Expectations"
        else:
            performance_level = "Far Below Expectations"

        # ============================================
        # ROLE COUNTS
        # ============================================
        teaching_count = len([s for s in all_staff_data if s['staff'].role == 'teaching'])
        non_teaching_count = len([s for s in all_staff_data if s['staff'].role == 'non_teaching'])
        supervisor_count = len([s for s in all_staff_data if s['staff'].role == 'supervisor'])

        # ============================================
        # CONTEXT FOR TEMPLATE
        # ============================================
        context = {
            # Filter options
            "periods": periods,
            "departments": Department.objects.all().order_by('name'),
            "selected_period": period_id,
            "selected_department": department_filter,
            "active_period": current_period,
            
            # Performance Statistics (REAL DATA)
            "performance_stats": performance_stats,
            "performance_level": performance_level,
            "status_distribution": status_distribution,
            "department_performance": department_performance,
            "target_stats": target_stats,
            "target_status_distribution": target_status_distribution,
            "score_distribution": score_distribution,
            "monthly_trend": monthly_trend,
            
            # Totals
            "total_appraisals": len(staff_with_scores),
            "total_targets": target_stats['total_targets'],
            "total_staff": len(all_staff_data),
            
            # Role counts
            "teaching_count": teaching_count,
            "non_teaching_count": non_teaching_count,
            "supervisor_count": supervisor_count,
        }

        return render(request, "hr/hr_performance_analytics.html", context)

    except Exception as e:
        messages.error(request, f"Error loading analytics: {str(e)}")
        import traceback
        traceback.print_exc()
        return redirect("hr:hr_dashboard")

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

from django.db.models import Avg, Count, Max, Min, Q, Case, When, IntegerField, F
from django.db.models.functions import ExtractMonth, ExtractYear



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
@user_passes_test(is_hr_user)
def download_evaluation_pdf(request, appraisal_id):
    """Generate PDF report for staff evaluation using service"""
    try:
        # Get evaluation data
        eval_data = IndividualReportService.get_staff_evaluation_data(appraisal_id)
        
        # Validate data
        is_valid, missing_items = IndividualReportService.validate_evaluation_data(eval_data)
        
        if not is_valid:
            messages.error(
                request,
                f"Cannot generate report: Missing {', '.join(missing_items)} for {eval_data['staff_user'].get_full_name()}",
            )
            return redirect(
                "hr:hr_staff_evaluation_detail", appraisal_id=appraisal_id
            )
        
        # Generate PDF
        pdf_content = IndividualReportService.generate_evaluation_pdf(eval_data)
        
        # Create response
        response = HttpResponse(content_type="application/pdf")
        filename = f"evaluation_{eval_data['staff_user'].get_full_name().replace(' ', '_')}_{eval_data['period'].name}.pdf"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response.write(pdf_content)
        
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
def download_evaluation_excel(request, appraisal_id):
    """Generate Excel report for staff evaluation using service"""
    try:
        # Get evaluation data
        eval_data = IndividualReportService.get_staff_evaluation_data(appraisal_id)
        
        # Validate data
        is_valid, missing_items = IndividualReportService.validate_evaluation_data(eval_data)
        
        if not is_valid:
            messages.error(
                request,
                f"Cannot generate report: Missing {', '.join(missing_items)} for {eval_data['staff_user'].get_full_name()}",
            )
            return redirect(
                "hr:hr_staff_evaluation_detail", appraisal_id=appraisal_id
            )
        
        # Generate Excel
        wb = IndividualReportService.generate_evaluation_excel(eval_data)
        
        # Create response
        response = HttpResponse(
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        filename = f"evaluation_{eval_data['staff_user'].get_full_name().replace(' ', '_')}_{eval_data['period'].name}.xlsx"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        wb.save(response)
        
        return response

    except Exception as e:
        messages.error(request, f"Error generating Excel: {str(e)}")
        import traceback
        traceback.print_exc()
        return redirect(
            "hr:hr_staff_evaluation_detail", appraisal_id=appraisal_id
        )


@login_required
def hr_generate_reports(request):
    """HR reporting dashboard - Unified report generation"""
    if not request.user.is_hr_staff:
        messages.error(request, "Only HR staff can access this page.")
        return redirect("users:role_based_redirect")

    periods = SPEPeriod.objects.all().order_by("-start_date")
    departments = Department.objects.all().order_by("name")

    if request.method == "POST":
        report_type = request.POST.get("report_type", "").strip()
        period_id = request.POST.get("report_period")
        department_id = request.POST.get("department")
        format_type = request.POST.get("format", "pdf").lower()

        try:
            if not department_id:
                messages.error(request, "Department selection is required.")
                return render(request, "hr/hr_generate_reports.html", {
                    "periods": periods,
                    "departments": departments,
                })

            # Get department and period
            department = get_object_or_404(Department, id=department_id)
            
            if period_id:
                period = get_object_or_404(SPEPeriod, id=period_id)
            else:
                period = SPEPeriod.objects.filter(is_active=True).first()
                if not period:
                    messages.error(request, "No active period found.")
                    return render(request, "hr/hr_generate_reports.html", {
                        "periods": periods,
                        "departments": departments,
                    })

            # Get evaluated staff for the department
            _, period, evaluated_staff = BulkReportService.get_department_evaluated_staff(
                department_id, period_id
            )

            if not evaluated_staff:
                messages.warning(request, f"No evaluated staff found for {department.name}.")
                return redirect("hr:hr_generate_reports")

            # Generate report based on type
            if report_type == "performance_summary":
                if format_type == "excel":
                    return BulkReportService.generate_department_excel_report(
                        department, period, evaluated_staff
                    )
                elif format_type == "pdf":
                    return BulkReportService.generate_department_pdf_report(
                        department, period, evaluated_staff
                    )
                else:
                    # HTML format
                    context = {
                        "report_type": "Performance Summary",
                        "department": department,
                        "period": period,
                        "evaluated_staff": evaluated_staff,
                        "total_staff": len(evaluated_staff),
                        "avg_score": sum(s['score'] for s in evaluated_staff) / len(evaluated_staff) if evaluated_staff else 0,
                    }
                    return render(request, "hr/reports/performance_summary.html", context)

            elif report_type == "individual_reports":
                # Generate ZIP with individual reports
                zip_data, filename, count = BulkReportService.generate_individual_reports_zip(
                    request, department, period, evaluated_staff
                )
                
                if zip_data:
                    response = HttpResponse(zip_data, content_type='application/zip')
                    response['Content-Disposition'] = f'attachment; filename="{filename}"'
                    messages.success(request, f"Generated {count} individual reports.")
                    return response
                else:
                    messages.error(request, "Could not generate individual reports.")
                    return redirect("hr:hr_generate_reports")

            elif report_type == "supervisor_ranking":
                # Filter to get only supervisors
                supervisor_staff = [s for s in evaluated_staff if s['user'].role == 'supervisor']
                
                if not supervisor_staff:
                    messages.warning(request, f"No evaluated supervisors found for {department.name}.")
                    return redirect("hr:hr_generate_reports")
                
                # Sort by score
                supervisor_staff.sort(key=lambda x: x['score'], reverse=True)
                
                if format_type == "excel":
                    # Create custom Excel for supervisor ranking
                    wb = openpyxl.Workbook()
                    ws = wb.active
                    ws.title = "Supervisor Ranking"
                    
                    # Add headers
                    ws.append(["Rank", "Supervisor Name", "Department", "Score", "Performance Level", "Status"])
                    
                    # Add data
                    for i, staff in enumerate(supervisor_staff, 1):
                        perf_level, _ = BulkReportService.get_performance_level(staff['score'])
                        ws.append([
                            i,
                            staff['user'].get_full_name(),
                            department.name,
                            f"{staff['score']:.1f}%",
                            perf_level,
                            staff['status'].title()
                        ])
                    
                    response = HttpResponse(
                        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                    )
                    filename = f"Supervisor_Ranking_{department.name.replace(' ', '_')}_{period.name.replace(' ', '_')}.xlsx"
                    response['Content-Disposition'] = f'attachment; filename="{filename}"'
                    wb.save(response)
                    return response
                    
                elif format_type == "pdf":
                    # Create custom PDF for supervisor ranking
                    buffer = io.BytesIO()
                    doc = SimpleDocTemplate(buffer, pagesize=A4)
                    story = []
                    styles = getSampleStyleSheet()
                    
                    # Title
                    title_style = ParagraphStyle(
                        'CustomTitle',
                        parent=styles['Heading1'],
                        fontSize=16,
                        spaceAfter=20,
                        alignment=1,
                        textColor=colors.HexColor("#2c5aa0")
                    )
                    story.append(Paragraph(f"Supervisor Ranking Report - {department.name}", title_style))
                    story.append(Paragraph(f"Period: {period.name}", styles['Normal']))
                    story.append(Spacer(1, 0.3*inch))
                    
                    # Table
                    table_data = [["Rank", "Supervisor Name", "Score", "Performance Level", "Status"]]
                    for i, staff in enumerate(supervisor_staff, 1):
                        perf_level, _ = BulkReportService.get_performance_level(staff['score'])
                        table_data.append([
                            str(i),
                            staff['user'].get_full_name(),
                            f"{staff['score']:.1f}%",
                            perf_level,
                            staff['status'].title()
                        ])
                    
                    table = Table(table_data, colWidths=[0.5*inch, 2*inch, 1*inch, 1.5*inch, 1*inch])
                    table.setStyle(TableStyle([
                        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#2c5aa0")),
                        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                        ('FONTSIZE', (0, 0), (-1, -1), 9),
                        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                    ]))
                    story.append(table)
                    
                    doc.build(story)
                    pdf = buffer.getvalue()
                    buffer.close()
                    
                    response = HttpResponse(content_type='application/pdf')
                    filename = f"Supervisor_Ranking_{department.name.replace(' ', '_')}_{period.name.replace(' ', '_')}.pdf"
                    response['Content-Disposition'] = f'attachment; filename="{filename}"'
                    response.write(pdf)
                    return response
                    
                else:
                    # HTML format
                    context = {
                        "report_type": "Supervisor Ranking",
                        "department": department,
                        "period": period,
                        "supervisor_staff": supervisor_staff,
                        "total_supervisors": len(supervisor_staff),
                        "avg_score": sum(s['score'] for s in supervisor_staff) / len(supervisor_staff) if supervisor_staff else 0,
                    }
                    return render(request, "hr/reports/supervisor_ranking.html", context)

            else:
                messages.error(request, f"Invalid report type: '{report_type}'. Please select a valid report type.")

        except Exception as e:
            messages.error(request, f"Error generating report: {str(e)}")
            import traceback
            traceback.print_exc()

    context = {
        "periods": periods,
        "departments": departments,
    }
    return render(request, "hr/hr_generate_reports.html", context)


@login_required
def download_department_reports(request):
    """Unified endpoint for all department report downloads"""
    if not request.user.is_hr_staff:
        messages.error(request, "Only HR staff can access this page.")
        return redirect("users:role_based_redirect")
    
    try:
        department_id = request.GET.get("department")
        period_id = request.GET.get("period")
        report_type = request.GET.get("type")  # 'excel', 'pdf', or 'zip'
        
        if not department_id:
            messages.error(request, "Department selection is required.")
            return redirect("hr:hr_performance_analytics")
        
        # Get department data using service
        department, period, evaluated_staff = BulkReportService.get_department_evaluated_staff(
            department_id, period_id
        )
        
        if not evaluated_staff:
            messages.warning(request, f"No evaluated staff found for {department.name}.")
            return redirect("hr:hr_performance_analytics")
        
        # Generate report based on type
        if report_type == 'excel':
            return BulkReportService.generate_department_excel_report(
                department, period, evaluated_staff
            )
        
        elif report_type == 'pdf':
            return BulkReportService.generate_department_pdf_report(
                department, period, evaluated_staff
            )
        
        elif report_type == 'zip':
            zip_data, filename, count = BulkReportService.generate_individual_reports_zip(
                request, department, period, evaluated_staff
            )
            
            if zip_data:
                response = HttpResponse(zip_data, content_type='application/zip')
                response['Content-Disposition'] = f'attachment; filename="{filename}"'
                messages.success(request, f"Generated {count} individual reports.")
                return response
            else:
                messages.error(request, "Could not generate individual reports.")
                return redirect("hr:hr_performance_analytics")
        
        else:
            messages.error(request, "Invalid report type.")
            return redirect("hr:hr_performance_analytics")
            
    except Exception as e:
        messages.error(request, f"Error generating report: {str(e)}")
        return redirect("hr:hr_performance_analytics")


# Keep other views as they are (hr_performance_analytics, hr_department_appraisals, etc.)
# They don't need to be changed
