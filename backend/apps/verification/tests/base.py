import shutil
import tempfile
from datetime import datetime, time, timedelta

from cryptography.fernet import Fernet
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User
from apps.geo.seed import seed_geo

JPEG = b"\xff\xd8\xff\xe0" + b"fake jpeg body " * 20
PNG = b"\x89PNG\r\n\x1a\n" + b"fake png body " * 20
PDF = b"%PDF-1.4\n" + b"fake pdf body " * 20
KEY = Fernet.generate_key().decode()


def upload(name, data, content_type="application/octet-stream"):
    return SimpleUploadedFile(name, data, content_type=content_type)


def tomorrow(hour=7):
    d = timezone.localdate() + timedelta(days=1)
    return timezone.make_aware(datetime.combine(d, time(hour, 0)))


class VerificationTestBase(APITestCase):
    """An isolated private-media folder and a real encryption key for every test class."""

    @classmethod
    def setUpClass(cls):
        cls._media = tempfile.mkdtemp(prefix="vct-private-")
        cls._settings = override_settings(PRIVATE_MEDIA_ROOT=cls._media, DOCUMENT_ENCRYPTION_KEYS=[KEY])
        cls._settings.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._settings.disable()
        shutil.rmtree(cls._media, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        seed_geo()
        cls.driver = User.objects.create_user("+919000000001", name="Meera Nair", gender="F")
        cls.rider = User.objects.create_user("+919000000002", name="Ravi", gender="M")
        cls.reviewer = User.objects.create_superuser("+919000000099", password="Reviewer-pass-42", name="Reviewer")

    def setUp(self):
        cache.clear()  # upload throttling counts per user; start each test fresh

    def as_user(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")

    def form(self, **over):
        body = {
            "email": "driver@example.com",
            "vehicleNumber": "tn 09 ab 1234",
            "idType": "pan",
            "licenceFront": upload("dl-front.jpg", JPEG),
            "licenceBack": upload("dl-back.png", PNG),
            "idFront": upload("ABCDE1234F.pdf", PDF),  # an ID number in a file name must never be stored
        }
        body.update(over)
        return {k: v for k, v in body.items() if v is not None}

    def approve(self, v, admin, **kwargs):
        """Approve every document, then the profile (what a reviewer does on the review page)."""
        from apps.verification import services

        for doc in list(v.documents.all()):
            services.review_document(v, doc.pk, admin, approve=True)
        return services.approve(v, admin, **kwargs)

    def submit(self, user=None, **over):
        self.as_user(user or self.driver)
        return self.client.post("/api/v1/me/driver-verification", self.form(**over), format="multipart")
