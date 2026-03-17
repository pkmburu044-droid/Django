import logging

from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Avg
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from spe.models import SPEPeriod

# Add this import at the top of your views.py file
from users.models import CustomUser  # Import your custom user model

from .forms import CustomUserCreationForm, StaffProfileForm
from .models import PerformanceTarget, StaffProfile

User = get_user_model()
logger = logging.getLogger(__name__)
from django.contrib.auth import logout

# users/views.py
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect
from django.views import View

from hr.models import SupervisorPerformanceTarget

from .forms import PFNumberLoginForm


class CustomLogoutView(View):
    def get(self, request):
        # Allow GET requests for logout
        logout(request)
        return redirect("login")  # Redirect to login page after logout

    def post(self, request):
        # Also handle POST requests
        logout(request)
        return redirect("login")


# Add this CustomLoginView class - it's referenced in your urls.py
class CustomLoginView(LoginView):
    form_class = PFNumberLoginForm
    template_name = "users/login.html"

    def form_valid(self, form):
        # Optional: Add any custom logic here
        return super().form_valid(form)


def role_based_redirect(request):
    if request.user.is_authenticated:
        print(
            f"🔧 DEBUG: User {request.user.email} with role '{request.user.role}'"
        )

        if request.user.role == "supervisor":
            return redirect("dashboards:supervisor_dashboard")
        elif request.user.role == "teaching":
            return redirect("dashboards:teaching_dashboard")
        elif request.user.role == "non_teaching":
            return redirect("dashboards:non_teaching_dashboard")
        elif request.user.role == "hr":
            return redirect("hr:hr_dashboard")
        elif request.user.role == "vc":
            return redirect("vc:vc_dashboard")
        elif request.user.role == "admin" or request.user.is_superuser:
            return redirect("/admin/")  # Redirect to Django admin
        else:
            print(
                f"⚠️ WARNING: Unknown role '{request.user.role}' for user {request.user.email}"
            )
            return redirect("login")
    return redirect("login")


def signup_view(request):
    if request.method == "POST":
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()  # department and profile handled in form.save()
            login(request, user)
            messages.success(
                request,
                "Account created successfully! Please complete your profile.",
            )
            return redirect("complete_profile")
    else:
        form = CustomUserCreationForm()

    return render(request, "users/signup.html", {"form": form})


@login_required
def complete_profile(request):
    user = request.user
    profile, created = StaffProfile.objects.get_or_create(user=user)

    # Auto-set department from user to profile
    if user.department and not profile.department:
        profile.department = user.department
        profile.save()

    if request.method == "POST":
        form = StaffProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile completed successfully ✅")
            # Use the role_based_redirect from spe app
            from spe.views import role_based_redirect

            return role_based_redirect(request)
    else:
        form = StaffProfileForm(instance=profile)

    return render(
        request,
        "users/complete_profile.html",
        {
            "form": form,
            "department": user.department,  # For display only
            "profile": profile,  # Pass profile to template
        },
    )


@login_required
def edit_profile(request):
    user = request.user
    profile, _ = StaffProfile.objects.get_or_create(user=user)

    # Auto-set department from user to profile if missing
    if user.department and not profile.department:
        profile.department = user.department
        profile.save()

    if request.method == "POST":
        form = StaffProfileForm(request.POST, instance=profile)
        if form.is_valid():
            try:
                form.save()
                messages.success(request, "Profile updated successfully!")
                return redirect("dashboards:profile_details")
            except Exception as e:
                messages.error(request, f"Error saving profile: {str(e)}")
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = StaffProfileForm(instance=profile)

    return render(
        request,
        "dashboards/edit_profile.html",
        {"form": form, "profile": profile, "user": user},
    )


