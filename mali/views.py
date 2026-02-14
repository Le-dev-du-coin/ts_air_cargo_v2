from django.views.generic import TemplateView, ListView, View, DetailView
from django.shortcuts import get_object_or_404, redirect
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.db.models import Q, Count, Sum
from core.models import Country, Lot, Colis, Client
from django.contrib import messages


class AgentMaliRequiredMixin:
    """Mixin pour restreindre l'accès aux agents Mali"""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        # Vérifier que l'utilisateur est agent ou admin Mali
        if request.user.role not in ["AGENT_MALI", "ADMIN_MALI"]:
            from django.contrib import messages
            from django.shortcuts import redirect

            messages.error(
                request, "Accès refusé. Cette section est réservée aux agents Mali."
            )
            return redirect("index")

        return super().dispatch(request, *args, **kwargs)

    def handle_no_permission(self):
        from django.contrib import messages

        messages.error(
            self.request, "Veuillez vous connecter pour accéder à l'Espace Mali."
        )
        return redirect("index")


class DashboardView(LoginRequiredMixin, AgentMaliRequiredMixin, TemplateView):
    template_name = "mali/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Récupérer le pays Mali
        try:
            mali = Country.objects.get(code="ML")
        except Country.DoesNotExist:
            context["error"] = "Pays Mali non configuré"
            return context

        # Date du jour et mois en cours
        today = timezone.now().date()
        first_day_of_month = today.replace(day=1)

        # Note: Le modèle Colis utilise les status: RECU, EXPEDIE, ARRIVE, LIVRE
        # Pas TRANSIT ou STOCK. Nous devons ajuster selon les vrais statuts.

        # 1. Colis Livrés (mois en cours)
        context["colis_livres_mois"] = Colis.objects.filter(
            lot__destination=mali, status="LIVRE", created_at__gte=first_day_of_month
        ).count()

        # 2. Dépenses (mois) - hardcodé à 0 pour l'instant
        context["depenses_mois"] = 0

        # 3. Colis Perdus (mois en cours)
        # Assuming we'll add a PERDU status later, for now it's 0
        context["colis_perdus_mois"] = 0

        # 4. Colis en attente de paiement (non payés)
        context["colis_attente_paiement"] = Colis.objects.filter(
            lot__destination=mali, status="LIVRE", est_paye=False
        ).count()

        # 5. Colis à Traiter (Arrivés, non livrés)
        context["colis_a_traiter"] = Colis.objects.filter(
            lot__destination=mali, status="ARRIVE"
        ).count()

        # 6. Lots en Transit
        context["lots_en_transit"] = Lot.objects.filter(
            destination=mali, status="EN_TRANSIT"
        ).count()

        # 7. Lots Arrivés (Incomplets) - Au moins 1 colis status ARRIVE
        lots_avec_stock = Lot.objects.filter(
            destination=mali, colis__status="ARRIVE"
        ).distinct()
        context["lots_arrives_incomplets"] = lots_avec_stock.count()

        # 7b. Lots Livrés (Mois) - Lots avec tous les colis livrés ce mois
        # Pour l'instant, on compte les lots avec statut LIVRE ou tous colis livrés
        context["lots_livres_mois"] = Lot.objects.filter(
            destination=mali, status="LIVRE", created_at__gte=first_day_of_month
        ).count()

        # 8. Encaissements du Jour (Montant total des livraisons du jour)
        encaissements = Colis.objects.filter(
            lot__destination=mali, status="LIVRE", created_at__date=today
        ).aggregate(total=Sum("prix_final"))
        context["encaissements_jour"] = encaissements["total"] or 0

        # 9. Total Clients Mali
        context["total_clients_mali"] = Client.objects.filter(country=mali).count()

        # Activité récente (derniers colis pointés/livrés aujourd'hui)
        context["activites_recentes"] = (
            Colis.objects.filter(
                lot__destination=mali,
                status__in=["ARRIVE", "LIVRE"],
                created_at__date=today,
            )
            .select_related("client", "lot")
            .order_by("-created_at")[:10]
        )

        return context


