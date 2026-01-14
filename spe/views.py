from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from hr.models import SupervisorAttribute
from spe.models import SPEAttribute, SPEIndicator, SPEPeriod, SupervisorRating
from users.models import StaffProfile

User = get_user_model()


@login_required
def start_self_assessment(request):
    from spe.services.assessment_services import SelfAssessmentService
    from spe.services.period_services import PeriodValidationService

    user = request.user

    # Active evaluation period
    period = SPEPeriod.objects.filter(is_active=True).first()

    # ✅ ADD DEBUG
    print(
        f"🚨 ACCESSING SELF-ASSESSMENT: User={user.email}, Forms Status='{period.forms_status if period else 'None'}"
    )

    if not period:
        messages.error(
            request, "No active evaluation period found for your department."
        )
        return redirect("users:role_based_redirect")

    # ✅ USE SERVICE CLASS FOR PERIOD VALIDATION
    validation_result = PeriodValidationService.validate_period_access(
        period, user
    )
    if not validation_result["is_accessible"]:
        print(f"🚨 BLOCKED: {validation_result['message']}")
        messages.error(request, validation_result["message"])
        return redirect("users:role_based_redirect")
    else:
        print(f"✅ ALLOWED: Forms status is 'ready'")

    profile, _ = StaffProfile.objects.get_or_create(user=user)

    if not profile.department:
        messages.error(
            request,
            "Please complete your profile with a department before starting evaluation.",
        )
        return redirect("edit_profile")

    # ✅ USE SERVICE CLASS TO CHECK EXISTING APPRAISAL
    existing_check = SelfAssessmentService.check_existing_submission(
        profile, period
    )
    if existing_check["exists"]:
        status_display = existing_check["appraisal"].get_status_display()
        messages.info(
            request,
            f"You have already {status_display.lower()} your self-assessment for this period.",
        )
        return redirect("users:role_based_redirect")

    role_to_type = {"teaching": "teaching", "non_teaching": "non_teaching"}
    if user.role not in role_to_type:
        messages.error(request, "Only staff can submit self-assessments.")
        return redirect("users:role_based_redirect")

    staff_type = role_to_type[user.role]

    # ✅ USE SERVICE CLASS TO LOAD ATTRIBUTES
    attributes_result = SelfAssessmentService.get_evaluation_attributes(
        profile, period, staff_type
    )
    attributes_list = attributes_result["attributes"]

    # Debug info
    print(f"🔍 DEBUG START_SELF_ASSESSMENT:")
    print(f"🔍 User: {user.get_full_name()} ({user.email})")
    print(f"🔍 Department: {profile.department.name}")
    print(f"🔍 Role: {user.role}")
    print(f"🔍 Staff Type: {staff_type}")
    print(f"🔍 Period: {period.name}")
    print(f"🔍 Forms Status: {period.forms_status}")
    print(f"🔍 Attributes found: {attributes_result['count']}")
    print(f"🔍 Global attributes: {attributes_result['global_count']}")
    print(f"🔍 Department attributes: {attributes_result['department_count']}")

    for attr in attributes_list:
        dept_name = attr.department.name if attr.department else "Global"
        print(
            f"🔍   - {attr.name} (Dept: {dept_name}, Type: {attr.staff_type})"
        )

    # ✅ USE SERVICE CLASS TO GET/CREATE DRAFT APPRAISAL
    appraisal = SelfAssessmentService.get_or_create_draft_appraisal(
        profile, period
    )

    # Handle empty attributes
    if not attributes_list:
        messages.error(
            request,
            "No evaluation criteria available yet. Please check back later.",
        )
        return render(
            request,
            "spe/evaluation_form.html",
            {
                "form": None,
                "attributes": attributes_list,
                "period": period,
                "profile": profile,
                "appraisal": appraisal,
            },
        )

    # ✅ COMPLETE POST HANDLING LOGIC USING SERVICE CLASSES
    if request.method == "POST":
        # Double-check forms status in case it changed during form filling
        period.refresh_from_db()
        if period.forms_status != "ready":
            print(
                f"🚨 POST BLOCKED: Forms status changed to '{period.forms_status}' during form filling"
            )
            messages.error(
                request,
                "This evaluation form is no longer available for submissions.",
            )
            return redirect("users:role_based_redirect")

        save_draft = request.POST.get("save_draft") == "true"

        # ✅ USE SERVICE CLASS FOR DOUBLE SUBMISSION CHECK
        submission_check = PeriodValidationService.validate_double_submission(
            profile, period
        )
        if submission_check["has_recent_submission"]:
            messages.warning(request, submission_check["message"])
            return redirect("users:role_based_redirect")

        # ✅ USE SERVICE CLASS FOR FORM PROCESSING
        processing_result = (
            SelfAssessmentService.process_self_assessment_submission(
                request, profile, period, attributes_list, save_draft
            )
        )

        # Handle missing ratings for final submission
        if processing_result["missing_ratings"] and not save_draft:
            messages.error(
                request,
                f"Please provide ratings for all indicators. Missing: {', '.join(processing_result['missing_ratings'][:3])}{'...' if len(processing_result['missing_ratings']) > 3 else ''}",
            )
            request.missing_ratings = processing_result["missing_ratings"]
        else:
            # ✅ USE SERVICE CLASS TO UPDATE APPRAISAL STATUS
            message = SelfAssessmentService.update_appraisal_status(
                appraisal, save_draft
            )
            messages.success(request, message)
            print(
                f"✅ {processing_result['saved_count']}/{processing_result['total_indicators']} indicators processed"
            )

            # Redirect after successful submission
            if not save_draft:
                return redirect("users:role_based_redirect")

    rating_choices = [
        (1, "1 - Poor"),
        (2, "2 - Fair"),
        (3, "3 - Good"),
        (4, "4 - Very Good"),
        (5, "5 - Excellent"),
    ]

    return render(
        request,
        "spe/evaluation_form.html",
        {
            "attributes": attributes_list,
            "rating_choices": rating_choices,
            "period": period,
            "profile": profile,
            "appraisal": appraisal,
            "missing_ratings": getattr(request, "missing_ratings", []),
            "attributes_stats": attributes_result,  # ✅ ADDED: Pass stats to template
        },
    )


