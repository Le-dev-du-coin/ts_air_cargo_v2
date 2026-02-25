from django.views.generic import TemplateView, ListView, View, DetailView
from django.views.generic.edit import UpdateView
from django.shortcuts import get_object_or_404, redirect
from django.http import HttpResponse
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.urls import reverse_lazy
from django.db.models import Q, Count, Sum, Value, F
from django.db.models.functions import Concat
from core.mixins import DestinationAgentRequiredMixin
from core.models import Country, Lot, Colis, Client
from report.models import Depense
from django.contrib import messages

from notification.models import ConfigurationNotification
from .forms import NotificationConfigForm

import logging

logger = logging.getLogger(__name__)


class DashboardView(LoginRequiredMixin, DestinationAgentRequiredMixin, TemplateView):
    template_name = "mali/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Récupérer la destination dynamique
        mali = self.get_current_country()
        if not mali:
            context["error"] = "Destination non configurée"
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
        depenses_classiques_mois_qs = Depense.objects.filter(
            pays=mali, date__year=today.year, date__month=today.month
        )
        depenses_classiques_mois = (
            depenses_classiques_mois_qs.aggregate(total=Sum("montant"))["total"] or 0
        )

        # 2b. Transferts (mois) - Considérés comme dépenses
        from report.models import TransfertArgent

        transferts_mois_qs = TransfertArgent.objects.filter(
            pays_expediteur=mali, date__year=today.year, date__month=today.month
        )
        transferts_mois = (
            transferts_mois_qs.aggregate(total=Sum("montant"))["total"] or 0
        )

        # Total Dépenses (Classiques + Transferts)
        depenses_mois = depenses_classiques_mois + transferts_mois

        context["depenses_mois"] = depenses_mois
        context["depenses_classiques_mois"] = (
            depenses_classiques_mois  # Pour info si besoin
        )
        context["transferts_mois"] = transferts_mois  # Pour info si besoin

        # Solde du mois (Recettes - Dépenses Totales)
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


