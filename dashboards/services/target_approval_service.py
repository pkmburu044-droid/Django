# dashboards/services/target_approval_service.py
import logging

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Avg, Count
from django.shortcuts import get_object_or_404
from django.utils import timezone

from spe.models import SPEPeriod
from users.models import CustomUser, PerformanceTarget, StaffProfile

from .performance_calculations import (
    StaffPerformanceCalculator,
    TargetCalculator,
)

logger = logging.getLogger(__name__)


class TargetApprovalService:
    """Comprehensive service for handling supervisor target approval operations"""

    @staticmethod
    def validate_supervisor_permission(user):
        """Check if user has supervisor permissions"""
        if not (
            user.role == "supervisor"
            or getattr(user.staffprofile, "supervisor", False)
        ):
            raise PermissionDenied("Only supervisors can approve targets.")

        supervisor_profile = user.staffprofile
        if not supervisor_profile.department:
            raise PermissionDenied("You are not assigned to any department.")

        return supervisor_profile

    @staticmethod
    def validate_staff_access(supervisor_profile, staff_user):
        """Validate that supervisor can access this staff member's targets"""
        staff_profile = staff_user.staffprofile

        is_authorized = (
            staff_profile.department
            and staff_profile.department == supervisor_profile.department
            and staff_user.role == supervisor_profile.department.staff_type
        )

        if not is_authorized:
            expected_role = (
                supervisor_profile.department.get_staff_type_display()
            )
            actual_role = staff_user.role
            expected_dept = supervisor_profile.department.name
            actual_dept = (
                staff_profile.department.name
                if staff_profile.department
                else "No department"
            )

            raise PermissionDenied(
                f"Access denied. You are a {expected_role} supervisor in {expected_dept}. "
                f"You can only view {supervisor_profile.department.staff_type} staff from your department. "
                f"This staff member is {actual_role} in {actual_dept}."
            )

        return staff_profile

    @staticmethod
    def get_department_staff(supervisor_department, exclude_user=None):
        """Get all staff from supervisor's department with matching staff type"""
        queryset = StaffProfile.objects.filter(
            department=supervisor_department,
            user__role=supervisor_department.staff_type,
        ).select_related("user")

        if exclude_user:
            queryset = queryset.exclude(user=exclude_user)

        return queryset

    @staticmethod
    def get_staff_with_targets_summary(supervisor, current_period=None):
        """Get summary of all staff with their target statistics"""
        supervisor_profile = supervisor.staffprofile
        department_staff = TargetApprovalService.get_department_staff(
            supervisor_profile.department, exclude_user=supervisor
        )

        staff_list = []
        total_pending_count = 0
        staff_with_targets_count = 0

        for staff_profile in department_staff:
            staff_user = staff_profile.user

            # Get target statistics using StaffPerformanceCalculator
            target_stats = (
                StaffPerformanceCalculator.calculate_target_statistics(
                    staff_user, current_period
                )
            )

            staff_data = {
                "id": staff_user.id,
                "profile": staff_profile,
                "user": staff_user,
                "name": staff_user.get_full_name(),
                "designation": staff_profile.designation,
                "role": staff_user.role,
                "total_targets": target_stats["targets_count"],
                "pending_count": target_stats["pending_targets_count"],
                "approved_count": target_stats["approved_targets_count"],
                "rejected_count": target_stats["rejected_targets_count"],
                "completed_count": target_stats["completed_targets_count"],
                "has_targets": target_stats["targets_count"] > 0,
                "has_pending_approvals": target_stats["pending_targets_count"]
                > 0,
            }

            # Add performance metrics if available and period exists
            if current_period:
                # Use TargetCalculator for completion rate and rating
                staff_data["completion_rate"] = (
                    TargetCalculator.calculate_target_completion_rate(
                        staff_user, current_period
                    )
                )
                staff_data["average_rating"] = (
                    TargetCalculator.calculate_average_target_rating(
                        staff_user, current_period
                    )
                )

                # Get latest update
                latest_update = (
                    PerformanceTarget.objects.filter(
                        staff=staff_user, period=current_period
                    )
                    .order_by("-updated_at")
                    .first()
                )
                staff_data["latest_update"] = (
                    latest_update.updated_at if latest_update else None
                )

            staff_list.append(staff_data)
            total_pending_count += target_stats["pending_targets_count"]

            if target_stats["targets_count"] > 0:
                staff_with_targets_count += 1

        # Sort by pending count first, then name
        staff_list.sort(key=lambda x: (-x["pending_count"], x["name"]))

        return {
            "staff_list": staff_list,
            "total_staff": len(staff_list),
            "total_pending_count": total_pending_count,
            "staff_with_targets_count": staff_with_targets_count,
        }

    @staticmethod
    def get_staff_targets_details(staff_user, current_period):
        """Get detailed target information for a specific staff member"""
        if not current_period:
            return {
                "targets": PerformanceTarget.objects.none(),
                "stats": StaffPerformanceCalculator.calculate_target_statistics(
                    staff_user, None
                ),
                "completion_rate": 0,
                "average_rating": 0,
                "status_distribution": [],
                "has_targets": False,
            }

        targets = PerformanceTarget.objects.filter(
            staff=staff_user, period=current_period
        ).order_by("target_number")

        # Get statistics
        target_stats = StaffPerformanceCalculator.calculate_target_statistics(
            staff_user, current_period
        )

        # Get completion rate and average rating
        completion_rate = TargetCalculator.calculate_target_completion_rate(
            staff_user, current_period
        )
        average_rating = TargetCalculator.calculate_average_target_rating(
            staff_user, current_period
        )
        status_distribution = TargetCalculator.get_target_status_distribution(
            staff_user, current_period
        )

        return {
            "targets": targets,
            "stats": target_stats,
            "completion_rate": completion_rate,
            "average_rating": average_rating,
            "status_distribution": status_distribution,
            "has_targets": targets.exists(),
        }

    @staticmethod
    @transaction.atomic
    def approve_target(target_id, supervisor):
        """Approve a single target"""
        target = get_object_or_404(PerformanceTarget, id=target_id)

        # Validate supervisor permission
        supervisor_profile = (
            TargetApprovalService.validate_supervisor_permission(supervisor)
        )

        # Validate access to staff
        TargetApprovalService.validate_staff_access(
            supervisor_profile, target.staff
        )

        # Save original status before updating
        original_status = target.status

        # Update target
        target.status = "approved"
        if hasattr(target, "approved_by"):
            target.approved_by = supervisor
        if hasattr(target, "approved_at"):
            target.approved_at = timezone.now()

        # IMPORTANT FIX: Only try to clear rejection fields if they exist AND
        # if the field can accept empty string (not None)
        if original_status == "rejected":
            # Instead of setting to None, try empty string
            if hasattr(target, "rejection_reason") and target.rejection_reason:
                try:
                    # Try to save with empty string
                    target.rejection_reason = ""
                except:
                    # If empty string not allowed, try to leave it as is
                    pass

            # These fields can be set to None if they allow it
            if hasattr(target, "rejected_by"):
                try:
                    target.rejected_by = None
                except:
                    pass

            if hasattr(target, "rejected_at"):
                try:
                    target.rejected_at = None
                except:
                    pass

        target.save()

        return target

    @staticmethod
    @transaction.atomic
    def reject_target(target_id, supervisor, rejection_reason):
        """Reject a single target with reason"""
        if not rejection_reason:
            raise ValueError("Rejection reason is required")

        target = get_object_or_404(PerformanceTarget, id=target_id)

        # Validate supervisor permission
        supervisor_profile = (
            TargetApprovalService.validate_supervisor_permission(supervisor)
        )

        # Validate access to staff
        TargetApprovalService.validate_staff_access(
            supervisor_profile, target.staff
        )

        # Update target
        target.status = "rejected"
        if hasattr(target, "rejection_reason"):
            target.rejection_reason = rejection_reason
        if hasattr(target, "rejected_by"):
            target.rejected_by = supervisor
        if hasattr(target, "rejected_at"):
            target.rejected_at = timezone.now()

        target.save()

        return target

    @staticmethod
    @transaction.atomic
    def bulk_approve_targets(
        supervisor, target_ids, action, rejection_reason=""
    ):
        """Approve or reject multiple targets in bulk"""
        if not target_ids:
            return 0, "No targets selected"

        # Validate supervisor permission
        supervisor_profile = (
            TargetApprovalService.validate_supervisor_permission(supervisor)
        )
        supervisor_department = supervisor_profile.department

        with transaction.atomic():
            # Get targets that supervisor has permission to access
            targets = PerformanceTarget.objects.filter(
                id__in=target_ids,
                staff__staffprofile__department=supervisor_department,
                staff__role=supervisor_department.staff_type,
                status="pending",  # Only process pending targets for bulk operations
            ).select_related("staff")

            if not targets.exists():
                return 0, "No valid pending targets found"

            staff_names = set()

            for target in targets:
                original_status = target.status

                if action == "approve":
                    target.status = "approved"
                    if hasattr(target, "approved_by"):
                        target.approved_by = supervisor
                    if hasattr(target, "approved_at"):
                        target.approved_at = timezone.now()

                    # Only clear rejection fields if target was previously rejected
                    if original_status == "rejected":
                        # Use empty string instead of None for rejection_reason
                        if (
                            hasattr(target, "rejection_reason")
                            and target.rejection_reason
                        ):
                            try:
                                target.rejection_reason = ""
                            except:
                                pass

                        if hasattr(target, "rejected_by"):
                            try:
                                target.rejected_by = None
                            except:
                                pass

                        if hasattr(target, "rejected_at"):
                            try:
                                target.rejected_at = None
                            except:
                                pass

                elif action == "reject":
                    target.status = "rejected"
                    if hasattr(target, "rejection_reason"):
                        target.rejection_reason = rejection_reason
                    if hasattr(target, "rejected_by"):
                        target.rejected_by = supervisor
                    if hasattr(target, "rejected_at"):
                        target.rejected_at = timezone.now()

                target.save()
                staff_names.add(
                    f"{target.staff.first_name} {target.staff.last_name}"
                )

            # Format staff list for message
            staff_list = ", ".join(sorted(list(staff_names))[:3])
            if len(staff_names) > 3:
                staff_list += f" and {len(staff_names) - 3} more"

            return targets.count(), staff_list

    @staticmethod
    @transaction.atomic
    def approve_all_pending_for_staff(staff_id, supervisor):
        """Approve all pending targets for a specific staff member"""
        staff_user = get_object_or_404(CustomUser, id=staff_id)

        # Validate supervisor permission
        supervisor_profile = (
            TargetApprovalService.validate_supervisor_permission(supervisor)
        )

        # Validate access to staff
        TargetApprovalService.validate_staff_access(
            supervisor_profile, staff_user
        )

        # Get and approve all pending targets
        pending_targets = PerformanceTarget.objects.filter(
            staff=staff_user, status="pending"
        )

        approved_count = pending_targets.count()

        if approved_count > 0:
            # We need to update each target individually to handle rejection_reason properly
            for target in pending_targets:
                original_status = target.status
                target.status = "approved"
                if hasattr(target, "approved_by"):
                    target.approved_by = supervisor
                if hasattr(target, "approved_at"):
                    target.approved_at = timezone.now()

                # Handle rejection fields if target was previously rejected
                if original_status == "rejected":
                    if (
                        hasattr(target, "rejection_reason")
                        and target.rejection_reason
                    ):
                        try:
                            target.rejection_reason = ""
                        except:
                            pass

                target.save()

        return approved_count

    @staticmethod
    def get_approval_dashboard_data(supervisor):
        """Get all data needed for the approval dashboard"""
        supervisor_profile = supervisor.staffprofile
        supervisor_department = supervisor_profile.department

        current_period = SPEPeriod.objects.filter(is_active=True).first()

        # Get staff summary
        staff_summary = TargetApprovalService.get_staff_with_targets_summary(
            supervisor, current_period
        )

        # Get targets by status
        filters = {
            "staff__staffprofile__department": supervisor_department,
            "staff__role": supervisor_department.staff_type,
        }

        if current_period:
            filters["period"] = current_period

        pending_targets = PerformanceTarget.objects.filter(
            **filters, status="pending"
        ).select_related("staff", "period")

        approved_targets = PerformanceTarget.objects.filter(
            **filters, status="approved"
        ).select_related("staff", "period")

        rejected_targets = PerformanceTarget.objects.filter(
            **filters, status="rejected"
        ).select_related("staff", "period")

        # Calculate department-wide statistics
        department_stats = PerformanceTarget.objects.filter(
            **filters
        ).aggregate(
            total_targets=Count("id"),
            avg_performance_rating=Avg("performance_rating"),
        )

        # Calculate completion rate manually since there's no completion_percentage field
        total_targets = department_stats["total_targets"] or 0
        completed_targets = PerformanceTarget.objects.filter(
            **filters, status__in=["evaluated", "completed"]
        ).count()

        avg_completion_rate = 0
        if total_targets > 0:
            avg_completion_rate = round(
                (completed_targets / total_targets) * 100, 1
            )

        return {
            "current_period": current_period,
            "active_period": current_period,
            "staff_with_targets": staff_summary["staff_list"],
            "pending_targets": pending_targets,
            "approved_targets": approved_targets,
            "rejected_targets": rejected_targets,
            "pending_approval_count": pending_targets.count(),
            "total_pending_count": staff_summary["total_pending_count"],
            "total_targets_count": total_targets,
            "total_staff": staff_summary["total_staff"],
            "staff_with_targets_count": staff_summary[
                "staff_with_targets_count"
            ],
            "supervisor_department": supervisor_department,
            "department_stats": {
                "total_targets": total_targets,
                "avg_completion_rate": avg_completion_rate,
                "avg_performance_rating": department_stats[
                    "avg_performance_rating"
                ]
                or 0,
            },
        }

    @staticmethod
    def get_performance_insights(staff_user, current_period):
        """Get performance insights for a staff member"""
        target_details = TargetApprovalService.get_staff_targets_details(
            staff_user, current_period
        )

        completion_rate = target_details["completion_rate"]
        average_rating = target_details["average_rating"]

        return {
            "has_evaluated_targets": average_rating > 0,
            "completion_status": (
                "Excellent"
                if completion_rate >= 90
                else (
                    "Good"
                    if completion_rate >= 70
                    else (
                        "Needs Improvement"
                        if completion_rate >= 50
                        else "Poor"
                    )
                )
            ),
            "rating_status": (
                "Excellent"
                if average_rating >= 4.5
                else (
                    "Good"
                    if average_rating >= 3.5
                    else (
                        "Satisfactory"
                        if average_rating >= 2.5
                        else "Needs Improvement"
                    )
                )
            ),
            "completion_rate": completion_rate,
            "average_rating": average_rating,
        }

    # Add this method to the TargetApprovalService class

    @staticmethod
    @transaction.atomic
    def submit_or_resubmit_target(target_id, staff_user):
        """Staff member submits or resubmits a target for approval"""
        target = get_object_or_404(
            PerformanceTarget, id=target_id, staff=staff_user
        )

        # Check if target can be submitted
        if target.status not in ["draft", "rejected"]:
            raise PermissionDenied(
                f"Cannot submit target with status: {target.status}"
            )

        # For rejected targets, we need to handle them carefully
        if target.status == "rejected":
            # Create a new version or update the existing one
            # Change status to 'pending' without touching rejection_reason
            target.status = "pending"

            # Don't try to modify rejection_reason field since it has NOT NULL constraint
            # Just update the status and save
            target.save()

        elif target.status == "draft":
            # Regular draft submission
            target.status = "pending"
            target.save()

        return target