@login_required
def set_performance_targets(request):
    MAX_TARGETS = 5

    try:
        next_period = SPEPeriod.objects.filter(is_active=True).first()
        if not next_period:
            messages.error(request, "No active evaluation period found.")
            return role_based_redirect(request)

        is_supervisor = request.user.role == "supervisor"

        if is_supervisor:
            TargetModel = SupervisorPerformanceTarget
            existing_targets = TargetModel.objects.filter(
                supervisor=request.user, period=next_period
            )
        else:
            TargetModel = PerformanceTarget
            existing_targets = TargetModel.objects.filter(
                staff=request.user, period=next_period
            )

        if (
            next_period.end_date
            and timezone.now().date() > next_period.end_date
        ):
            messages.error(request, "The target setting period has ended.")

        # ✅ HANDLE POST REQUESTS
        if request.method == "POST":
            action = request.POST.get("action")

            if action == "submit_for_approval":
                # ✅ FIX: Submit both draft AND rejected targets for approval
                targets_to_submit = existing_targets.filter(
                    status__in=["draft", "rejected"]
                )

                if targets_to_submit.exists():
                    # ✅ FIX: Count targets before submission
                    total_targets = targets_to_submit.count()
                    draft_targets_count = targets_to_submit.filter(
                        status="draft"
                    ).count()
                    rejected_targets_count = targets_to_submit.filter(
                        status="rejected"
                    ).count()

                    try:
                        with transaction.atomic():
                            # ✅ FIX: Handle draft targets
                            draft_targets = targets_to_submit.filter(
                                status="draft"
                            )
                            if draft_targets.exists():
                                draft_targets.update(status="pending")

                            # ✅ CRITICAL FIX: Handle rejected targets with .update()
                            rejected_targets = targets_to_submit.filter(
                                status="rejected"
                            )
                            if rejected_targets.exists():
                                if is_supervisor:
                                    # For supervisor targets
                                    for target in rejected_targets:
                                        SupervisorPerformanceTarget.objects.filter(
                                            id=target.id,
                                            supervisor=request.user,
                                        ).update(
                                            status="pending",
                                            updated_at=timezone.now(),
                                        )
                                else:
                                    # For regular staff targets
                                    for target in rejected_targets:
                                        PerformanceTarget.objects.filter(
                                            id=target.id, staff=request.user
                                        ).update(
                                            status="pending",
                                            updated_at=timezone.now(),
                                        )

                            # ✅ FIX: Show proper success message
                            if (
                                rejected_targets_count > 0
                                and draft_targets_count > 0
                            ):
                                messages.success(
                                    request,
                                    f"✅ Successfully submitted {total_targets} target(s) for approval! "
                                    f"({draft_targets_count} draft(s) and {rejected_targets_count} rejected target(s) resubmitted)",
                                )
                            elif rejected_targets_count > 0:
                                messages.success(
                                    request,
                                    f"✅ Successfully resubmitted {rejected_targets_count} rejected target(s) for approval! "
                                    "Your supervisor will review them again.",
                                )
                            else:
                                messages.success(
                                    request,
                                    f"✅ Successfully submitted {draft_targets_count} draft target(s) for approval!",
                                )

                            logger.info(
                                f"User {request.user.email} submitted {total_targets} targets in period {next_period.name}"
                            )

                    except Exception as e:
                        logger.error(
                            f"Error submitting targets for {request.user.email}: {str(e)}"
                        )
                        messages.error(
                            request, f"Error submitting targets: {str(e)}"
                        )
                        return redirect("users:set_performance_targets")

                else:
                    messages.info(
                        request, "No draft or rejected targets to submit."
                    )
                return redirect("users:set_performance_targets")

            # ✅ SAVE AS DRAFT - FIXED TO INCLUDE SUCCESS_MEASURES
            elif action == "save_draft":
                # DEBUG: Log what's in POST for measures
                logger.debug(
                    f"DEBUG: User {request.user.email} - is_supervisor: {is_supervisor}"
                )
                for i in range(1, MAX_TARGETS + 1):
                    measures_key = f"measures_{i}"
                    if measures_key in request.POST:
                        logger.debug(
                            f"DEBUG: {measures_key} = '{request.POST.get(measures_key, '')}'"
                        )

                with transaction.atomic():
                    targets_created = 0
                    targets_updated = 0
                    targets_revised = 0

                    for i in range(1, MAX_TARGETS + 1):
                        target_desc = request.POST.get(
                            f"target_{i}", ""
                        ).strip()
                        measures = request.POST.get(
                            f"measures_{i}", ""
                        ).strip()

                        logger.debug(
                            f"DEBUG: Processing target {i}: desc='{target_desc[:50]}...', measures='{measures[:50]}...'"
                        )

                        if not target_desc:
                            continue

                        if len(target_desc) > 1000:
                            messages.error(
                                request,
                                f"Target {i} is too long. Maximum 1000 characters allowed.",
                            )
                            return redirect("users:set_performance_targets")

                        existing_target = existing_targets.filter(
                            target_number=i
                        ).first()

                        if existing_target:
                            # ✅ FIX: Allow editing for draft and rejected targets
                            if existing_target.status in ["draft", "rejected"]:
                                # Check if target is being revised (had content before)
                                was_rejected = (
                                    existing_target.status == "rejected"
                                )
                                had_content = existing_target.description or (
                                    hasattr(
                                        existing_target, "success_measures"
                                    )
                                    and existing_target.success_measures
                                )

                                existing_target.description = target_desc

                                # ✅ CRITICAL FIX: Save success_measures for BOTH supervisors and regular staff
                                # Check if the model has success_measures field
                                if hasattr(
                                    existing_target, "success_measures"
                                ):
                                    existing_target.success_measures = measures
                                    logger.debug(
                                        f"DEBUG: Set success_measures for target {i}: '{measures[:50]}...'"
                                    )
                                elif hasattr(existing_target, "measures"):
                                    existing_target.measures = measures
                                    logger.debug(
                                        f"DEBUG: Set measures for target {i}: '{measures[:50]}...'"
                                    )

                                existing_target.status = "draft"

                                # ✅ FIX: Clear rejection details if it was rejected
                                if was_rejected:
                                    if hasattr(
                                        existing_target, "rejection_reason"
                                    ):
                                        existing_target.rejection_reason = ""
                                    if hasattr(existing_target, "rejected_by"):
                                        existing_target.rejected_by = None
                                    if hasattr(existing_target, "rejected_at"):
                                        existing_target.rejected_at = None

                                    if had_content:
                                        targets_revised += 1
                                    else:
                                        targets_updated += 1
                                else:
                                    targets_updated += 1

                                existing_target.save()
                                logger.debug(
                                    f"DEBUG: Updated target {i} for {request.user.email}"
                                )
                        else:
                            # Create new target
                            if is_supervisor:
                                # ✅ CRITICAL FIX: Include success_measures for supervisors
                                target = TargetModel.objects.create(
                                    supervisor=request.user,
                                    period=next_period,
                                    target_number=i,
                                    description=target_desc,
                                    success_measures=measures,  # ← THIS WAS MISSING OR NOT BEING SAVED
                                    status="draft",
                                )
                                logger.debug(
                                    f"DEBUG: Created supervisor target {i} with measures: '{measures[:50]}...'"
                                )
                            else:
                                target = TargetModel.objects.create(
                                    staff=request.user,
                                    period=next_period,
                                    target_number=i,
                                    description=target_desc,
                                    success_measures=measures,
                                    status="draft",
                                )
                                logger.debug(
                                    f"DEBUG: Created staff target {i} with measures: '{measures[:50]}...'"
                                )
                            targets_created += 1

                    # ✅ FIX: Better success message
                    message_parts = []
                    if targets_created > 0:
                        message_parts.append(
                            f"{targets_created} new target(s) created"
                        )
                    if targets_updated > 0:
                        message_parts.append(
                            f"{targets_updated} target(s) updated"
                        )
                    if targets_revised > 0:
                        message_parts.append(
                            f"{targets_revised} rejected target(s) revised"
                        )

                    if message_parts:
                        messages.success(
                            request, f"✅ {', '.join(message_parts)} as draft!"
                        )
                    else:
                        messages.info(
                            request, "No changes were made to your targets."
                        )

                return redirect("users:set_performance_targets")

            elif action == "delete_drafts":
                draft_count = existing_targets.filter(status="draft").count()
                if draft_count > 0:
                    existing_targets.filter(status="draft").delete()
                    messages.success(
                        request, f"✅ {draft_count} draft target(s) deleted."
                    )
                else:
                    messages.info(request, "No draft targets to delete.")
                return redirect("users:set_performance_targets")

        # ✅ PRE-FILL EXISTING TARGETS - FIXED TO INCLUDE MEASURES
        target_forms = []
        existing_targets_dict = {
            target.target_number: target for target in existing_targets
        }

        period_ended = (
            next_period.end_date
            and timezone.now().date() > next_period.end_date
        )

        for i in range(1, MAX_TARGETS + 1):
            target = existing_targets_dict.get(i)

            if period_ended:
                can_edit = False
            elif target:
                can_edit = target.status in ["draft", "rejected"]
            else:
                can_edit = not period_ended

            # Get measures - handle different field names for measures
            measures_value = ""
            if target:
                # Try different possible field names for measures
                if (
                    hasattr(target, "success_measures")
                    and target.success_measures
                ):
                    measures_value = target.success_measures
                    logger.debug(
                        f"DEBUG: Found success_measures for target {i}: '{measures_value[:50]}...'"
                    )
                elif hasattr(target, "measures") and target.measures:
                    measures_value = target.measures
                    logger.debug(
                        f"DEBUG: Found measures for target {i}: '{measures_value[:50]}...'"
                    )
                elif (
                    hasattr(target, "performance_measures")
                    and target.performance_measures
                ):
                    measures_value = target.performance_measures
                else:
                    measures_value = ""
                    logger.debug(f"DEBUG: No measures found for target {i}")
            else:
                measures_value = ""

            target_forms.append(
                {
                    "number": i,
                    "description": target.description if target else "",
                    "measures": measures_value,
                    "status": target.status if target else "new",
                    "can_edit": can_edit,
                    "is_rejected": (
                        target.status == "rejected" if target else False
                    ),
                    "rejection_reason": (
                        target.rejection_reason
                        if target and hasattr(target, "rejection_reason")
                        else ""
                    ),
                }
            )

        # ✅ STATUS COUNTS FOR TEMPLATE
        draft_count = existing_targets.filter(status="draft").count()
        pending_count = existing_targets.filter(status="pending").count()
        approved_count = existing_targets.filter(status="approved").count()
        rejected_count = existing_targets.filter(status="rejected").count()
        total_targets = existing_targets.count()

        # Debug: Check what's in the database
        logger.debug(
            f"DEBUG: User {request.user.email} targets - total: {total_targets}, draft: {draft_count}, pending: {pending_count}, approved: {approved_count}, rejected: {rejected_count}"
        )

        # ✅ FIX: Better permission checks
        can_submit = (
            draft_count > 0 or rejected_count > 0
        ) and not period_ended
        can_create = total_targets < MAX_TARGETS and not period_ended
        has_editable_targets = draft_count > 0 or rejected_count > 0

        context = {
            "next_period": next_period,
            "target_forms": target_forms,
            "existing_targets": total_targets > 0,
            "max_targets": MAX_TARGETS,
            "period_end_date": next_period.end_date,
            "period_ended": period_ended,
            "draft_count": draft_count,
            "pending_count": pending_count,
            "approved_count": approved_count,
            "rejected_count": rejected_count,
            "has_draft_targets": draft_count > 0,
            "has_pending_targets": pending_count > 0,
            "has_approved_targets": approved_count > 0,
            "has_rejected_targets": rejected_count > 0,
            "can_submit": can_submit,
            "can_create": can_create,
            "has_editable_targets": has_editable_targets,
            "total_targets": total_targets,
            "is_supervisor": is_supervisor,
            "is_teaching_staff": request.user.role == "teaching",
            "is_non_teaching_staff": request.user.role == "non_teaching",
        }

        # Debug logging
        logger.debug(
            f"DEBUG: Rendering template for {request.user.email}, is_supervisor: {is_supervisor}"
        )
        for form in target_forms:
            logger.debug(
                f"DEBUG: Target {form['number']} - measures length: {len(form['measures'])}"
            )

        return render(request, "users/set_targets.html", context)

    except Exception as e:
        logger.error(
            f"Error in set_performance_targets for user {request.user.email}: {str(e)}",
            exc_info=True,
        )
        messages.error(request, f"An error occurred: {str(e)}")
        return role_based_redirect(request)

