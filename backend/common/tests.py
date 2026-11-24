from axes.models import AccessAttempt
from django.conf import settings
from django.test import TestCase, override_settings

from apps.accounts.models import User

LOGIN = "/" + settings.ADMIN_URL + "login/"


class AdminSiteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("+919000000001", password="Correct-horse-42", name="Root")
        cls.staff_without_perms = User.objects.create_user("+919000000002", password="Another-pass-42", is_staff=True)
        cls.app_user = User.objects.create_user("+919000000003", name="Rider")  # OTP only, no password

    def login(self, phone, password):
        return self.client.post(LOGIN, {"username": phone, "password": password, "next": "/" + settings.ADMIN_URL})

    def test_admin_lives_at_configured_path_not_default(self):
        self.assertNotEqual(settings.ADMIN_URL, "admin/")
        self.assertEqual(self.client.get("/admin/").status_code, 404)
        r = self.client.get(LOGIN)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "VConnects Travel administration")

    def test_superuser_can_log_in(self):
        r = self.login("+919000000001", "Correct-horse-42")
        self.assertEqual(r.status_code, 302)
        self.assertContains(self.client.get("/" + settings.ADMIN_URL), "Operations")

    def test_app_users_and_non_staff_cannot_log_in(self):
        self.assertEqual(self.login("+919000000003", "").status_code, 200)  # form re-shown with an error
        regular = User.objects.create_user("+919000000004", password="Regular-pass-42")
        r = self.login(regular.phone, "Regular-pass-42")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Please enter the correct")

    def test_repeated_failures_lock_the_login(self):
        for _ in range(settings.AXES_FAILURE_LIMIT):
            self.login("+919000000001", "wrong-password")
        self.assertTrue(AccessAttempt.objects.filter(username="+919000000001").exists())
        r = self.login("+919000000001", "Correct-horse-42")  # even the right password is refused
        self.assertEqual(r.status_code, 429)
        self.assertFalse(r.wsgi_request.user.is_authenticated)

    def test_lockout_is_per_username_not_whole_ip(self):
        for _ in range(settings.AXES_FAILURE_LIMIT):
            self.login("+919999999999", "guessing")  # someone hammering another account
        other = User.objects.create_superuser("+919000000005", password="Second-admin-42")
        self.assertEqual(self.login(other.phone, "Second-admin-42").status_code, 302)

    def test_phone_accepted_in_any_common_format(self):
        for typed in ("9000000001", "90000 00001", "+91 90000-00001", "+919000000001"):
            with self.subTest(typed=typed):
                self.client.logout()
                self.assertEqual(self.login(typed, "Correct-horse-42").status_code, 302)

    def test_changing_the_format_does_not_earn_extra_attempts(self):
        formats = ["9000000001", "90000 00001", "+919000000001", "+91 90000 00001", "90000-00001"]
        for typed in formats[: settings.AXES_FAILURE_LIMIT]:
            self.login(typed, "wrong-password")
        self.assertEqual(AccessAttempt.objects.get().username, "+919000000001")
        self.assertEqual(self.login("9000000001", "Correct-horse-42").status_code, 429)

    def test_success_resets_failure_count(self):
        for _ in range(settings.AXES_FAILURE_LIMIT - 1):
            self.login("+919000000001", "wrong-password")
        self.assertEqual(self.login("+919000000001", "Correct-horse-42").status_code, 302)
        self.client.logout()
        for _ in range(settings.AXES_FAILURE_LIMIT - 1):
            self.login("+919000000001", "wrong-password")
        self.assertEqual(self.login("+919000000001", "Correct-horse-42").status_code, 302)

    @override_settings(AXES_ENABLED=False)
    def test_staff_without_permissions_sees_no_models(self):
        self.client.force_login(self.staff_without_perms)
        r = self.client.get("/" + settings.ADMIN_URL)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "have permission to view or edit anything")
