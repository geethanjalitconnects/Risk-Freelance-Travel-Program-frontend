from django.urls import path

from . import views

urlpatterns = [
    path("bookings", views.BookingListView.as_view(), name="booking-list"),
    path("bookings/<uuid:pk>", views.BookingDetailView.as_view(), name="booking-detail"),
    path("bookings/quote", views.PriceQuoteView.as_view(), name="booking-quote"),
    path("bookings/<uuid:pk>/pay", views.PayView.as_view(), name="booking-pay"),
    path("bookings/<uuid:pk>/payment/verify", views.PaymentVerifyView.as_view(), name="booking-payment-verify"),
    path("bookings/<uuid:pk>/cancel", views.CancelView.as_view(), name="booking-cancel"),
    path("bookings/<uuid:pk>/cancellation-quote", views.CancelQuoteView.as_view(), name="booking-cancel-quote"),
    path("bookings/<uuid:pk>/start", views.StartView.as_view(), name="booking-start"),
    path("bookings/<uuid:pk>/checkins", views.CheckInView.as_view(), name="booking-checkins"),
    path("bookings/<uuid:pk>/missed", views.MissedCheckInView.as_view(), name="booking-missed"),
    path("bookings/<uuid:pk>/share", views.ShareView.as_view(), name="booking-share"),
    path("bookings/<uuid:pk>/sos", views.SosView.as_view(), name="booking-sos"),
    path("bookings/<uuid:pk>/complete", views.CompleteView.as_view(), name="booking-complete"),
    path("bookings/<uuid:pk>/rate", views.RateView.as_view(), name="booking-rate"),
    path("bookings/<uuid:pk>/problems", views.ProblemView.as_view(), name="booking-problems"),
    path("rides/<uuid:pk>/complete", views.RideCompleteView.as_view(), name="ride-complete"),
    path("rides/<uuid:pk>/cancel", views.RideCancelView.as_view(), name="ride-cancel"),
    path("rides/<uuid:pk>/cancellation-quote", views.RideCancelQuoteView.as_view(), name="ride-cancel-quote"),
]
