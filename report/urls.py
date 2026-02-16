from django.urls import path
from .views import DepenseListView, DepenseCreateView, DepenseDeleteView

app_name = "report"

urlpatterns = [
    path("depenses/", DepenseListView.as_view(), name="depense_list"),
    path("depenses/add/", DepenseCreateView.as_view(), name="depense_add"),
    path(
        "depenses/<int:pk>/delete/", DepenseDeleteView.as_view(), name="depense_delete"
    ),
]
