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
    ColisPerduView,
    ColisAttentePaiementView,
    ColisEncaissementView,
    RapportJourPDFView,
    LotTransitPDFView,
    NotificationConfigView,
)
from report.views import (
    DepenseListView,
    DepenseCreateView,
    DepenseDeleteView,
    RapportFinancierView,
    TransfertListView,
    TransfertCreateView,
    RapportExportView,
)

app_name = "mali"

urlpatterns = [
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path(
        "notifications/config/",
        NotificationConfigView.as_view(),
        name="notifications_config",
    ),
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
    path(
        "colis/<int:pk>/encaisser/",
        ColisEncaissementView.as_view(),
        name="colis_encaisser",
    ),
    path("rapport/jour/pdf/", RapportJourPDFView.as_view(), name="rapport_jour_pdf"),
    path(
        "lot/<int:pk>/manifeste/pdf/",
        LotTransitPDFView.as_view(),
        name="lot_manifeste_pdf",
    ),
    # Finance
    path(
        "finance/depenses/",
        DepenseListView.as_view(template_name="mali/finance/depenses.html"),
        name="depenses_list",
    ),
    path("finance/depenses/add/", DepenseCreateView.as_view(), name="depense_add"),
    path(
        "finance/depenses/<int:pk>/delete/",
        DepenseDeleteView.as_view(),
        name="depense_delete",
    ),
    path(
        "finance/rapport/",
        RapportFinancierView.as_view(),
        name="rapport_financier",
    ),
    path(
        "finance/transferts/",
        TransfertListView.as_view(template_name="mali/finance/transferts.html"),
        name="transferts_list",
    ),
    path(
        "finance/transferts/add/",
        TransfertCreateView.as_view(),
        name="transfert_add",
    ),
    path(
        "finance/rapport/export/",
        RapportExportView.as_view(),
        name="rapport_export",
    ),
]
