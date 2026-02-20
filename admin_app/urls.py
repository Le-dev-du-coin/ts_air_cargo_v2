from django.urls import path
from . import views

app_name = "admin_app"

urlpatterns = [
    path(
        "config/notifications/",
        views.NotificationConfigView.as_view(),
        name="notification_config",
    ),
    path(
        "config/notifications/status/",
        views.WaChapStatusView.as_view(),
        name="wachap_status",
    ),
]
