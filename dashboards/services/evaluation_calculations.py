# dashboards/services/evaluation_calculations.py
from decimal import Decimal

from django.db.models import Avg, Q

from spe.models import SelfAssessment, SupervisorEvaluation
from users.models import PerformanceTarget


class EvaluationCalculator:
    """Service class to isolate evaluation calculation logic"""

    @staticmethod
    def calculate_staff_evaluation_results(appraisal):
        """
        Calculate comprehensive evaluation results for staff
        Used in staff_evaluation_results view
        """
        staff_user = appraisal.profile.user
        period = appraisal.period

        # Get self assessments
        self_assessments = SelfAssessment.objects.filter(
            staff=staff_user, period=period
        ).select_related("attribute", "indicator")

        # Get supervisor evaluations
        self_assessment_ids = [sa.id for sa in self_assessments]
        evaluations = SupervisorEvaluation.objects.filter(
            self_assessment_id__in=self_assessment_ids
        ).select_related(
            "self_assessment",
            "self_assessment__attribute",
            "self_assessment__indicator",
            "supervisor",
        )

        # Calculate combined scores for evaluations
        total_combined_score = 0
        evaluated_count = 0
        eval_dict = {}

        for eval_obj in evaluations:
            try:
                # Get corresponding self-assessment
                self_assessment = SelfAssessment.objects.get(
                    staff=staff_user,
                    period=period,
                    attribute=eval_obj.self_assessment.attribute,
                    indicator=eval_obj.self_assessment.indicator,
                )
                # Calculate average of self and supervisor ratings
                combined_score = (
                    self_assessment.self_rating + eval_obj.supervisor_rating
                ) / 2
                total_combined_score += combined_score
                evaluated_count += 1

                eval_dict[eval_obj.self_assessment_id] = {
                    "self_rating": self_assessment.self_rating,
                    "supervisor_rating": eval_obj.supervisor_rating,
                    "combined_score": round(combined_score, 1),
                    "remarks": eval_obj.remarks,
                    "supervisor_name": f"{eval_obj.supervisor.first_name} {eval_obj.supervisor.last_name}",
                    "attribute_name": eval_obj.self_assessment.attribute.name,
                    "indicator_description": eval_obj.self_assessment.indicator.description,
                }

            except SelfAssessment.DoesNotExist:
                # If no self-assessment, use supervisor rating only
                total_combined_score += eval_obj.supervisor_rating
                evaluated_count += 1

                eval_dict[eval_obj.self_assessment_id] = {
                    "self_rating": None,
                    "supervisor_rating": eval_obj.supervisor_rating,
                    "combined_score": eval_obj.supervisor_rating,
                    "remarks": eval_obj.remarks,
                    "supervisor_name": f"{eval_obj.supervisor.first_name} {eval_obj.supervisor.last_name}",
                    "attribute_name": eval_obj.self_assessment.attribute.name,
                    "indicator_description": eval_obj.self_assessment.indicator.description,
                }

        # Calculate final scores
        avg_score = (
            total_combined_score / evaluated_count
            if evaluated_count > 0
            else 0
        )
        percentage_score = (avg_score / 5) * 100

        # Performance category
        if percentage_score >= 90:
            performance = "Outstanding"
            performance_class = "success"
        elif percentage_score >= 80:
            performance = "Exceeds Expectations"
            performance_class = "success"
        elif percentage_score >= 50:
            performance = "Meets Expectations"
            performance_class = "info"
        elif percentage_score >= 30:
            performance = "Below Expectations"
            performance_class = "warning"
        else:
            performance = "Far Below Expectations"
            performance_class = "danger"

        return {
            "self_assessments": self_assessments,
            "supervisor_evals": eval_dict,
            "summary": {
                "total_indicators": evaluated_count,
                "avg_score": round(avg_score, 2),
                "percentage_score": round(percentage_score, 2),
                "supervisor_name": (
                    evaluations[0].supervisor.get_full_name()
                    if evaluations
                    else "Unknown"
                ),
            },
            "performance": performance,
            "performance_class": performance_class,
        }

    @staticmethod
    def calculate_target_evaluation_results(staff_user, period):
        """
        Calculate comprehensive target evaluation results
        """
        performance_targets = PerformanceTarget.objects.filter(
            staff=staff_user, period=period
        ).order_by("target_number")

        # Target evaluation statistics
        evaluated_targets = performance_targets.filter(
            Q(performance_rating__isnull=False)
            | Q(supervisor_comments__isnull=False)
        )

        target_status_counts = {
            "draft": performance_targets.filter(status="draft").count(),
            "pending": performance_targets.filter(status="pending").count(),
            "approved": performance_targets.filter(status="approved").count(),
            "rejected": performance_targets.filter(status="rejected").count(),
            "completed": performance_targets.filter(
                status="completed"
            ).count(),
        }

        # Calculate average target rating
        avg_target_rating_result = performance_targets.aggregate(
            avg_rating=Avg("performance_rating")
        )["avg_rating"]
        avg_target_rating = (
            float(avg_target_rating_result)
            if avg_target_rating_result
            else 0.0
        )

        target_evaluation_stats = {
            "total_targets": performance_targets.count(),
            "approved_targets": performance_targets.filter(
                status="approved"
            ).count(),
            "completed_targets": performance_targets.filter(
                status="completed"
            ).count(),
            "evaluated_targets": evaluated_targets.count(),
            "pending_evaluation": performance_targets.filter(
                status="approved", performance_rating__isnull=True
            ).count(),
            "average_target_rating": avg_target_rating,
            "target_completion_rate": (
                (
                    performance_targets.filter(status="completed").count()
                    / performance_targets.count()
                    * 100
                )
                if performance_targets.count() > 0
                else 0
            ),
            "evaluation_completion_rate": (
                (
                    evaluated_targets.count()
                    / performance_targets.filter(status="approved").count()
                    * 100
                )
                if performance_targets.filter(status="approved").count() > 0
                else 0
            ),
        }

        # Individual target evaluation details
        target_evaluations = []
        total_target_score = 0
        evaluated_target_count = 0

        for target in performance_targets:
            target_data = {
                "target_number": target.target_number,
                "description": target.description,
                "success_measures": target.success_measures,
                "status": target.status,
                "status_display": target.get_status_display(),
                "rating_scale": target.rating_scale,
                "performance_rating": target.performance_rating,
                "supervisor_comments": target.supervisor_comments,
                "evaluated_at": target.evaluated_at,
                "evaluated_by": target.evaluated_by,
                "is_evaluated": target.performance_rating is not None,
                "is_approved": target.status == "approved",
                "is_completed": target.status == "completed",
            }

            # Calculate individual target score
            if target.performance_rating is not None:
                target_score = (
                    float(target.performance_rating)
                    if isinstance(target.performance_rating, Decimal)
                    else target.performance_rating
                )
                total_target_score += target_score
                evaluated_target_count += 1

                # Add performance category
                if target_score >= 90:
                    target_data["performance_category"] = "Outstanding"
                    target_data["performance_class"] = "success"
                elif target_score >= 80:
                    target_data["performance_category"] = "Excellent"
                    target_data["performance_class"] = "success"
                elif target_score >= 70:
                    target_data["performance_category"] = "Good"
                    target_data["performance_class"] = "info"
                elif target_score >= 60:
                    target_data["performance_category"] = "Satisfactory"
                    target_data["performance_class"] = "warning"
                elif target_score >= 50:
                    target_data["performance_category"] = "Needs Improvement"
                    target_data["performance_class"] = "warning"
                else:
                    target_data["performance_category"] = "Unsatisfactory"
                    target_data["performance_class"] = "danger"

            target_evaluations.append(target_data)

        # Overall target performance summary
        overall_target_average = (
            total_target_score / evaluated_target_count
            if evaluated_target_count > 0
            else 0
        )

        overall_target_rating = "Not Evaluated"
        if evaluated_target_count > 0:
            if overall_target_average >= 90:
                overall_target_rating = "Outstanding"
            elif overall_target_average >= 80:
                overall_target_rating = "Excellent"
            elif overall_target_average >= 70:
                overall_target_rating = "Good"
            elif overall_target_average >= 60:
                overall_target_rating = "Satisfactory"
            elif overall_target_average >= 50:
                overall_target_rating = "Needs Improvement"
            else:
                overall_target_rating = "Unsatisfactory"

        overall_target_performance = {
            "average_score": round(overall_target_average, 1),
            "evaluated_count": evaluated_target_count,
            "overall_rating": overall_target_rating,
            "completion_percentage": target_evaluation_stats[
                "evaluation_completion_rate"
            ],
        }

        return {
            "performance_targets": performance_targets,
            "target_evaluations": target_evaluations,
            "target_stats": target_evaluation_stats,
            "target_status_counts": target_status_counts,
            "overall_target_performance": overall_target_performance,
            "has_targets": performance_targets.exists(),
            "has_evaluated_targets": evaluated_target_count > 0,
        }