@login_required
def manage_attributes(request):
    if request.user.role != "hr":
        messages.error(request, "Only HR staff can access this page.")
        return redirect("users:role_based_redirect")

    # ✅ SUPPORT TEACHING & NON-TEACHING STAFF TYPES
    staff_type = request.GET.get("staff_type", "teaching")
    period_id = request.GET.get("period")

    periods = SPEPeriod.objects.all().order_by("-start_date")

    # ✅ Period selection logic
    selected_period = None
    if request.method == "GET":
        if period_id and period_id != "None":
            try:
                selected_period = periods.filter(id=int(period_id)).first()
            except (ValueError, TypeError):
                selected_period = periods.first()
        else:
            selected_period = periods.first()

    elif request.method == "POST":
        post_period_id = request.POST.get("period") or request.POST.get(
            "period_id"
        )
        if post_period_id and post_period_id != "None":
            try:
                selected_period = periods.filter(
                    id=int(post_period_id)
                ).first()
            except (ValueError, TypeError):
                selected_period = periods.first()
        else:
            selected_period = periods.first()

    # ✅ Load GLOBAL attributes (department=None)
    attributes = []
    if selected_period:
        attributes = (
            SPEAttribute.objects.filter(
                period=selected_period,
                staff_type=staff_type,
                department__isnull=True,  # ✅ Only global forms
            )
            .prefetch_related("indicators")
            .order_by("id")
        )

    if request.method == "POST":
        action = request.POST.get("action", "").strip()

        try:
            # ✅ FORM STATUS MANAGEMENT ACTIONS - GLOBAL SCOPE
            if action == "publish_forms":
                if selected_period:
                    selected_period.forms_status = "ready"
                    selected_period.save()
                    messages.success(
                        request,
                        f"✅ Global {staff_type.title()} Forms published to ALL staff!",
                    )

            elif action == "unpublish_forms":
                if selected_period:
                    selected_period.forms_status = "draft"
                    selected_period.save()
                    messages.info(
                        request,
                        f"✅ Global {staff_type.title()} Forms unpublished.",
                    )

            elif action == "close_forms":
                if selected_period:
                    selected_period.forms_status = "closed"
                    selected_period.save()
                    messages.info(
                        request,
                        f"✅ Global {staff_type.title()} Forms closed.",
                    )

            # ✅ REOPEN FORMS - GLOBAL SCOPE
            elif action == "reopen_forms":
                if selected_period:
                    selected_period.forms_status = "ready"
                    selected_period.save()
                    messages.success(
                        request,
                        f"✅ Global {staff_type.title()} Forms reopened! Staff can now submit evaluations again.",
                    )

            elif action == "activate_period":
                period = get_object_or_404(
                    SPEPeriod, id=request.POST.get("period_id")
                )

                # Deactivate ALL periods globally
                SPEPeriod.objects.all().update(is_active=False)

                # Activate selected period
                period.is_active = True
                period.save()

                messages.success(
                    request, f"✅ Period '{period.name}' activated globally."
                )
                selected_period = period

            # ✅ CRITERIA BUILDER - CREATE GLOBAL FORMS (department=None)
            elif action == "save_criteria":
                period = get_object_or_404(
                    SPEPeriod, id=request.POST.get("period")
                )
                attribute_name = request.POST.get("attribute_name").strip()

                if attribute_name:
                    existing_attribute = SPEAttribute.objects.filter(
                        name=attribute_name,
                        period=period,
                        department__isnull=True,  # ✅ Only check global forms
                        staff_type=staff_type,
                    ).first()

                    if existing_attribute:
                        messages.error(
                            request,
                            f"❌ Attribute '{attribute_name}' already exists for global {staff_type} forms.",
                        )
                    else:
                        attribute = SPEAttribute.objects.create(
                            name=attribute_name,
                            period=period,
                            staff_type=staff_type,
                            department=None,  # ✅ Create as global form
                            created_by=request.user,
                        )

                        # Create indicators
                        indicators_created = 0
                        indicator_index = 0

                        while True:
                            indicator_field = f"indicator_{indicator_index}"
                            indicator_desc = request.POST.get(
                                indicator_field, ""
                            ).strip()

                            if not indicator_desc:
                                indicator_index += 1
                                next_indicator = request.POST.get(
                                    f"indicator_{indicator_index}", ""
                                ).strip()
                                if not next_indicator:
                                    break
                                continue

                            SPEIndicator.objects.create(
                                attribute=attribute, description=indicator_desc
                            )
                            indicators_created += 1
                            indicator_index += 1

                        messages.success(
                            request,
                            f"✅ Created global '{attribute_name}' with {indicators_created} indicators for {staff_type} staff!",
                        )
                else:
                    messages.error(
                        request, "❌ Please enter an attribute name"
                    )

            # ✅ SINGLE ATTRIBUTE OPERATIONS - GLOBAL SCOPE
            elif action == "add_attribute":
                period = get_object_or_404(
                    SPEPeriod, id=request.POST.get("period")
                )
                name = request.POST.get("attribute_name").strip()

                if name:
                    existing_attribute = SPEAttribute.objects.filter(
                        name=name,
                        period=period,
                        department__isnull=True,  # ✅ Only check global forms
                        staff_type=staff_type,
                    ).first()

                    if existing_attribute:
                        messages.error(
                            request,
                            f"❌ Attribute '{name}' already exists for global {staff_type} forms.",
                        )
                    else:
                        SPEAttribute.objects.create(
                            name=name,
                            period=period,
                            staff_type=staff_type,
                            department=None,  # ✅ Create as global form
                            created_by=request.user,
                        )
                        messages.success(
                            request,
                            f"✅ Global attribute '{name}' added for {staff_type} staff.",
                        )
                else:
                    messages.error(
                        request, "❌ Please enter an attribute name"
                    )

            elif action == "edit_attribute":
                attr = get_object_or_404(
                    SPEAttribute,
                    id=request.POST.get("attribute_id"),
                    department__isnull=True,  # ✅ Only edit global forms
                )
                new_name = request.POST.get("attribute_name").strip()

                if new_name != attr.name:
                    existing_attribute = (
                        SPEAttribute.objects.filter(
                            name=new_name,
                            period=attr.period,
                            department__isnull=True,  # ✅ Only check global forms
                            staff_type=attr.staff_type,
                        )
                        .exclude(id=attr.id)
                        .first()
                    )

                    if existing_attribute:
                        messages.error(
                            request,
                            f"❌ Attribute '{new_name}' already exists for global {staff_type} forms.",
                        )
                    else:
                        attr.name = new_name
                        attr.save()
                        messages.success(
                            request,
                            f"✅ Global attribute renamed to '{attr.name}'.",
                        )
                else:
                    messages.info(
                        request, "No changes made to attribute name."
                    )

            elif action == "delete_attribute":
                attr = get_object_or_404(
                    SPEAttribute,
                    id=request.POST.get("attribute_id"),
                    department__isnull=True,  # ✅ Only delete global forms
                )
                name = attr.name
                attr.delete()
                messages.warning(
                    request,
                    f"🗑️ Global attribute '{name}' deleted successfully.",
                )

            elif action == "add_indicator":
                attr = get_object_or_404(
                    SPEAttribute,
                    id=request.POST.get("attribute_id"),
                    department__isnull=True,  # ✅ Only add to global forms
                )
                desc = request.POST.get("indicator_desc").strip()
                if desc:
                    SPEIndicator.objects.create(
                        attribute=attr, description=desc
                    )
                    messages.success(
                        request,
                        f"✅ Indicator added under global '{attr.name}'.",
                    )
                else:
                    messages.error(
                        request, "❌ Please enter an indicator description"
                    )

            elif action == "edit_indicator":
                ind = get_object_or_404(
                    SPEIndicator,
                    id=request.POST.get("indicator_id"),
                    attribute__department__isnull=True,  # ✅ Only edit global forms
                )
                ind.description = request.POST.get("indicator_desc").strip()
                ind.save()
                messages.success(request, "✅ Indicator updated successfully.")

            elif action == "delete_indicator":
                ind = get_object_or_404(
                    SPEIndicator,
                    id=request.POST.get("indicator_id"),
                    attribute__department__isnull=True,  # ✅ Only delete from global forms
                )
                desc = ind.description
                ind.delete()
                messages.warning(
                    request, f"🗑️ Indicator '{desc}' deleted successfully."
                )

        except Exception as e:
            messages.error(request, f"⚠️ Error: {e}")

        # ✅ PRESERVE STAFF_TYPE IN REDIRECT
        redirect_url = f"{request.path}?staff_type={staff_type}"
        if selected_period and selected_period.id:
            redirect_url += f"&period={selected_period.id}"

        return redirect(redirect_url)

    context = {
        "periods": periods,
        "selected_period": selected_period,
        "staff_type": staff_type,
        "staff_type_display": (
            "Teaching Staff"
            if staff_type == "teaching"
            else "Non-Teaching Staff"
        ),
        "attributes": attributes,
    }
    return render(request, "spe/manage_attributes.html", context)


