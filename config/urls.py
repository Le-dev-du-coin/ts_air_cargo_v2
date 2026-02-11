from django.contrib import admin
from django.urls import path, include
from core.views import IndexView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('__reload__/', include("django_browser_reload.urls")),
    path('', include("core.urls")),
    path('chine/', include("chine.urls")),
    path('mali/', include("mali.urls")),
    path('ivoire/', include("ivoire.urls")),
    path('', IndexView.as_view(), name='index'),
]