class AujourdhuiView(LoginRequiredMixin, DestinationAgentRequiredMixin, TemplateView):
    """Page Aujourd'hui avec statistiques quotidiennes et rapports imprimables"""

    template_name = "mali/aujourdhui.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Récupérer la destination dynamique
        mali = self.get_current_country()
        if not mali:
            context["error"] = "Destination non configurée"
            return context

        today = timezone.now().date()
        from report.models import TransfertArgent

        # --- 1. SOLDE VEILLE (Report) ---
        # Calcul : Total Recettes (depuis début) - Total Dépenses (depuis début) jusqu'à hier
        from django.db.models import Sum, F

        recettes_globales = (
            Colis.objects.filter(
                lot__destination=mali,
                status="LIVRE",
                est_paye=True,
                updated_at__date__lt=today,  # Avant aujourd'hui
            ).aggregate(total=Sum(F("prix_final") - F("montant_jc")))["total"]
            or 0
        )

        depenses_globales = (
            Depense.objects.filter(pays=mali, date__lt=today).aggregate(
                total=Sum("montant")
            )["total"]
            or 0
        )

        # Les transferts sont considérés comme des dépenses (sorties de caisse)
        transferts_globaux = (
            TransfertArgent.objects.filter(
                pays_expediteur=mali, date__lt=today
            ).aggregate(total=Sum("montant"))["total"]
            or 0
        )

        context["solde_veille"] = recettes_globales - (
            depenses_globales + transferts_globaux
        )

        # --- 2. ACTIVITÉ DU JOUR (Cargo, Express, Bateau) ---
        colis_livres_jour = Colis.objects.filter(
            lot__destination=mali, status="LIVRE", est_paye=True, updated_at__date=today
        ).select_related("client", "lot")

        # Séparation par type de transport (via le Lot)
        # Note: Lot.type_transport choices: CARGO, EXPRESS, BATEAU

        # A. Cargo (Air)
        colis_cargo = colis_livres_jour.filter(lot__type_transport="CARGO")
        recette_cargo = (
            colis_cargo.aggregate(total=Sum(F("prix_final") - F("montant_jc")))["total"]
            or 0
        )
        context["colis_cargo_list"] = colis_cargo.annotate(
            net_price=F("prix_final") - F("montant_jc")
        ).order_by("-updated_at")
        context["recette_cargo_jour"] = recette_cargo

        # B. Express (Air)
        colis_express = colis_livres_jour.filter(lot__type_transport="EXPRESS")
        recette_express = (
            colis_express.aggregate(total=Sum(F("prix_final") - F("montant_jc")))[
                "total"
            ]
            or 0
        )
        context["colis_express_list"] = colis_express.annotate(
            net_price=F("prix_final") - F("montant_jc")
        ).order_by("-updated_at")
        context["recette_express_jour"] = recette_express

        # C. Bateau (Maritime)
        colis_bateau = colis_livres_jour.filter(lot__type_transport="BATEAU")
        recette_bateau = (
            colis_bateau.aggregate(total=Sum(F("prix_final") - F("montant_jc")))[
                "total"
            ]
            or 0
        )
        context["colis_bateau_list"] = colis_bateau.annotate(
            net_price=F("prix_final") - F("montant_jc")
        ).order_by("-updated_at")
        context["recette_bateau_jour"] = recette_bateau

        # Total Recettes Jour
        context["total_recettes_jour"] = (
            recette_cargo + recette_express + recette_bateau
        )

        # Total JC Jour (Pour info)
        context["total_jc_jour"] = (
            colis_livres_jour.aggregate(total=Sum("montant_jc"))["total"] or 0
        )

        # --- 3. DÉPENSES & TRANSFERTS DU JOUR ---
        # Dépenses
        depenses_jour_qs = Depense.objects.filter(pays=mali, date=today).order_by(
            "-created_at"
        )
        total_depenses = depenses_jour_qs.aggregate(total=Sum("montant"))["total"] or 0

        # Transferts (considérés comme dépenses jour)

        transferts_jour_qs = TransfertArgent.objects.filter(
            pays_expediteur=mali, date=today
        ).order_by("-created_at")
        total_transferts = (
            transferts_jour_qs.aggregate(total=Sum("montant"))["total"] or 0
        )

        context["depenses_jour_list"] = depenses_jour_qs
        context["transferts_jour_list"] = transferts_jour_qs
        context["total_sorties_jour"] = total_depenses + total_transferts
        context["total_depenses_only"] = total_depenses
        context["total_transferts_only"] = total_transferts

        # --- 4. SOLDE CAISSE ACTUEL ---
        # Solde Veille + Recettes Jour - Sorties Jour
        context["solde_caisse_actuel"] = (
            context["solde_veille"]
            + context["total_recettes_jour"]
            - context["total_sorties_jour"]
        )

        return context


class LotsEnTransitView(LoginRequiredMixin, DestinationAgentRequiredMixin, ListView):
    """Liste des lots en transit vers le Mali"""

    template_name = "mali/lots_transit.html"
    context_object_name = "lots"
    paginate_by = 20

    def get_queryset(self):
        mali = self.get_current_country()
        if not mali:
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
        mali = self.get_current_country()
        if not mali:
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
        mali = self.get_current_country()
        if not mali:
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


class LotDetailView(LoginRequiredMixin, DestinationAgentRequiredMixin, DetailView):
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

        colis_queryset = self.object.colis.select_related("client").order_by(
            "-created_at"
        )

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


