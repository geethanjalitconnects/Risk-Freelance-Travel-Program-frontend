from django.urls import path

from .views import CityDetailView, CityListView

urlpatterns = [
    path("cities", CityListView.as_view(), name="city-list"),
    path("cities/<str:code>", CityDetailView.as_view(), name="city-detail"),
]
