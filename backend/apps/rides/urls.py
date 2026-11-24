from django.urls import path

from .views import MyRidesView, RideCreateView, RideDetailView, RideSearchView

urlpatterns = [
    path("rides", RideCreateView.as_view(), name="ride-create"),
    path("rides/search", RideSearchView.as_view(), name="ride-search"),
    path("rides/mine", MyRidesView.as_view(), name="ride-mine"),
    path("rides/<uuid:pk>", RideDetailView.as_view(), name="ride-detail"),
]
