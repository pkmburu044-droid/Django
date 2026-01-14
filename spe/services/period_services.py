from users.models import StaffAppraisal


class PeriodValidationService:

    @staticmethod
    def validate_period_access(period, user):
        if not period:
            return {
                "is_accessible": False,
                "message": "No active evaluation period found for your department.",
            }

        if period.forms_status != "ready":
            if period.forms_status == "draft":
                return {
                    "is_accessible": False,
                    "message": "This evaluation form is not yet published. Please check back later.",
                }
            elif period.forms_status == "closed":
                return {
                    "is_accessible": False,
                    "message": "The evaluation period has ended. Forms are no longer accepting submissions.",
                }
            else:
                return {
                    "is_accessible": False,
                    "message": "This evaluation form is not currently available.",
                }

        return {"is_accessible": True, "message": "Forms status is ready"}

    @staticmethod
    def validate_double_submission(profile, period):
        recent_check = (
            StaffAppraisal.objects.filter(profile=profile, period=period)
            .exclude(status="draft")
            .exists()
        )

        return {
            "has_recent_submission": recent_check,
            "message": (
                "This evaluation has already been submitted. Please refresh the page."
                if recent_check
                else None
            ),
        }
