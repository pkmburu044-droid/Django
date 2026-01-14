# users/services.py
from typing import Dict, List

from django.db import transaction

from hr.models import (
    SupervisorAppraisal,
    SupervisorAttribute,
    SupervisorEvaluation,
    SupervisorIndicator,
    SupervisorPerformanceTarget,
)
from spe.models import (
    SelfAssessment,
    SPEAttribute,
    SPEPeriod,
    SupervisorRating,
)
from users.models import StaffProfile

from .models import StaffAppraisal, StaffProfile


class AppraisalService:
    """
    Handles staff appraisal business logic
    """

    @classmethod
    def submit_self_assessment(
        cls, staff_user, period, assessment_data: List[Dict]
    ):
        """
        Handle self-assessment submission with all related records
        """
        try:
            with transaction.atomic():
                profile = StaffProfile.objects.get(user=staff_user)

                # Get or create appraisal
                appraisal, created = StaffAppraisal.objects.get_or_create(
                    profile=profile,
                    period=period,
                    defaults={"status": "draft"},
                )

                # Save self-assessments
                for data in assessment_data:
                    SelfAssessment.objects.update_or_create(
                        appraisal=appraisal,
                        attribute=data["attribute"],
                        indicator=data["indicator"],
                        defaults={
                            "self_rating": data["rating"],
                            "remarks": data.get("remarks"),
                        },
                    )

                # Update appraisal status
                appraisal.status = "submitted"
                appraisal.save()

                return True, "Self-assessment submitted successfully"

        except Exception as e:
            return False, f"Error submitting self-assessment: {str(e)}"

    @classmethod
    def initialize_self_assessments(cls, staff_user, period):
        """
        Initialize self-assessment records for a staff member
        """
        profile = StaffProfile.objects.get(user=staff_user)
        appraisal, _ = StaffAppraisal.objects.get_or_create(
            profile=profile, period=period, defaults={"status": "draft"}
        )

        # Get attributes for staff type
        staff_type = (
            "teaching" if staff_user.role == "teaching" else "non_teaching"
        )
        attributes = SPEAttribute.objects.filter(
            period=period, staff_type=staff_type, department=profile.department
        ).prefetch_related("indicators")

        # Create self-assessment records
        for attribute in attributes:
            for indicator in attribute.indicators.all():
                SelfAssessment.objects.get_or_create(
                    appraisal=appraisal,
                    attribute=attribute,
                    indicator=indicator,
                    defaults={
                        "self_rating": 3,  # Default rating
                        "remarks": "",
                    },
                )

        return appraisal


class SupervisorReportService:
    """
    Service class for handling supervisor report-related operations
    """

    @classmethod
    def get_supervisor_self_report(cls, user):
        """
        Get comprehensive self-report data for a supervisor
        """
        try:
            # Get supervisor's profile
            try:
                profile = StaffProfile.objects.get(user=user)
            except StaffProfile.DoesNotExist:
                return {
                    "success": False,
                    "message": "Please complete your profile first.",
                }

            # Get active period
            period = SPEPeriod.objects.filter(is_active=True).first()
            if not period:
                return {
                    "success": False,
                    "message": "No active evaluation period.",
                }

            # Get supervisor's own appraisal
            appraisal = SupervisorAppraisal.objects.filter(
                supervisor=user,
                period=period,
                status__in=["evaluated", "completed", "approved"],
            ).first()

            if not appraisal:
                return {
                    "success": False,
                    "message": "You haven't been evaluated for the current period.",
                }

            # Get supervisor attributes and indicators
            supervisor_attributes = SupervisorAttribute.objects.filter(
                is_active=True
            )
            supervisor_indicators = SupervisorIndicator.objects.filter(
                attribute__in=supervisor_attributes, is_active=True
            ).select_related("attribute")

            # Get evaluations for this supervisor
            vc_evaluations = SupervisorEvaluation.objects.filter(
                supervisor=user, period=period
            ).select_related("attribute", "indicator")

            self_ratings = SupervisorRating.objects.filter(
                supervisor=user, period=period
            ).select_related("attribute", "indicator")

            # Get approved targets
            approved_targets = SupervisorPerformanceTarget.objects.filter(
                supervisor=user, period=period, status="approved"
            ).order_by("target_number")

            # Create dictionaries for easy lookup
            vc_ratings_dict = {}
            for eval in vc_evaluations:
                if eval.indicator:
                    vc_ratings_dict[eval.indicator.id] = eval

            self_ratings_dict = {}
            for rating in self_ratings:
                if rating.indicator:
                    self_ratings_dict[rating.indicator.id] = rating

            # Prepare criteria data with both ratings
            criteria_data = []
            for indicator in supervisor_indicators:
                vc_evaluation = vc_ratings_dict.get(indicator.id)
                self_rating = self_ratings_dict.get(indicator.id)

                criteria_data.append(
                    {
                        "attribute": indicator.attribute,
                        "indicator": indicator,
                        "vc_rating": (
                            vc_evaluation.rating if vc_evaluation else None
                        ),
                        "vc_comments": (
                            vc_evaluation.comments if vc_evaluation else ""
                        ),
                        "self_rating": (
                            self_rating.rating if self_rating else None
                        ),
                        "self_comments": (
                            self_rating.comments if self_rating else ""
                        ),
                        "rating_gap": (
                            (vc_evaluation.rating - self_rating.rating)
                            if vc_evaluation and self_rating
                            else None
                        ),
                    }
                )

            # Calculate statistics
            total_criteria = len(criteria_data)
            criteria_with_both_ratings = len(
                [
                    c
                    for c in criteria_data
                    if c["vc_rating"] is not None
                    and c["self_rating"] is not None
                ]
            )

            if criteria_with_both_ratings > 0:
                total_rating_gap = sum(
                    [
                        c["rating_gap"]
                        for c in criteria_data
                        if c["rating_gap"] is not None
                    ]
                )
                average_rating_gap = (
                    total_rating_gap / criteria_with_both_ratings
                )
            else:
                average_rating_gap = 0

            # Calculate percentage scores
            if appraisal.criteria_score:
                criteria_percentage = (appraisal.criteria_score / 5) * 100
            else:
                criteria_percentage = 0

            if appraisal.target_score:
                target_percentage = (appraisal.target_score / 5) * 100
            else:
                target_percentage = 0

            context = {
                "appraisal": appraisal,
                "criteria_data": criteria_data,
                "approved_targets": approved_targets,
                "total_criteria": total_criteria,
                "criteria_with_both_ratings": criteria_with_both_ratings,
                "average_rating_gap": round(average_rating_gap, 2),
                "criteria_percentage": round(criteria_percentage, 2),
                "target_percentage": round(target_percentage, 2),
                "period": period,
                "evaluated_by": (
                    appraisal.evaluated_by.get_full_name()
                    if appraisal.evaluated_by
                    else "Vice Chancellor"
                ),
            }

            return {"success": True, "context": context}

        except Exception as e:
            return {
                "success": False,
                "message": f"Error loading report: {str(e)}",
            }

    @classmethod
    def get_supervisor_evaluation_status(cls, user):
        """
        Check if supervisor has been evaluated in current period
        """
        period = SPEPeriod.objects.filter(is_active=True).first()
        if not period:
            return {"has_evaluation": False, "message": "No active period"}

        appraisal = SupervisorAppraisal.objects.filter(
            supervisor=user,
            period=period,
            status__in=["evaluated", "completed", "approved"],
        ).first()

        return {
            "has_evaluation": appraisal is not None,
            "appraisal": appraisal,
            "period": period,
        }