@login_required
def edit_period_attributes(request, period_id):
    if request.user.role != "supervisor":
        messages.error(request, "Only supervisors can access this page.")
        return redirect("users:role_based_redirect")

    supervisor_dept = request.user.department

    # ✅ FIXED: Remove supervisor filtering since supervisor field was removed
    # Only allow access to any period (no supervisor restriction)
    period = get_object_or_404(SPEPeriod, id=period_id)

    # Get all attributes and their indicators for this period AND department
    attributes = SPEAttribute.objects.filter(
        period=period, department=supervisor_dept
    ).prefetch_related("indicators")

    if request.method == "POST":
        try:
            with transaction.atomic():
                # Handle period information update
                period.name = request.POST.get("period_name")
                start_date = request.POST.get("start_date")
                end_date = request.POST.get("end_date")

                if start_date:
                    period.start_date = start_date
                if end_date:
                    period.end_date = end_date

                period.save()

                # Handle NEW attribute creation
                new_attribute_name = request.POST.get("new_attribute_name")
                if new_attribute_name and new_attribute_name.strip():
                    # ✅ FIXED: Use supervisor's department staff_type instead of hardcoded
                    staff_type = (
                        supervisor_dept.staff_type
                        if supervisor_dept
                        else "teaching"
                    )

                    new_attribute = SPEAttribute.objects.create(
                        name=new_attribute_name.strip(),
                        period=period,
                        staff_type=staff_type,  # ✅ Now dynamic based on department
                        department=supervisor_dept,
                        created_by=request.user,
                    )
                    messages.success(
                        request,
                        f"✅ New attribute '{new_attribute.name}' created.",
                    )

                # Handle NEW indicator creation
                new_indicator_desc = request.POST.get("new_indicator_desc")
                new_indicator_attribute_id = request.POST.get(
                    "new_indicator_attribute"
                )
                if (
                    new_indicator_desc
                    and new_indicator_desc.strip()
                    and new_indicator_attribute_id
                ):
                    try:
                        attribute = SPEAttribute.objects.get(
                            id=new_indicator_attribute_id,
                            period=period,
                            department=supervisor_dept,
                        )
                        # ✅ REMOVED: Weight parameter since SPEIndicator doesn't have weight field
                        SPEIndicator.objects.create(
                            attribute=attribute,
                            description=new_indicator_desc.strip(),
                        )
                        messages.success(
                            request,
                            f"✅ New indicator added to '{attribute.name}'.",
                        )
                    except (SPEAttribute.DoesNotExist, ValueError):
                        messages.error(
                            request,
                            "⚠️ Invalid attribute selected for new indicator.",
                        )

                # Update EXISTING attributes and indicators
                for attribute in attributes:
                    attribute_name = request.POST.get(
                        f"attribute_{attribute.id}_name"
                    )

                    if attribute_name:
                        attribute.name = attribute_name
                        attribute.save()

                    # Update indicators for this attribute
                    for indicator in attribute.indicators.all():
                        indicator_name = request.POST.get(
                            f"indicator_{indicator.id}_name"
                        )

                        if indicator_name:
                            indicator.description = indicator_name
                            # ✅ REMOVED: Weight processing since SPEIndicator doesn't have weight field
                            indicator.save()

                messages.success(
                    request,
                    f'Period "{period.name}" and all its attributes/indicators have been updated successfully.',
                )
                return redirect(
                    "spe:edit_period_attributes", period_id=period.id
                )

        except Exception as e:
            messages.error(request, f"Error updating period: {str(e)}")

    context = {
        "period": period,
        "attributes": attributes,
    }

    return render(request, "spe/edit_period_attributes.html", context)


