from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse


class ForcePasswordChangeMiddleware:
    """Django admin: an account with ``must_change_password`` can only open the password change
    page (and sign out) until it has chosen a new password."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        prefix = "/" + settings.ADMIN_URL
        if not (request.path.startswith(prefix) and user is not None and user.is_authenticated and user.must_change_password):
            return self.get_response(request)

        change = reverse("admin:password_change")
        allowed = (change, reverse("admin:logout"), reverse("admin:password_change_done"), reverse("admin:jsi18n"))
        if request.path not in allowed:
            return redirect(change)
        response = self.get_response(request)
        # Django's password change view redirects only after a valid change.
        if request.path == change and request.method == "POST" and response.status_code == 302:
            user.refresh_from_db()
            user.must_change_password = False
            user.admin_token_version += 1  # end any dashboard sessions using the old password
            user.save(update_fields=["must_change_password", "admin_token_version"])
        return response
