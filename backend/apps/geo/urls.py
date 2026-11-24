from django.urls import path

from .views import AreaDetailView

urlpatterns = [
    path("areas/<str:code>", AreaDetailView.as_view(), name="area-detail"),
]