class ColisArriveView(LoginRequiredMixin, DestinationAgentRequiredMixin, View):
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

        # Notification immédiate au client avec rappel du prix
        try:
            from notification.tasks import send_notification_async
            from django.contrib.humanize.templatetags.humanize import intcomma

            if colis.client and colis.client.user:
                prix = colis.prix_final or 0
                jc = colis.montant_jc or 0
                montant_a_payer = max(0, prix - jc)
                fmt_prix = f"{montant_a_payer:,.0f}".replace(",", " ")

                date_arrive = timezone.now().strftime("%d/%m/%Y \u00e0 %H:%M")
                nom_pointage = (
                    colis.client.user.get_full_name() or colis.client.user.username
                )
                notif_msg = (
                    f"Bonjour *{nom_pointage}*,\n\n"
                    f"📍 *Bonne nouvelle ! Votre colis est arriv\u00e9 !*\n\n"
                    f"Nous venons de r\u00e9ceptionner votre colis *{colis.reference}* "
                    f"dans notre agence au Mali 🇲🇱 le *{date_arrive}*.\n\n"
                    f"💰 *Montant \u00e0 r\u00e9gler : {fmt_prix} FCFA*\n\n"
                    f"Merci de passer le r\u00e9cup\u00e9rer \u00e0 votre convenance.\n\n"
                    f"🌐 Suivez vos colis : https://ts-aircargo.com/login\n"
                    f"\u2014\u2014\n"
                    f"*\u00c9quipe TS AIR CARGO* 🇨🇳 🇲🇱 🇨🇮"
                )
                send_notification_async.delay(
                    user_id=colis.client.user.id,
                    message=notif_msg,
                    categorie="colis_arrive",
                    titre=f"Colis {colis.reference} arrivé — {fmt_prix} FCFA à régler",
                    region="mali",
                )
        except Exception as e:
            import logging as _log

            _log.getLogger(__name__).error(
                f"Erreur notif pointage colis {colis.pk}: {e}"
            )

        if request.headers.get("HX-Request"):
            from django.shortcuts import render
            import json

            response = render(
                request,
                "mali/partials/colis_status_badge.html",
                {"colis": colis, "lot": colis.lot},
            )
            # Déclenche l'événement JS "colisArrived" écouté dans lot_transit_detail.html
            # → retire le <li id="colis-item-{pk}"> avec animation de sortie
            response["HX-Trigger"] = json.dumps({"colisArrived": {"pk": colis.pk}})
            return response

        messages.success(request, f"Colis {colis.reference} marqué comme Arrivé.")
        return redirect("mali:lot_transit_detail", pk=colis.lot.pk)


class LotArriveView(LoginRequiredMixin, DestinationAgentRequiredMixin, View):
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

        # Enregistrer la date d'arrivée si pas encore définie
        if not lot.date_arrivee:
            lot.date_arrivee = timezone.now()

        # Si le lot était en transit, il passe en ARRIVE (global)
        # MODIF : On ne change PAS le statut automatiquement ici pour permettre le pointage dans la vue Transit.
        # Le statut passera à ARRIVE quand ? Manuellement ou quand tout est pointé ?
        # Pour l'instant on laisse en TRANSIT pour que l'agent puisse voir la liste et pointer.
        # if lot.status == "EN_TRANSIT":
        #    lot.status = "ARRIVE"
        #    lot.date_arrivee = timezone.now()

        lot.save()

        # On peut aussi forcer l'arrivée de tous les colis non pointés si on veut
        # lot.colis.filter(status="EXPEDIE").update(status="ARRIVE")

        messages.success(
            request,
            f"Frais enregistrés pour le lot {lot.numero}. Vous pouvez maintenant pointer les colis.",
        )
        return redirect("mali:lot_transit_detail", pk=lot.pk)


class NotifyArrivalsView(LoginRequiredMixin, DestinationAgentRequiredMixin, View):
    """Déclenche les notifications groupées pour les colis arrivés (pointés)"""

    def post(self, request, pk):
        lot = get_object_or_404(Lot, pk=pk)

        # Trouver les colis ARRIVE dans ce lot qui n'ont pas encore été notifiés par WhatsApp
        colis_to_notify = lot.colis.filter(
            status="ARRIVE", whatsapp_notified=False
        ).select_related("client", "client__user")

        if not colis_to_notify.exists():
            messages.warning(request, "Aucun nouveau colis pointé à notifier.")
            return redirect("mali:lot_transit_detail", pk=pk)

        # Grouper par client
        by_client = {}
        for c in colis_to_notify:
            if not c.client or not c.client.user:
                continue
            if c.client.id not in by_client:
                by_client[c.client.id] = {"user": c.client.user, "colis": []}
            by_client[c.client.id]["colis"].append(c)

        count_clients = 0
        from notification.tasks import send_notification_async

        for cid, data in by_client.items():
            user = data["user"]
            colis_list = data["colis"]
            nb = len(colis_list)
            refs = ", ".join([c.reference for c in colis_list])

            message = (
                f"📦 *Colis Arrivé(s) au Mali*\n\n"
                f"Bonjour {user.get_full_name() or user.username},\n"
                f"Vos colis suivants sont disponibles à l'agence :\n"
                f"Ref(s): *{refs}*\n\n"
                f"Merci de passer pour le retrait."
            )

            send_notification_async.delay(
                user_id=user.id,
                message=message,
                categorie="colis_arrive",
                titre=f"Arrivée de {nb} colis",
                region="mali",
            )

            # Marquer comme notifié
            lot.colis.filter(id__in=[c.id for c in colis_list]).update(
                whatsapp_notified=True
            )
            count_clients += 1

        messages.success(request, f"Notifications envoyées à {count_clients} clients.")
        return redirect("mali:lot_transit_detail", pk=pk)


