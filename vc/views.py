# Standard library
import io

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Avg, Q
from django.http import HttpResponse, JsonResponse

# Django
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch

# Third-party
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from hr.models import (
    SupervisorAppraisal,
    SupervisorAttribute,
    SupervisorIndicator,
    SupervisorPerformanceTarget,
)
from spe.models import SPEPeriod, SupervisorEvaluation, SupervisorRating

# Local apps
from users.models import (
    CustomUser,
    Department,
    PerformanceTarget,
    StaffAppraisal,
    StaffProfile,
)
from vc.services.vc_department_service import VCDepartmentService
from vc.services.vc_evaluation_service import VCEvaluationService


@login_required
def vc_dashboard(request):
    if not request.user.is_vc_staff:
        messages.error(request, "Only Vice Chancellor can access this page.")
        return redirect("users:role_based_redirect")

    try:
        current_period = SPEPeriod.objects.filter(is_active=True).first()

        # Basic counts
        total_departments = Department.objects.count()
        total_staff = CustomUser.objects.filter(
            role__in=["teaching", "non_teaching", "supervisor"], is_active=True
        ).count()

        total_supervisors = CustomUser.objects.filter(
            role="supervisor", is_active=True
        ).count()

        # Supervisor evaluation counts
        evaluated_count = 0
        if current_period:
            evaluated_count = (
                SupervisorRating.objects.filter(period=current_period)
                .values("supervisor")
                .distinct()
                .count()
            )

        pending_count = (
            total_supervisors - evaluated_count if total_supervisors else 0
        )
        completion_rate = (
            round((evaluated_count / total_supervisors * 100), 1)
            if total_supervisors > 0
            else 0
        )

        # Get top departments
        departments = Department.objects.all()[:5]
        department_stats = []

        for dept in departments:
            dept_staff = CustomUser.objects.filter(
                department=dept,
                role__in=["teaching", "non_teaching", "supervisor"],
                is_active=True,
            )

            supervisors_count = dept_staff.filter(role="supervisor").count()
            regular_staff_count = dept_staff.filter(
                role__in=["teaching", "non_teaching"]
            ).count()

            # Calculate evaluation rate for this department
            evaluation_rate = 0
            if current_period:
                evaluated_supervisors = (
                    SupervisorRating.objects.filter(
                        supervisor__in=dept_staff.filter(role="supervisor"),
                        period=current_period,
                    )
                    .values("supervisor")
                    .distinct()
                    .count()
                )

                total_evaluable = supervisors_count + regular_staff_count
                if total_evaluable > 0:
                    evaluation_rate = round(
                        (evaluated_supervisors / total_evaluable) * 100, 1
                    )

            department_stats.append(
                {
                    "name": dept.name,
                    "total_staff": dept_staff.count(),
                    "supervisors": supervisors_count,
                    "evaluation_rate": evaluation_rate,
                    "avg_score": 0,  # You can calculate this if needed
                }
            )

        context = {
            "current_period": current_period,
            "total_departments": total_departments,
            "total_staff": total_staff,
            "total_supervisors": total_supervisors,
            "evaluated_count": evaluated_count,
            "pending_count": pending_count,
            "completion_rate": completion_rate,
            "department_stats": department_stats,
            "recent_activities": [],
        }

        return render(request, "vc/vc_dashboard.html", context)

    except Exception as e:
        messages.error(request, f"Error loading dashboard: {str(e)}")
        return redirect("vc:vc_dashboard")


@login_required
def vc_department_overview(request):
    if not request.user.is_vc_staff:
        messages.error(request, "Only Vice Chancellor can access this page.")
        return redirect("users:role_based_redirect")

    try:
        active_period = SPEPeriod.objects.filter(is_active=True).first()
        departments = Department.objects.all().order_by("name")

        total_departments = departments.count()
        total_all_staff = 0
        total_supervisors = 0
        total_regular_staff = 0

        department_data = []

        for dept in departments:
            dept_staff = CustomUser.objects.filter(
                department=dept,
                role__in=["teaching", "non_teaching", "supervisor"],
                is_active=True,
            )

            supervisors = dept_staff.filter(role="supervisor")
            regular_staff = dept_staff.filter(
                role__in=["teaching", "non_teaching"]
            )

            supervisors_count = supervisors.count()
            regular_staff_count = regular_staff.count()
            total_staff = dept_staff.count()

            total_all_staff += total_staff
            total_supervisors += supervisors_count
            total_regular_staff += regular_staff_count

            total_evaluations = 0
            average_score = 0
            evaluation_rate = 0

            if active_period:
                # 1. COUNT UNIQUE STAFF EVALUATED (not total evaluation records)
                # Count unique supervisors evaluated
                evaluated_supervisors = (
                    SupervisorRating.objects.filter(
                        supervisor__in=supervisors, period=active_period
                    )
                    .values("supervisor")
                    .distinct()
                    .count()
                )

                # Count unique regular staff evaluated
                evaluated_regular_staff = (
                    StaffAppraisal.objects.filter(
                        profile__user__in=regular_staff,
                        period=active_period,
                        status__in=["reviewed", "finalized"],
                    )
                    .values("profile__user")
                    .distinct()
                    .count()
                )

                total_evaluated_staff = (
                    evaluated_supervisors + evaluated_regular_staff
                )

                # 2. COUNT TOTAL EVALUATION RECORDS (for display)
                supervisor_evaluations = SupervisorRating.objects.filter(
                    supervisor__in=supervisors, period=active_period
                ).count()

                staff_appraisals = StaffAppraisal.objects.filter(
                    profile__user__in=regular_staff,
                    period=active_period,
                    status__in=["reviewed", "finalized"],
                )

                total_evaluations = (
                    supervisor_evaluations + staff_appraisals.count()
                )

                # 3. CALCULATE AVERAGE SCORE
                all_scores = []

                # Get staff appraisal scores - convert to float
                staff_scores = staff_appraisals.filter(
                    overall_score__isnull=False
                ).values_list("overall_score", flat=True)

                for score in staff_scores:
                    if score is not None:
                        all_scores.append(float(score))

                # Get supervisor appraisal scores - convert to float
                supervisor_appraisal_scores = (
                    SupervisorAppraisal.objects.filter(
                        supervisor__in=supervisors,
                        period=active_period,
                        overall_score__isnull=False,
                    ).values_list("overall_score", flat=True)
                )

                for score in supervisor_appraisal_scores:
                    if score is not None:
                        all_scores.append(float(score))

                # Also check SupervisorRating for scores - FIXED HERE
                # Calculate average rating per supervisor from SupervisorRating
                supervisor_ratings_qs = SupervisorRating.objects.filter(
                    supervisor__in=supervisors,
                    period=active_period,
                    rating__isnull=False,
                )

                # Calculate average rating for each supervisor
                supervisor_avg_ratings = supervisor_ratings_qs.values(
                    "supervisor"
                ).annotate(avg_rating=Avg("rating"))

                for item in supervisor_avg_ratings:
                    if item["avg_rating"] is not None:
                        all_scores.append(float(item["avg_rating"]))

                if all_scores:
                    average_score = sum(all_scores) / len(all_scores)

                # 4. CALCULATE EVALUATION RATE (using unique evaluated staff)
                total_evaluable_staff = supervisors_count + regular_staff_count
                if total_evaluable_staff > 0:
                    evaluation_rate = round(
                        (total_evaluated_staff / total_evaluable_staff) * 100,
                        1,
                    )

            # 5. CALCULATE TARGETS COMPLETION
            targets_completion = 0
            if active_period:
                approved_supervisor_targets = (
                    SupervisorPerformanceTarget.objects.filter(
                        supervisor__in=supervisors,
                        period=active_period,
                        status="approved",
                    ).count()
                )

                approved_staff_targets = PerformanceTarget.objects.filter(
                    staff__in=regular_staff,
                    period=active_period,
                    status="approved",
                ).count()

                total_approved_targets = (
                    approved_supervisor_targets + approved_staff_targets
                )

                total_supervisor_targets = (
                    SupervisorPerformanceTarget.objects.filter(
                        supervisor__in=supervisors, period=active_period
                    ).count()
                )

                total_staff_targets = PerformanceTarget.objects.filter(
                    staff__in=regular_staff, period=active_period
                ).count()

                total_targets = total_supervisor_targets + total_staff_targets

                if total_targets > 0:
                    targets_completion = round(
                        (total_approved_targets / total_targets) * 100, 1
                    )

            dept_obj = {
                "department": dept,
                "total_staff": total_staff,
                "supervisors_count": supervisors_count,
                "regular_staff_count": regular_staff_count,
                "total_evaluations": total_evaluations,
                "average_score": round(float(average_score), 1),
                "evaluation_rate": evaluation_rate,
                "targets_completion": targets_completion,
            }

            department_data.append(dept_obj)

        context = {
            "department_data": department_data,
            "total_departments": total_departments,
            "total_all_staff": total_all_staff,
            "total_supervisors": total_supervisors,
            "total_regular_staff": total_regular_staff,
            "current_period": active_period,
        }

        return render(request, "vc/vc_department_overview.html", context)

    except Exception as e:
        messages.error(request, f"Error loading department overview: {str(e)}")
        return redirect("vc:vc_dashboard")


