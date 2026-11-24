"""Test helpers (not used by the application)."""
from django.utils import timezone

from .models import DriverVerification, IdType, VerificationStatus


def approve_driver(user, vehicle_number="TN09AB1234"):
    """Mark ``user`` as an approved driver without documents, for tests that publish rides."""
    DriverVerification.objects.update_or_create(
        user=user,
        defaults={
            "status": VerificationStatus.APPROVED,
            "vehicle_number": vehicle_number,
            "id_type": IdType.PAN,
            "submitted_at": timezone.now(),
            "reviewed_at": timezone.now(),
        },
    )
    user.verified_id = user.verified_license = True
    user.save(update_fields=["verified_id", "verified_license"])
    return user