class NotifyArrivalsView(LoginRequiredMixin, DestinationAgentRequiredMixin, View):
    """Déclenche les notifications groupées pour les colis arrivés (pointés)"""

    def post(self, request, pk):
        lot = get_object_or_404(Lot, pk=pk)

        # Trouver les colis ARRIVE dans ce lot qui n'ont pas encore été notifiés par WhatsApp
        colis_to_notify = lot.colis.filter(
            status="ARRIVE", whatsapp_notified=False
        ).select_related("client", "client__user")

        if not colis_to_notify.exists():
            messages.warning(request, "Aucun nouveau colis pointé à notifier.")
            return redirect("mali:lot_transit_detail", pk=pk)

        # Grouper par client
        by_client = {}
        for c in colis_to_notify:
            if not c.client or not c.client.user:
                continue
            if c.client.id not in by_client:
                by_client[c.client.id] = {"user": c.client.user, "colis": []}
            by_client[c.client.id]["colis"].append(c)

        count_clients = 0
        from notification.tasks import send_notification_async

        for cid, data in by_client.items():
            user = data["user"]
            colis_list = data["colis"]
            nb = len(colis_list)

            # Construire la liste détaillée avec le prix de chaque colis
            lines = []
            total = 0
            for c in colis_list:
                prix = max(0, (c.prix_final or 0) - (c.montant_jc or 0))
                total += prix
                fmt = f"{prix:,.0f}".replace(",", " ")
                lines.append(f"   \u2022 *{c.reference}* — {fmt} FCFA")

            liste_str = "\n".join(lines)
            fmt_total = f"{total:,.0f}".replace(",", " ")

            nom_notify = user.get_full_name() or user.username
            message = (
                f"Bonjour *{nom_notify}*,\n\n"
                f"📍 *{'Bonne nouvelle ! Votre colis est arriv\u00e9 !' if nb == 1 else f'Bonne nouvelle ! Vos {nb} colis sont arriv\u00e9s !'}*\n\n"
                f"Nous venons de r\u00e9ceptionner {'votre colis' if nb == 1 else 'vos colis'} \u00e0 l'agence au Mali 🇲🇱 :\n"
                f"{liste_str}\n\n"
                f"💰 *Total \u00e0 r\u00e9gler : {fmt_total} FCFA*\n\n"
                f"Merci de passer {'le' if nb == 1 else 'les'} r\u00e9cup\u00e9rer \u00e0 votre convenance.\n\n"
                f"🌐 Suivez vos colis : https://ts-aircargo.com/login\n"
                f"\u2014\u2014\n"
                f"*\u00c9quipe TS AIR CARGO* 🇨🇳 🇲🇱 🇨🇮"
            )

            send_notification_async.delay(
                user_id=user.id,
                message=message,
                categorie="colis_arrive",
                titre=f"{'Colis arrivé' if nb == 1 else f'{nb} colis arrivés'} — {fmt_total} FCFA à régler",
                region="mali",
            )

            # Marquer comme notifié
            lot.colis.filter(id__in=[c.id for c in colis_list]).update(
                whatsapp_notified=True
            )
            count_clients += 1

        messages.success(request, f"Notifications envoyées à {count_clients} clients.")
        return redirect("mali:lot_transit_detail", pk=pk)