class TargetCalculator:
    """Calculator for target-related evaluations and performance metrics"""

    @staticmethod
    def calculate_target_score(approved_targets, total_targets):
        """Calculate target completion score"""
        if total_targets == 0:
            return 0
        return round((approved_targets / total_targets) * 100, 1)

    @staticmethod
    def calculate_performance_rating(target_ratings):
        """Calculate average performance rating from target ratings"""
        if not target_ratings:
            return 0
        valid_ratings = [
            rating for rating in target_ratings if rating is not None
        ]
        if not valid_ratings:
            return 0
        return round(sum(valid_ratings) / len(valid_ratings), 1)

    @staticmethod
    def get_target_completion_stats(targets):
        """Get comprehensive target completion statistics"""
        total_targets = targets.count()
        approved_targets = targets.filter(status="approved").count()
        completed_targets = targets.filter(status="completed").count()
        pending_targets = targets.filter(status="pending").count()
        rejected_targets = targets.filter(status="rejected").count()
        draft_targets = targets.filter(status="draft").count()

        completion_rate = TargetCalculator.calculate_target_score(
            completed_targets, total_targets
        )
        approval_rate = TargetCalculator.calculate_target_score(
            approved_targets, total_targets
        )

        return {
            "total_targets": total_targets,
            "approved_targets": approved_targets,
            "completed_targets": completed_targets,
            "pending_targets": pending_targets,
            "rejected_targets": rejected_targets,
            "draft_targets": draft_targets,
            "completion_rate": completion_rate,
            "approval_rate": approval_rate,
            "pending_approval_count": pending_targets + rejected_targets,
        }

    @staticmethod
    def calculate_supervisor_target_stats(supervisor, period):
        """Calculate target statistics for a supervisor"""
        from hr.models import SupervisorPerformanceTarget

        targets = SupervisorPerformanceTarget.objects.filter(
            supervisor=supervisor, period=period
        )

        stats = TargetCalculator.get_target_completion_stats(targets)

        # Calculate ratings for approved targets
        approved_targets_with_ratings = targets.filter(
            status="approved", performance_rating__isnull=False
        )
        average_rating = (
            approved_targets_with_ratings.aggregate(Avg("performance_rating"))[
                "performance_rating__avg"
            ]
            or 0
        )

        stats["average_rating"] = round(average_rating, 1)
        stats["rated_targets"] = approved_targets_with_ratings.count()
        stats["pending_rating_count"] = (
            stats["approved_targets"] - stats["rated_targets"]
        )

        return stats

    @staticmethod
    def calculate_department_target_stats(department, period):
        """Calculate target statistics for a department"""
        from hr.models import SupervisorPerformanceTarget

        targets = SupervisorPerformanceTarget.objects.filter(
            supervisor__staffprofile__department=department, period=period
        )

        return TargetCalculator.get_target_completion_stats(targets)

    @staticmethod
    def get_performance_category(score):
        """Get performance category based on score"""
        if score >= 90:
            return {"category": "Outstanding", "class": "success"}
        elif score >= 80:
            return {"category": "Excellent", "class": "success"}
        elif score >= 70:
            return {"category": "Good", "class": "info"}
        elif score >= 60:
            return {"category": "Satisfactory", "class": "warning"}
        elif score >= 50:
            return {"category": "Needs Improvement", "class": "warning"}
        else:
            return {"category": "Unsatisfactory", "class": "danger"}

    @staticmethod
    def calculate_overall_target_performance(targets):
        """Calculate overall performance metrics for targets"""
        stats = TargetCalculator.get_target_completion_stats(targets)

        # Get performance ratings
        rated_targets = targets.filter(performance_rating__isnull=False)
        ratings = [target.performance_rating for target in rated_targets]

        if ratings:
            avg_rating = sum(ratings) / len(ratings)
            performance_category = TargetCalculator.get_performance_category(
                avg_rating
            )
        else:
            avg_rating = 0
            performance_category = {
                "category": "Not Rated",
                "class": "secondary",
            }

        stats.update(
            {
                "average_rating": round(avg_rating, 1),
                "rated_targets_count": len(ratings),
                "performance_category": performance_category["category"],
                "performance_class": performance_category["class"],
            }
        )

        return stats
