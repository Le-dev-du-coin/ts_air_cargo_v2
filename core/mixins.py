from django.contrib.auth.mixins import AccessMixin
from django.contrib import messages
from django.shortcuts import redirect


class DestinationAgentRequiredMixin(AccessMixin):
    """
    Mixin générique pour restreindre l'accès au module de destination
    (Mali, Côte d'Ivoire, Sénégal, etc.).
    Vérifie que :
    1. L'utilisateur est connecté
    2. L'utilisateur a un rôle lié à une destination (ex: AGENT_MALI, AGENT_RCI) ou est GLOBAL_ADMIN
    """

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        # Rôles autorisés pour les destinations
        allowed_roles = [
            "GLOBAL_ADMIN",
            "AGENT_MALI",
            "ADMIN_MALI",
            "AGENT_RCI",
            "ADMIN_RCI",
        ]

        if request.user.role not in allowed_roles:
            messages.error(
                request,
                "Accès refusé. Cette section est réservée aux agents de destination.",
            )
            return redirect("index")

        # Optionnel: on peut aussi s'assurer que request.user.country n'est pas None
        if request.user.role != "GLOBAL_ADMIN" and not request.user.country:
            messages.error(
                request,
                "Accès refusé. Aucun pays de destination n'est assigné à votre compte.",
            )
            return redirect("index")

        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = {}
        if hasattr(super(), "get_context_data"):
            context = super().get_context_data(**kwargs)
        context["current_country"] = self.get_current_country()
        return context

    def get_current_country(self):
        """
        Retourne le pays de la destination associée à l'agent connecté.
        Pour un GLOBAL_ADMIN sans pays, on renverra le Mali par défaut ou on gérera via session.
        """
        if getattr(self.request.user, "country", None):
            return self.request.user.country

        from core.models import Country

        return Country.objects.first()

    def handle_no_permission(self):
        messages.error(
            self.request,
            "Veuillez vous connecter pour accéder à l'Espace de Destination.",
        )
        return redirect("index")