@login_required
def evaluate_self_assessment(request, staff_id):
    messages.info(
        request, "Supervisor evaluation feature is under development."
    )
    return redirect("users:role_based_redirect")


@login_required
def delete_attribute(request, attribute_id):
    """Delete an attribute and all its indicators"""
    if request.method == "POST":
        try:
            attribute = get_object_or_404(SPEAttribute, id=attribute_id)
            period_id = attribute.period.id
            attribute_name = attribute.name

            # Delete the attribute (this will cascade delete indicators due to ForeignKey)
            attribute.delete()

            messages.success(
                request,
                f"Attribute '{attribute_name}' and all its indicators have been deleted.",
            )

            # Return to the attribute management page
            return redirect("spe:edit_period_attributes", period_id=period_id)

        except Exception as e:
            messages.error(request, f"Error deleting attribute: {str(e)}")
            return redirect("spe:manage_attributes")

    # If not POST, redirect to manage attributes
    return redirect("spe:manage_attributes")


@login_required
def delete_indicator(request, indicator_id):
    """Delete a specific indicator"""
    if request.method == "POST":
        try:
            indicator = get_object_or_404(SPEIndicator, id=indicator_id)
            period_id = indicator.attribute.period.id
            indicator_description = indicator.description

            # Delete the indicator
            indicator.delete()

            messages.success(
                request,
                f"Indicator '{indicator_description}' has been deleted.",
            )

            # Return to the attribute management page
            return redirect("spe:edit_period_attributes", period_id=period_id)

        except Exception as e:
            messages.error(request, f"Error deleting indicator: {str(e)}")
            return redirect("spe:manage_attributes")

    # If not POST, redirect to manage attributes
    return redirect("spe:manage_attributes")


