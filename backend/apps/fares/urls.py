from django.urls import path

from .views import FareQuoteView

urlpatterns = [
    path("fares/quote", FareQuoteView.as_view(), name="fare-quote"),
]
