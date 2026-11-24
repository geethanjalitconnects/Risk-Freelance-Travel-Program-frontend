"""Phase 6: the payout details API."""
from cryptography.fernet import Fernet
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User
from apps.payments.models import FinancialAuditLog, PayoutAccount
from apps.verification.testing import approve_driver

KEY = Fernet.generate_key().decode()
NUMBER = "50100123456789"
BANK = {
    "method": "bank", "holderName": "Meera  Nair", "bankName": "HDFC Bank", "accountNumber": "5010 0123 4567 89",
    "confirmAccountNumber": NUMBER, "ifsc": "hdfc0001234",
}


@override_settings(PAYOUT_ENCRYPTION_KEYS=[KEY])
class PayoutAccountApiTests(APITestCase):
    url = reverse("payout-account")

    @classmethod
    def setUpTestData(cls):
        cls.driver = approve_driver(User.objects.create_user("+919000000002", name="Meera", gender="F"))
        cls.rider = User.objects.create_user("+919000000003", name="Ravi", gender="M")

    def as_user(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")

    def put(self, body, user=None):
        self.as_user(user or self.driver)
        return self.client.put(self.url, body, format="json")

    def test_needs_sign_in_and_approval(self):
        self.assertEqual(self.client.get(self.url).status_code, 401)
        r = self.put(BANK, self.rider)
        self.assertEqual((r.status_code, r.json()["code"]), (403, "verification_required"))
        self.assertEqual(self.client.get(self.url).json(), {"account": None, "canEdit": False})

    def test_save_bank_details_masked(self):
        r = self.put(BANK)
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()["account"]
        self.assertTrue(r.json()["canEdit"])
        self.assertEqual(
            {k: body[k] for k in ("method", "holderName", "ifsc", "accountLast4", "display", "status")},
            {"method": "bank", "holderName": "Meera Nair", "ifsc": "HDFC0001234", "accountLast4": "6789",
             "display": "HDFC Bank ••••6789", "status": "pending"},
        )
        self.assertNotIn(NUMBER, r.content.decode())
        self.assertNotIn(NUMBER, self.client.get(self.url).content.decode())
        self.assertEqual(PayoutAccount.objects.get(user=self.driver).account_number(), NUMBER)

        log = FinancialAuditLog.objects.get(action="payout_account_changed")
        self.assertEqual(log.actor, self.driver)
        self.assertNotIn(NUMBER, str(log.details))
        self.assertEqual(log.details["destination"], "HDFC Bank ••••6789")

    def test_validation_errors_never_echo_the_number(self):
        r = self.put({**BANK, "confirmAccountNumber": "50100123456780"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["confirmAccountNumber"], ["The account numbers don't match."])
        self.assertNotIn("5010012345678", r.content.decode())

        r = self.put({**BANK, "ifsc": "HDFC1001234", "accountNumber": "123", "bankName": " "})
        self.assertEqual(set(r.json()), {"ifsc", "accountNumber", "bankName"})
        r = self.put({**BANK, "holderName": "M3era!"})
        self.assertIn("holderName", r.json())
        self.assertFalse(PayoutAccount.objects.exists())

    def test_upi_and_switching_clears_the_other_method(self):
        self.put(BANK)
        r = self.put({"method": "upi", "holderName": "Meera Nair", "upiId": "Meera.N@okaxis"})
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()["account"]
        self.assertEqual((body["display"], body["accountLast4"], body["ifsc"]), ("me*****@okaxis", "", ""))
        pa = PayoutAccount.objects.get(user=self.driver)
        self.assertIsNone(pa.account_number_enc)
        self.assertEqual(pa.upi_id(), "meera.n@okaxis")
        self.assertEqual(self.put({"method": "upi", "holderName": "Meera Nair", "upiId": "nope"}).status_code, 400)

    def test_editing_resets_verification(self):
        self.put(BANK)
        PayoutAccount.objects.filter(user=self.driver).update(status="verified", provider_account_id="acc_X")
        self.put({**BANK, "accountNumber": "123456789012", "confirmAccountNumber": "123456789012"})
        pa = PayoutAccount.objects.get(user=self.driver)
        self.assertEqual((pa.status, pa.provider_account_id, pa.account_last4), ("pending", "", "9012"))
        self.assertEqual(PayoutAccount.objects.count(), 1)
