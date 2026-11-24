from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from common.views import health

admin.site.site_header = settings.ADMIN_SITE_HEADER
admin.site.site_title = settings.ADMIN_SITE_TITLE
admin.site.index_title = "Operations"
# The "View site" link would point at the API root; there is no server-rendered site.
admin.site.site_url = None

api_v1 = [
    path("health", health, name="health"),
    path("", include("apps.accounts.urls")),
    path("", include("apps.verification.urls")),
    path("", include("apps.geo.urls")),
    path("", include("apps.fares.urls")),
    path("risk/", include("apps.risk.urls")),
    path("", include("apps.rides.urls")),
    path("", include("apps.bookings.urls")),
    path("", include("apps.payments.urls")),
]

urlpatterns = [
    # Path from the ADMIN_URL environment variable, not the default /admin/.
    path(settings.ADMIN_URL, admin.site.urls),
    path("api/v1/", include(api_v1)),
    # Admin dashboard API: admin tokens only (see apps/adminpanel).
    path("api/admin/", include("apps.adminpanel.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
]