@login_required
def vc_department_staff(request, department_id):
    if not request.user.is_vc_staff:
        messages.error(request, "Only Vice Chancellor can access this page.")
        return redirect("users:role_based_redirect")

    try:
        department = get_object_or_404(Department, id=department_id)
        active_period = SPEPeriod.objects.filter(is_active=True).first()

        # Get all staff in the department
        all_staff = (
            CustomUser.objects.filter(
                department=department,
                role__in=["teaching", "non_teaching", "supervisor"],
                is_active=True,
            )
            .select_related("department")
            .order_by("first_name")
        )

        staff_data = []
        evaluated_staff_count = 0

        for staff in all_staff:
            # Initialize
            is_evaluated = False
            evaluation_count = 0
            latest_evaluation = None
            latest_date = None
            overall_score = None
            approved_targets = 0
            total_targets = 0
            completion_rate = 0

            # For teaching/non-teaching staff - check StaffAppraisal
            if staff.role in ["teaching", "non_teaching"]:
                # Get StaffProfile if exists
                try:
                    profile = StaffProfile.objects.get(user=staff)
                    
                    # Check StaffAppraisal in current period
                    appraisals = StaffAppraisal.objects.filter(
                        profile=profile,
                        period=active_period if active_period else None
                    )
                    
                    if appraisals.exists():
                        evaluation_count = appraisals.count()
                        latest = appraisals.order_by("-updated_at").first()
                        
                        # Check if evaluation is complete (status = 'reviewed', 'completed', 'finalized')
                        if latest.status in ["reviewed", "completed", "finalized"]:
                            is_evaluated = True
                            evaluated_staff_count += 1
                            latest_evaluation = latest
                            latest_date = latest.updated_at
                            
                            if latest.overall_score:
                                overall_score = float(latest.overall_score)
                            elif latest.total_score:
                                overall_score = float(latest.total_score)
                    
                    # Also check targets for regular staff
                    if active_period:
                        targets = PerformanceTarget.objects.filter(
                            staff=staff,
                            period=active_period
                        )
                        total_targets = targets.count()
                        approved_targets = targets.filter(status="approved").count()
                        completion_rate = (approved_targets / total_targets * 100) if total_targets > 0 else 0
                        
                except StaffProfile.DoesNotExist:
                    # No profile exists for this staff
                    pass

            # For supervisors - check SupervisorAppraisal
            elif staff.role == "supervisor":
                # Check SupervisorAppraisal in current period
                appraisals = SupervisorAppraisal.objects.filter(
                    supervisor=staff,
                    period=active_period if active_period else None
                )
                
                if appraisals.exists():
                    evaluation_count = appraisals.count()
                    latest = appraisals.order_by("-evaluated_at").first()
                    
                    # Check if evaluation is complete (status = 'evaluated', 'completed', 'approved')
                    if latest.status in ["evaluated", "completed", "approved"]:
                        is_evaluated = True
                        evaluated_staff_count += 1
                        latest_evaluation = latest
                        latest_date = latest.evaluated_at or latest.created_at
                        
                        if latest.overall_score:
                            overall_score = float(latest.overall_score)
                        elif latest.total_score:
                            overall_score = float(latest.total_score)
                
                # Check SupervisorRating in current period
                if active_period:
                    ratings = SupervisorRating.objects.filter(
                        supervisor=staff,
                        period=active_period
                    )
                    if ratings.exists():
                        rating_count = ratings.count()
                        evaluation_count += rating_count
                        
                        # If we have ratings but no appraisal, mark as evaluated
                        if not is_evaluated:
                            is_evaluated = True
                            evaluated_staff_count += 1
                        
                        latest_rating = ratings.order_by("-submitted_at").first()
                        if not latest_date or (latest_rating.submitted_at > latest_date if latest_date else True):
                            latest_date = latest_rating.submitted_at
                        
                        # Calculate average rating
                        avg_rating = ratings.aggregate(avg=Avg("rating"))["avg"]
                        if avg_rating:
                            overall_score = float(avg_rating) * 20  # Convert 1-5 scale to percentage
                
                # Check supervisor targets
                if active_period:
                    targets = PerformanceTarget.objects.filter(
                        staff=staff,
                        period=active_period
                    )
                    total_targets = targets.count()
                    approved_targets = targets.filter(status="approved").count()
                    completion_rate = (approved_targets / total_targets * 100) if total_targets > 0 else 0

            # Create staff object
            staff_obj = {
                "user": staff,
                "role": staff.get_role_display(),
                "role_code": staff.role,
                "pf_number": getattr(staff, "pf_number", ""),
                "designation": getattr(staff, "designation", ""),
                "email": staff.email,
                "phone": getattr(staff, "phone", ""),
                "is_active": staff.is_active,
                "is_evaluated": is_evaluated,
                "evaluation_count": evaluation_count,
                "latest_evaluation": latest_evaluation,
                "latest_evaluation_date": latest_date,
                "overall_score": overall_score,
                "approved_targets": approved_targets,
                "total_targets": total_targets,
                "completion_rate": completion_rate,
                "initials": f"{staff.first_name[0] if staff.first_name else ''}{staff.last_name[0] if staff.last_name else ''}".upper(),
            }

            staff_data.append(staff_obj)

        # Calculate statistics
        supervisors_count = len([s for s in staff_data if s["role_code"] == "supervisor"])
        regular_staff_count = len([s for s in staff_data if s["role_code"] in ["teaching", "non_teaching"]])
        active_staff_count = len([s for s in staff_data if s["is_active"]])
        total_staff = len(staff_data)

        # Calculate average performance score (only for evaluated staff)
        all_scores = [
            s["overall_score"]
            for s in staff_data
            if s["overall_score"] is not None and s["is_evaluated"]
        ]
        avg_performance_score = round(sum(all_scores) / len(all_scores), 2) if all_scores else 0

        # Calculate evaluation rate
        evaluation_rate = (evaluated_staff_count / total_staff * 100) if total_staff > 0 else 0

        print(f"\n=== DEBUG SUMMARY ===")
        print(f"Total staff: {total_staff}")
        print(f"Evaluated staff: {evaluated_staff_count}")
        print(f"Evaluation rate: {evaluation_rate:.1f}%")
        print(f"Average score: {avg_performance_score:.1f}")
        print(f"Supervisors: {supervisors_count}, Regular staff: {regular_staff_count}")

        paginator = Paginator(staff_data, 20)
        page_number = request.GET.get("page")
        page_obj = paginator.get_page(page_number)

        context = {
            "department": department,
            "staff_data": page_obj,
            "current_period": active_period,
            "supervisors_count": supervisors_count,
            "regular_staff_count": regular_staff_count,
            "total_staff": total_staff,
            "active_staff_count": active_staff_count,
            "avg_performance_score": avg_performance_score,
            "evaluated_staff_count": evaluated_staff_count,
            "evaluation_rate": round(evaluation_rate, 1),
            "all_scores_count": len(all_scores),
        }

        return render(request, "vc/vc_department_staff.html", context)

    except Exception as e:
        messages.error(request, f"Error loading department staff: {str(e)}")
        import traceback
        traceback.print_exc()
        return redirect("vc:vc_department_overview")

