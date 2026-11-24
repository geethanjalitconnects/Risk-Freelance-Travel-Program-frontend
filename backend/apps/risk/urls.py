from django.urls import path

from .views import RiskConfigView, RiskPreviewView, RiskSamplesView, RiskScoreView

urlpatterns = [
    path("config", RiskConfigView.as_view(), name="risk-config"),
    path("samples", RiskSamplesView.as_view(), name="risk-samples"),
    path("score", RiskScoreView.as_view(), name="risk-score"),
    path("preview", RiskPreviewView.as_view(), name="risk-preview"),
]
