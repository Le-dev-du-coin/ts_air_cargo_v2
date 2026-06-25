from django.contrib.auth.views import LoginView
from django.contrib.auth import logout
from django.shortcuts import redirect, get_object_or_404
from django.urls import reverse_lazy
from django.views.generic import TemplateView
from django.http import HttpResponse, Http404
from .forms import LoginForm
from django.contrib.auth.decorators import user_passes_test


class IndexView(TemplateView):
    template_name = "index.html"


class CustomLoginView(LoginView):
    form_class = LoginForm
    template_name = "registration/login.html"
    redirect_authenticated_user = True

    def form_valid(self, form):
        # Se souvenir de moi (expiration de session)
        remember_me = self.request.POST.get("remember_me", False)
        if remember_me:
            # Expire dans 30 jours
            self.request.session.set_expiry(2592000)
        else:
            # Expire à la fermeture du navigateur
            self.request.session.set_expiry(0)
        return super().form_valid(form)

    def get_success_url(self):
        user = self.request.user
        if user.role == "GLOBAL_ADMIN":
            return reverse_lazy("admin:index")
        elif user.role in ["ADMIN_CHINE", "AGENT_CHINE"]:
            return reverse_lazy("chine:dashboard")
        elif user.role in ["ADMIN_MALI", "AGENT_MALI"]:
            return reverse_lazy("mali:dashboard")
        elif user.role in ["ADMIN_RCI", "AGENT_RCI"]:
            return reverse_lazy("ivoire:dashboard")
        elif user.role == "CLIENT":
            return reverse_lazy("customers:dashboard")
        # Add other role redirections here
        return reverse_lazy("index")


def logout_view(request):
    logout(request)
    return redirect("index")


@user_passes_test(lambda u: u.is_superuser or u.role == "GLOBAL_ADMIN")
def flower_redirect(request):
    """
    Redirige les Super-Administrateurs vers le panel Flower de surveillance des tâches Celery.
    (Par défaut sur le port 5555 configuré dans start_flower.sh)
    """
    # Récupère l'IP/Domaine actuel du serveur et redirige vers le port 5555
    host = request.META.get("HTTP_HOST", "localhost").split(":")[0]
    return redirect(f"http://{host}:5555/")


from django.http import JsonResponse
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin

class CalculatePriceAPIView(LoginRequiredMixin, View):
    """
    API Globale pour calculer le prix d'un colis en temps réel via AJAX.
    Utilisable par toutes les applications (Chine, Mali, Côte d'Ivoire).
    """

    def get(self, request):
        client_id = request.GET.get("client_id")
        lot_id = request.GET.get("lot_id")
        type_colis = request.GET.get("type_colis", "STANDARD")
        poids = request.GET.get("poids", 0)
        cbm = request.GET.get("cbm", 0)
        nombre_pieces = request.GET.get("nombre_pieces", 1)
        prix_kilo_manuel = request.GET.get("prix_kilo_manuel", "")

        if not all([client_id, lot_id]):
            return JsonResponse({"error": "Paramètres manquants (client_id, lot_id)"}, status=400)

        try:
            from core.models import Client, Lot, Colis
            from decimal import Decimal

            client = Client.objects.get(pk=client_id)
            lot = Lot.objects.get(pk=lot_id)

            # Conversion sécurisée (évite erreurs si virgule ou vide)
            try:
                p_val = Decimal(str(poids).replace(",", ".")) if poids and str(poids).strip() else Decimal("0")
                c_val = Decimal(str(cbm).replace(",", ".")) if cbm and str(cbm).strip() else Decimal("0")
                n_val = int(nombre_pieces) if nombre_pieces else 1
                pm_val = Decimal(str(prix_kilo_manuel).replace(",", ".")) if prix_kilo_manuel and str(prix_kilo_manuel).strip() else None
            except (ValueError, TypeError, Exception):
                p_val = Decimal("0")
                c_val = Decimal("0")
                n_val = 1
                pm_val = None

            temp_colis = Colis(
                client=client,
                lot=lot,
                type_colis=type_colis,
                poids=p_val,
                cbm=c_val,
                nombre_pieces=n_val,
                prix_kilo_manuel=pm_val
            )
            temp_colis.recalculate_prices()

            return JsonResponse(
                {
                    "prix_final": float(temp_colis.prix_final or 0),
                    "prix_transport": float(temp_colis.prix_transport or 0),
                    "success": True,
                }
            )
        except Exception as e:
            return JsonResponse({"error": str(e), "prix_final": 0, "success": False}, status=400)
