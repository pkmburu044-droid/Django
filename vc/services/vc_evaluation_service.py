# vc/services/vc_evaluation_service.py
from django.contrib.auth import get_user_model

from hr.models import SupervisorAppraisal, SupervisorEvaluation
from spe.models import SPEPeriod, SupervisorRating

CustomUser = get_user_model()


class VCEvaluationService:
    """Service class for VC evaluation operations"""

    @staticmethod
    def get_supervisor_evaluation_list():
        """Get list of supervisors for VC evaluation"""
        try:
            current_period = SPEPeriod.objects.filter(is_active=True).first()
            if not current_period:
                return {
                    "success": False,
                    "error": "No active evaluation period found.",
                }

            # Get all supervisors
            supervisors = CustomUser.objects.filter(
                role="supervisor", is_active=True
            ).select_related("staffprofile__department")

            # Enhance supervisor data with evaluation status
            supervisor_data = []
            for supervisor in supervisors:
                # Get appraisal for current period
                appraisal = SupervisorAppraisal.objects.filter(
                    supervisor=supervisor, period=current_period
                ).first()

                # Check if supervisor has targets
                has_targets = supervisor.supervisor_performance_targets.filter(
                    period=current_period, status="approved"
                ).exists()

                # Check if VC has already evaluated
                vc_evaluated = (
                    SupervisorEvaluation.objects.filter(
                        supervisor=supervisor,
                        period=current_period,
                        evaluated_by__is_vc_staff=True,
                    ).exists()
                    if hasattr(supervisor, "evaluations")
                    else False
                )

                # Get self-rating status
                self_rated = SupervisorRating.objects.filter(
                    supervisor=supervisor, period=current_period
                ).exists()

                status = "pending"
                if appraisal and appraisal.status in [
                    "evaluated",
                    "completed",
                    "approved",
                ]:
                    status = "evaluated"
                elif self_rated and has_targets:
                    status = "ready_for_evaluation"
                elif not has_targets:
                    status = "no_targets"

                supervisor_data.append(
                    {
                        "supervisor": supervisor,
                        "appraisal": appraisal,
                        "department": (
                            supervisor.staffprofile.department
                            if hasattr(supervisor, "staffprofile")
                            and supervisor.staffprofile
                            else None
                        ),
                        "status": status,
                        "has_targets": has_targets,
                        "self_rated": self_rated,
                        "vc_evaluated": vc_evaluated,
                    }
                )

            # Count statistics
            total_supervisors = len(supervisor_data)
            evaluatable_count = len(
                [
                    s
                    for s in supervisor_data
                    if s["status"] == "ready_for_evaluation"
                ]
            )
            evaluated_count = len(
                [s for s in supervisor_data if s["status"] == "evaluated"]
            )
            pending_count = len(
                [s for s in supervisor_data if s["status"] == "pending"]
            )

            completion_rate = (
                round((evaluated_count / total_supervisors * 100), 1)
                if total_supervisors > 0
                else 0
            )

            return {
                "success": True,
                "supervisors": supervisor_data,
                "current_period": current_period,
                "total_supervisors": total_supervisors,
                "evaluatable_count": evaluatable_count,
                "evaluated_count": evaluated_count,
                "pending_count": pending_count,
                "completion_rate": completion_rate,
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"Error retrieving supervisor evaluation list: {str(e)}",
            }
