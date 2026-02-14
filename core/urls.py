from django.urls import path
from .views import CustomLoginView, logout_view

app_name = "core"

urlpatterns = [
    # Route par défaut (Client)
    path("login/", CustomLoginView.as_view(extra_context={'title': 'Espace Client', 'user_type': 'client'}), name="login"),
    
    # Routes spécifiques
    # Routes spécifiques par Pays (Branding)
    # Chine (Rouge)
    path("login/agent/chine/", CustomLoginView.as_view(extra_context={'title': 'Agent Chine', 'flag': '🇨🇳', 'theme': 'red', 'user_type': 'agent'}), name="login_agent_chine"),
    path("login/admin/chine/", CustomLoginView.as_view(extra_context={'title': 'Admin Chine', 'flag': '🇨🇳', 'theme': 'red', 'user_type': 'admin'}), name="login_admin_chine"),
    
    # Mali (Vert)
    path("login/agent/mali/", CustomLoginView.as_view(extra_context={'title': 'Agent Mali', 'flag': '🇲🇱', 'theme': 'green', 'user_type': 'agent'}), name="login_agent_mali"),
    path("login/admin/mali/", CustomLoginView.as_view(extra_context={'title': 'Admin Mali', 'flag': '🇲🇱', 'theme': 'green', 'user_type': 'admin'}), name="login_admin_mali"),
    
    # RCI (Orange)
    path("login/agent/ivoire/", CustomLoginView.as_view(extra_context={'title': 'Agent RCI', 'flag': '🇨🇮', 'theme': 'orange', 'user_type': 'agent'}), name="login_agent_rci"),
    path("login/admin/ivoire/", CustomLoginView.as_view(extra_context={'title': 'Admin RCI', 'flag': '🇨🇮', 'theme': 'orange', 'user_type': 'admin'}), name="login_admin_rci"),

    # Routes génériques (Fallback)
    path("login/agent/", CustomLoginView.as_view(extra_context={'title': 'Accès Agent', 'user_type': 'agent'}), name="login_agent"),
    path("login/admin/", CustomLoginView.as_view(extra_context={'title': 'Administration', 'user_type': 'admin'}), name="login_admin"),
    
    path("logout/", logout_view, name="logout"),
]
