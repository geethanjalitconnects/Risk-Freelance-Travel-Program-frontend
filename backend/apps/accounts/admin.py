"""Users in the admin: search by phone, filter by gender and driver verification status,
deactivate / reactivate. Superusers only (reviewers have no permission on users)."""
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from apps.verification.models import VerificationStatus

from . import services
from .models import PhoneOTP, TrustedContact, User


class TrustedContactInline(admin.TabularInline):
    model = TrustedContact
    extra = 0
    fields = ["name", "phone", "relation", "created_at"]
    readonly_fields = ["created_at"]


class DriverVerificationFilter(admin.SimpleListFilter):
    title = "driver verification"
    parameter_name = "verification"

    def lookups(self, request, model_admin):
        return VerificationStatus.choices

    def queryset(self, request, queryset):
        value = self.value()
        if not value:
            return queryset
        if value == VerificationStatus.NOT_SUBMITTED:
            return queryset.filter(driver_verification__isnull=True)
        return queryset.filter(driver_verification__status=value)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ["-date_joined"]
    list_display = ["phone", "name", "gender", "verification_status", "is_active", "is_staff", "date_joined"]
    list_filter = ["gender", DriverVerificationFilter, "is_active", "is_staff"]
    search_fields = ["phone", "name"]
    list_select_related = ["driver_verification"]
    inlines = [TrustedContactInline]
    actions = ["deactivate_selected", "reactivate_selected"]
    # is_active is changed only through the actions, so the side effects (cancelled bookings,
    # revoked tokens) always happen.
    readonly_fields = ["is_active", "deactivated_at", "verified_id", "verified_license", "last_login", "date_joined"]
    fieldsets = (
        (None, {"fields": ("phone", "password")}),
        ("Profile", {"fields": ("name", "gender", "bio", "languages")}),
        ("Status", {"fields": ("is_active", "deactivated_at", "verified_id", "verified_license")}),
        ("Admin access", {"fields": ("is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("phone", "name", "password1", "password2")}),
    )

    @admin.display(description="Driver verification", ordering="driver_verification__status")
    def verification_status(self, obj):
        v = getattr(obj, "driver_verification", None)
        return v.get_status_display() if v else VerificationStatus.NOT_SUBMITTED.label

    def has_delete_permission(self, request, obj=None):
        # Deleting users would destroy booking history; deactivate instead.
        return False

    @admin.action(description="Deactivate selected accounts (blocks sign-in, cancels upcoming bookings)")
    def deactivate_selected(self, request, queryset):
        users = cancelled = 0
        for user in queryset:
            try:
                cancelled += services.deactivate(user, request.user)
                users += 1
            except services.AccountActionError as e:
                self.message_user(request, f"{user.phone}: {e}", messages.ERROR)
        if users:
            self.message_user(
                request, f"Deactivated {users} account{'s' if users != 1 else ''}; cancelled {cancelled} upcoming booking{'s' if cancelled != 1 else ''}.",
                messages.SUCCESS,
            )

    @admin.action(description="Reactivate selected accounts")
    def reactivate_selected(self, request, queryset):
        for user in queryset:
            services.reactivate(user)
        self.message_user(request, f"Reactivated {queryset.count()} account(s).", messages.SUCCESS)


@admin.register(PhoneOTP)
class PhoneOTPAdmin(admin.ModelAdmin):
    """Audit of sign-in code requests. The codes are never stored or shown (only a keyed hash
    exists, and it is excluded here)."""

    list_display = ["phone", "created_at", "expires_at", "attempts", "consumed_at"]
    search_fields = ["phone"]
    exclude = ["code_hash"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