class AujourdhuiView(LoginRequiredMixin, AgentMaliRequiredMixin, TemplateView):
    """Page Aujourd'hui avec statistiques quotidiennes et rapports imprimables"""

    template_name = "mali/aujourdhui.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Récupérer le pays Mali
        try:
            mali = Country.objects.get(code="ML")
        except Country.DoesNotExist:
            context["error"] = "Pays Mali non configuré"
            return context

        today = timezone.now().date()

        # Statistiques quotidiennes
        # 1. Colis en attente de livraison (renommé de "Colis Attendus")
        context["colis_attente_livraison"] = Colis.objects.filter(
            lot__destination=mali, status="EXPEDIE"
        ).count()

        # 2. Colis Arrivés Aujourd'hui
        context["colis_arrives_aujourdhui"] = Colis.objects.filter(
            lot__destination=mali, status="ARRIVE", created_at__date=today
        ).count()

        # 3. Colis Livrés Aujourd'hui
        context["colis_livres_aujourdhui"] = Colis.objects.filter(
            lot__destination=mali, status="LIVRE", created_at__date=today
        ).count()

        # Données pour le rapport du jour
        context["colis_livres_detail"] = (
            Colis.objects.filter(
                lot__destination=mali, status="LIVRE", created_at__date=today
            )
            .select_related("client", "lot")
            .order_by("-created_at")
        )

        # Encaissements du jour pour la recette
        encaissements = Colis.objects.filter(
            lot__destination=mali, status="LIVRE", created_at__date=today
        ).aggregate(total=Sum("prix_final"))
        context["encaissements_jour"] = encaissements["total"] or 0

        return context


class LotsEnTransitView(LoginRequiredMixin, AgentMaliRequiredMixin, ListView):
    """Liste des lots en transit vers le Mali"""

    template_name = "mali/lots_transit.html"
    context_object_name = "lots"
    paginate_by = 20

    def get_queryset(self):
        try:
            mali = Country.objects.get(code="ML")
        except Country.DoesNotExist:
            return Lot.objects.none()

        queryset = (
            Lot.objects.filter(destination=mali, status="EN_TRANSIT")
            .select_related("destination")
            .prefetch_related("colis")
            .annotate(
                nb_colis=Count("colis"),
                poids_total=Sum("colis__poids"),
                total_recettes=Sum("colis__prix_final"),
            )
        )

        query = self.request.GET.get("q")
        if query:
            from django.db.models import Q, Value
            from django.db.models.functions import Concat

            # Recherche par numéro lot ou client (nom, prénom, téléphone, ou nom complet)
            queryset = (
                queryset.annotate(
                    full_name_search=Concat(
                        "colis__client__nom", Value(" "), "colis__client__prenom"
                    ),
                    full_name_alt=Concat(
                        "colis__client__prenom", Value(" "), "colis__client__nom"
                    ),
                )
                .filter(
                    Q(numero__icontains=query)
                    | Q(colis__client__nom__icontains=query)
                    | Q(colis__client__prenom__icontains=query)
                    | Q(colis__client__telephone__icontains=query)
                    | Q(full_name_search__icontains=query)
                    | Q(full_name_alt__icontains=query)
                )
                .distinct()
            )

        return queryset.order_by("-date_expedition")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["q"] = self.request.GET.get("q", "")
        # On peut aussi ajouter total_lots car il semble utilisé dans le template
        context["total_lots"] = self.get_queryset().count()
        return context