@login_required
def supervisor_evaluation_form(request):
    """Supervisor self-evaluation form"""
    # Check if user is a supervisor
    if request.user.role != "supervisor":
        messages.error(request, "Only supervisors can access this page.")
        return redirect("users:role_based_redirect")

    # Get active period
    active_period = SPEPeriod.objects.filter(is_active=True).first()
    if not active_period:
        messages.error(request, "No active evaluation period.")
        return redirect("spe:supervisor_dashboard")

    # Get supervisor attributes for evaluation
    supervisor_attributes = SupervisorAttribute.objects.filter(
        is_active=True
    ).prefetch_related("indicators")

    # Calculate total indicators
    total_indicators = 0
    for attribute in supervisor_attributes:
        total_indicators += attribute.indicators.count()

    # Check if already submitted for this period
    existing_evaluation = SupervisorRating.objects.filter(
        supervisor=request.user, period=active_period
    ).exists()

    # Handle form submission
    if request.method == "POST":
        try:
            if existing_evaluation:
                messages.warning(
                    request,
                    "You have already submitted an evaluation for this period.",
                )
                return redirect("spe:supervisor_dashboard")

            # Process ratings for each indicator
            ratings_submitted = 0
            for attribute in supervisor_attributes:
                for indicator in attribute.indicators.all():
                    rating_key = f"rating_{attribute.id}_{indicator.id}"
                    rating_value = request.POST.get(rating_key)

                    if rating_value:
                        # Save the rating
                        SupervisorRating.objects.create(
                            supervisor=request.user,
                            period=active_period,
                            attribute=attribute,
                            indicator=indicator,
                            rating=int(rating_value),
                            comments=request.POST.get(
                                f"comments_{attribute.id}_{indicator.id}", ""
                            ),
                        )
                        ratings_submitted += 1

            messages.success(
                request,
                f"✅ Self-evaluation submitted successfully! {ratings_submitted} ratings saved.",
            )
            return redirect("spe:supervisor_dashboard")

        except Exception as e:
            messages.error(
                request, f"❌ Error submitting evaluation: {str(e)}"
            )

    context = {
        "active_period": active_period,
        "supervisor_attributes": supervisor_attributes,
        "existing_evaluation": existing_evaluation,
        "total_indicators": total_indicators,  # ← ADD THIS LINE
    }
    return render(request, "spe/supervisor_evaluation_form.html", context)


