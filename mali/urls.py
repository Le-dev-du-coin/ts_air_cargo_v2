from django.urls import path
from .views import (
    DashboardView,
    AujourdhuiView,
    LotsEnTransitView,
    LotsArrivesView,
    LotsLivresView,
    LotArriveView,
    LotTransitDetailView,
    LotArriveDetailView,
    LotLivreDetailView,
    ColisArriveView,
    ColisLivreView,
    ColisPerduView,
    ColisAttentePaiementView,
    RapportJourPDFView,
    LotTransitPDFView,
)

app_name = "mali"

urlpatterns = [
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path("aujourdhui/", AujourdhuiView.as_view(), name="aujourdhui"),
    path("lots/transit/", LotsEnTransitView.as_view(), name="lots_transit"),
    path("lots/arrives/", LotsArrivesView.as_view(), name="lots_arrives"),
    path("lots/livres/", LotsLivresView.as_view(), name="lots_livres"),
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
    path(
        "lots/livres/<int:pk>/",
        LotLivreDetailView.as_view(),
        name="lot_livre_detail",
    ),
    path("lots/<int:pk>/arrive/", LotArriveView.as_view(), name="lot_arrive"),
    path("colis/<int:pk>/arrive/", ColisArriveView.as_view(), name="colis_arrive"),
    path("colis/<int:pk>/livre/", ColisLivreView.as_view(), name="colis_livre"),
    path("colis/<int:pk>/perdu/", ColisPerduView.as_view(), name="colis_perdu"),
    path(
        "colis/attente-paiement/",
        ColisAttentePaiementView.as_view(),
        name="colis_attente_paiement",
    ),
    path("rapport/jour/pdf/", RapportJourPDFView.as_view(), name="rapport_jour_pdf"),
    path(
        "lot/<int:pk>/manifeste/pdf/",
        LotTransitPDFView.as_view(),
        name="lot_manifeste_pdf",
    ),
]
