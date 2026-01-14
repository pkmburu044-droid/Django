# dashboards/services/performance_calculations.py
from django.db.models import Avg, Count, Q

from hr.models import SupervisorPerformanceTarget
from spe.models import (
    NonTeachingStaffEvaluation,
    SelfAssessment,
    SupervisorEvaluation,
    TeachingStaffEvaluation,
)
from users.models import PerformanceTarget, StaffAppraisal, StaffProfile


class StaffPerformanceCalculator:
    """Service class to isolate staff performance calculation logic"""

    @staticmethod
    def calculate_combined_evaluation_score(staff_user, period):
        """
        Calculate combined score using formula: (self_rating + supervisor_rating) / 2
        This is used in multiple dashboard views
        """
        try:
            # Get self assessments for this period
            self_assessments = SelfAssessment.objects.filter(
                staff=staff_user, period=period
            )

            # Get supervisor evaluations for these self assessments
            evaluations = SupervisorEvaluation.objects.filter(
                self_assessment__in=self_assessments
            )

            total_combined_score = 0
            total_evaluations = 0

            for evaluation in evaluations:
                try:
                    # Get corresponding self-assessment
                    self_assessment = SelfAssessment.objects.get(
                        id=evaluation.self_assessment_id
                    )
                    # ✅ FIXED: Calculate average of self and supervisor ratings
                    combined_score = (
                        self_assessment.self_rating
                        + evaluation.supervisor_rating
                    ) / 2
                    total_combined_score += combined_score
                    total_evaluations += 1

                except SelfAssessment.DoesNotExist:
                    # If no self-assessment, use supervisor rating only
                    total_combined_score += evaluation.supervisor_rating
                    total_evaluations += 1

            if total_evaluations > 0:
                avg_score = total_combined_score / total_evaluations
                percentage_score = (avg_score / 5) * 100
                return {
                    "avg_score": round(avg_score, 1),
                    "percentage_score": round(percentage_score, 1),
                    "total_evaluations": total_evaluations,
                }

        except Exception as e:
            print(f"Error calculating combined score for {staff_user}: {e}")

        return {"avg_score": 0, "percentage_score": 0, "total_evaluations": 0}

    @staticmethod
    def calculate_performance_history(staff_user, limit=6):
        """Calculate performance history for dashboard graphs"""
        performance_history = []

        try:
            # Get reviewed appraisals
            reviewed_appraisals = StaffAppraisal.objects.filter(
                profile__user=staff_user, status="reviewed"
            ).order_by("-period__start_date")[:limit]

            for appraisal in reviewed_appraisals:
                # Calculate score for this appraisal period
                score_data = StaffPerformanceCalculator.calculate_combined_evaluation_score(
                    staff_user, appraisal.period
                )

                if score_data["total_evaluations"] > 0:
                    performance_history.append(
                        {
                            "period": appraisal.period.name,
                            "score": score_data["percentage_score"],
                            "date": appraisal.period.start_date.strftime(
                                "%b %Y"
                            ),
                            "rating": score_data["avg_score"],
                        }
                    )

        except Exception as e:
            print(f"Error generating performance history: {e}")

        return performance_history

    @staticmethod
    def calculate_target_statistics(staff_user, period):
        """Calculate performance target statistics"""
        if not period:
            return {
                "targets_count": 0,
                "approved_targets_count": 0,
                "pending_targets_count": 0,
                "completed_targets_count": 0,
                "rejected_targets_count": 0,
            }

        targets = PerformanceTarget.objects.filter(
            staff=staff_user, period=period
        )

        return {
            "targets_count": targets.count(),
            "approved_targets_count": targets.filter(
                status="approved"
            ).count(),
            "pending_targets_count": targets.filter(status="pending").count(),
            "completed_targets_count": targets.filter(
                status="completed"
            ).count(),
            "rejected_targets_count": targets.filter(
                status="rejected"
            ).count(),
        }