@login_required
def supervisor_self_report(request):
    """View for supervisors to see their own appraisal report using services"""
    from users.services import SupervisorReportService

    user = request.user

    if user.role != "supervisor":
        messages.error(request, "Access denied. Supervisor role required.")
        return redirect("users:role_based_redirect")

    print(f"=== DEBUG: supervisor_self_report for user {user.pf_number} ===")

    # Use service to get supervisor report data
    report_data = SupervisorReportService.get_supervisor_self_report(user)

    print(f"DEBUG: Report data success: {report_data.get('success')}")

    if not report_data["success"]:
        messages.info(request, report_data["message"])
        print(f"DEBUG: No report data - {report_data['message']}")
        return render(
            request, "spe/supervisor_self_report.html", {"appraisal": None}
        )

    # Get the context from service
    service_context = report_data["context"]

    # Debug the actual data content
    appraisal = service_context.get("appraisal")
    approved_targets = service_context.get("approved_targets", [])
    criteria_data = service_context.get("criteria_data", [])

    print(f"DEBUG: Appraisal object: {appraisal}")
    print(f"DEBUG: Appraisal type: {type(appraisal)}")
    print(f"DEBUG: Approved targets count: {len(approved_targets)}")
    if approved_targets:
        print(f"DEBUG: First target: {approved_targets[0]}")
        print(f"DEBUG: First target type: {type(approved_targets[0])}")
    print(f"DEBUG: Criteria data count: {len(criteria_data)}")

    # Get scores from service
    criteria_percentage = service_context.get("criteria_percentage", 0)
    target_percentage = service_context.get("target_percentage", 0)

    # DEBUG: Print the scores we're getting
    print(f"DEBUG: Criteria percentage: {criteria_percentage}")
    print(f"DEBUG: Target percentage: {target_percentage}")

    # Calculate COMBINED average score properly
    if criteria_percentage > 0 and target_percentage > 0:
        # Both scores available - calculate weighted average
        combined_score = (criteria_percentage + target_percentage) / 2
    elif criteria_percentage > 0:
        # Only criteria score available
        combined_score = criteria_percentage
    elif target_percentage > 0:
        # Only target score available
        combined_score = target_percentage
    else:
        # No scores available
        combined_score = 0

    print(f"DEBUG: Combined score calculated: {combined_score}")

    # Build template context
    context = {
        # Core appraisal data
        "appraisal": appraisal,
        "period": service_context.get("period"),
        "evaluated_by": service_context.get("evaluated_by", "Vice Chancellor"),
        # Targets data
        "approved_targets": approved_targets,
        "targets": approved_targets,  # Also provide as 'targets'
        # Evaluation criteria data
        "criteria_data": criteria_data,
        "criteria_with_both_ratings": service_context.get(
            "criteria_with_both_ratings", 0
        ),
        "total_criteria": service_context.get("total_criteria", 0),
        "average_rating_gap": service_context.get("average_rating_gap", 0),
        # Scores - PROVIDE BOTH INDIVIDUAL AND COMBINED
        "criteria_percentage": criteria_percentage,
        "target_percentage": target_percentage,
        "combined_score": combined_score,  # Add this for template
        # Create evaluation_stats for the template - USE COMBINED SCORE
        "evaluation_stats": {
            "average_score": combined_score,  # Use the combined score here
            "total_targets": len(approved_targets),
            "evaluated_targets": len(
                [
                    t
                    for t in approved_targets
                    if getattr(t, "performance_rating", None) is not None
                ]
            ),
            "completion_rate": (
                (
                    len(
                        [
                            t
                            for t in approved_targets
                            if getattr(t, "performance_rating", None)
                            is not None
                        ]
                    )
                    / len(approved_targets)
                    * 100
                )
                if approved_targets
                else 0
            ),
            "overall_rating": get_overall_rating_description(
                combined_score
            ),  # Use combined score
        },
        # Status counts for template
        "status_counts": {
            "approved": len(approved_targets),
            "evaluated": len(
                [
                    t
                    for t in approved_targets
                    if getattr(t, "performance_rating", None) is not None
                ]
            ),
        },
    }

    print(
        f"DEBUG: Final context - appraisal: {context['appraisal'] is not None}"
    )
    print(
        f"DEBUG: Final context - approved_targets: {len(context['approved_targets'])}"
    )
    print(
        f"DEBUG: Final context - criteria_data: {len(context['criteria_data'])}"
    )
    print(
        f"DEBUG: Final context - criteria_percentage: {context['criteria_percentage']}"
    )
    print(
        f"DEBUG: Final context - target_percentage: {context['target_percentage']}"
    )
    print(
        f"DEBUG: Final context - combined_score: {context['combined_score']}"
    )
    print(
        f"DEBUG: Final context - evaluation_stats: {context['evaluation_stats']}"
    )

    return render(request, "spe/supervisor_self_report.html", context)


def get_overall_rating_description(score):
    """Helper function to convert average score to rating description"""
    if score >= 90:
        return "Outstanding"
    elif score >= 80:
        return "Excellent"
    elif score >= 70:
        return "Good"
    elif score >= 60:
        return "Satisfactory"
    elif score >= 50:
        return "Needs Improvement"
    else:
        return "Unsatisfactory"


from users.models import StaffProfile
