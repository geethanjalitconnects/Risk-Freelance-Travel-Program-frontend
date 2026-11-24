from django.urls import path

from .views import MyDocumentUploadView, MyVerificationView

urlpatterns = [
    path("me/driver-verification", MyVerificationView.as_view(), name="driver-verification"),
    path("me/driver-verification/documents/<str:kind>", MyDocumentUploadView.as_view(), name="driver-verification-document"),
]