class SupervisorPerformanceCalculator:
    """Service class to isolate supervisor performance calculation logic"""

    @staticmethod
    def calculate_supervisor_combined_score(supervisor, period):
        """
        Calculate supervisor's combined score from criteria and targets
        Used in VC evaluation views
        """
        try:
            # Get VC evaluations for criteria
            vc_evaluations = SupervisorEvaluation.objects.filter(
                supervisor=supervisor, period=period
            )

            # Get target performance ratings
            approved_targets = SupervisorPerformanceTarget.objects.filter(
                supervisor=supervisor,
                period=period,
                status="approved",
                performance_rating__isnull=False,
            )

            criteria_total_score = 0
            criteria_count = vc_evaluations.count()
            target_total_score = 0
            target_count = approved_targets.count()

            # Calculate criteria average
            for evaluation in vc_evaluations:
                criteria_total_score += evaluation.rating

            # Calculate target average
            for target in approved_targets:
                target_total_score += target.performance_rating

            # Calculate weighted overall average (50% criteria, 50% targets)
            if criteria_count > 0 and target_count > 0:
                criteria_avg = criteria_total_score / criteria_count
                target_avg = target_total_score / target_count
                overall_avg = (criteria_avg * 0.5) + (target_avg * 0.5)
            elif criteria_count > 0:
                overall_avg = criteria_total_score / criteria_count
            elif target_count > 0:
                overall_avg = target_total_score / target_count
            else:
                overall_avg = 0

            overall_percentage = (overall_avg / 5) * 100

            return {
                "criteria_score": (
                    criteria_total_score / criteria_count
                    if criteria_count > 0
                    else 0
                ),
                "target_score": (
                    target_total_score / target_count
                    if target_count > 0
                    else 0
                ),
                "overall_score": round(overall_percentage, 1),
                "criteria_count": criteria_count,
                "target_count": target_count,
            }

        except Exception as e:
            print(f"Error calculating supervisor combined score: {e}")
            return {
                "criteria_score": 0,
                "target_score": 0,
                "overall_score": 0,
                "criteria_count": 0,
                "target_count": 0,
            }

    @staticmethod
    def calculate_department_performance(supervisor_department, period):
        """Calculate department-wide performance statistics"""
        try:
            # Get staff in department
            department_staff = StaffProfile.objects.filter(
                department=supervisor_department
            )

            total_staff = department_staff.count()

            # Count submitted appraisals
            submitted_appraisals = StaffAppraisal.objects.filter(
                profile__user__department=supervisor_department,
                period=period,
                status__in=["submitted", "reviewed"],
            ).count()

            # Count reviewed appraisals
            reviewed_appraisals = StaffAppraisal.objects.filter(
                profile__user__department=supervisor_department,
                period=period,
                status="reviewed",
            ).count()

            # Calculate average scores
            teaching_avg = (
                TeachingStaffEvaluation.objects.filter(
                    staff__department=supervisor_department,
                    period=period,
                    status="reviewed",
                ).aggregate(avg=Avg("percent_score"))["avg"]
                or 0
            )

            non_teaching_avg = (
                NonTeachingStaffEvaluation.objects.filter(
                    staff__department=supervisor_department,
                    period=period,
                    status="reviewed",
                ).aggregate(avg=Avg("percent_score"))["avg"]
                or 0
            )

            # Calculate weighted average
            teaching_count = TeachingStaffEvaluation.objects.filter(
                staff__department=supervisor_department,
                period=period,
                status="reviewed",
            ).count()

            non_teaching_count = NonTeachingStaffEvaluation.objects.filter(
                staff__department=supervisor_department,
                period=period,
                status="reviewed",
            ).count()

            total_count = teaching_count + non_teaching_count

            if total_count > 0:
                avg_department_score = (
                    (teaching_avg * teaching_count)
                    + (non_teaching_avg * non_teaching_count)
                ) / total_count
            else:
                avg_department_score = 0

            return {
                "total_staff": total_staff,
                "submitted_appraisals": submitted_appraisals,
                "reviewed_appraisals": reviewed_appraisals,
                "avg_department_score": round(avg_department_score, 1),
                "pending_evaluations": total_staff - reviewed_appraisals,
            }

        except Exception as e:
            print(f"Error calculating department performance: {e}")
            return {
                "total_staff": 0,
                "submitted_appraisals": 0,
                "reviewed_appraisals": 0,
                "avg_department_score": 0,
                "pending_evaluations": 0,
            }


class TargetCalculator:
    """Service class to isolate target calculation logic"""

    @staticmethod
    def calculate_target_completion_rate(staff_user, period):
        """Calculate percentage of completed targets"""
        targets = PerformanceTarget.objects.filter(
            staff=staff_user, period=period
        )
        total_targets = targets.count()
        completed_targets = targets.filter(
            Q(status="evaluated") | Q(performance_rating__isnull=False)
        ).count()

        if total_targets > 0:
            return round((completed_targets / total_targets) * 100, 1)
        return 0

    @staticmethod
    def calculate_average_target_rating(staff_user, period):
        """Calculate average rating for performance targets"""
        evaluated_targets = PerformanceTarget.objects.filter(
            staff=staff_user, period=period, performance_rating__isnull=False
        )

        avg_rating = (
            evaluated_targets.aggregate(avg=Avg("performance_rating"))["avg"]
            or 0
        )

        return round(avg_rating, 1)

    @staticmethod
    def get_target_status_distribution(staff_user, period):
        """Get distribution of target statuses"""
        targets = PerformanceTarget.objects.filter(
            staff=staff_user, period=period
        )

        status_distribution = (
            targets.values("status")
            .annotate(count=Count("id"))
            .order_by("status")
        )

        return list(status_distribution)
