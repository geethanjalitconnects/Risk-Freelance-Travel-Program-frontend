from django.urls import path

from . import views

urlpatterns = [
    path("login", views.LoginView.as_view(), name="admin-api-login"),
    path("logout", views.LogoutView.as_view(), name="admin-api-logout"),
    path("me", views.MeView.as_view(), name="admin-api-me"),
    path("password", views.PasswordChangeView.as_view(), name="admin-api-password"),
    path("queue", views.QueueView.as_view(), name="admin-api-queue"),
    path("review/<uuid:user_id>", views.ReviewDetailView.as_view(), name="admin-api-review"),
    path("review/<uuid:user_id>/documents/<uuid:doc_id>/approve", views.DocumentApproveView.as_view()),
    path("review/<uuid:user_id>/documents/<uuid:doc_id>/reject", views.DocumentRejectView.as_view()),
    path("review/<uuid:user_id>/approve", views.ApproveView.as_view(), name="admin-api-approve"),
    path("review/<uuid:user_id>/reject", views.RejectView.as_view(), name="admin-api-reject"),
    path("review/<uuid:user_id>/request-resubmit", views.RequestResubmitView.as_view()),
    path("review/<uuid:user_id>/revoke", views.RevokeView.as_view()),
    path("documents/<uuid:doc_id>/file", views.DocumentFileView.as_view(), name="admin-api-document"),
    path("emails/<int:email_id>/retry", views.EmailRetryView.as_view()),
    path("audit", views.AuditLogView.as_view(), name="admin-api-audit"),
]