class ColisLivreView(LoginRequiredMixin, DestinationAgentRequiredMixin, View):
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

        colis.status = "LIVRE"
        colis.save()

        # Notification Livraison (Async)
        try:
            from notification.tasks import send_notification_async

            if colis.client and colis.client.user:
                nom_livre = (
                    colis.client.user.get_full_name() or colis.client.user.username
                )
                message = (
                    f"Bonjour *{nom_livre}*,\n\n"
                    f"\u2705 *Livraison r\u00e9ussie !*\n\n"
                    f"Votre colis *{colis.reference}* a bien \u00e9t\u00e9 livr\u00e9 avec succ\u00e8s.\n\n"
                    f"Merci d'avoir choisi TS AIR CARGO pour vos envois !\n"
                    f"Nous esp\u00e9rons vous revoir tr\u00e8s prochainement. 😊\n\n"
                    f"🌐 Cr\u00e9ez une nouvelle commande : https://ts-aircargo.com/login\n"
                    f"\u2014\u2014\n"
                    f"*\u00c9quipe TS AIR CARGO* 🇨🇳 🇲🇱 🇨🇮"
                )
                send_notification_async.delay(
                    user_id=colis.client.user.id,
                    message=message,
                    categorie="colis_livre",
                    titre=f"Livraison effectuée - {colis.reference}",
                    region="mali",
                )
        except Exception as e:
            from chine.views import logger

            logger.error(f"Erreur trigger notification livraison {colis.id}: {e}")

        if request.headers.get("HX-Request"):
            from django.shortcuts import render
            from django.http import HttpResponse

            # Check if we are in transit mode context (sent by hidden input)
            if request.POST.get("context") == "transit":
                return HttpResponse(
                    f'<li id="colis-item-{colis.pk}" hx-swap-oob="delete"></li>'
                )

            return render(
                request,
                "mali/partials/colis_status_badge.html",
                {"colis": colis, "lot": colis.lot},
            )

        messages.success(request, f"Colis {colis.reference} livré avec succès.")
        return redirect("mali:lot_arrived_detail", pk=colis.lot.pk)


class ColisPerduView(LoginRequiredMixin, DestinationAgentRequiredMixin, View):
    """Marquer un colis comme PERDU"""

    def post(self, request, pk):
        colis = get_object_or_404(Colis, pk=pk)
        colis.status = "PERDU"
        colis.save()

        if request.headers.get("HX-Request"):
            from django.http import HttpResponse

            return HttpResponse(
                f'<li id="colis-item-{colis.pk}" hx-swap-oob="delete"></li>'
            )

        messages.warning(request, f"Colis {colis.reference} marqué comme PERDU.")
        return redirect("mali:lot_arrived_detail", pk=colis.lot.pk)


class ColisAttentePaiementView(
    LoginRequiredMixin, DestinationAgentRequiredMixin, ListView
):
    """Liste des colis LIVRÉS mais NON PAYÉS"""

    template_name = "mali/colis_attente_paiement.html"
    context_object_name = "colis_list"
    paginate_by = 20

    def get_queryset(self):
        mali = self.get_current_country()
        if not mali:
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


class ColisEncaissementView(LoginRequiredMixin, DestinationAgentRequiredMixin, View):
    """Encaisser un colis (marquer comme payé) avec mise à jour de la date"""

    def post(self, request, pk):
        colis = get_object_or_404(Colis, pk=pk)

        # Marquer comme payé
        colis.est_paye = True
        # Force update of updated_at to ensure it counts for TODAY's report
        colis.updated_at = timezone.now()
        colis.save()

        messages.success(request, f"Paiement encaissé pour le colis {colis.reference}.")

        # Redirection vers la liste des paiements en attente (ou la page précédente)
        return redirect("mali:colis_attente_paiement")


