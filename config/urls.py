from django.contrib import admin
from django.urls import path, include
from core.views import IndexView
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),
    path("__reload__/", include("django_browser_reload.urls")),
    path("", include("core.urls")),
    path("chine/", include("chine.urls")),
    path("mali/", include("mali.urls")),
    path("ivoire/", include("ivoire.urls")),
    path("clients/", include("customers.urls")),
    path("admin-app/", include("admin_app.urls", namespace="admin_app")),
    path("", IndexView.as_view(), name="index"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