@login_required
def vc_view_staff_results(request, staff_id):
    if not request.user.is_vc_staff:
        messages.error(request, "Only Vice Chancellor can access this page.")
        return redirect("users:role_based_redirect")
    
    try:
        staff = get_object_or_404(CustomUser, id=staff_id)
        active_period = SPEPeriod.objects.filter(is_active=True).first()
        
        # Create a minimal context first to test
        minimal_context = {
            'staff': staff,
            'current_period': active_period,
            'evaluator_name': 'Vice Chancellor',
            'test': 'test value',  # Simple test value
        }
        
        print(f"DEBUG: Context type: {type(minimal_context)}")
        print(f"DEBUG: Context keys: {list(minimal_context.keys())}")
        
        # Try with minimal context first
        return render(
            request=request, 
            template_name='vc/vc_staff_results.html', 
            context=minimal_context
        )
        
    except Exception as e:
        messages.error(request, f"Error loading staff results: {str(e)}")
        import traceback
        traceback.print_exc()
        return redirect('vc:vc_department_overview')

@login_required
def vc_evaluate_supervisor_list(request):
    if not request.user.is_vc_staff:
        messages.error(request, "Only Vice Chancellor can access this page.")
        return redirect("users:role_based_redirect")

    evaluation_data = VCEvaluationService.get_supervisor_evaluation_list()

    if not evaluation_data["success"]:
        messages.error(request, evaluation_data["error"])
        return redirect("vc:vc_dashboard")

    context = {
        "supervisors": evaluation_data["supervisors"],
        "current_period": evaluation_data["current_period"],
        "total_supervisors": evaluation_data["total_supervisors"],
        "evaluatable_count": evaluation_data["evaluatable_count"],
        "evaluated_count": evaluation_data["evaluated_count"],
        "pending_count": evaluation_data["pending_count"],
        "completion_rate": evaluation_data["completion_rate"],
    }

    return render(request, "vc/vc_evaluate_supervisor_list.html", context)


@login_required
def vc_evaluate_supervisor(request, supervisor_id):
    if not request.user.is_vc_staff:
        messages.error(request, "Only Vice Chancellor can access this page.")
        return redirect("users:role_based_redirect")

    supervisor = get_object_or_404(
        CustomUser, id=supervisor_id, role="supervisor"
    )
    current_period = SPEPeriod.objects.filter(is_active=True).first()

    if not current_period:
        messages.error(request, "No active evaluation period found.")
        return redirect("vc:vc_evaluate_supervisor_list")

    approved_targets = SupervisorPerformanceTarget.objects.filter(
        supervisor=supervisor, period=current_period, status="approved"
    )

    if not approved_targets.exists():
        messages.warning(
            request,
            f"No approved performance targets found for {supervisor.get_full_name()}",
        )
        return redirect("vc:vc_evaluate_supervisor_list")

    appraisal, created = SupervisorAppraisal.objects.get_or_create(
        supervisor=supervisor,
        period=current_period,
        defaults={
            "status": "pending",
            "evaluated_by": request.user,
        },
    )

    supervisor_attributes = SupervisorAttribute.objects.filter(is_active=True)
    supervisor_indicators = SupervisorIndicator.objects.filter(
        attribute__in=supervisor_attributes, is_active=True
    ).select_related("attribute")

    vc_evaluations = SupervisorEvaluation.objects.filter(
        supervisor=supervisor, period=current_period
    ).select_related("attribute", "indicator")

    self_ratings = SupervisorRating.objects.filter(
        supervisor=supervisor, period=current_period
    ).select_related("attribute", "indicator")

    vc_ratings_dict = {
        e.indicator.id: e for e in vc_evaluations if e.indicator
    }
    self_ratings_dict = {
        r.indicator.id: r for r in self_ratings if r.indicator
    }

    if request.method == "POST":
        try:
            for indicator in supervisor_indicators:
                rating_key = f"rating_{indicator.id}"
                comments_key = f"comments_{indicator.id}"

                rating = request.POST.get(rating_key)
                comments = request.POST.get(comments_key, "")

                if rating:
                    SupervisorEvaluation.objects.update_or_create(
                        supervisor=supervisor,
                        period=current_period,
                        indicator=indicator,
                        defaults={
                            "rating": float(rating),
                            "comments": comments,
                            "evaluated_by": request.user,
                        },
                    )

            for target in approved_targets:
                target_rating_key = f"target_rating_{target.id}"
                target_comments_key = f"target_comments_{target.id}"

                target_rating = request.POST.get(target_rating_key)
                target_comments = request.POST.get(target_comments_key, "")

                if target_rating:
                    target.performance_rating = float(target_rating)
                    target.performance_comments = target_comments
                    target.save()

            appraisal.criteria_score = appraisal.calculate_criteria_score()
            appraisal.target_score = appraisal.calculate_target_score()
            appraisal.overall_score = appraisal.calculate_overall_score()
            appraisal.status = "evaluated"
            appraisal.evaluated_at = timezone.now()
            appraisal.evaluated_by = request.user
            appraisal.save()

            messages.success(
                request,
                f"Evaluation for {supervisor.get_full_name()} submitted successfully!",
            )
            return redirect("vc:vc_evaluate_supervisor_list")

        except Exception as e:
            messages.error(request, f"Error submitting evaluation: {str(e)}")

    criteria_data = []
    for ind in supervisor_indicators:
        vc_eval = vc_ratings_dict.get(ind.id)
        self_eval = self_ratings_dict.get(ind.id)

        criteria_data.append(
            {
                "attribute": ind.attribute,
                "indicator": ind,
                "vc_rating": vc_eval.rating if vc_eval else None,
                "vc_comments": vc_eval.comments if vc_eval else "",
                "self_rating": self_eval.rating if self_eval else None,
                "rating_gap": (
                    (vc_eval.rating - self_eval.rating)
                    if (vc_eval and self_eval)
                    else None
                ),
            }
        )

    context = {
        "supervisor": supervisor,
        "appraisal": appraisal,
        "current_period": current_period,
        "criteria_data": criteria_data,
        "approved_targets": approved_targets,
        "has_targets": approved_targets.exists(),
    }

    return render(request, "vc/vc_evaluate_supervisor.html", context)

