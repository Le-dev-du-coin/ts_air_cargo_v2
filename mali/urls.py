from django.urls import path
from .views import (
    DashboardView,
    AujourdhuiView,
    LotsEnTransitView,
    LotsArrivesView,
    LotArriveView,
    LotTransitDetailView,
    LotArriveDetailView,
    ColisArriveView,
    ColisLivreView,
)

app_name = "mali"

urlpatterns = [
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path("aujourdhui/", AujourdhuiView.as_view(), name="aujourdhui"),
    path("lots/transit/", LotsEnTransitView.as_view(), name="lots_transit"),
    path("lots/arrives/", LotsArrivesView.as_view(), name="lots_arrives"),
    path(
        "lots/transit/<int:pk>/",
        LotTransitDetailView.as_view(),
        name="lot_transit_detail",
    ),
    path(
        "lots/arrives/<int:pk>/",
        LotArriveDetailView.as_view(),
        name="lot_arrived_detail",
    ),
    path("lots/<int:pk>/arrive/", LotArriveView.as_view(), name="lot_arrive"),
    path("colis/<int:pk>/arrive/", ColisArriveView.as_view(), name="colis_arrive"),
    path("colis/<int:pk>/livrer/", ColisLivreView.as_view(), name="colis_livre"),
]
