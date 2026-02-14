from django.urls import path
from .views import (
    DashboardView,
    AujourdhuiView,
    LotsEnTransitView,
    LotArriveView,
    LotDetailView,
    ColisArriveView,
)

app_name = "mali"

urlpatterns = [
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path("aujourdhui/", AujourdhuiView.as_view(), name="aujourdhui"),
    path("lots/transit/", LotsEnTransitView.as_view(), name="lots_transit"),
    path("lots/<int:pk>/", LotDetailView.as_view(), name="lot_detail"),
    path("lots/<int:pk>/arrive/", LotArriveView.as_view(), name="lot_arrive"),
    path("colis/<int:pk>/arrive/", ColisArriveView.as_view(), name="colis_arrive"),
]