from spe.models import SelfAssessment  # Add this import

@login_required
def vc_download_supervisor_report(request, supervisor_id):
    if not request.user.is_vc_staff:
        messages.error(request, "Only Vice Chancellor can access this page.")
        return redirect("users:role_based_redirect")

    supervisor = get_object_or_404(CustomUser, id=supervisor_id)
    current_period = SPEPeriod.objects.filter(is_active=True).first()

    if not current_period:
        messages.error(request, "No active evaluation period found.")
        return redirect("vc:vc_evaluate_supervisor_list")

    if supervisor.role == "supervisor":
        # First, get the VC appraisal (overall evaluation)
        vc_appraisal = SupervisorAppraisal.objects.filter(
            supervisor=supervisor,
            period=current_period,
            evaluated_by__role='vc',
            status__in=["evaluated", "completed", "approved"],
        ).first()

        if not vc_appraisal:
            messages.error(
                request,
                f"No VC evaluation found for {supervisor.get_full_name()} in current period.",
            )
            return redirect("vc:vc_evaluate_supervisor_list")

        print(f"\n=== DEBUG: VC REPORT FOR {supervisor.get_full_name()} ===")

        # Get all indicators
        supervisor_attributes = SupervisorAttribute.objects.filter(is_active=True)
        supervisor_indicators = SupervisorIndicator.objects.filter(
            attribute__in=supervisor_attributes, is_active=True
        ).select_related("attribute")

        # Get supervisor's self-ratings (from spe app)
        self_ratings = SupervisorRating.objects.filter(
            supervisor=supervisor, 
            period=current_period
        ).select_related("attribute", "indicator")

        print(f"DEBUG: Found {self_ratings.count()} self-ratings")

        # CRITICAL: Find VC detailed ratings from hr app
        vc_user = CustomUser.objects.filter(role='vc').first()
        has_vc_detailed_ratings = False
        vc_detailed_ratings = []
        
        # Option 1: Check SupervisorEvaluation model in hr app (where VC ratings are stored)
        if vc_user:
            try:
                from hr.models import SupervisorEvaluation
                # Get VC evaluations from hr app
                vc_detailed_ratings = SupervisorEvaluation.objects.filter(
                    supervisor=supervisor,
                    period=current_period,
                    hr_user=vc_user  # VC is stored as hr_user in this model
                ).select_related("attribute", "indicator")
                
                print(f"DEBUG: Found {vc_detailed_ratings.count()} VC ratings in hr.SupervisorEvaluation")
                
                if vc_detailed_ratings.exists():
                    has_vc_detailed_ratings = True
                else:
                    # Try SupervisorOverallEvaluation model
                    from hr.models import SupervisorOverallEvaluation
                    overall_evaluations = SupervisorOverallEvaluation.objects.filter(
                        supervisor=supervisor,
                        period=current_period,
                        evaluated_by=vc_user
                    )
                    print(f"DEBUG: Found {overall_evaluations.count()} ratings in SupervisorOverallEvaluation")
                    
                    if overall_evaluations.exists():
                        vc_detailed_ratings = overall_evaluations
                        has_vc_detailed_ratings = True
                        
            except ImportError as e:
                print(f"DEBUG: Error importing hr models: {e}")
            except Exception as e:
                print(f"DEBUG: Error checking hr models: {e}")

        # Get approved targets
        approved_targets = SupervisorPerformanceTarget.objects.filter(
            supervisor=supervisor, period=current_period, status="approved"
        ).order_by("target_number")

        print(f"DEBUG: Found {approved_targets.count()} approved targets")

        # Create dictionaries for lookup
        self_ratings_dict = {
            r.indicator.id: r for r in self_ratings if r.indicator
        }
        
        # Create VC ratings dictionary
        vc_ratings_dict = {}
        if has_vc_detailed_ratings and vc_detailed_ratings:
            for evaluation in vc_detailed_ratings:
                # Check what type of model we have
                if hasattr(evaluation, 'indicator') and evaluation.indicator:
                    # hr.SupervisorEvaluation or hr.SupervisorOverallEvaluation
                    vc_ratings_dict[evaluation.indicator.id] = evaluation
                    print(f"DEBUG: Mapped VC rating for indicator {evaluation.indicator.id}")
                elif hasattr(evaluation, 'self_assessment') and evaluation.self_assessment:
                    # spe.SupervisorEvaluation (unlikely for supervisors)
                    if hasattr(evaluation.self_assessment, 'indicator') and evaluation.self_assessment.indicator:
                        vc_ratings_dict[evaluation.self_assessment.indicator.id] = evaluation

        # Prepare criteria data
        criteria_data = []
        total_vc_ratings = 0
        total_indicators = supervisor_indicators.count()
        
        for ind in supervisor_indicators:
            self_eval = self_ratings_dict.get(ind.id)
            
            # Get VC rating if exists
            vc_eval = vc_ratings_dict.get(ind.id)
            vc_rating_value = None
            vc_comments_value = ""
            
            if vc_eval:
                # Extract rating and comments based on model type
                if hasattr(vc_eval, 'rating'):  # hr.SupervisorEvaluation or hr.SupervisorOverallEvaluation
                    vc_rating_value = vc_eval.rating
                    vc_comments_value = getattr(vc_eval, 'comments', '') or getattr(vc_eval, 'remarks', '') or ''
                    print(f"DEBUG: Found VC rating {vc_rating_value} for indicator {ind.id}: {ind.description[:50]}...")
            
            # Count VC ratings
            if vc_rating_value is not None:
                total_vc_ratings += 1
            
            # Calculate rating gap if both exist
            rating_gap = None
            if self_eval and vc_rating_value is not None and self_eval.rating is not None:
                rating_gap = vc_rating_value - self_eval.rating

            criteria_data.append({
                "attribute": ind.attribute,
                "indicator": ind,
                "vc_rating": vc_rating_value,
                "vc_comments": vc_comments_value,
                "self_rating": self_eval.rating if self_eval else None,
                "self_comments": self_eval.comments if self_eval else "",
                "rating_gap": rating_gap,
                "has_vc_rating": vc_rating_value is not None,
            })

        # Calculate percentages
        criteria_percentage = (
            (vc_appraisal.criteria_score / 5 * 100)
            if vc_appraisal.criteria_score is not None
            else 0
        )
        target_percentage = (
            (vc_appraisal.target_score / 5 * 100) if vc_appraisal.target_score is not None else 0
        )
        
        vc_rating_percentage = (total_vc_ratings / total_indicators * 100) if total_indicators > 0 else 0
        
        # CRITICAL: FIXED STATUS DETERMINATION LOGIC
        # Check if targets have VC ratings
        target_vc_ratings = 0
        target_data = []
        for t in approved_targets:
            has_vc_target_rating = t.performance_rating is not None
            target_data.append({
                "target_number": t.target_number,
                "description": t.description,
                "performance_rating": t.performance_rating,
                "performance_comments": t.performance_comments,
                "has_vc_rating": has_vc_target_rating,
            })
            if has_vc_target_rating:
                target_vc_ratings += 1
        
        total_targets = len(approved_targets)
        targets_fully_evaluated = target_vc_ratings == total_targets if total_targets > 0 else False
        
        # NEW LOGIC: A supervisor is fully evaluated when:
        # 1. Has VC appraisal (overall evaluation)
        # 2. All indicators have VC ratings (total_vc_ratings == total_indicators)
        # 3. All targets have VC ratings (targets_fully_evaluated)
        # 4. Has VC detailed ratings (has_vc_detailed_ratings)
        
        is_fully_evaluated = (
            vc_appraisal is not None and
            total_vc_ratings == total_indicators and  # Use == instead of >=
            targets_fully_evaluated and
            has_vc_detailed_ratings
        )
        
        # Partially evaluated means SOME but not ALL requirements are met
        is_partially_evaluated = (
            (vc_appraisal is not None or has_vc_detailed_ratings) and  # Has SOME evaluation
            not is_fully_evaluated  # But not fully evaluated
        )
        
        # Not evaluated means NO evaluation at all
        is_not_evaluated = (
            vc_appraisal is None and 
            not has_vc_detailed_ratings and 
            total_vc_ratings == 0
        )

        # Prepare context
        context = {
            "supervisor": supervisor,
            "appraisal": vc_appraisal,
            "current_period": current_period,
            "criteria_data": criteria_data,
            "target_data": target_data,
            "evaluated_by": vc_appraisal.evaluated_by.get_full_name() if vc_appraisal.evaluated_by else "Vice Chancellor",
            "report_date": vc_appraisal.evaluated_at if vc_appraisal.evaluated_at else timezone.now(),
            "criteria_percentage": criteria_percentage,
            "target_percentage": target_percentage,
            "has_vc_detailed_ratings": has_vc_detailed_ratings,
            "total_vc_ratings": total_vc_ratings,
            "total_indicators": total_indicators,
            "vc_rating_percentage": vc_rating_percentage,
            "target_vc_ratings": target_vc_ratings,
            "total_targets": total_targets,
            "is_fully_evaluated": is_fully_evaluated,
            "is_partially_evaluated": is_partially_evaluated,
            "is_not_evaluated": is_not_evaluated,
            "overall_score": vc_appraisal.overall_score or 0,
            "total_score": vc_appraisal.total_score or 0,
            "average_score": vc_appraisal.average_score or 0,
            "criteria_score": vc_appraisal.criteria_score or 0,
            "target_score": vc_appraisal.target_score or 0,
        }

        print(f"\n=== DEBUG SUMMARY ===")
        print(f"Supervisor: {supervisor.get_full_name()}")
        print(f"VC Appraisal exists: {vc_appraisal is not None}")
        print(f"Total indicators: {total_indicators}")
        print(f"Self ratings: {len(self_ratings_dict)}")
        print(f"VC ratings found: {total_vc_ratings}/{total_indicators}")
        print(f"Targets with VC ratings: {target_vc_ratings}/{total_targets}")
        print(f"VC rating percentage: {vc_rating_percentage:.1f}%")
        print(f"Has VC detailed ratings: {has_vc_detailed_ratings}")
        print(f"Targets fully evaluated: {targets_fully_evaluated}")
        print(f"Status - Fully evaluated: {is_fully_evaluated}")
        print(f"Status - Partially evaluated: {is_partially_evaluated}")
        print(f"Status - Not evaluated: {is_not_evaluated}")
        
        # Show which indicators have VC ratings
        print(f"\nIndicators with VC ratings:")
        for i, item in enumerate(criteria_data):
            if item['has_vc_rating']:
                indicator_desc = item['indicator'].description[:50] + "..." if len(item['indicator'].description) > 50 else item['indicator'].description
                print(f"  {i+1}. {indicator_desc}: {item['vc_rating']}/5")
        
        print(f"===================\n")

        # Handle PDF download
        if request.GET.get("download") == "pdf":
            if is_not_evaluated:
                messages.warning(
                    request,
                    f"Cannot generate PDF report: {supervisor.get_full_name()} has no detailed VC ratings. "
                    f"Please complete the evaluation first."
                )
                return redirect("vc:vc_evaluate_supervisor", supervisor_id=supervisor_id)
            
            # Check if we have enough data for PDF
            if total_vc_ratings == 0:
                messages.warning(
                    request,
                    f"Cannot generate PDF: No VC ratings found. Please complete the detailed evaluation."
                )
                return redirect("vc:vc_evaluate_supervisor", supervisor_id=supervisor_id)
                
            return generate_supervisor_evaluation_pdf(request, vc_appraisal, context)

        # Show appropriate messages
        if is_not_evaluated:
            messages.info(
                request,
                f"Note: {supervisor.get_full_name()} has an overall VC evaluation but no detailed ratings per indicator. "
                f"Click 'Evaluate Now' to add detailed ratings.",
                extra_tags='info'
            )
        elif is_partially_evaluated:
            messages.warning(
                request,
                f"Note: {supervisor.get_full_name()} has {total_vc_ratings}/{total_indicators} indicators rated by VC and {target_vc_ratings}/{total_targets} targets rated. "
                f"Consider completing the evaluation.",
                extra_tags='warning'
            )
        elif is_fully_evaluated:
            messages.success(
                request,
                f"{supervisor.get_full_name()} has been fully evaluated by VC.",
                extra_tags='success'
            )

        return render(request, "vc/vc_supervisor_report.html", context)

    # Handle non-supervisor staff (existing code remains)
    else:
        appraisal = StaffAppraisal.objects.filter(
            profile__user=supervisor,
            period=current_period,
            status__in=["evaluated", "completed", "approved"],
        ).first()

        if not appraisal:
            messages.error(
                request,
                f"No evaluation found for {supervisor.get_full_name()} in current period.",
            )
            return redirect("vc:vc_department_staff", department_id=supervisor.department.id)

        context = {
            "summary": {
                "supervisor_name": supervisor.get_full_name(),
                "percentage_score": appraisal.overall_score,
                "total_indicators": 0,
                "combined_overall_score": appraisal.overall_score,
            },
            "overall_target_performance": {
                "average_score": (
                    appraisal.target_score if appraisal.target_score else 0
                ),
                "evaluated_count": 0,
                "overall_rating": "",
            },
            "target_stats": {
                "total_targets": 0,
                "approved_targets": 0,
                "evaluated_targets": 0,
                "completed_targets": 0,
            },
            "has_targets": False,
            "has_evaluated_targets": False,
            "self_assessments": [],
            "supervisor_evals": {},
            "target_evaluations": [],
            "performance": "",
        }

        if request.GET.get("download") == "pdf":
            from dashboards.views import generate_staff_evaluation_pdf
            return generate_staff_evaluation_pdf(request, appraisal, context)

        return render(request, "vc/vc_supervisor_report.html", context)

