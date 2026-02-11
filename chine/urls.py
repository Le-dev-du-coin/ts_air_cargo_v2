from django.urls import path
from .views import (
    DashboardView, 
    ClientListView, ClientCreateView,
    LotListView, LotCreateView, LotDetailView,
    ColisCreateView
)

app_name = "chine"

urlpatterns = [
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    
    # Clients
    path("clients/", ClientListView.as_view(), name="client_list"),
    path("clients/add/", ClientCreateView.as_view(), name="client_add"),
    
    # Lots
    path("lots/", LotListView.as_view(), name="lot_list"),
    path("lots/create/", LotCreateView.as_view(), name="lot_create"),
    path("lots/<int:pk>/", LotDetailView.as_view(), name="lot_detail"),
    
    # Colis (Nested under lot)
    path("lots/<int:lot_id>/colis/add/", ColisCreateView.as_view(), name="colis_add"),
]
