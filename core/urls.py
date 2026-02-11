from django.urls import path
from .views import CustomLoginView, logout_view

app_name = "core"

urlpatterns = [
    # Route par défaut (Client)
    path("login/", CustomLoginView.as_view(extra_context={'title': 'Espace Client', 'user_type': 'client'}), name="login"),
    
    # Routes spécifiques
    path("login/agent/", CustomLoginView.as_view(extra_context={'title': 'Accès Agent', 'user_type': 'agent'}), name="login_agent"),
    path("login/admin/", CustomLoginView.as_view(extra_context={'title': 'Administration', 'user_type': 'admin'}), name="login_admin"),
    
    path("logout/", logout_view, name="logout"),
]
