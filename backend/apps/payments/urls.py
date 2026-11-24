from django.urls import path

from .webhooks import RazorpayWebhookView
from .views import MyEarningsHistoryView, MyEarningsView, MyPaymentsView, MyPayoutAccountView, MyWithdrawalsView

urlpatterns = [
    path("me/payout-account", MyPayoutAccountView.as_view(), name="payout-account"),
    path("me/earnings", MyEarningsView.as_view(), name="earnings"),
    path("me/earnings/history", MyEarningsHistoryView.as_view(), name="earnings-history"),
    path("me/withdrawals", MyWithdrawalsView.as_view(), name="withdrawals"),
    path("me/payments", MyPaymentsView.as_view(), name="my-payments"),
    path("payments/razorpay/webhook", RazorpayWebhookView.as_view(), name="razorpay-webhook"),
]
