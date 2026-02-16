from django.views.generic import TemplateView, ListView, View, DetailView
from django.shortcuts import get_object_or_404, redirect
from django.http import HttpResponse
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.db.models import Q, Count, Sum, Value, F
from django.db.models.functions import Concat
from core.models import Country, Lot, Colis, Client
from report.models import Depense
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

        # 1. Colis Livrés (mois en cours) et Recettes
        colis_livres_mois_qs = Colis.objects.filter(
            lot__destination=mali, status="LIVRE", updated_at__gte=first_day_of_month
        )
        context["colis_livres_mois"] = colis_livres_mois_qs.count()

        # Recettes nettes du mois (déjà payés + livrés)
        recettes_mois = (
            colis_livres_mois_qs.filter(est_paye=True).aggregate(
                total=Sum(F("prix_final") - F("montant_jc"))
            )["total"]
            or 0
        )
        context["recettes_mois"] = recettes_mois

        # 2. Dépenses (mois)
        depenses_mois = (
            Depense.objects.filter(
                pays=mali, date__year=today.year, date__month=today.month
            ).aggregate(total=Sum("montant"))["total"]
            or 0
        )
        context["depenses_mois"] = depenses_mois

        # Solde du mois (Recettes - Dépenses)
        context["solde_mois"] = recettes_mois - depenses_mois

        # 3. Colis Perdus (mois en cours)
        context["colis_perdus_mois"] = Colis.objects.filter(
            lot__destination=mali, status="PERDU", updated_at__gte=first_day_of_month
        ).count()

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

        # 7b. Lots Livrés (Mois) - Lots ayant des colis livrés ce mois ci
        context["lots_livres_mois"] = (
            Lot.objects.filter(
                destination=mali,
                colis__status="LIVRE",
                colis__updated_at__gte=first_day_of_month,
            )
            .distinct()
            .count()
        )

        # 8. Encaissements du Jour (Montant total des livraisons du jour)
        encaissements = Colis.objects.filter(
            lot__destination=mali, status="LIVRE", updated_at__date=today
        ).aggregate(total=Sum("prix_final"))
        context["encaissements_jour"] = encaissements["total"] or 0

        # 9. Total Clients Mali
        context["total_clients_mali"] = Client.objects.filter(country=mali).count()

        # Activité récente (derniers colis pointés/livrés aujourd'hui)
        # Activité récente (derniers colis pointés/livrés aujourd'hui)
        context["activites_recentes"] = (
            Colis.objects.filter(
                lot__destination=mali,
                status__in=["ARRIVE", "LIVRE", "PERDU"],
                updated_at__date=today,
            )
            .select_related("client", "lot")
            .order_by("-updated_at")[:10]
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
            lot__destination=mali, status="LIVRE", updated_at__date=today
        ).count()

        # Données pour le rapport du jour
        context["colis_livres_detail"] = (
            Colis.objects.filter(
                lot__destination=mali,
                status="LIVRE",
                est_paye=True,
                updated_at__date=today,
            )
            .select_related("client", "lot")
            .annotate(net_price=F("prix_final") - F("montant_jc"))
            .order_by("-updated_at")
        )

        # Encaissements du jour pour la recette
        aggregates = context["colis_livres_detail"].aggregate(
            total_net=Sum("net_price"), total_jc=Sum("montant_jc")
        )
        context["encaissements_jour"] = aggregates["total_net"] or 0
        context["total_jc_jour"] = aggregates["total_jc"] or 0

        # Dépenses du jour
        depenses_jour_qs = Depense.objects.filter(pays=mali, date=today).order_by(
            "-created_at"
        )
        context["depenses_jour_list"] = depenses_jour_qs
        context["total_depenses_jour"] = (
            depenses_jour_qs.aggregate(total=Sum("montant"))["total"] or 0
        )

        # Cash Net du Jour (Recettes - Dépenses)
        context["cash_net_jour"] = (
            context["encaissements_jour"] - context["total_depenses_jour"]
        )

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

        # Un lot apparaît en transit s'il a au moins un colis EXPEDIE
        queryset = (
            Lot.objects.filter(destination=mali, colis__status="EXPEDIE")
            .select_related("destination")
            .prefetch_related("colis")
            .annotate(
                # On ne compte que les colis en transit pour ce lot dans cette vue
                nb_colis_transit=Count("colis", filter=Q(colis__status="EXPEDIE")),
                poids_total_transit=Sum(
                    "colis__poids", filter=Q(colis__status="EXPEDIE")
                ),
                total_recettes_transit=Sum(
                    "colis__prix_final", filter=Q(colis__status="EXPEDIE")
                ),
            )
            .filter(nb_colis_transit__gt=0)
            .distinct()
        )

        query = self.request.GET.get("q")
        if query:
            queryset = (
                queryset.annotate(
                    nom_complet=Concat(
                        "colis__client__nom", Value(" "), "colis__client__prenom"
                    ),
                    prenom_complet=Concat(
                        "colis__client__prenom", Value(" "), "colis__client__nom"
                    ),
                )
                .filter(
                    Q(numero__icontains=query)
                    | Q(colis__client__nom__icontains=query)
                    | Q(colis__client__prenom__icontains=query)
                    | Q(colis__client__telephone__icontains=query)
                    | Q(nom_complet__icontains=query)
                    | Q(prenom_complet__icontains=query)
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


class LotsArrivesView(LotsEnTransitView):
    """Vue historique des lots arrivés au Mali (statut ARRIVE ou LIVRE)"""

    template_name = "mali/lots_arrives.html"

    def get_queryset(self):
        try:
            mali = Country.objects.get(code="ML")
        except Country.DoesNotExist:
            return Lot.objects.none()

        # Un lot apparaît en arrivés s'il a au moins un colis ARRIVE
        queryset = (
            Lot.objects.filter(destination=mali, colis__status="ARRIVE")
            .select_related("destination")
            .prefetch_related("colis")
            .annotate(
                # On ne compte que les colis arrivés pour ce lot dans cette vue
                nb_colis_arrive=Count("colis", filter=Q(colis__status="ARRIVE")),
                poids_total_arrive=Sum(
                    "colis__poids", filter=Q(colis__status="ARRIVE")
                ),
                total_recettes_arrive=Sum(
                    "colis__prix_final", filter=Q(colis__status="ARRIVE")
                ),
            )
            .filter(nb_colis_arrive__gt=0)
            .distinct()
        )

        query = self.request.GET.get("q")
        if query:
            queryset = (
                queryset.annotate(
                    nom_complet=Concat(
                        "colis__client__nom", Value(" "), "colis__client__prenom"
                    ),
                    prenom_complet=Concat(
                        "colis__client__prenom", Value(" "), "colis__client__nom"
                    ),
                )
                .filter(
                    Q(numero__icontains=query)
                    | Q(colis__client__nom__icontains=query)
                    | Q(colis__client__prenom__icontains=query)
                    | Q(colis__client__telephone__icontains=query)
                    | Q(nom_complet__icontains=query)
                    | Q(prenom_complet__icontains=query)
                )
                .distinct()
            )

        return queryset.order_by("-date_arrivee", "-created_at")


class LotsLivresView(LotsEnTransitView):
    """Historique des lots ayant des colis LIVRÉS ou PERDUS"""

    template_name = "mali/lots_livres.html"

    def get_queryset(self):
        try:
            mali = Country.objects.get(code="ML")
        except Country.DoesNotExist:
            return Lot.objects.none()

        # Un lot apparaît en livrés s'il a au moins un colis LIVRE ou PERDU
        queryset = (
            Lot.objects.filter(destination=mali, colis__status__in=["LIVRE", "PERDU"])
            .select_related("destination")
            .prefetch_related("colis")
            .annotate(
                nb_colis_livre=Count(
                    "colis", filter=Q(colis__status__in=["LIVRE", "PERDU"])
                ),
                total_recettes_livre=Sum(
                    "colis__prix_final", filter=Q(colis__status__in=["LIVRE", "PERDU"])
                )
                - Sum(
                    "colis__montant_jc", filter=Q(colis__status__in=["LIVRE", "PERDU"])
                ),
            )
            .filter(nb_colis_livre__gt=0)
            .distinct()
        )

        # Filtrage par mois/année
        month = self.request.GET.get("month")
        year = self.request.GET.get("year")
        if month and year:
            queryset = queryset.filter(
                colis__updated_at__month=month, colis__updated_at__year=year
            )
        elif year:
            queryset = queryset.filter(colis__updated_at__year=year)

        query = self.request.GET.get("q")
        if query:
            queryset = (
                queryset.annotate(
                    nom_complet=Concat(
                        "colis__client__nom", Value(" "), "colis__client__prenom"
                    ),
                )
                .filter(
                    Q(numero__icontains=query)
                    | Q(colis__client__nom__icontains=query)
                    | Q(colis__client__telephone__icontains=query)
                )
                .distinct()
            )

        return queryset.order_by("-updated_at")


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
            total_jc=Sum("montant_jc"),
        )
        context["total_poids"] = aggregates["total_poids"] or 0
        context["total_cbm"] = aggregates["total_cbm"] or 0
        context["total_montant_colis"] = (aggregates["total_montant"] or 0) - (
            aggregates["total_jc"] or 0
        )

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


class LotTransitDetailView(LotDetailView):
    """Vue détaillée pour un lot en TRANSIT (Seulement colis EXPÉDIÉS)"""

    template_name = "mali/lot_transit_detail.html"

    def get_context_data(self, **kwargs):
        # On override pour ne filtrer que les colis EXPEDIE
        context = super().get_context_data(**kwargs)

        # Recalcul des agrégats pour les colis EXPEDIE uniquement
        aggregates = self.object.colis.filter(status="EXPEDIE").aggregate(
            total_poids=Sum("poids"),
            total_montant=Sum("prix_final"),
            total_jc=Sum("montant_jc"),
        )
        context["total_poids"] = aggregates["total_poids"] or 0
        context["total_montant_colis"] = (aggregates["total_montant"] or 0) - (
            aggregates["total_jc"] or 0
        )

        # Filtrage des colis listés
        colis_qs = self.object.colis.filter(status="EXPEDIE")

        qc = self.request.GET.get("qc")
        if qc:
            colis_qs = colis_qs.annotate(
                nom_complet=Concat("client__nom", Value(" "), "client__prenom"),
            ).filter(
                Q(reference__icontains=qc)
                | Q(client__nom__icontains=qc)
                | Q(nom_complet__icontains=qc)
            )

        from django.core.paginator import Paginator

        paginator = Paginator(colis_qs.order_by("-created_at"), 20)
        context["colis_list"] = paginator.get_page(self.request.GET.get("page"))
        context["is_transit_mode"] = True
        return context


class LotArriveDetailView(LotDetailView):
    """Vue détaillée pour un lot ARRIVÉ (Seulement colis ARRIVÉS)"""

    template_name = "mali/lot_arrived_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Recalcul des agrégats pour les colis ARRIVE uniquement
        aggregates = self.object.colis.filter(status="ARRIVE").aggregate(
            total_poids=Sum("poids"),
            total_montant=Sum("prix_final"),
        )
        context["total_poids"] = aggregates["total_poids"] or 0
        context["total_montant_colis"] = aggregates["total_montant"] or 0

        # Filtrage des colis listés
        colis_qs = self.object.colis.filter(status="ARRIVE")
        qc = self.request.GET.get("qc")
        if qc:
            colis_qs = colis_qs.annotate(
                nom_complet=Concat("client__nom", Value(" "), "client__prenom"),
            ).filter(
                Q(reference__icontains=qc)
                | Q(client__nom__icontains=qc)
                | Q(nom_complet__icontains=qc)
            )

        from django.core.paginator import Paginator

        paginator = Paginator(colis_qs.order_by("-created_at"), 20)
        context["colis_list"] = paginator.get_page(self.request.GET.get("page"))
        context["is_arrive_mode"] = True
        return context


class LotLivreDetailView(LotDetailView):
    """Vue détaillée pour un lot LIVRÉ/PERDU"""

    template_name = "mali/lot_livre_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Recalcul des agrégats pour les colis LIVRE/PERDU uniquement
        aggregates = self.object.colis.filter(status__in=["LIVRE", "PERDU"]).aggregate(
            total_montant=Sum("prix_final"),
            total_jc=Sum("montant_jc"),
        )
        context["total_montant_colis"] = (aggregates["total_montant"] or 0) - (
            aggregates["total_jc"] or 0
        )

        # Filtrage des colis listés
        colis_qs = self.object.colis.filter(status__in=["LIVRE", "PERDU"]).annotate(
            net_price=F("prix_final") - F("montant_jc")
        )

        from django.core.paginator import Paginator

        paginator = Paginator(colis_qs.order_by("-updated_at"), 20)
        context["colis_list"] = paginator.get_page(self.request.GET.get("page"))
        context["is_livre_mode"] = True
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
            return redirect("mali:lot_transit_detail", pk=colis.lot.pk)

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
        return redirect("mali:lot_transit_detail", pk=colis.lot.pk)


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
        return redirect("mali:lot_arrived_detail", pk=lot.pk)


class ColisLivreView(LoginRequiredMixin, AgentMaliRequiredMixin, View):
    """Marquer un colis individuel comme LIVRÉ"""

    def post(self, request, pk):
        colis = get_object_or_404(Colis, pk=pk)

        # On ne peut livrer qu'un colis ARRIVÉ
        if colis.status != "ARRIVE":
            messages.error(request, "Seuls les colis déjà arrivés peuvent être livrés.")
            return redirect("mali:lot_arrived_detail", pk=colis.lot.pk)

        # Mise à jour des informations de livraison
        colis.mode_livraison = request.POST.get("mode_livraison", "AGENCE")
        colis.infos_recepteur = request.POST.get("infos_recepteur", "")
        colis.commentaire_livraison = request.POST.get("commentaire", "")

        # Gestion Jeton Cédé
        try:
            jc = request.POST.get("montant_jc", "0")
            colis.montant_jc = float(jc) if jc else 0
        except ValueError:
            colis.montant_jc = 0

        # Gestion Paiement
        status_paiement = request.POST.get("status_paiement")
        if status_paiement == "PAYE":
            colis.est_paye = True

        # Gestion WhatsApp (Marquage uniquement pour l'instant)
        if request.POST.get("whatsapp_notified") == "on":
            colis.whatsapp_notified = True

        colis.status = "LIVRE"
        colis.save()

        if request.headers.get("HX-Request"):
            from django.shortcuts import render

            return render(
                request,
                "mali/partials/colis_status_badge.html",
                {"colis": colis, "lot": colis.lot},
            )

        messages.success(request, f"Colis {colis.reference} marqué comme Livré.")
        return redirect("mali:lot_arrived_detail", pk=colis.lot.pk)


class ColisPerduView(LoginRequiredMixin, AgentMaliRequiredMixin, View):
    """Marquer un colis comme PERDU"""

    def post(self, request, pk):
        colis = get_object_or_404(Colis, pk=pk)
        colis.status = "PERDU"
        colis.save()

        if request.headers.get("HX-Request"):
            from django.shortcuts import render

            return render(
                request,
                "mali/partials/colis_status_badge.html",
                {"colis": colis, "lot": colis.lot},
            )

        messages.warning(request, f"Colis {colis.reference} marqué comme PERDU.")
        return redirect("mali:lot_arrived_detail", pk=colis.lot.pk)


class ColisAttentePaiementView(LoginRequiredMixin, AgentMaliRequiredMixin, ListView):
    """Liste des colis LIVRÉS mais NON PAYÉS"""

    template_name = "mali/colis_attente_paiement.html"
    context_object_name = "colis_list"
    paginate_by = 20

    def get_queryset(self):
        try:
            mali = Country.objects.get(code="ML")
        except Country.DoesNotExist:
            return Colis.objects.none()

        queryset = (
            Colis.objects.filter(lot__destination=mali, status="LIVRE", est_paye=False)
            .select_related("client", "lot")
            .order_by("-updated_at")
        )

        query = self.request.GET.get("q")
        if query:
            queryset = (
                queryset.annotate(
                    nom_complet=Concat("client__nom", Value(" "), "client__prenom"),
                    prenom_complet=Concat("client__prenom", Value(" "), "client__nom"),
                )
                .filter(
                    Q(reference__icontains=query)
                    | Q(client__nom__icontains=query)
                    | Q(client__prenom__icontains=query)
                    | Q(client__telephone__icontains=query)
                    | Q(nom_complet__icontains=query)
                    | Q(prenom_complet__icontains=query)
                )
                .distinct()
            )
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Calcul du total des impayés
        total_impaye = (
            self.get_queryset().aggregate(total=Sum("prix_final"))["total"] or 0
        )
        context["total_impaye"] = total_impaye
        context["q"] = self.request.GET.get("q", "")
        return context


class RapportJourPDFView(LoginRequiredMixin, AgentMaliRequiredMixin, View):
    """Génération du rapport journalier en PDF (xhtml2pdf)"""

    def get(self, request):
        today = timezone.now().date()

        # Données du rapport
        colis_livres = (
            Colis.objects.filter(
                lot__destination__code="ML",
                status="LIVRE",
                est_paye=True,
                updated_at__date=today,
            )
            .select_related("client", "lot")
            .annotate(net_price=F("prix_final") - F("montant_jc"))
            .order_by("-updated_at")
        )

        encaissements = colis_livres.aggregate(total=Sum("net_price"))["total"] or 0
        total_jc = colis_livres.aggregate(total=Sum("montant_jc"))["total"] or 0

        # Contexte pour le template
        context = {
            "date": today,
            "total_jc": total_jc,
            "colis_livres": colis_livres,
            "total_encaissements": encaissements,
            "user": request.user,
        }

        # Génération du HTML
        from django.template.loader import render_to_string
        from xhtml2pdf import pisa

        html_string = render_to_string("mali/pdf/rapport_jour.html", context)

        # Création du PDF
        response = HttpResponse(content_type="application/pdf")
        response["Content-Disposition"] = (
            f'inline; filename="rapport_journalier_{today}.pdf"'
        )

        pisa_status = pisa.CreatePDF(html_string, dest=response)

        if pisa_status.err:
            return HttpResponse("Erreur lors de la génération du PDF", status=500)

        return response


class LotTransitPDFView(LoginRequiredMixin, AgentMaliRequiredMixin, View):
    """Génération du manifeste de lot en PDF"""

    def get(self, request, pk):
        lot = get_object_or_404(Lot, pk=pk)

        # Colis du lot triés par référence ou client
        colis_list = lot.colis.all().select_related("client").order_by("reference")

        context = {
            "lot": lot,
            "colis_list": colis_list,
            "total_poids": lot.colis.aggregate(Sum("poids"))["poids__sum"] or 0,
            "total_cbm": lot.colis.aggregate(Sum("cbm"))["cbm__sum"] or 0,
            "total_colis": lot.colis.count(),
            "user": request.user,
            "date_impression": timezone.now(),
        }

        from xhtml2pdf import pisa
        from django.template.loader import render_to_string

        html_string = render_to_string("mali/pdf/manifeste_lot.html", context)

        response = HttpResponse(content_type="application/pdf")
        response["Content-Disposition"] = (
            f'inline; filename="manifeste_lot_{lot.numero}.pdf"'
        )

        pisa_status = pisa.CreatePDF(html_string, dest=response)

        if pisa_status.err:
            return HttpResponse("Erreur lors de la génération du PDF", status=500)

        return response