@login_required
def vc_download_department_report(request, department_id=None):
    if not request.user.is_vc_staff:
        messages.error(request, "Only Vice Chancellor can access this page.")
        return redirect("users:role_based_redirect")

    if department_id:
        department = get_object_or_404(Department, id=department_id)
        dept_data = VCDepartmentService.get_department_staff_detail(
            department_id
        )
        performance_data = (
            VCDepartmentService.get_department_performance_stats(department_id)
        )
        departments = [department]
    else:
        dept_data = VCDepartmentService.get_department_overview()
        performance_data = (
            VCDepartmentService.get_department_performance_stats()
        )
        departments = Department.objects.all()

    if not dept_data["success"]:
        messages.error(request, dept_data["error"])
        return redirect("vc:vc_department_overview")

    current_period = SPEPeriod.objects.filter(is_active=True).first()

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

    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Heading1"],
        fontSize=16,
        spaceAfter=18,
        alignment=1,
        textColor=colors.HexColor("#2c3e50"),
    )

    if department_id:
        title_text = (
            f"DEPARTMENT PERFORMANCE REPORT - {department.name.upper()}"
        )
    else:
        title_text = "UNIVERSITY-WIDE DEPARTMENT PERFORMANCE REPORT"

    story.append(Paragraph(title_text, title_style))
    story.append(Spacer(1, 0.1 * inch))

    header_data = [
        ["REPORT INFORMATION", "PERIOD DETAILS"],
        [
            f"Report Type: {'Department' if department_id else 'University-Wide'}",
            f"Period: {current_period.name if current_period else 'N/A'}",
        ],
        [
            f"Generated By: {request.user.get_full_name()}",
            f"Generation Date: {timezone.now().strftime('%B %d, %Y')}",
        ],
        [
            f"Total Departments: {len(departments)}",
            f"Report Scope: {'Single Department' if department_id else 'All Departments'}",
        ],
    ]

    header_table = Table(header_data, colWidths=[3 * inch, 3 * inch])
    header_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#34495e")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#f8f9fa")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.append(header_table)
    story.append(Spacer(1, 0.15 * inch))

    if department_id and dept_data["success"]:
        dept = dept_data["department"]
        summary_rows = [
            ["Department Summary", ""],
            [
                f"Department Name: {dept.name}",
                f"Total Staff: {dept_data['total_staff']}",
            ],
            [
                f"Supervisors: {dept_data['supervisors_count']}",
                f"Regular Staff: {dept_data['regular_staff_count']}",
            ],
            [
                f"Active Staff: {dept_data.get('active_staff_count', 0)}",
                f"Avg Performance Score: {dept_data.get('avg_performance_score', 0):.1f}",
            ],
        ]
    else:
        total_staff = sum(
            dept["total_staff"]
            for dept in dept_data.get("department_data", [])
        )
        total_supervisors = sum(
            dept["supervisors_count"]
            for dept in dept_data.get("department_data", [])
        )

        summary_rows = [
            ["University Performance Summary", ""],
            [
                f"Total Departments: {dept_data.get('total_departments', 0)}",
                f"Total Staff: {total_staff}",
            ],
            [
                f"Total Supervisors: {total_supervisors}",
                f"Total Regular Staff: {dept_data.get('total_regular_staff', 0)}",
            ],
        ]

    summary_table = Table(summary_rows, colWidths=[3 * inch, 3 * inch])
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3498db")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ]
        )
    )
    story.append(summary_table)
    story.append(Spacer(1, 0.2 * inch))

    if performance_data.get("success") and performance_data.get(
        "performance_data"
    ):
        story.append(Paragraph("PERFORMANCE STATISTICS", styles["Heading4"]))

        perf_rows = [
            [
                "Department",
                "Supervisors",
                "Evaluated",
                "Rate",
                "Avg Score",
                "Max",
                "Min",
            ]
        ]

        for perf in performance_data["performance_data"]:
            perf_rows.append(
                [
                    perf["department"].name,
                    str(perf["total_supervisors"]),
                    str(perf["evaluated_supervisors"]),
                    f"{perf['evaluation_rate']:.1f}%",
                    f"{perf['avg_score']:.1f}",
                    f"{perf['max_score']:.1f}",
                    f"{perf['min_score']:.1f}",
                ]
            )

        perf_table = Table(
            perf_rows,
            colWidths=[
                1.5 * inch,
                0.8 * inch,
                0.8 * inch,
                0.8 * inch,
                0.8 * inch,
                0.7 * inch,
                0.7 * inch,
            ],
            repeatRows=1,
        )
        perf_table.setStyle(
            TableStyle(
                [
                    (
                        "BACKGROUND",
                        (0, 0),
                        (-1, 0),
                        colors.HexColor("#2c3e50"),
                    ),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.white, colors.HexColor("#f8f9fa")],
                    ),
                    ("ALIGN", (1, 1), (-1, -1), "CENTER"),
                ]
            )
        )
        story.append(perf_table)
        story.append(Spacer(1, 0.2 * inch))

    if department_id and dept_data.get("staff_data"):
        story.append(Paragraph("STAFF DETAILS", styles["Heading4"]))

        staff_rows = [
            [
                "Name",
                "PF No.",
                "Role",
                "Status",
                "Performance",
                "Targets Comp.",
            ]
        ]

        for staff in dept_data["staff_data"]:
            staff_rows.append(
                [
                    staff["user"].get_full_name(),
                    staff.get("pf_number", "N/A"),
                    staff["role"].title(),
                    "Active" if staff["is_active"] else "Inactive",
                    f"{staff.get('performance_score', 'N/A')}",
                    f"{staff.get('completion_rate', 0):.1f}%",
                ]
            )

        staff_table = Table(
            staff_rows,
            colWidths=[
                1.8 * inch,
                0.8 * inch,
                0.8 * inch,
                0.8 * inch,
                0.8 * inch,
                1.0 * inch,
            ],
            repeatRows=1,
        )
        staff_table.setStyle(
            TableStyle(
                [
                    (
                        "BACKGROUND",
                        (0, 0),
                        (-1, 0),
                        colors.HexColor("#27ae60"),
                    ),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.white, colors.HexColor("#fef9e7")],
                    ),
                ]
            )
        )
        story.append(staff_table)
        story.append(Spacer(1, 0.2 * inch))

    story.append(Spacer(1, 0.3 * inch))
    story.append(
        Paragraph(
            "Confidential Report - For Internal Use Only", styles["Normal"]
        )
    )
    story.append(
        Paragraph("Generated by Vice Chancellor's Office", styles["Normal"])
    )

    doc.build(story)
    buffer.seek(0)

    response = HttpResponse(buffer, content_type="application/pdf")

    if department_id:
        filename = f"Department_Report_{department.name.replace(' ', '_')}_{current_period.name if current_period else ''}.pdf"
    else:
        filename = f"University_Department_Report_{current_period.name if current_period else ''}.pdf"

    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def generate_supervisor_evaluation_pdf(request, appraisal, context):
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

    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Heading1"],
        fontSize=16,
        spaceAfter=18,
        alignment=1,
        textColor=colors.HexColor("#2c3e50"),
    )

    is_supervisor_appraisal = hasattr(appraisal, "supervisor")
    title_text = (
        "KIRINYAGA UNIVERSITY SUPERVISOR PERFORMANCE EVALUATION REPORT"
        if is_supervisor_appraisal
        else "KIRINYAGA UNIVERSITY STAFF PERFORMANCE EVALUATION REPORT"
    )
    story.append(Paragraph(title_text, title_style))
    story.append(Spacer(1, 0.1 * inch))

    if hasattr(appraisal, "profile"):
        profile = appraisal.profile
        person_user = getattr(profile, "user", None)
        pf_number = getattr(person_user, "pf_number", "N/A")
        designation = getattr(profile, "designation", "N/A")
        department_name = (
            profile.department.name
            if getattr(profile, "department", None)
            else "N/A"
        )
        person_name = person_user.get_full_name() if person_user else "N/A"
        evaluated_entity = "Staff"
    elif hasattr(appraisal, "supervisor"):
        person_user = appraisal.supervisor
        profile = getattr(person_user, "staffprofile", None)
        pf_number = getattr(person_user, "pf_number", "N/A")
        designation = (
            getattr(profile, "designation", "N/A") if profile else "N/A"
        )
        department_name = (
            profile.department.name
            if profile and getattr(profile, "department", None)
            else (
                getattr(person_user, "department").name
                if getattr(person_user, "department", None)
                else "N/A"
            )
        )
        person_name = person_user.get_full_name()
        evaluated_entity = "Supervisor"
    else:
        person_user = (
            context.get("supervisor")
            or context.get("appraisee")
            or getattr(appraisal, "user", None)
        )
        pf_number = (
            getattr(person_user, "pf_number", "N/A") if person_user else "N/A"
        )
        profile = (
            getattr(person_user, "staffprofile", None) if person_user else None
        )
        designation = (
            getattr(profile, "designation", "N/A") if profile else "N/A"
        )
        department_name = (
            profile.department.name
            if profile and getattr(profile, "department", None)
            else "N/A"
        )
        person_name = person_user.get_full_name() if person_user else "N/A"
        evaluated_entity = "Person"

    header_data = [
        [f"{evaluated_entity} INFORMATION", "EVALUATION DETAILS"],
        [
            f"Name: {person_name}",
            f"Period: {getattr(appraisal, 'period', context.get('current_period', 'N/A')).name if getattr(appraisal, 'period', None) or context.get('current_period') else 'N/A'}",
        ],
        [
            f"Department: {department_name}",
            f"Evaluation Date: {context.get('report_date', timezone.now()).strftime('%B %d, %Y')}",
        ],
        [
            f"Designation: {designation}",
            f"Evaluated By: {context.get('evaluated_by', 'N/A')}",
        ],
        [
            f"PF Number: {pf_number}",
            f"Overall Score: {getattr(appraisal, 'overall_score', 'N/A') if getattr(appraisal, 'overall_score', None) is not None else 'N/A'}",
        ],
    ]
    header_table = Table(header_data, colWidths=[3 * inch, 3 * inch])
    header_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#34495e")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#f8f9fa")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.append(header_table)
    story.append(Spacer(1, 0.15 * inch))

    criteria_pct = context.get(
        "criteria_percentage", context.get("criteria_percentage", 0)
    )
    target_pct = context.get(
        "target_percentage", context.get("target_percentage", 0)
    )
    combined_pct = context.get("combined_score")
    if combined_pct is None:
        parts = [v for v in (criteria_pct, target_pct) if v and v > 0]
        combined_pct = (
            (sum(parts) / len(parts))
            if parts
            else (criteria_pct or target_pct or 0)
        )

    summary_rows = [
        ["Metric", "Value"],
        ["Criteria Score", f"{criteria_pct:.1f}%"],
        ["Targets Score", f"{target_pct:.1f}%"],
        ["Combined Score", f"{combined_pct:.1f}%"],
        ["Interpretation", get_performance_category(combined_pct)],
    ]
    summary_table = Table(summary_rows, colWidths=[2.5 * inch, 3.5 * inch])
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3498db")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ]
        )
    )
    story.append(summary_table)
    story.append(Spacer(1, 0.2 * inch))

    criteria_rows = []
    criteria_rows.append(
        ["Attribute", "Indicator", "Self", "VC/Other", "Gap", "Comments"]
    )
    criteria_list = context.get("criteria_data")
    if criteria_list and isinstance(criteria_list, (list, tuple)):
        for c in criteria_list:
            attr_name = (
                getattr(c.get("attribute"), "name", c.get("attribute"))
                if isinstance(c, dict)
                else ""
            )
            indicator = (
                getattr(c.get("indicator"), "description", c.get("indicator"))
                if isinstance(c, dict)
                else ""
            )
            self_r = c.get("self_rating", "N/A")
            vc_r = c.get("vc_rating", c.get("vc_rating", "N/A"))
            gap = c.get("rating_gap", "-")
            comments = c.get("vc_comments", "") or c.get("comments", "")
            criteria_rows.append(
                [
                    str(attr_name),
                    str(indicator),
                    str(self_r),
                    str(vc_r),
                    (f"{gap:+.1f}" if isinstance(gap, (int, float)) else gap),
                    comments,
                ]
            )
    else:
        self_assessments = context.get("self_assessments", [])
        supervisor_evals = context.get("supervisor_evals", {})
        for sa in self_assessments:
            attr_name = (
                sa.attribute.name
                if hasattr(sa, "attribute")
                else getattr(sa, "attribute", "")
            )
            indicator = (
                sa.indicator.description
                if hasattr(sa, "indicator")
                else getattr(sa, "indicator", "")
            )
            self_r = getattr(sa, "self_rating", "N/A")
            ev = (
                supervisor_evals.get(sa.id, {})
                if isinstance(supervisor_evals, dict)
                else {}
            )
            sup_r = ev.get("supervisor_rating", "N/A")
            gap = ev.get("rating_gap", "-") if isinstance(ev, dict) else "-"
            comments = (
                (ev.get("remarks") or ev.get("comments") or "")
                if isinstance(ev, dict)
                else ""
            )
            criteria_rows.append(
                [
                    attr_name,
                    indicator,
                    str(self_r),
                    str(sup_r),
                    (f"{gap:+.1f}" if isinstance(gap, (int, float)) else gap),
                    comments,
                ]
            )

    if len(criteria_rows) > 1:
        criteria_table = Table(
            criteria_rows,
            colWidths=[
                1.3 * inch,
                2.1 * inch,
                0.7 * inch,
                0.7 * inch,
                0.6 * inch,
                1.2 * inch,
            ],
            repeatRows=1,
        )
        criteria_table.setStyle(
            TableStyle(
                [
                    (
                        "BACKGROUND",
                        (0, 0),
                        (-1, 0),
                        colors.HexColor("#2c3e50"),
                    ),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.white, colors.HexColor("#f8f9fa")],
                    ),
                    ("ALIGN", (2, 1), (4, -1), "CENTER"),
                ]
            )
        )
        story.append(
            Paragraph("DETAILED PERFORMANCE CRITERIA", styles["Heading4"])
        )
        story.append(criteria_table)
        story.append(Spacer(1, 0.2 * inch))

    targets = (
        context.get("target_data")
        or context.get("target_evaluations")
        or context.get("approved_targets")
        or context.get("targets")
        or []
    )
    normalized_targets = []
    for t in targets:
        if isinstance(t, dict):
            normalized_targets.append(t)
        else:
            normalized_targets.append(
                {
                    "target_number": getattr(t, "target_number", ""),
                    "description": getattr(t, "description", "")
                    or getattr(t, "summary", ""),
                    "performance_rating": getattr(
                        t, "performance_rating", None
                    ),
                    "performance_comments": getattr(
                        t,
                        "performance_comments",
                        getattr(t, "supervisor_comments", ""),
                    ),
                }
            )

    if normalized_targets:
        t_rows = [
            ["#", "Description", "Rating", "Performance Category", "Comments"]
        ]
        for t in normalized_targets:
            rating = t.get("performance_rating")
            rating_display = (
                f"{rating:.1f}%"
                if isinstance(rating, (int, float))
                else (str(rating) if rating is not None else "N/A")
            )
            perf_cat = (
                get_performance_category(rating)
                if isinstance(rating, (int, float))
                else "Not Evaluated"
            )
            t_rows.append(
                [
                    str(t.get("target_number", "")),
                    t.get("description", "")[:80],
                    rating_display,
                    perf_cat,
                    t.get("performance_comments", "") or "-",
                ]
            )

        targets_table = Table(
            t_rows,
            colWidths=[
                0.5 * inch,
                3.0 * inch,
                0.8 * inch,
                1.2 * inch,
                1.0 * inch,
            ],
            repeatRows=1,
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
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.white, colors.HexColor("#fef9e7")],
                    ),
                ]
            )
        )
        story.append(Paragraph("PERFORMANCE TARGETS", styles["Heading4"]))
        story.append(targets_table)
        story.append(Spacer(1, 0.2 * inch))

    story.append(
        Paragraph("PERFORMANCE INTERPRETATION GUIDE", styles["Heading5"])
    )
    guide_data = [
        ["Score Range", "Performance Level"],
        ["90-100%", "Outstanding"],
        ["80-89%", "Excellent"],
        ["70-79%", "Good"],
        ["60-69%", "Satisfactory"],
        ["50-59%", "Needs Improvement"],
        ["Below 50%", "Unsatisfactory"],
    ]
    guide_table = Table(guide_data, colWidths=[1.5 * inch, 4.5 * inch])
    guide_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#27ae60")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ]
        )
    )
    story.append(guide_table)
    story.append(Spacer(1, 0.25 * inch))

    if is_supervisor_appraisal:
        sign_left = "Supervisor Signature"
        sign_right = "Vice Chancellor Signature"
    else:
        sign_left = "Employee Signature"
        sign_right = "Supervisor Signature"

    sig_rows = [
        ["", ""],
        ["_________________________", "_________________________"],
        [sign_left, sign_right],
        ["", ""],
        [
            f"Date: {timezone.now().strftime('%Y-%m-%d')}",
            f"Date: {getattr(appraisal, 'updated_at', timezone.now()).strftime('%Y-%m-%d')}",
        ],
    ]
    sig_table = Table(sig_rows, colWidths=[3 * inch, 3 * inch])
    sig_table.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
            ]
        )
    )
    story.append(sig_table)

    doc.build(story)
    buffer.seek(0)
    response = HttpResponse(buffer, content_type="application/pdf")
    filename_safe_name = (
        person_name.replace(" ", "_")
        if person_name
        else f"{evaluated_entity}_{getattr(appraisal, 'id', 'report')}"
    )
    filename = f"Evaluation_{filename_safe_name}_{getattr(appraisal, 'period', context.get('current_period', '')).name if getattr(appraisal, 'period', None) or context.get('current_period') else ''}.pdf"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def get_performance_category(score):
    if score is None:
        return "Not Evaluated"
    try:
        s = float(score)
    except Exception:
        return "Not Evaluated"
    if s >= 90:
        return "Outstanding"
    if s >= 80:
        return "Excellent"
    if s >= 70:
        return "Good"
    if s >= 60:
        return "Satisfactory"
    if s >= 50:
        return "Needs Improvement"
    return "Unsatisfactory"


