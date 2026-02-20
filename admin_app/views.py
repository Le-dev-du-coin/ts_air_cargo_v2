import logging
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic.edit import UpdateView
from django.contrib import messages
from django.urls import reverse_lazy

from notification.models import ConfigurationNotification
from notification.services.wachap_monitor import wachap_monitor
from .forms import NotificationConfigAdminForm
from django.http import JsonResponse

logger = logging.getLogger(__name__)


class AdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Réserve l'accès aux superutilisateurs, Global Admin et Admin Chine."""

    ALLOWED_ROLES = {"GLOBAL_ADMIN", "ADMIN_CHINE", "AGENT_CHINE"}

    def test_func(self):
        user = self.request.user
        return user.is_superuser or (
            hasattr(user, "role") and user.role in self.ALLOWED_ROLES
        )

    def handle_no_permission(self):
        messages.error(
            self.request,
            "Accès refusé. Cette section est réservée aux administrateurs.",
        )
        from django.shortcuts import redirect

        return redirect("index")


class NotificationConfigView(AdminRequiredMixin, UpdateView):
    """
    Page de configuration centralisée des notifications WhatsApp.
    Accessible via /admin-app/config/notifications/
    Gère les instances : Côte d'Ivoire, Chine, Système.
    """

    model = ConfigurationNotification
    form_class = NotificationConfigAdminForm
    template_name = "admin_app/config_notifications.html"
    success_url = reverse_lazy("admin_app:notification_config")

    def get_object(self, queryset=None):
        return ConfigurationNotification.get_solo()

    def form_valid(self, form):
        messages.success(
            self.request, "✅ Configuration des notifications mise à jour."
        )
        return super().form_valid(form)


class WaChapStatusView(AdminRequiredMixin, UpdateView):
    """
    Retourne l'état en temps réel de toutes les instances WaChap.
    Utilisable en AJAX pour afficher un indicateur de santé dans l'UI.
    """

    # On hérite de UpdateView pour le mixin uniquement ; on override get()
    model = ConfigurationNotification
    form_class = NotificationConfigAdminForm
    template_name = "admin_app/config_notifications.html"

    def get(self, request, *args, **kwargs):
        try:
            status = wachap_monitor.check_all_instances()
            return JsonResponse({"status": "ok", "instances": status})
        except Exception as e:
            logger.error(f"Erreur WaChapStatusView: {e}")
            return JsonResponse({"status": "error", "message": str(e)}, status=500)