class RapportJourPDFView(LoginRequiredMixin, DestinationAgentRequiredMixin, View):
    """Génération du rapport journalier en PDF (xhtml2pdf)"""

    def get(self, request):
        today = timezone.now().date()
        report_type = request.GET.get(
            "type", "global"
        )  # global, cargo, express, bateau

        # Titre du rapport selon le type
        titre_rapport = "Rapport Journalier Global"
        if report_type == "cargo":
            titre_rapport = "Rapport Journalier - CARGO"
        elif report_type == "express":
            titre_rapport = "Rapport Journalier - EXPRESS"
        elif report_type == "bateau":
            titre_rapport = "Rapport Journalier - BATEAU"

        # Base QuerySet : Colis livrés et payés aujourd'hui au Mali
        colis_qs = (
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

        # Filtrage par type
        if report_type in ["cargo", "express", "bateau"]:
            colis_qs = colis_qs.filter(lot__type_transport=report_type.upper())

        # Calcul des totaux pour ces colis filtrés
        encaissements = colis_qs.aggregate(total=Sum("net_price"))["total"] or 0
        total_jc = colis_qs.aggregate(total=Sum("montant_jc"))["total"] or 0

        # Récupération des dépenses et transferts (Uniquement pour le rapport Global ?)
        # Décision : On affiche les dépenses/transferts uniquement sur le rapport Global
        # Car il est difficile de les attribuer à une activité spécifique (sauf si on catégorise les transferts)
        total_depenses = 0
        total_transferts = 0
        solde_veille = 0

        if report_type == "global":
            # Solde Veille
            recettes_globales_veille = (
                Colis.objects.filter(
                    lot__destination__code="ML",
                    status="LIVRE",
                    est_paye=True,
                    updated_at__date__lt=today,
                ).aggregate(total=Sum(F("prix_final") - F("montant_jc")))["total"]
                or 0
            )
            depenses_globales_veille = (
                Depense.objects.filter(pays__code="ML", date__lt=today).aggregate(
                    total=Sum("montant")
                )["total"]
                or 0
            )
            from report.models import TransfertArgent

            transferts_globaux_veille = (
                TransfertArgent.objects.filter(
                    pays_expediteur__code="ML", date__lt=today
                ).aggregate(total=Sum("montant"))["total"]
                or 0
            )
            solde_veille = recettes_globales_veille - (
                depenses_globales_veille + transferts_globaux_veille
            )

            # Dépenses Jour
            total_depenses = (
                Depense.objects.filter(pays__code="ML", date=today).aggregate(
                    total=Sum("montant")
                )["total"]
                or 0
            )
            # Transferts Jour
            total_transferts = (
                TransfertArgent.objects.filter(
                    pays_expediteur__code="ML", date=today
                ).aggregate(total=Sum("montant"))["total"]
                or 0
            )

        # Calcul du solde final (pour ce rapport)
        # Si Global : Solde Veille + Recettes - (Dépenses + Transferts)
        # Si Spécifique : Juste Recettes (car pas de dépenses spécifiques trackées ici)
        solde_final = 0
        if report_type == "global":
            solde_final = (
                solde_veille + encaissements - (total_depenses + total_transferts)
            )
        else:
            solde_final = (
                encaissements  # Pour un rapport spécifique, le solde est le CA généré
            )

        # Contexte pour le template
        context = {
            "date": today,
            "report_type": report_type,
            "titre_rapport": titre_rapport,
            "colis_list": colis_qs,  # Renommé pour cohérence avec template (vérifier template)
            "total_encaissements": encaissements,
            "total_jc": total_jc,
            "total_depenses": total_depenses,
            "total_transferts": total_transferts,
            "solde_veille": solde_veille,
            "solde_final": solde_final,
            "user": request.user,
        }

        # Génération du HTML
        from django.template.loader import render_to_string
        from xhtml2pdf import pisa

        # Vérifier si le template attend 'colis_livres' ou 'colis_list'
        # Je vais utiliser 'colis_livres' comme avant pour minimiser les changements template si possible,
        # mais 'colis_list' est plus standard. Je vais passer les deux pour être sûr ou vérifier le template.
        context["colis_livres"] = colis_qs

        html_string = render_to_string("mali/pdf/rapport_jour.html", context)

        # Création du PDF
        response = HttpResponse(content_type="application/pdf")
        filename = f"rapport_jour_{report_type}_{today}.pdf"
        response["Content-Disposition"] = f'inline; filename="{filename}"'

        pisa_status = pisa.CreatePDF(html_string, dest=response)

        if pisa_status.err:
            return HttpResponse("Erreur lors de la génération du PDF", status=500)

        return response


class LotTransitPDFView(LoginRequiredMixin, DestinationAgentRequiredMixin, View):
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


class NotificationConfigView(
    LoginRequiredMixin, DestinationAgentRequiredMixin, UpdateView
):
    """
    Permet à l'agent Mali de configurer les rappels automatiques.
    NB : La configuration des credentials API WaChap est gestion de l'admin_app.
    """

    model = ConfigurationNotification
    form_class = NotificationConfigForm  # Rappels uniquement
    template_name = "mali/config_notifications.html"
    success_url = reverse_lazy("mali:dashboard")

    def get_object(self, queryset=None):
        return ConfigurationNotification.get_solo()

    def form_valid(self, form):
        messages.success(self.request, "✅ Configuration des rappels mise à jour.")
        return super().form_valid(form)