@login_required
def vc_department_stats_api(request):
    if not request.user.is_vc_staff:
        return JsonResponse({"error": "Unauthorized"}, status=403)

    dept_data = VCDepartmentService.get_department_overview()
    perf_data = VCDepartmentService.get_department_performance_stats()

    if not dept_data["success"] or not perf_data["success"]:
        return JsonResponse({"error": "Failed to retrieve data"}, status=500)

    response_data = {
        "success": True,
        "departments": [],
        "summary": {
            "total_departments": dept_data["total_departments"],
            "total_staff": dept_data["total_all_staff"],
            "total_supervisors": dept_data["total_supervisors"],
            "total_regular_staff": dept_data["total_regular_staff"],
        },
    }

    for dept_item in dept_data["department_data"]:
        dept_id = dept_item["department"].id
        perf_item = next(
            (
                p
                for p in perf_data["performance_data"]
                if p["department"].id == dept_id
            ),
            None,
        )

        department_info = {
            "id": dept_id,
            "name": dept_item["department"].name,
            "total_staff": dept_item["total_staff"],
            "supervisors_count": dept_item["supervisors_count"],
            "regular_staff_count": dept_item["regular_staff_count"],
            "evaluation_rate": dept_item["evaluation_rate"],
            "average_score": dept_item["average_score"],
            "targets_completion": dept_item["targets_completion"],
        }

        if perf_item:
            department_info.update(
                {
                    "evaluated_supervisors": perf_item[
                        "evaluated_supervisors"
                    ],
                    "max_score": perf_item["max_score"],
                    "min_score": perf_item["min_score"],
                    "score_distribution": perf_item["score_distribution"],
                }
            )

        response_data["departments"].append(department_info)

    return JsonResponse(response_data)


