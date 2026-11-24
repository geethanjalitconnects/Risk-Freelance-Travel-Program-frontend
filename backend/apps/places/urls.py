from django.urls import path

from .views import AutocompleteView, DetailsView, ReverseView

urlpatterns = [
    path("places/autocomplete", AutocompleteView.as_view(), name="places-autocomplete"),
    path("places/details", DetailsView.as_view(), name="places-details"),
    path("places/reverse", ReverseView.as_view(), name="places-reverse"),
]
