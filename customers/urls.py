from django.urls import path
from . import views

app_name = "customers"

urlpatterns = [
    path("", views.ClientDashboardView.as_view(), name="dashboard"),
    path("colis/", views.ClientParcelListView.as_view(), name="parcel_list"),
    path(
        "colis/<int:pk>/", views.ClientParcelDetailView.as_view(), name="parcel_detail"
    ),
    path("profil/", views.ClientProfileUpdateView.as_view(), name="profile_update"),
    path(
        "password-change/",
        views.ClientPasswordChangeView.as_view(),
        name="password_change",
    ),
    path("parametres/", views.ClientSettingsView.as_view(), name="settings"),
]
