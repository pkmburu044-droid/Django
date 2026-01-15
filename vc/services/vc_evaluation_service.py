# vc/services/vc_evaluation_service.py
from django.contrib.auth import get_user_model
from django.db.models import Q

from hr.models import (
    SupervisorAppraisal, 
    SupervisorEvaluation,  # This is from hr app
    SupervisorPerformanceTarget,
    SupervisorAttribute,
    SupervisorIndicator
)
from spe.models import SPEPeriod, SupervisorRating

CustomUser = get_user_model()


class VCEvaluationService:
    """Service class for VC evaluation operations"""

    @staticmethod
    def get_supervisor_evaluation_list():
        """Get list of supervisors for VC evaluation with proper status"""
        try:
            current_period = SPEPeriod.objects.filter(is_active=True).first()
            if not current_period:
                return {
                    "success": False,
                    "error": "No active evaluation period found.",
                }

            # Get all active supervisors
            supervisors = CustomUser.objects.filter(
                role="supervisor", is_active=True
            ).select_related("staffprofile__department")

            # Get VC user(s) - users with role='vc'
            vc_users = CustomUser.objects.filter(role='vc', is_active=True)
            
            # Get all active supervisor indicators
            supervisor_indicators = SupervisorIndicator.objects.filter(is_active=True)
            total_indicators_required = supervisor_indicators.count()
            
            # Enhance supervisor data with evaluation status
            supervisor_data = []
            total_supervisors = 0
            evaluatable_count = 0
            evaluated_count = 0
            pending_count = 0
            
            for supervisor in supervisors:
                total_supervisors += 1
                
                # Get department
                department = None
                if hasattr(supervisor, 'staffprofile') and supervisor.staffprofile:
                    department = supervisor.staffprofile.department
                elif hasattr(supervisor, 'department'):
                    department = supervisor.department

                # Check if supervisor has approved targets
                approved_targets = SupervisorPerformanceTarget.objects.filter(
                    supervisor=supervisor,
                    period=current_period,
                    status="approved"
                )
                has_targets = approved_targets.exists()
                
                # Check if approved targets have VC ratings
                evaluated_targets = approved_targets.filter(
                    performance_rating__isnull=False
                ).count()
                targets_fully_evaluated = evaluated_targets == approved_targets.count()
                targets_partially_evaluated = evaluated_targets > 0 and evaluated_targets < approved_targets.count()

                # Check if supervisor has self-ratings
                self_ratings = SupervisorRating.objects.filter(
                    supervisor=supervisor,
                    period=current_period
                )
                self_rated = self_ratings.exists()
                self_rating_count = self_ratings.count()
                has_all_self_ratings = self_rating_count >= total_indicators_required
                has_some_self_ratings = self_rating_count > 0 and self_rating_count < total_indicators_required

                # Check if supervisor has been evaluated by VC
                vc_rating_count = 0
                has_vc_detailed_ratings = False
                
                if vc_users.exists():
                    vc_user = vc_users.first()
                    
                    # Check if VC has evaluated this supervisor in SupervisorEvaluation (hr app)
                    vc_detailed_ratings = SupervisorEvaluation.objects.filter(
                        supervisor=supervisor,  # Supervisor being evaluated
                        hr_user=vc_user,  # VC doing the evaluation (hr_user field)
                        period=current_period
                    )
                    vc_rating_count = vc_detailed_ratings.count()
                    has_vc_detailed_ratings = vc_rating_count > 0
                
                # Check if supervisor has VC appraisal (overall evaluation)
                vc_appraisal = SupervisorAppraisal.objects.filter(
                    supervisor=supervisor,
                    period=current_period,
                    evaluated_by__role='vc',
                ).first()

                has_vc_appraisal = vc_appraisal is not None
                has_full_vc_ratings = vc_rating_count >= total_indicators_required
                has_some_vc_ratings = vc_rating_count > 0 and vc_rating_count < total_indicators_required

                # Determine status based on the correct logic:
                # Priority order:
                # 1. evaluated - Has both self-ratings AND VC ratings for all indicators AND VC appraisal
                # 2. partially_evaluated - Has some VC ratings but not all
                # 3. ready_for_evaluation - Has approved targets and complete self-ratings
                # 4. incomplete_self_ratings - Has approved targets but incomplete self-ratings
                # 5. no_targets - No approved targets
                
                if has_targets and has_all_self_ratings and has_full_vc_ratings and has_vc_appraisal:
                    # Has everything - Fully evaluated
                    status = "evaluated"
                    status_label = "Fully Evaluated"
                    badge_class = "success"
                    evaluated_count += 1
                elif has_targets and has_all_self_ratings and has_some_vc_ratings:
                    # Has targets, self-ratings, and some VC ratings
                    status = "partially_evaluated"
                    status_label = "Partially Evaluated"
                    badge_class = "warning"
                    pending_count += 1
                elif has_targets and has_all_self_ratings and has_vc_appraisal and not has_vc_detailed_ratings:
                    # Has targets, self-ratings, VC appraisal but no detailed VC ratings
                    status = "needs_detailed_ratings"
                    status_label = "Needs Detailed Ratings"
                    badge_class = "info"
                    pending_count += 1
                elif has_targets and has_all_self_ratings and not has_vc_appraisal:
                    # Has targets and complete self-ratings - Ready for VC evaluation
                    status = "ready_for_evaluation"
                    status_label = "Ready for Evaluation"
                    badge_class = "primary"
                    evaluatable_count += 1
                elif has_targets and has_some_self_ratings:
                    # Has targets but incomplete self-ratings
                    status = "incomplete_self_ratings"
                    status_label = "Incomplete Self-Ratings"
                    badge_class = "secondary"
                    pending_count += 1
                elif has_targets and not self_rated:
                    # Has targets but no self-ratings
                    status = "pending_self_rating"
                    status_label = "Pending Self-Rating"
                    badge_class = "light"
                    pending_count += 1
                elif not has_targets:
                    # No approved targets
                    status = "no_targets"
                    status_label = "No Approved Targets"
                    badge_class = "danger"
                    pending_count += 1
                else:
                    # Default status
                    status = "pending"
                    status_label = "Pending"
                    badge_class = "secondary"
                    pending_count += 1

                # Calculate percentages
                self_rating_percentage = (self_rating_count / total_indicators_required * 100) if total_indicators_required > 0 else 0
                vc_rating_percentage = (vc_rating_count / total_indicators_required * 100) if total_indicators_required > 0 else 0
                target_evaluation_percentage = (evaluated_targets / approved_targets.count() * 100) if approved_targets.exists() else 0

                supervisor_data.append(
                    {
                        "supervisor": supervisor,
                        "appraisal": vc_appraisal,
                        "department": department,
                        "status": status,
                        "status_label": status_label,
                        "badge_class": f"bg-{badge_class}",
                        "has_targets": has_targets,
                        "approved_targets_count": approved_targets.count(),
                        "evaluated_targets_count": evaluated_targets,
                        "targets_fully_evaluated": targets_fully_evaluated,
                        "targets_partially_evaluated": targets_partially_evaluated,
                        "target_evaluation_percentage": target_evaluation_percentage,
                        "self_rated": self_rated,
                        "self_rating_count": self_rating_count,
                        "has_all_self_ratings": has_all_self_ratings,
                        "vc_rating_count": vc_rating_count,
                        "has_vc_detailed_ratings": has_vc_detailed_ratings,
                        "has_full_vc_ratings": has_full_vc_ratings,
                        "has_vc_appraisal": has_vc_appraisal,
                        "total_indicators_required": total_indicators_required,
                        "self_rating_percentage": self_rating_percentage,
                        "vc_rating_percentage": vc_rating_percentage,
                    }
                )

            # Count statistics
            evaluatable_count = len([
                s for s in supervisor_data 
                if s["status"] == "ready_for_evaluation"
            ])
            evaluated_count = len([
                s for s in supervisor_data 
                if s["status"] == "evaluated"
            ])
            pending_count = len([
                s for s in supervisor_data 
                if s["status"] in ["pending", "pending_self_rating", "no_targets", 
                                   "partially_evaluated", "incomplete_self_ratings", 
                                   "needs_detailed_ratings"]
            ])
            partially_evaluated_count = len([
                s for s in supervisor_data 
                if s["status"] == "partially_evaluated"
            ])
            needs_detailed_ratings_count = len([
                s for s in supervisor_data 
                if s["status"] == "needs_detailed_ratings"
            ])

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
                "partially_evaluated_count": partially_evaluated_count,
                "needs_detailed_ratings_count": needs_detailed_ratings_count,
                "completion_rate": completion_rate,
                "total_indicators_required": total_indicators_required,
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"Error retrieving supervisor evaluation list: {str(e)}",
            }

    @staticmethod
    def check_if_supervisor_can_be_evaluated(supervisor_id):
        """Check if a supervisor can be evaluated by VC"""
        try:
            current_period = SPEPeriod.objects.filter(is_active=True).first()
            if not current_period:
                return {
                    "success": False,
                    "can_evaluate": False,
                    "error": "No active evaluation period.",
                    "reasons": ["No active evaluation period"]
                }

            supervisor = CustomUser.objects.get(
                id=supervisor_id, role="supervisor", is_active=True
            )

            reasons = []
            can_evaluate = True
            evaluation_details = {}

            # 1. Check approved targets
            approved_targets = SupervisorPerformanceTarget.objects.filter(
                supervisor=supervisor,
                period=current_period,
                status="approved"
            )
            has_targets = approved_targets.exists()
            evaluated_targets = approved_targets.filter(
                performance_rating__isnull=False
            ).count()
            
            if not has_targets:
                can_evaluate = False
                reasons.append("No approved performance targets")
            else:
                evaluation_details["total_targets"] = approved_targets.count()
                evaluation_details["evaluated_targets"] = evaluated_targets
                evaluation_details["targets_fully_evaluated"] = evaluated_targets == approved_targets.count()
                
                if evaluated_targets < approved_targets.count():
                    reasons.append(f"Incomplete target evaluations ({evaluated_targets}/{approved_targets.count()} targets rated)")

            # 2. Check self-ratings completeness
            supervisor_indicators = SupervisorIndicator.objects.filter(is_active=True)
            total_indicators = supervisor_indicators.count()
            
            self_ratings = SupervisorRating.objects.filter(
                supervisor=supervisor,
                period=current_period
            )
            self_rating_count = self_ratings.count()
            self_rating_percentage = (self_rating_count / total_indicators * 100) if total_indicators > 0 else 0
            
            evaluation_details["total_indicators"] = total_indicators
            evaluation_details["self_rating_count"] = self_rating_count
            evaluation_details["self_rating_percentage"] = self_rating_percentage
            
            if self_rating_count < total_indicators:
                can_evaluate = False
                reasons.append(f"Incomplete self-ratings ({self_rating_count}/{total_indicators} indicators)")

            # 3. Check if already evaluated by VC
            vc_users = CustomUser.objects.filter(role='vc', is_active=True)
            already_evaluated = False
            
            if vc_users.exists():
                vc_user = vc_users.first()
                vc_ratings_count = SupervisorEvaluation.objects.filter(
                    supervisor=supervisor,
                    hr_user=vc_user,  # Using hr_user field for VC
                    period=current_period
                ).count()
                
                vc_rating_percentage = (vc_ratings_count / total_indicators * 100) if total_indicators > 0 else 0
                
                evaluation_details["vc_rating_count"] = vc_ratings_count
                evaluation_details["vc_rating_percentage"] = vc_rating_percentage
                
                if vc_ratings_count >= total_indicators:
                    can_evaluate = False
                    reasons.append(f"Already evaluated by VC ({vc_ratings_count}/{total_indicators} indicators)")
                    already_evaluated = True
                elif vc_ratings_count > 0:
                    reasons.append(f"Partially evaluated by VC ({vc_ratings_count}/{total_indicators} indicators)")

            # 4. Check for VC appraisal
            vc_appraisal = SupervisorAppraisal.objects.filter(
                supervisor=supervisor,
                period=current_period,
                evaluated_by__role='vc',
            ).first()
            
            evaluation_details["has_vc_appraisal"] = vc_appraisal is not None
            
            if vc_appraisal and not already_evaluated:
                # Has appraisal but no detailed ratings
                reasons.append("Has overall VC appraisal but needs detailed ratings")

            return {
                "success": True,
                "can_evaluate": can_evaluate,
                "already_evaluated": already_evaluated,
                "supervisor": supervisor,
                "period": current_period,
                "has_targets": has_targets,
                "evaluation_details": evaluation_details,
                "reasons": reasons,
                "error": ", ".join(reasons) if reasons else None
            }

        except CustomUser.DoesNotExist:
            return {
                "success": False,
                "can_evaluate": False,
                "error": "Supervisor not found.",
                "reasons": ["Supervisor not found"]
            }
        except Exception as e:
            return {
                "success": False,
                "can_evaluate": False,
                "error": f"Error checking evaluation status: {str(e)}",
                "reasons": [str(e)]
            }

    @staticmethod
    def get_supervisor_evaluation_progress(supervisor_id):
        """Get detailed evaluation progress for a supervisor"""
        try:
            current_period = SPEPeriod.objects.filter(is_active=True).first()
            if not current_period:
                return {
                    "success": False,
                    "error": "No active evaluation period found.",
                }

            supervisor = CustomUser.objects.get(
                id=supervisor_id, role="supervisor", is_active=True
            )

            # Get VC user
            vc_users = CustomUser.objects.filter(role='vc', is_active=True)
            vc_user = vc_users.first() if vc_users.exists() else None

            # Get all active indicators
            supervisor_indicators = SupervisorIndicator.objects.filter(is_active=True)
            total_indicators = supervisor_indicators.count()

            # Get self-ratings
            self_ratings = SupervisorRating.objects.filter(
                supervisor=supervisor,
                period=current_period
            ).select_related("attribute", "indicator")
            self_rating_count = self_ratings.count()

            # Get VC ratings from hr.SupervisorEvaluation
            vc_ratings = []
            vc_rating_count = 0
            if vc_user:
                vc_ratings = SupervisorEvaluation.objects.filter(
                    supervisor=supervisor,
                    hr_user=vc_user,  # VC is hr_user in this model
                    period=current_period
                ).select_related("attribute", "indicator")
                vc_rating_count = vc_ratings.count()

            # Get approved targets
            approved_targets = SupervisorPerformanceTarget.objects.filter(
                supervisor=supervisor,
                period=current_period,
                status="approved"
            )
            approved_targets_count = approved_targets.count()
            
            # Get evaluated targets
            evaluated_targets = approved_targets.filter(
                performance_rating__isnull=False
            ).count()

            # Check for VC appraisal
            vc_appraisal = SupervisorAppraisal.objects.filter(
                supervisor=supervisor,
                period=current_period,
                evaluated_by__role='vc',
            ).first()

            # Calculate completion
            self_rating_completion = (self_rating_count / total_indicators * 100) if total_indicators > 0 else 0
            vc_rating_completion = (vc_rating_count / total_indicators * 100) if total_indicators > 0 else 0
            target_completion = (evaluated_targets / approved_targets_count * 100) if approved_targets_count > 0 else 0
            
            # Determine status
            has_all_self_ratings = self_rating_count >= total_indicators
            has_all_vc_ratings = vc_rating_count >= total_indicators
            has_all_targets_evaluated = evaluated_targets == approved_targets_count
            has_some_vc_ratings = vc_rating_count > 0 and vc_rating_count < total_indicators

            # Determine overall status
            if approved_targets_count > 0 and has_all_self_ratings and has_all_vc_ratings and has_all_targets_evaluated and vc_appraisal:
                status = "evaluated"
                status_label = "Fully Evaluated"
            elif approved_targets_count > 0 and has_all_self_ratings and has_some_vc_ratings:
                status = "partially_evaluated"
                status_label = "Partially Evaluated"
            elif approved_targets_count > 0 and has_all_self_ratings and vc_appraisal and not has_some_vc_ratings:
                status = "needs_detailed_ratings"
                status_label = "Needs Detailed Ratings"
            elif approved_targets_count > 0 and has_all_self_ratings:
                status = "ready_for_evaluation"
                status_label = "Ready for Evaluation"
            elif approved_targets_count > 0 and self_rating_count > 0:
                status = "incomplete_self_ratings"
                status_label = "Incomplete Self-Ratings"
            elif approved_targets_count > 0:
                status = "pending_self_rating"
                status_label = "Pending Self-Rating"
            else:
                status = "no_targets"
                status_label = "No Approved Targets"

            return {
                "success": True,
                "supervisor": supervisor,
                "period": current_period,
                "total_indicators": total_indicators,
                "self_rating_count": self_rating_count,
                "vc_rating_count": vc_rating_count,
                "approved_targets_count": approved_targets_count,
                "evaluated_targets_count": evaluated_targets,
                "self_rating_completion": self_rating_completion,
                "vc_rating_completion": vc_rating_completion,
                "target_completion": target_completion,
                "has_vc_appraisal": vc_appraisal is not None,
                "vc_appraisal": vc_appraisal,
                "status": status,
                "status_label": status_label,
                "has_all_self_ratings": has_all_self_ratings,
                "has_all_vc_ratings": has_all_vc_ratings,
                "has_all_targets_evaluated": has_all_targets_evaluated,
                "missing_self_ratings": total_indicators - self_rating_count,
                "missing_vc_ratings": total_indicators - vc_rating_count,
                "missing_target_evaluations": approved_targets_count - evaluated_targets,
                "can_evaluate": approved_targets_count > 0 and has_all_self_ratings,
            }

        except CustomUser.DoesNotExist:
            return {
                "success": False,
                "error": "Supervisor not found.",
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Error getting evaluation progress: {str(e)}",
            }