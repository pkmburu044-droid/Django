from django.db.models import Q
from django.utils import timezone

from spe.models import SelfAssessment, SPEAttribute
from users.models import StaffAppraisal


class SelfAssessmentService:

    @staticmethod
    def check_existing_submission(profile, period):
        existing_appraisal = (
            StaffAppraisal.objects.filter(profile=profile, period=period)
            .exclude(status="draft")
            .first()
        )

        return {
            "exists": existing_appraisal is not None,
            "appraisal": existing_appraisal,
        }

    @staticmethod
    def get_evaluation_attributes(profile, period, staff_type):
        attributes_qs = (
            SPEAttribute.objects.filter(staff_type=staff_type, period=period)
            .filter(
                Q(department=profile.department) | Q(department__isnull=True)
            )
            .prefetch_related("indicators")
            .order_by("id")
        )

        attributes_list = list(attributes_qs)

        global_count = len(
            [attr for attr in attributes_list if attr.department is None]
        )
        department_count = len(
            [attr for attr in attributes_list if attr.department is not None]
        )

        return {
            "attributes": attributes_list,
            "count": len(attributes_list),
            "global_count": global_count,
            "department_count": department_count,
        }

    @staticmethod
    def get_or_create_draft_appraisal(profile, period):
        appraisal = (
            StaffAppraisal.objects.filter(
                profile=profile, period=period, status="draft"
            )
            .order_by("-created_at")
            .first()
        )

        if not appraisal:
            appraisal = StaffAppraisal.objects.create(
                profile=profile,
                period=period,
                status="draft",
                supervisor_name="",
                supervisor_designation="",
            )

        return appraisal

    @staticmethod
    def process_self_assessment_submission(
        request, profile, period, attributes_list, save_draft=False
    ):
        missing_ratings = []
        total_indicators = 0
        saved_count = 0

        print(f"PROCESSING POST DATA: save_draft={save_draft}")

        for attribute in attributes_list:
            for indicator in attribute.indicators.all():
                total_indicators += 1
                rating_key = f"rating_{attribute.id}_{indicator.id}"
                remarks_key = f"remarks_{attribute.id}_{indicator.id}"

                rating_value = request.POST.get(rating_key)
                remarks_value = request.POST.get(remarks_key, "").strip()

                print(
                    f"Processing: {rating_key} = {rating_value}, {remarks_key} = {remarks_value}"
                )

                if not rating_value and not save_draft:
                    missing_ratings.append(
                        f"{attribute.name} - {indicator.description}"
                    )
                    continue

                self_assessment, created = (
                    SelfAssessment.objects.get_or_create(
                        staff=request.user,
                        period=period,
                        attribute=attribute,
                        indicator=indicator,
                        defaults={
                            "self_rating": (
                                int(rating_value) if rating_value else None
                            ),
                            "remarks": remarks_value,
                        },
                    )
                )

                if not created:
                    self_assessment.self_rating = (
                        int(rating_value) if rating_value else None
                    )
                    self_assessment.remarks = remarks_value
                    self_assessment.save()

                saved_count += 1
                print(
                    f"Saved: {attribute.name} - {indicator.description} = {rating_value}"
                )

        return {
            "missing_ratings": missing_ratings,
            "total_indicators": total_indicators,
            "saved_count": saved_count,
            "success": len(missing_ratings) == 0 or save_draft,
        }

    @staticmethod
    def update_appraisal_status(appraisal, save_draft=False):
        if save_draft:
            appraisal.status = "draft"
            message = "Draft saved successfully! You can come back later to complete your assessment."
            print(f"DRAFT SAVED")
        else:
            appraisal.status = "submitted"
            appraisal.submitted_at = timezone.now()
            message = "Self-assessment submitted successfully!"
            print(f"SUBMITTED")

        appraisal.save()
        return message