@login_required
def view_performance_targets(request):
    """View to display current performance targets with evaluation results for both staff and supervisors"""
    try:
        # Get current active period
        current_period = SPEPeriod.objects.filter(is_active=True).first()

        if not current_period:
            messages.info(request, "No active evaluation period found.")
            return render(
                request,
                "users/view_targets.html",
                {
                    "targets": [],
                    "is_teaching_staff": request.user.role == "teaching",
                    "is_supervisor": request.user.role == "supervisor",
                    "evaluation_results": None,
                    "evaluation_stats": None,
                },
            )

        # ✅ DETERMINE USER TYPE AND CORRECT MODEL
        is_supervisor = request.user.role == "supervisor"

        if is_supervisor:
            # Use SupervisorPerformanceTarget model for supervisors
            TargetModel = SupervisorPerformanceTarget
            targets = TargetModel.objects.filter(
                supervisor=request.user,  # Only this supervisor's targets
                period=current_period,
            ).order_by("target_number")
        else:
            # Use PerformanceTarget model for regular staff
            TargetModel = PerformanceTarget
            targets = TargetModel.objects.filter(
                staff=request.user,
                period=current_period,  # Only this user's targets
            ).order_by("target_number")

        # Evaluation Results Data - HANDLE DIFFERENT FIELD NAMES
        evaluation_results = []
        total_rating_score = 0
        evaluated_count = 0

        for target in targets:
            # ✅ HANDLE DIFFERENT FIELD NAMES BETWEEN MODELS
            if is_supervisor:
                # SupervisorPerformanceTarget fields
                target_data = {
                    "target_number": target.target_number,
                    "description": target.description,
                    "status": target.status,
                    "is_evaluated": target.performance_rating is not None,
                    "performance_rating": target.performance_rating,
                    "supervisor_comments": target.performance_comments,
                    "evaluated_at": target.rated_at,
                    "evaluated_by": target.rated_by,
                    "rating_scale": target.performance_rating,
                }

                # Calculate score for evaluated targets
                if target.performance_rating is not None:
                    total_rating_score += target.performance_rating
                    evaluated_count += 1

            else:
                # PerformanceTarget fields (regular staff)
                target_data = {
                    "target_number": target.target_number,
                    "description": target.description,
                    "status": target.status,
                    "is_evaluated": target.rating_scale is not None,
                }

                # Add success_measures if available
                if hasattr(target, "success_measures"):
                    target_data["success_measures"] = target.success_measures

                # Add evaluation fields if available
                if hasattr(target, "rating_scale"):
                    target_data["rating_scale"] = target.rating_scale

                if hasattr(target, "performance_rating"):
                    target_data["performance_rating"] = target.performance_rating
                    # Calculate score for evaluated targets
                    if target.performance_rating is not None:
                        total_rating_score += target.performance_rating
                        evaluated_count += 1

                if hasattr(target, "supervisor_comments"):
                    target_data["supervisor_comments"] = target.supervisor_comments

                if hasattr(target, "evaluated_at"):
                    target_data["evaluated_at"] = target.evaluated_at

                if hasattr(target, "evaluated_by"):
                    target_data["evaluated_by"] = target.evaluated_by

            evaluation_results.append(target_data)

        # ✅ FIXED: Calculate percentage scores correctly - CHECK IF RATINGS ARE ALREADY PERCENTAGES
        if evaluated_count > 0:
            # Check if ratings are already percentages (look at first evaluated target)
            sample_rating = None
            for target in targets:
                if target.performance_rating is not None:
                    sample_rating = target.performance_rating
                    break
            
            if sample_rating is not None:
                if sample_rating > 5:
                    # Ratings are already percentages (like 80.0, 75.0, etc.)
                    # total_rating_score is sum of percentages
                    average_score_percentage = total_rating_score / evaluated_count
                    # Convert to 1-5 scale for rating description
                    average_rating = (average_score_percentage / 100) * 5
                else:
                    # Ratings are 1-5 scale
                    average_rating = total_rating_score / evaluated_count
                    # Convert to percentage
                    average_score_percentage = (average_rating / 5) * 100
            else:
                # No ratings found
                average_rating = 0
                average_score_percentage = 0
        else:
            average_rating = 0
            average_score_percentage = 0

        # Evaluation Statistics - FIXED PERCENTAGE CALCULATION
        evaluation_stats = {
            "total_targets": targets.count(),
            "evaluated_targets": evaluated_count,
            "pending_evaluation": targets.count() - evaluated_count,
            "completion_rate": (
                (evaluated_count / targets.count() * 100)
                if targets.count() > 0
                else 0
            ),
            "average_score": round(average_score_percentage, 1),  # This is now correct percentage
            "average_rating": round(average_rating, 1),  # Keep the 1-5 scale average for reference
            # ✅ FIXED: Pass average_score_percentage (percentage) instead of average_rating (1-5 scale)
            "overall_rating": (
                get_overall_rating_description(average_score_percentage)  # ✅ FIXED HERE
                if evaluated_count > 0
                else "Not Evaluated"
            ),
        }

        # Status counts for template
        status_counts = {
            "draft": targets.filter(status="draft").count(),
            "pending": targets.filter(status="pending").count(),
            "approved": targets.filter(status="approved").count(),
            "rejected": targets.filter(status="rejected").count(),
            "evaluated": evaluated_count,
        }

        # Rejected targets details - HANDLE DIFFERENT FIELD NAMES
        rejected_targets = targets.filter(status="rejected")
        has_rejected_targets = rejected_targets.exists()

        rejection_details = []
        for target in rejected_targets:
            if is_supervisor:
                # Supervisor rejection details
                rejection_info = {
                    "target_number": target.target_number,
                    "description": target.description,
                    "rejection_reason": target.rejection_reason or "No reason provided",
                    "rejected_by": (
                        target.rejected_by.get_full_name()
                        if target.rejected_by
                        else "HR/Admin"
                    ),
                    "rejected_at": target.rejected_at,
                }
            else:
                # Staff rejection details
                rejection_info = {
                    "target_number": target.target_number,
                    "description": target.description,
                    "rejection_reason": getattr(
                        target, "rejection_reason", "No reason provided"
                    ),
                    "rejected_by": (
                        target.rejected_by.get_full_name()
                        if hasattr(target, "rejected_by") and target.rejected_by
                        else "Supervisor"
                    ),
                    "rejected_at": getattr(target, "rejected_at", None),
                }

            rejection_details.append(rejection_info)

        # ✅ GET RATING CHOICES BASED ON MODEL
        if is_supervisor:
            # Use SupervisorPerformanceTarget rating choices
            rating_choices = getattr(
                SupervisorPerformanceTarget,
                "RATING_CHOICES",
                [
                    (1, "1 - Poor"),
                    (2, "2 - Fair"),
                    (3, "3 - Good"),
                    (4, "4 - Very Good"),
                    (5, "5 - Excellent"),
                ],
            )
        else:
            # Use PerformanceTarget rating choices
            rating_choices = getattr(PerformanceTarget, "RATING_CHOICES", [])

        # Check if user can edit targets
        can_edit_targets = (
            not targets.filter(status__in=["pending", "approved"]).exists()
            or has_rejected_targets
        )

        context = {
            "targets": targets,
            "current_period": current_period,
            "has_targets": targets.exists(),
            "status_counts": status_counts,
            "is_teaching_staff": request.user.role == "teaching",
            "is_non_teaching_staff": request.user.role == "non_teaching",
            "is_supervisor": is_supervisor,
            "total_targets": targets.count(),
            # Evaluation Results Context
            "evaluation_results": evaluation_results,
            "evaluation_stats": evaluation_stats,
            "has_evaluations": evaluated_count > 0,
            "rating_choices": rating_choices,
            # Rejection handling context
            "has_rejected_targets": has_rejected_targets,
            "rejected_targets_count": rejected_targets.count(),
            "rejection_details": rejection_details,
            "can_edit_targets": can_edit_targets,
            "can_submit_for_approval": (
                targets.filter(status__in=["draft", "rejected"]).exists()
                and not targets.filter(status="pending").exists()
            ),
        }

        return render(request, "users/view_targets.html", context)

    except Exception as e:
        logger.error(
            f"Error in view_performance_targets: {str(e)}", exc_info=True
        )
        messages.error(request, f"Error loading targets: {str(e)}")
        return redirect("users:view_performance_targets")


