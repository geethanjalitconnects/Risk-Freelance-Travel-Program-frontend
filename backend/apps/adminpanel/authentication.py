from rest_framework import authentication, exceptions, permissions

from . import tokens


class AdminJWTAuthentication(authentication.BaseAuthentication):
    """``Authorization: Bearer <admin token>``. The only authentication on /api/admin/*: user
    tokens and sessions are not accepted there."""

    keyword = "Bearer"

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).split()
        if not header or header[0].lower() != self.keyword.lower().encode():
            return None
        if len(header) != 2:
            raise exceptions.AuthenticationFailed("Invalid authorization header.")
        try:
            user, role = tokens.decode(header[1].decode("latin-1"))
        except tokens.InvalidAdminToken as e:
            raise exceptions.AuthenticationFailed(str(e))
        request.admin_role = role
        return user, role

    def authenticate_header(self, request):
        return 'Bearer realm="admin"'  # makes DRF answer 401 (not 403) without a token


class IsDashboardStaff(permissions.BasePermission):
    """A valid admin token whose account has changed its first password."""

    def has_permission(self, request, view):
        if getattr(request, "admin_role", None) is None:
            return False
        if request.user.must_change_password and not getattr(view, "allow_before_password_change", False):
            raise exceptions.PermissionDenied({"detail": "Change your password before continuing.", "code": "password_change_required"})
        return True


class IsSuperAdmin(IsDashboardStaff):
    message = "Only admins can see this."

    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.admin_role == "admin"