@login_required
def vc_performance_trends_api(request):
    if not request.user.is_vc_staff:
        return JsonResponse({"error": "Unauthorized"}, status=403)

    try:
        periods = SPEPeriod.objects.all().order_by("-start_date")[:6]

        trend_data = []
        for period in periods:
            dept_stats = []
            departments = Department.objects.all()

            for dept in departments:
                evaluations = SupervisorAppraisal.objects.filter(
                    supervisor__staffprofile__department=dept,
                    period=period,
                    status__in=["evaluated", "completed", "approved"],
                )

                if evaluations.exists():
                    avg_score = evaluations.aggregate(Avg("overall_score"))[
                        "overall_score__avg"
                    ]
                    eval_count = evaluations.count()
                else:
                    avg_score = 0
                    eval_count = 0

                dept_stats.append(
                    {
                        "department": dept.name,
                        "average_score": round(avg_score, 1),
                        "evaluation_count": eval_count,
                    }
                )

            trend_data.append(
                {
                    "period": period.name,
                    "period_id": period.id,
                    "start_date": period.start_date.strftime("%Y-%m-%d"),
                    "end_date": (
                        period.end_date.strftime("%Y-%m-%d")
                        if period.end_date
                        else None
                    ),
                    "department_stats": dept_stats,
                }
            )

        return JsonResponse(
            {
                "success": True,
                "trends": trend_data,
            }
        )

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=500)


@login_required
def vc_search_staff(request):
    if not request.user.is_vc_staff:
        messages.error(request, "Only Vice Chancellor can access this page.")
        return redirect("users:role_based_redirect")

    query = request.GET.get("q", "")
    results = []

    if query:
        users = CustomUser.objects.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(email__icontains=query)
            | Q(pf_number__icontains=query)
        ).select_related("staffprofile__department")

        for user in users:
            profile = user.staffprofile
            if profile:
                results.append(
                    {
                        "user": user,
                        "department": (
                            profile.department.name
                            if profile.department
                            else "N/A"
                        ),
                        "designation": profile.designation or "N/A",
                        "pf_number": user.pf_number or "N/A",
                    }
                )

    context = {
        "query": query,
        "results": results,
        "result_count": len(results),
    }

    return render(request, "vc/vc_search_staff.html", context)


@login_required
def vc_export_data(request, data_type):
    if not request.user.is_vc_staff:
        messages.error(request, "Only Vice Chancellor can access this page.")
        return redirect("users:role_based_redirect")

    messages.info(
        request, f"Export functionality for {data_type} coming soon!"
    )
    return redirect("vc:vc_dashboard")