def get_overall_rating_description(average_score):
    """Helper function to convert average score to rating description"""
    if average_score >= 90:
        return "Outstanding"
    elif average_score >= 80:
        return "Exceeds Expectations"
    elif average_score >= 50:
        return "Meets Expectations"
    elif average_score >= 30:
        return "Below Expectations"
    else:
        return "Far Below Expectations"

@login_required
def evaluate_staff_targets(request, staff_id=None):
    """
    SINGLE view that handles both:
    - Evaluation dashboard (when no staff_id)
    - Individual staff evaluation (when staff_id provided)
    """
    try:
        print(
            f"=== DEBUG: evaluate_staff_targets for {request.user.email} ==="
        )

        # Check if user is a supervisor
        is_supervisor = request.user.role == "supervisor"
        if not is_supervisor:
            messages.error(
                request, "Access denied. Supervisor privileges required."
            )
            return redirect("dashboards:supervisor_dashboard")

        # Get supervisor profile and department
        supervisor_profile = request.user.staffprofile
        supervisor_department = supervisor_profile.department

        if not supervisor_department:
            messages.error(request, "You are not assigned to any department.")
            return redirect("dashboards:supervisor_dashboard")

        print(
            f"DEBUG: Supervisor department: {supervisor_department.name}"
        )

        # Get current active period
        current_period = SPEPeriod.objects.filter(is_active=True).first()
        if not current_period:
            messages.error(request, "No active evaluation period found.")
            return redirect("dashboards:supervisor_dashboard")

        # ===== INDIVIDUAL STAFF EVALUATION =====
        if staff_id:
            print(f"DEBUG: Individual evaluation for staff_id: {staff_id}")
            staff_user = get_object_or_404(CustomUser, id=staff_id)
            staff_profile = get_object_or_404(StaffProfile, user=staff_user)

            print(
                f"DEBUG: Staff department: {staff_profile.department.name} ({staff_user.role})"
            )

            # ✅ UPDATED AUTHORIZATION: Staff must be in supervisor's department (NO staff type check)
            is_authorized = (
                staff_profile.department
                and staff_profile.department == supervisor_department
                # ✅ REMOVED: and staff_user.role == supervisor_department.staff_type
            )

            print(
                f"DEBUG: Authorization - Same department: {staff_profile.department == supervisor_department}"
            )
            print(f"DEBUG: Is authorized: {is_authorized}")

            if not is_authorized:
                messages.error(
                    request,
                    f"Access denied. You are a supervisor in {supervisor_department.name}. "
                    f"You can only evaluate staff from your department. "
                    f"This staff member is in {staff_profile.department.name if staff_profile.department else 'No Department'}.",
                )
                return redirect("users:evaluate_staff_targets")

            # ✅ Check if staff has approved targets
            has_approved_targets = PerformanceTarget.objects.filter(
                staff=staff_user, period=current_period, status="approved"
            ).exists()

            if not has_approved_targets:
                messages.error(
                    request,
                    f"Cannot evaluate {staff_user.get_full_name()}. No approved targets found for the current period.",
                )
                return redirect("users:evaluate_staff_targets")

            # Get targets for evaluation (only approved ones)
            targets = PerformanceTarget.objects.filter(
                staff=staff_user,
                period=current_period,
                status="approved",  # ✅ Only approved targets can be evaluated
            ).order_by("target_number")

            print(
                f"DEBUG: Found {targets.count()} approved targets for evaluation"
            )

            if not targets.exists():
                messages.error(
                    request,
                    f"No approved targets found for {staff_user.get_full_name()} to evaluate.",
                )
                return redirect("users:evaluate_staff_targets")

            # Handle POST request for evaluation submission
            if request.method == "POST":
                print("DEBUG: Processing POST request for evaluation")
                with transaction.atomic():
                    targets_updated = 0
                    validation_errors = []

                    for target in targets:
                        rating_key = f"rating_{target.id}"
                        comments_key = f"comments_{target.id}"
                        approve_key = f"approve_{target.id}"

                        rating_scale = request.POST.get(rating_key)
                        supervisor_comments = request.POST.get(
                            comments_key, ""
                        )
                        should_approve = request.POST.get(approve_key) == "on"

                        # Update target status if approval checkbox is checked
                        if should_approve and target.status == "pending":
                            target.status = "approved"
                            print(f"DEBUG: Target {target.id} approved")

                        # Only update evaluation if rating is provided
                        if rating_scale:
                            try:
                                rating_scale_int = int(rating_scale)

                                if rating_scale_int not in [1, 2, 3, 4, 5]:
                                    validation_errors.append(
                                        f"Rating for target {target.target_number} must be 1-5."
                                    )
                                    continue

                                target.rating_scale = rating_scale_int
                                target.supervisor_comments = (
                                    supervisor_comments
                                )
                                target.evaluated_by = request.user
                                target.evaluated_at = timezone.now()
                                target.save()
                                targets_updated += 1

                            except (ValueError, TypeError):
                                error_msg = f"Invalid rating format for target {target.target_number}."
                                validation_errors.append(error_msg)
                                continue
                        else:
                            target.save()

                    if validation_errors:
                        for error in validation_errors:
                            messages.error(request, error)

                    if targets_updated > 0:
                        messages.success(
                            request,
                            f"Performance evaluation completed for {staff_user.get_full_name()}. {targets_updated} target(s) evaluated.",
                        )
                    else:
                        messages.info(
                            request,
                            "Target status updated. No ratings were provided.",
                        )

                    return redirect("users:evaluate_staff_targets")

            # ✅ Get supervisees with approved targets (without staff type filtering)
            users_with_approved_targets = CustomUser.objects.filter(
                performance_targets__period=current_period,
                performance_targets__status="approved",
            ).values_list("id", flat=True)

            # Then get staff profiles for those users
            supervisees_profiles = (
                StaffProfile.objects.filter(
                    department=supervisor_department,
                    # ✅ REMOVED: user__role=supervisor_department.staff_type,
                    user_id__in=users_with_approved_targets,
                )
                .exclude(user=request.user)
                .select_related("user")
            )

            supervisees = [profile.user for profile in supervisees_profiles]
            print(
                f"DEBUG: Found {len(supervisees)} supervisees with approved targets for dropdown"
            )

            context = {
                "staff": staff_user,
                "staff_profile": staff_profile,
                "targets": targets,
                "supervisees": supervisees,
                "current_period": current_period,
                "is_evaluation_form": True,
                "rating_choices": PerformanceTarget.RATING_CHOICES,
                "has_pending_targets": targets.filter(
                    status="pending"
                ).exists(),
                "supervisor_department": supervisor_department,
            }
            return render(
                request,
                "dashboards/supervisor_evaluation_dashboard.html",
                context,
            )

        # ===== EVALUATION DASHBOARD =====
        else:
            print("DEBUG: Evaluation dashboard mode")

            # ✅ Get supervisees with approved targets (without staff type filtering)
            users_with_approved_targets = CustomUser.objects.filter(
                performance_targets__period=current_period,
                performance_targets__status="approved",
            ).values_list("id", flat=True)

            # Then get staff profiles for those users
            supervisees_profiles = (
                StaffProfile.objects.filter(
                    department=supervisor_department,
                    # ✅ REMOVED: user__role=supervisor_department.staff_type,
                    user_id__in=users_with_approved_targets,
                )
                .exclude(user=request.user)
                .select_related("user")
            )

            print(
                f"DEBUG: Found {supervisees_profiles.count()} supervisees in {supervisor_department.name} with approved targets"
            )

            evaluation_stats = []
            total_targets_to_evaluate = 0
            total_targets_evaluated = 0
            total_pending_approval = 0

            for staff_profile in supervisees_profiles:
                staff_user = staff_profile.user

                # Get APPROVED targets for this staff member
                all_targets = PerformanceTarget.objects.filter(
                    staff=staff_user,
                    period=current_period,
                    status="approved",  # ✅ Only approved targets
                )

                # Count targets by status
                pending_targets = all_targets.filter(status="pending").count()
                approved_targets = all_targets.filter(
                    status="approved"
                ).count()
                total_targets = all_targets.count()

                # Count evaluated vs pending evaluation
                evaluated_targets = all_targets.filter(
                    rating_scale__isnull=False
                ).count()
                pending_evaluation = total_targets - evaluated_targets

                total_targets_to_evaluate += total_targets
                total_targets_evaluated += evaluated_targets
                total_pending_approval += pending_targets

                # Calculate average rating
                evaluated_targets_qs = all_targets.filter(
                    rating_scale__isnull=False
                )
                avg_percentage = (
                    evaluated_targets_qs.aggregate(
                        avg_percentage=Avg("performance_rating")
                    )["avg_percentage"]
                    or 0
                )

                evaluation_stats.append(
                    {
                        "staff": staff_user,
                        "profile": staff_profile,
                        "designation": staff_profile.designation,
                        "role": staff_user.role,
                        "total_targets": total_targets,
                        "pending_targets": pending_targets,
                        "approved_targets": approved_targets,
                        "evaluated_targets": evaluated_targets,
                        "pending_evaluation": pending_evaluation,
                        "completion_rate": (
                            (evaluated_targets / total_targets * 100)
                            if total_targets > 0
                            else 0
                        ),
                        "average_rating": round(avg_percentage, 1),
                        "has_targets": total_targets > 0,
                        "has_pending_approval": pending_targets > 0,
                        "has_pending_evaluation": pending_evaluation > 0,
                    }
                )

            print(
                f"DEBUG: Evaluation stats created for {len(evaluation_stats)} staff with approved targets"
            )

            context = {
                "evaluation_stats": evaluation_stats,
                "current_period": current_period,
                "total_supervisees": len(evaluation_stats),
                "total_targets_to_evaluate": total_targets_to_evaluate,
                "total_targets_evaluated": total_targets_evaluated,
                "total_pending_approval": total_pending_approval,
                "overall_completion_rate": (
                    (total_targets_evaluated / total_targets_to_evaluate * 100)
                    if total_targets_to_evaluate > 0
                    else 0
                ),
                "is_dashboard_view": True,
                "supervisor_department": supervisor_department,
            }

            return render(
                request,
                "dashboards/supervisor_evaluation_dashboard.html",
                context,
            )

    except Exception as e:
        logger.error(
            f"Error in evaluate_staff_targets for supervisor {request.user.email}: {str(e)}",
            exc_info=True,
        )
        messages.error(
            request,
            f"An error occurred while processing your request: {str(e)}",
        )
        return redirect("dashboards:supervisor_dashboard")
    
