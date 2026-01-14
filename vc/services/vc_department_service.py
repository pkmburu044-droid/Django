# vc/services/vc_department_service.py
from django.db.models import Avg

from hr.models import SupervisorAppraisal, SupervisorPerformanceTarget
from spe.models import SPEPeriod, SupervisorRating
from users.models import (
    CustomUser,
    Department,
    PerformanceTarget,
    StaffAppraisal,
)


class VCDepartmentService:
    """Service class for VC department operations"""

    @staticmethod
    def get_department_overview():
        """Get comprehensive department overview for VC"""
        try:
            departments = Department.objects.all()
            current_period = SPEPeriod.objects.filter(is_active=True).first()

            department_data = []
            total_regular_staff_all = 0

            for department in departments:
                # Get ALL active staff in this department (matching your view)
                all_staff = CustomUser.objects.filter(
                    department=department,
                    role__in=["teaching", "non_teaching", "supervisor"],
                    is_active=True,
                )
                total_staff = all_staff.count()

                # Count staff by role
                supervisors = all_staff.filter(role="supervisor")
                regular_staff = all_staff.filter(
                    role__in=["teaching", "non_teaching"]
                )

                supervisors_count = supervisors.count()
                regular_staff_count = regular_staff.count()
                total_regular_staff_all += regular_staff_count

                # Initialize metrics
                total_evaluations = 0
                avg_score = 0
                evaluation_rate = 0
                targets_completion = 0

                if current_period:
                    # 1. COUNT EVALUATIONS FOR DISPLAY
                    # Supervisor evaluations (from SupervisorRating)
                    supervisor_evaluations_count = (
                        SupervisorRating.objects.filter(
                            supervisor__in=supervisors, period=current_period
                        ).count()
                    )

                    # Staff evaluations (from StaffAppraisal)
                    staff_evaluations_count = StaffAppraisal.objects.filter(
                        profile__user__in=regular_staff,
                        period=current_period,
                        status__in=["reviewed", "finalized"],
                    ).count()

                    total_evaluations = (
                        supervisor_evaluations_count + staff_evaluations_count
                    )

                    # 2. COUNT UNIQUE EVALUATED STAFF (for evaluation rate calculation)
                    # Unique supervisors evaluated
                    evaluated_supervisors = (
                        SupervisorRating.objects.filter(
                            supervisor__in=supervisors, period=current_period
                        )
                        .values("supervisor")
                        .distinct()
                        .count()
                    )

                    # Unique regular staff evaluated
                    evaluated_regular_staff = (
                        StaffAppraisal.objects.filter(
                            profile__user__in=regular_staff,
                            period=current_period,
                            status__in=["reviewed", "finalized"],
                        )
                        .values("profile__user")
                        .distinct()
                        .count()
                    )

                    total_evaluated_staff = (
                        evaluated_supervisors + evaluated_regular_staff
                    )

                    # 3. CALCULATE EVALUATION RATE
                    total_evaluable_staff = (
                        supervisors_count + regular_staff_count
                    )
                    if total_evaluable_staff > 0:
                        evaluation_rate = round(
                            (total_evaluated_staff / total_evaluable_staff)
                            * 100,
                            1,
                        )

                    # 4. CALCULATE AVERAGE SCORE
                    all_scores = []

                    # Get staff appraisal scores
                    staff_scores = StaffAppraisal.objects.filter(
                        profile__user__in=regular_staff,
                        period=current_period,
                        status__in=["reviewed", "finalized"],
                        overall_score__isnull=False,
                    ).values_list("overall_score", flat=True)

                    all_scores.extend(list(staff_scores))

                    # Get supervisor appraisal scores (if using SupervisorAppraisal)
                    supervisor_appraisal_scores = (
                        SupervisorAppraisal.objects.filter(
                            supervisor__in=supervisors,
                            period=current_period,
                            overall_score__isnull=False,
                        ).values_list("overall_score", flat=True)
                    )

                    all_scores.extend(list(supervisor_appraisal_scores))

                    # Get supervisor rating scores from SupervisorRating - FIXED HERE
                    # Calculate average rating per supervisor
                    supervisor_ratings_qs = SupervisorRating.objects.filter(
                        supervisor__in=supervisors,
                        period=current_period,
                        rating__isnull=False,  # Changed from 'overall_rating' to 'rating'
                    )

                    # Calculate average rating for each supervisor
                    supervisor_avg_ratings = supervisor_ratings_qs.values(
                        "supervisor"
                    ).annotate(avg_rating=Avg("rating"))

                    for item in supervisor_avg_ratings:
                        if item["avg_rating"]:
                            all_scores.append(item["avg_rating"])

                    if all_scores:
                        avg_score = sum(all_scores) / len(all_scores)

                    # 5. CALCULATE TARGETS COMPLETION
                    # Approved targets
                    approved_supervisor_targets = (
                        SupervisorPerformanceTarget.objects.filter(
                            supervisor__in=supervisors,
                            period=current_period,
                            status="approved",
                        ).count()
                    )

                    approved_staff_targets = PerformanceTarget.objects.filter(
                        staff__in=regular_staff,
                        period=current_period,
                        status="approved",
                    ).count()

                    total_approved_targets = (
                        approved_supervisor_targets + approved_staff_targets
                    )

                    # Total targets
                    total_supervisor_targets = (
                        SupervisorPerformanceTarget.objects.filter(
                            supervisor__in=supervisors, period=current_period
                        ).count()
                    )

                    total_staff_targets = PerformanceTarget.objects.filter(
                        staff__in=regular_staff, period=current_period
                    ).count()

                    total_targets = (
                        total_supervisor_targets + total_staff_targets
                    )

                    if total_targets > 0:
                        targets_completion = round(
                            (total_approved_targets / total_targets) * 100, 1
                        )

                department_data.append(
                    {
                        "department": department,
                        "total_staff": total_staff,
                        "supervisors_count": supervisors_count,
                        "regular_staff_count": regular_staff_count,
                        "total_evaluations": total_evaluations,
                        "evaluation_rate": evaluation_rate,
                        "average_score": (
                            round(avg_score, 1) if avg_score else 0
                        ),
                        "targets_completion": targets_completion,
                    }
                )

            total_all_staff = sum(
                dept["total_staff"] for dept in department_data
            )
            total_supervisors = sum(
                dept["supervisors_count"] for dept in department_data
            )

            return {
                "success": True,
                "department_data": department_data,
                "total_departments": departments.count(),
                "total_all_staff": total_all_staff,
                "total_supervisors": total_supervisors,
                "total_regular_staff": total_regular_staff_all,
                "current_period": current_period,
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Error retrieving department overview: {str(e)}",
            }

    @staticmethod
    def get_department_staff_detail(department_id):
        """Get detailed staff information for a specific department"""
        try:
            department = Department.objects.get(id=department_id)
            current_period = SPEPeriod.objects.filter(is_active=True).first()

            # Get all active staff in this department
            staff_members = CustomUser.objects.filter(
                department=department,
                role__in=["teaching", "non_teaching", "supervisor"],
                is_active=True,
            ).order_by("first_name", "last_name")

            # Enhance staff data with performance information
            staff_data = []
            for user in staff_members:
                staff_info = {
                    "user": user,
                    "role": user.role,
                    "performance_score": None,
                    "total_appraisals": 0,
                    "last_evaluation": None,
                    "approved_targets": 0,
                    "total_targets": 0,
                    "completion_rate": 0,
                    "is_active": user.is_active,
                }

                if current_period:
                    if user.role == "supervisor":
                        # Supervisor performance data
                        ratings = SupervisorRating.objects.filter(
                            supervisor=user, period=current_period
                        )

                        # Get average rating if available - FIXED HERE
                        if ratings.exists():
                            avg_rating = ratings.aggregate(avg=Avg("rating"))[
                                "avg"
                            ]  # Changed from 'overall_rating' to 'rating'
                            if avg_rating:
                                staff_info["performance_score"] = round(
                                    avg_rating, 1
                                )

                        # Current period targets
                        current_targets = (
                            SupervisorPerformanceTarget.objects.filter(
                                supervisor=user, period=current_period
                            )
                        )
                        approved_targets = current_targets.filter(
                            status="approved"
                        ).count()
                        total_targets = current_targets.count()

                        staff_info["approved_targets"] = approved_targets
                        staff_info["total_targets"] = total_targets
                        staff_info["completion_rate"] = (
                            round((approved_targets / total_targets * 100), 1)
                            if total_targets > 0
                            else 0
                        )

                    elif user.role in ["teaching", "non_teaching"]:
                        # Regular staff performance data
                        appraisals = StaffAppraisal.objects.filter(
                            profile__user=user,
                            period=current_period,
                            status__in=["reviewed", "finalized"],
                        )

                        # Get average score if available
                        if appraisals.exists():
                            avg_score = appraisals.filter(
                                overall_score__isnull=False
                            ).aggregate(avg=Avg("overall_score"))["avg"]
                            if avg_score:
                                staff_info["performance_score"] = round(
                                    avg_score, 1
                                )

                        # Current period targets
                        current_targets = PerformanceTarget.objects.filter(
                            staff=user, period=current_period
                        )
                        approved_targets = current_targets.filter(
                            status="approved"
                        ).count()
                        total_targets = current_targets.count()

                        staff_info["approved_targets"] = approved_targets
                        staff_info["total_targets"] = total_targets
                        staff_info["completion_rate"] = (
                            round((approved_targets / total_targets * 100), 1)
                            if total_targets > 0
                            else 0
                        )

                staff_data.append(staff_info)

            # Calculate department statistics
            supervisors_count = len(
                [s for s in staff_data if s["role"] == "supervisor"]
            )
            regular_staff_count = len(
                [
                    s
                    for s in staff_data
                    if s["role"] in ["teaching", "non_teaching"]
                ]
            )
            active_staff_count = len([s for s in staff_data if s["is_active"]])

            # Calculate average performance score
            all_scores = [
                s["performance_score"]
                for s in staff_data
                if s["performance_score"] is not None
            ]
            avg_performance_score = (
                round(sum(all_scores) / len(all_scores), 1)
                if all_scores
                else 0
            )

            return {
                "success": True,
                "department": department,
                "staff_data": staff_data,
                "current_period": current_period,
                "supervisors_count": supervisors_count,
                "regular_staff_count": regular_staff_count,
                "total_staff": len(staff_data),
                "active_staff_count": active_staff_count,
                "avg_performance_score": avg_performance_score,
            }

        except Department.DoesNotExist:
            return {"success": False, "error": "Department not found."}
        except Exception as e:
            return {
                "success": False,
                "error": f"Error retrieving department staff: {str(e)}",
            }

    @staticmethod
    def get_department_performance_stats(department_id=None):
        """Get performance statistics for departments"""
        try:
            current_period = SPEPeriod.objects.filter(is_active=True).first()
            if not current_period:
                return {
                    "success": False,
                    "error": "No active evaluation period found.",
                }

            departments = Department.objects.all()
            if department_id:
                departments = departments.filter(id=department_id)

            performance_data = []

            for department in departments:
                # Get all active staff in department
                all_staff = CustomUser.objects.filter(
                    department=department,
                    role__in=["teaching", "non_teaching", "supervisor"],
                    is_active=True,
                )

                supervisors = all_staff.filter(role="supervisor")
                regular_staff = all_staff.filter(
                    role__in=["teaching", "non_teaching"]
                )

                total_supervisors = supervisors.count()
                total_regular_staff = regular_staff.count()
                total_staff = all_staff.count()

                # Get evaluations for all staff
                supervisor_ratings = SupervisorRating.objects.filter(
                    supervisor__in=supervisors, period=current_period
                )

                supervisor_appraisals = SupervisorAppraisal.objects.filter(
                    supervisor__in=supervisors,
                    period=current_period,
                    status__in=["evaluated", "completed", "approved"],
                )

                staff_appraisals = StaffAppraisal.objects.filter(
                    profile__user__in=regular_staff,
                    period=current_period,
                    status__in=["reviewed", "finalized", "completed"],
                )

                # Count evaluated staff
                evaluated_supervisors = (
                    supervisor_ratings.values("supervisor").distinct().count()
                )
                evaluated_regular_staff = (
                    staff_appraisals.values("profile__user").distinct().count()
                )
                total_evaluated = (
                    evaluated_supervisors + evaluated_regular_staff
                )

                # Calculate evaluation rate for ALL staff
                evaluation_rate = (
                    round((total_evaluated / total_staff * 100), 1)
                    if total_staff > 0
                    else 0
                )

                # Get all scores for average calculation
                all_scores = []

                # Supervisor scores from ratings - FIXED HERE
                supervisor_rating_avgs = (
                    supervisor_ratings.filter(
                        rating__isnull=False  # Changed from 'overall_rating' to 'rating'
                    )
                    .values("supervisor")
                    .annotate(avg_rating=Avg("rating"))
                )

                for item in supervisor_rating_avgs:
                    if item["avg_rating"]:
                        all_scores.append(item["avg_rating"])

                # Supervisor scores from appraisals
                supervisor_appraisal_scores = supervisor_appraisals.filter(
                    overall_score__isnull=False
                ).values_list("overall_score", flat=True)
                all_scores.extend(list(supervisor_appraisal_scores))

                # Staff scores from appraisals
                staff_scores = staff_appraisals.filter(
                    overall_score__isnull=False
                ).values_list("overall_score", flat=True)
                all_scores.extend(list(staff_scores))

                if all_scores:
                    avg_score = sum(all_scores) / len(all_scores)
                    max_score = max(all_scores)
                    min_score = min(all_scores)
                else:
                    avg_score = max_score = min_score = 0

                # Score distribution
                excellent_count = len([s for s in all_scores if s >= 85])
                good_count = len([s for s in all_scores if 70 <= s < 85])
                average_count = len([s for s in all_scores if 50 <= s < 70])
                poor_count = len([s for s in all_scores if s < 50])

                performance_data.append(
                    {
                        "department": department,
                        "total_staff": total_staff,
                        "total_supervisors": total_supervisors,
                        "total_regular_staff": total_regular_staff,
                        "evaluated_staff": total_evaluated,
                        "evaluation_rate": evaluation_rate,
                        "avg_score": round(avg_score, 1),
                        "max_score": round(max_score, 1) if max_score else 0,
                        "min_score": round(min_score, 1) if min_score else 0,
                        "score_distribution": {
                            "excellent": excellent_count,
                            "good": good_count,
                            "average": average_count,
                            "poor": poor_count,
                        },
                    }
                )

            return {
                "success": True,
                "performance_data": performance_data,
                "current_period": current_period,
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"Error retrieving performance statistics: {str(e)}",
            }