class LotDetailView(LoginRequiredMixin, AgentMaliRequiredMixin, DetailView):
    """Vue détaillée d'un lot pour l'agent Mali (avec pointage des colis)"""

    model = Lot
    template_name = "mali/lot_detail.html"
    context_object_name = "lot"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from django.db.models import Sum, Q

        # Calculs financiers sur TOUS les colis du lot (indépendamment de la recherche)
        aggregates = self.object.colis.aggregate(
            total_poids=Sum("poids"),
            total_cbm=Sum("cbm"),
            total_montant=Sum("prix_final"),
        )
        context["total_poids"] = aggregates["total_poids"] or 0
        context["total_cbm"] = aggregates["total_cbm"] or 0
        context["total_montant_colis"] = aggregates["total_montant"] or 0

        # Calcul Bénéfice Net (Recettes - Frais Expédition - Frais Douane)
        frais_exp = self.object.frais_transport or 0
        frais_douane = self.object.frais_douane or 0
        context["benefice"] = context["total_montant_colis"] - frais_exp - frais_douane

        # Colis du lot (avec support recherche et pagination)
        from django.core.paginator import Paginator

        colis_queryset = self.object.colis.all().order_by("-created_at")

        qc = self.request.GET.get("qc")
        if qc:
            from django.db.models import Value
            from django.db.models.functions import Concat

            colis_queryset = colis_queryset.annotate(
                nom_complet=Concat("client__nom", Value(" "), "client__prenom"),
                prenom_complet=Concat("client__prenom", Value(" "), "client__nom"),
            ).filter(
                Q(reference__icontains=qc)
                | Q(client__nom__icontains=qc)
                | Q(client__prenom__icontains=qc)
                | Q(client__telephone__icontains=qc)
                | Q(nom_complet__icontains=qc)
                | Q(prenom_complet__icontains=qc)
            )
            context["qc"] = qc

        paginator = Paginator(colis_queryset, 20)
        page_number = self.request.GET.get("page")
        context["colis_list"] = paginator.get_page(page_number)

        return context


class ColisArriveView(LoginRequiredMixin, AgentMaliRequiredMixin, View):
    """Marquer un colis individuel comme ARRIVÉ (Pointage)"""

    def post(self, request, pk):
        colis = get_object_or_404(Colis, pk=pk)

        # Restriction : frais de douane requis pour pointer
        if not colis.lot.frais_douane:
            if request.headers.get("HX-Request"):
                from django.shortcuts import render

                return render(
                    request,
                    "mali/partials/colis_status_badge.html",
                    {"colis": colis, "lot": colis.lot, "error_locked": True},
                )
            messages.error(
                request,
                "Veuillez renseigner les frais de douane du lot avant de pointer les colis.",
            )
            return redirect("mali:lot_detail", pk=colis.lot.pk)

        colis.status = "ARRIVE"
        colis.save()

        if request.headers.get("HX-Request"):
            from django.shortcuts import render

            return render(
                request,
                "mali/partials/colis_status_badge.html",
                {"colis": colis, "lot": colis.lot},
            )

        messages.success(request, f"Colis {colis.reference} marqué comme Arrivé.")
        return redirect("mali:lot_detail", pk=colis.lot.pk)


class LotArriveView(LoginRequiredMixin, AgentMaliRequiredMixin, View):
    """Vue pour finaliser l'arrivée d'un lot et saisir les frais"""

    def post(self, request, pk):
        lot = get_object_or_404(Lot, pk=pk)

        # Mise à jour des frais (optionnel)
        frais_douane = request.POST.get("frais_douane")
        frais_transport = request.POST.get("frais_transport")

        if frais_douane:
            lot.frais_douane = frais_douane
        if frais_transport:
            lot.frais_transport = frais_transport

        # Si le lot était en transit, il passe en ARRIVE (global)
        if lot.status == "EN_TRANSIT":
            lot.status = "ARRIVE"
            lot.date_arrivee = timezone.now()

        lot.save()

        # On peut aussi forcer l'arrivée de tous les colis non pointés si on veut
        # lot.colis.filter(status="EXPEDIE").update(status="ARRIVE")

        messages.success(request, f"Le lot {lot.numero} a été mis à jour avec succès.")
        return redirect("mali:lot_detail", pk=lot.pk)