@login_required
def view_staff_targets(request):
    # Check if user is a supervisor using role field
    if request.user.role != "supervisor":
        messages.error(
            request, "You don't have permission to view staff targets."
        )
        return redirect("users:role_based_redirect")

    # Get current evaluation period
    current_period = SPEPeriod.objects.filter(is_active=True).first()

    # Get supervisor's department
    try:
        supervisor_profile = request.user.staffprofile
        supervisor_department = supervisor_profile.department

        if not supervisor_department:
            messages.error(request, "You are not assigned to any department.")
            return redirect("dashboards:supervisor_dashboard")

    except StaffProfile.DoesNotExist:
        messages.error(request, "Please complete your profile first.")
        return redirect("users:complete_profile")

    # Get staff members in the same department with matching staff type
    staff_members = (
        CustomUser.objects.filter(
            staffprofile__department=supervisor_department,
            role=supervisor_department.staff_type,  # teaching or non_teaching
            is_active=True,
        )
        .exclude(id=request.user.id)
        .select_related("staffprofile")
    )

    # Get all targets for staff members
    staff_targets = PerformanceTarget.objects.filter(
        staff__in=staff_members
    ).select_related("staff", "staff__staffprofile")

    # Filter by current period if exists
    if current_period:
        staff_targets = staff_targets.filter(period=current_period)

    # Get status counts for all staff targets
    from django.db.models import Count, Q

    status_counts = staff_targets.aggregate(
        total=Count("id"),
        draft=Count("id", filter=Q(status="draft")),
        pending=Count("id", filter=Q(status="pending")),
        approved=Count("id", filter=Q(status="approved")),
        rejected=Count("id", filter=Q(status="rejected")),
        evaluated=Count("id", filter=Q(performance_rating__isnull=False)),
    )

    # Get targets needing approval (pending status)
    pending_approval = staff_targets.filter(status="pending")

    # Get recently evaluated targets
    recently_evaluated = staff_targets.filter(
        performance_rating__isnull=False
    ).order_by("-evaluated_at")[:5]

    # Group targets by staff member for the template
    staff_with_targets = []
    for staff in staff_members:
        staff_targets_list = staff_targets.filter(staff=staff)
        target_stats = staff_targets_list.aggregate(
            total=Count("id"),
            pending=Count("id", filter=Q(status="pending")),
            approved=Count("id", filter=Q(status="approved")),
            evaluated=Count("id", filter=Q(performance_rating__isnull=False)),
            avg_score=Avg(
                "performance_rating",
                filter=Q(performance_rating__isnull=False),
            ),
        )

        staff_with_targets.append(
            {
                "staff": staff,
                "targets": staff_targets_list,
                "stats": target_stats,
            }
        )

    context = {
        "current_period": current_period,
        "staff_with_targets": staff_with_targets,
        "pending_approval": pending_approval,
        "recently_evaluated": recently_evaluated,
        "status_counts": status_counts,
        "total_staff": staff_members.count(),
        "supervisor_department": supervisor_department,
    }

    return render(request, "dashboards/supervisor_view_targets.html", context)
