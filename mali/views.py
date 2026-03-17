from django.views.generic import TemplateView, ListView, View, DetailView
from django.views.generic.edit import UpdateView
from django.shortcuts import get_object_or_404, redirect, render
from django.http import HttpResponse
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.urls import reverse_lazy
from django.db.models import Q, Count, Sum, Value, F, DecimalField
from django.db.models.functions import Concat, Coalesce
from core.mixins import DestinationAgentRequiredMixin, AdminMaliRequiredMixin
from core.models import Country, Lot, Colis, Client, User
from report.models import Depense
from django.contrib import messages

from notification.models import ConfigurationNotification
from .forms import NotificationConfigForm

import logging

logger = logging.getLogger(__name__)


def apply_flexible_search(queryset, query, search_fields):
    """
    Applique une recherche flexible : chaque mot de la requête doit se trouver
    dans au moins un des champs de recherche (Logique AND entre les mots).
    """
    if not query:
        return queryset

    words = query.split()
    for word in words:
        q_obj = Q()
        for field in search_fields:
            if "__icontains" not in field:
                q_obj |= Q(**{f"{field}__icontains": word})
            else:
                q_obj |= Q(**{field: word})
        queryset = queryset.filter(q_obj)
    return queryset.distinct()


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

        # Poids total des colis livrés (mois en cours)
        total_poids_mois = colis_livres_mois_qs.aggregate(
            total=Sum("poids")
        )["total"] or 0
        context["total_poids_mois"] = total_poids_mois

        # 2. Dépenses (mois)
        depenses_classiques_mois_qs = Depense.objects.filter(
            pays=mali, date__year=today.year, date__month=today.month, is_china_indicative=False
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

        # Date du rapport (aujourd'hui par défaut)
        date_str = self.request.GET.get("date")
        if date_str:
            try:
                from datetime import datetime

                target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                target_date = timezone.now().date()
        else:
            target_date = timezone.now().date()

        context["target_date"] = target_date
        today = target_date
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
            Depense.objects.filter(pays=mali, date__lt=today, is_china_indicative=False).aggregate(
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
            lot__destination=mali, status="LIVRE", updated_at__date=today
        ).select_related("client", "lot")

        # Séparation par type de transport (via le Lot)
        # Note: Lot.type_transport choices: CARGO, EXPRESS, BATEAU

        # A. Cargo (Air)
        colis_cargo = colis_livres_jour.filter(lot__type_transport="CARGO")
        recette_cargo = (
            colis_cargo.aggregate(
                total=Sum(F("prix_final") - F("montant_jc") - F("reste_a_payer"))
            )["total"]
            or 0
        )
        poids_cargo = colis_cargo.aggregate(total=Sum("poids"))["total"] or 0
        
        context["colis_cargo_list"] = colis_cargo.annotate(
            net_price=F("prix_final") - F("montant_jc") - F("reste_a_payer")
        ).order_by("-updated_at")
        context["recette_cargo_jour"] = recette_cargo
        context["poids_cargo_jour"] = poids_cargo

        # B. Express (Air)
        colis_express = colis_livres_jour.filter(lot__type_transport="EXPRESS")
        recette_express = (
            colis_express.aggregate(
                total=Sum(F("prix_final") - F("montant_jc") - F("reste_a_payer"))
            )["total"]
            or 0
        )
        poids_express = colis_express.aggregate(total=Sum("poids"))["total"] or 0
        
        context["colis_express_list"] = colis_express.annotate(
            net_price=F("prix_final") - F("montant_jc") - F("reste_a_payer")
        ).order_by("-updated_at")
        context["recette_express_jour"] = recette_express
        context["poids_express_jour"] = poids_express

        # C. Bateau (Maritime)
        colis_bateau = colis_livres_jour.filter(lot__type_transport="BATEAU")
        recette_bateau = (
            colis_bateau.aggregate(
                total=Sum(F("prix_final") - F("montant_jc") - F("reste_a_payer"))
            )["total"]
            or 0
        )
        poids_bateau = colis_bateau.aggregate(total=Sum("poids"))["total"] or 0
        cbm_bateau = colis_bateau.aggregate(total=Sum("cbm"))["total"] or 0
        
        context["colis_bateau_list"] = colis_bateau.annotate(
            net_price=F("prix_final") - F("montant_jc") - F("reste_a_payer")
        ).order_by("-updated_at")
        context["recette_bateau_jour"] = recette_bateau
        context["poids_bateau_jour"] = poids_bateau
        context["cbm_bateau_jour"] = cbm_bateau

        # Total Recettes Jour
        context["total_recettes_jour"] = (
            recette_cargo + recette_express + recette_bateau
        )
        
        # Poids Total Jour (Kilos livrés du jour)
        context["total_poids_jour"] = poids_cargo + poids_express + poids_bateau

        # Total JC Jour (Pour info)
        context["total_jc_jour"] = (
            colis_livres_jour.aggregate(total=Sum("montant_jc"))["total"] or 0
        )

        # --- 3. DÉPENSES & TRANSFERTS DU JOUR ---
        # Dépenses - On exclut les dépenses indicatives Chine du solde Mali
        depenses_jour_qs = Depense.objects.filter(pays=mali, date=today).order_by(
            "-created_at"
        )
        
        # Dépenses réelles (Mali)
        total_depenses_mali = depenses_jour_qs.filter(
            is_china_indicative=False
        ).aggregate(total=Sum("montant"))["total"] or 0
        
        # Dépenses indicatives (Chine)
        total_depenses_chine = depenses_jour_qs.filter(
            is_china_indicative=True
        ).aggregate(total=Sum("montant"))["total"] or 0

        # Transferts (considérés comme dépenses jour)
        transferts_jour_qs = TransfertArgent.objects.filter(
            pays_expediteur=mali, date=today
        ).order_by("-created_at")
        
        total_transferts = (
            transferts_jour_qs.aggregate(total=Sum("montant"))["total"] or 0
        )

        context["depenses_jour_list"] = depenses_jour_qs
        context["transferts_jour_list"] = transferts_jour_qs
        
        # Séparation des transferts pour l'affichage
        context["transferts_chine_list"] = transferts_jour_qs.filter(destinataire="CHINE")
        context["transferts_gaoussou_list"] = transferts_jour_qs.filter(destinataire="GAOUSSOU")
        
        # Sorties Jour réelles (pour solde caisse)
        context["total_sorties_jour"] = total_depenses_mali + total_transferts
        context["total_depenses_only"] = total_depenses_mali
        context["total_depenses_chine_only"] = total_depenses_chine
        context["total_transferts_only"] = total_transferts

        # --- 4. SOLDE CAISSE ACTUEL ---
        # Solde Veille + Recettes Jour - Sorties Jour (Réelles)
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
                # Nombre de colis déjà payés en Chine dans ce lot (parmi les colis en transit)
                nb_colis_payes_chine=Count(
                    "colis",
                    filter=Q(colis__status="EXPEDIE", colis__est_paye=True),
                ),
            )
            .filter(nb_colis_transit__gt=0)
            .distinct()
        )

        query = self.request.GET.get("q")
        if query:
            queryset = queryset.annotate(
                nom_complet=Concat(
                    "colis__client__nom", Value(" "), "colis__client__prenom"
                ),
                prenom_complet=Concat(
                    "colis__client__prenom", Value(" "), "colis__client__nom"
                ),
            )
            search_fields = [
                "numero",
                "colis__client__nom",
                "colis__client__prenom",
                "colis__client__telephone",
                "nom_complet",
                "prenom_complet",
            ]
            queryset = apply_flexible_search(queryset, query, search_fields)

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
                # Nombre de colis déjà payés en Chine (parmi les colis arrivés)
                nb_colis_payes_chine=Count(
                    "colis",
                    filter=Q(colis__status="ARRIVE", colis__est_paye=True),
                ),
            )
            .filter(nb_colis_arrive__gt=0)
            .distinct()
        )

        query = self.request.GET.get("q")
        if query:
            queryset = queryset.annotate(
                nom_complet=Concat(
                    "colis__client__nom", Value(" "), "colis__client__prenom"
                ),
                prenom_complet=Concat(
                    "colis__client__prenom", Value(" "), "colis__client__nom"
                ),
            )
            search_fields = [
                "numero",
                "colis__client__nom",
                "colis__client__prenom",
                "colis__client__telephone",
                "nom_complet",
                "prenom_complet",
            ]
            queryset = apply_flexible_search(queryset, query, search_fields)

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
                # Nombre de colis payés en Chine parmi les livrés/perdus
                nb_colis_payes_chine=Count(
                    "colis",
                    filter=Q(
                        colis__status__in=["LIVRE", "PERDU"], colis__paye_en_chine=True
                    ),
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
            queryset = queryset.annotate(
                nom_complet=Concat(
                    "colis__client__nom", Value(" "), "colis__client__prenom"
                ),
            )
            search_fields = [
                "numero",
                "colis__client__nom",
                "colis__client__telephone",
                "nom_complet",
            ]
            queryset = apply_flexible_search(queryset, query, search_fields)

        return queryset.order_by("-updated_at")


class ColisSortieGarantieView(
    LoginRequiredMixin, DestinationAgentRequiredMixin, ListView
):
    """Liste des colis sortis sous garantie avec filtres de période et stats"""

    template_name = "mali/colis_sortie_garantie.html"
    context_object_name = "colis_list"
    paginate_by = 20

    def get_queryset(self):
        mali = self.get_current_country()
        if not mali:
            return Colis.objects.none()

        queryset = Colis.objects.filter(
            lot__destination=mali,
            status="LIVRE",
            sortie_sous_garantie=True,
        ).select_related("client", "lot")

        now = timezone.now()
        self.filter_month = self.request.GET.get("month", "")
        self.filter_year = self.request.GET.get("year", "")

        if self.filter_year:
            try:
                queryset = queryset.filter(updated_at__year=int(self.filter_year))
            except (ValueError, TypeError):
                pass
        if self.filter_month:
            try:
                queryset = queryset.filter(updated_at__month=int(self.filter_month))
            except (ValueError, TypeError):
                pass

        # Filtre textuel
        query = self.request.GET.get("q")
        if query:
            queryset = queryset.annotate(
                nom_complet=Concat("client__nom", Value(" "), "client__prenom"),
            ).filter(
                Q(reference__icontains=query)
                | Q(client__nom__icontains=query)
                | Q(nom_complet__icontains=query)
                | Q(sortie_autorisee_par__icontains=query)
            )

        return queryset.order_by("-updated_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        now = timezone.now()

        mali = self.get_current_country()

        # Queryset non paginé pour stats
        base_qs = (
            Colis.objects.filter(
                lot__destination=mali,
                status="LIVRE",
                sortie_sous_garantie=True,
            )
            if mali
            else Colis.objects.none()
        )

        # Stats globales
        total_stats = base_qs.aggregate(
            total_count=Count("id"),
            total_montant=Sum(F("prix_final") - F("montant_jc")),
        )

        # Stats mois en cours
        stats_month = base_qs.filter(
            updated_at__year=now.year, updated_at__month=now.month
        ).aggregate(
            count=Count("id"),
            montant=Sum(F("prix_final") - F("montant_jc")),
        )

        # Stats année en cours
        stats_year = base_qs.filter(updated_at__year=now.year).aggregate(
            count=Count("id"),
            montant=Sum(F("prix_final") - F("montant_jc")),
        )

        context.update(
            {
                "filter_month": self.filter_month,
                "filter_year": self.filter_year,
                "current_year": now.year,
                "current_month": now.month,
                "years_range": range(now.year - 2, now.year + 1),
                "stats_total": {
                    "count": total_stats["total_count"] or 0,
                    "montant": total_stats["total_montant"] or 0,
                },
                "stats_month": {
                    "count": stats_month["count"] or 0,
                    "montant": stats_month["montant"] or 0,
                },
                "stats_year": {
                    "count": stats_year["count"] or 0,
                    "montant": stats_year["montant"] or 0,
                },
            }
        )
        return context


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
            colis_queryset = colis_queryset.annotate(
                nom_complet=Concat("client__nom", Value(" "), "client__prenom"),
                prenom_complet=Concat("client__prenom", Value(" "), "client__nom"),
            )
            search_fields = [
                "reference",
                "client__nom",
                "client__prenom",
                "client__telephone",
                "poids",
                "nom_complet",
                "prenom_complet",
            ]
            colis_queryset = apply_flexible_search(colis_queryset, qc, search_fields)
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
                prenom_complet=Concat("client__prenom", Value(" "), "client__nom"),
            )
            search_fields = [
                "reference",
                "client__nom",
                "client__prenom",
                "client__telephone",
                "poids",
                "nom_complet",
                "prenom_complet",
            ]
            colis_qs = apply_flexible_search(colis_qs, qc, search_fields)
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
                | Q(client__telephone__icontains=qc)
                | Q(poids__icontains=qc)
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

        qc = self.request.GET.get("qc")
        if qc:
            colis_qs = colis_qs.annotate(
                nom_complet=Concat("client__nom", Value(" "), "client__prenom"),
            ).filter(
                Q(reference__icontains=qc)
                | Q(client__nom__icontains=qc)
                | Q(nom_complet__icontains=qc)
                | Q(client__telephone__icontains=qc)
                | Q(poids__icontains=qc)
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


class ColisArriveBulkView(LoginRequiredMixin, DestinationAgentRequiredMixin, View):
    """Marquer plusieurs colis comme ARRIVÉ (Pointage Groupé) et envoyer une seule notification par client"""

    def post(self, request, pk):
        lot = get_object_or_404(Lot, pk=pk)
        colis_ids = request.POST.getlist("colis_ids")

        if not colis_ids:
            messages.warning(request, "Aucun colis sélectionné.")
            return redirect("mali:lot_transit_detail", pk=lot.pk)

        # Restriction : frais de douane requis pour pointer
        if not lot.frais_douane:
            if request.headers.get("HX-Request"):
                from django.http import HttpResponse

                return HttpResponse(
                    '<div id="bulk-error" class="text-xs font-bold text-red-500 bg-red-50 p-2 rounded border border-red-200 mb-4">'
                    "⚠️ Veuillez renseigner les frais de douane du lot avant de pointer les colis."
                    "</div>",
                    status=400,
                )
            messages.error(
                request,
                "Veuillez renseigner les frais de douane du lot avant de pointer les colis.",
            )
            return redirect("mali:lot_transit_detail", pk=lot.pk)

        colis_qs = Colis.objects.filter(id__in=colis_ids, lot=lot, status="EXPEDIE")

        if not colis_qs.exists():
            if request.headers.get("HX-Request"):
                from django.http import HttpResponse

                return HttpResponse()
            return redirect("mali:lot_transit_detail", pk=lot.pk)

        # Get list of colis objects before updating status
        colis_list = list(colis_qs.select_related("client", "client__user"))

        # Mettre à jour le statut en masse
        colis_qs.update(status="ARRIVE")

        # Grouper les notifications par client pour envoi combiné
        from notification.tasks import send_notification_async

        by_client = {}
        for c in colis_list:
            if not c.client or not c.client.user:
                continue
            if c.client.id not in by_client:
                by_client[c.client.id] = {"user": c.client.user, "colis": []}
            by_client[c.client.id]["colis"].append(c)

        for cid, data in by_client.items():
            user = data["user"]
            client_colis = data["colis"]
            nb = len(client_colis)

            lines = []
            total = 0
            for c in client_colis:
                prix = max(0, (c.prix_final or 0) - (c.montant_jc or 0))
                total += prix
                fmt = f"{prix:,.0f}".replace(",", " ")

                details = ""
                if c.type_colis == "TELEPHONE":
                    details = f" - {c.nombre_pieces} unité(s)"
                elif c.poids:
                    details = f" - {c.poids} kg"

                lines.append(f"   \u2022 *{c.reference}*{details} — {fmt} FCFA")

            liste_str = "\n".join(lines)
            fmt_total = f"{total:,.0f}".replace(",", " ")
            nom_notify = user.get_full_name() or user.username

            date_arrive = timezone.now().strftime("%d/%m/%Y \u00e0 %H:%M")
            message = (
                f"Bonjour *{nom_notify}*,\n\n"
                f"📍 *{'Bonne nouvelle ! Votre colis est arriv\u00e9 !' if nb == 1 else f'Bonne nouvelle ! Vos {nb} colis sont arriv\u00e9s !'}*\n\n"
                f"Nous venons de r\u00e9ceptionner {'votre colis' if nb == 1 else 'vos colis'} \u00e0 l'agence au Mali 🇲🇱 le *{date_arrive}* :\n"
                f"{liste_str}\n\n"
                f"💰 *Total \u00e0 r\u00e9gler : {fmt_total} FCFA*\n\n"
                f"Merci de passer {'le' if nb == 1 else 'les'} r\u00e9cup\u00e9rer \u00e0 votre convenance.\n\n"
                f"🌐 Suivez vos colis : https://ts-aircargo.com/login\n"
                f"\u2014\u2014\n"
                f"*\u00c9quipe TS AIR CARGO* 🇨🇳 🇲🇱 🇨🇮"
            )

            try:
                send_notification_async.delay(
                    user_id=user.id,
                    message=message,
                    categorie="colis_arrive",
                    titre=f"{'Colis arrivé' if nb == 1 else f'{nb} colis arrivés'} — {fmt_total} FCFA à régler",
                    region="mali",
                )

                # Marquer comme notifié (sinon NotifyArrivalsView spammerait à nouveau)
                Colis.objects.filter(id__in=[c.id for c in client_colis]).update(
                    whatsapp_notified=True
                )

            except Exception as e:
                import logging as _log

                _log.getLogger(__name__).error(
                    f"Erreur notif bulk pointage colis lot {lot.pk}: {e}"
                )

        if request.headers.get("HX-Request"):
            from django.http import HttpResponse
            import json

            response = HttpResponse("")
            response["HX-Trigger"] = json.dumps(
                {"colisArrivedBulk": {"pks": [c.id for c in colis_list]}}
            )
            return response

        messages.success(request, f"{len(colis_list)} colis marqués comme Arrivés.")
        return redirect("mali:lot_transit_detail", pk=lot.pk)


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

        # Gestion Sortie sous Garantie
        if request.POST.get("sortie_sous_garantie") == "on":
            colis.sortie_sous_garantie = True
            colis.sortie_autorisee_par = request.POST.get("sortie_autorisee_par", "")
        else:
            colis.sortie_sous_garantie = False
            colis.sortie_autorisee_par = ""

        # Gestion Jeton Cédé
        try:
            jc = request.POST.get("montant_jc", "0")
            colis.montant_jc = float(jc) if jc else 0
        except ValueError:
            colis.montant_jc = 0

        # Gestion Paiement
        # Si le colis a été payé en Chine, on préserve est_paye=True (anti double-encaissement),
        # Sinon, on applique le choix du formulaire : PAYE ou NON_PAYE (en attente)
        if colis.paye_en_chine:
            # Déjà encaissé en Chine — immutable
            colis.est_paye = True
        else:
            status_paiement = request.POST.get("status_paiement")
            if status_paiement == "PAYE":
                colis.est_paye = True
                colis.reste_a_payer = 0
            elif status_paiement == "NON_PAYE":
                colis.est_paye = False  # -> "En attente de paiement"
                try:
                    rp = request.POST.get("reste_a_payer", "0")
                    colis.reste_a_payer = float(rp) if rp else 0
                except ValueError:
                    colis.reste_a_payer = 0

        colis.mode_paiement = request.POST.get("mode_paiement")

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


class ColisLivreBulkView(LoginRequiredMixin, DestinationAgentRequiredMixin, View):
    """Marquer plusieurs colis comme LIVRÉ (Livraison Groupée) avec paiement standard"""

    def post(self, request, pk):
        lot = get_object_or_404(Lot, pk=pk)
        colis_ids = request.POST.getlist("colis_ids")

        if not colis_ids:
            messages.warning(request, "Aucun colis sélectionné pour la livraison.")
            return redirect("mali:lot_arrived_detail", pk=lot.pk)

        colis_qs = Colis.objects.filter(id__in=colis_ids, lot=lot, status="ARRIVE")

        if not colis_qs.exists():
            if request.headers.get("HX-Request"):
                from django.http import HttpResponse

                return HttpResponse()
            return redirect("mali:lot_arrived_detail", pk=lot.pk)

        # Get list of colis objects before updating
        colis_list = list(colis_qs.select_related("client", "client__user"))

        # Mettre à jour en masse : Statut LIVRÉ et Paiement NON_PAYÉ (En attente) par défaut
        # comme demandé (action directe sans modal)
        for c in colis_list:
            c.status = "LIVRE"
            c.mode_livraison = "AGENCE"
            # Si déjà payé en Chine on garde, sinon on met en attente (False)
            if not c.paye_en_chine:
                c.est_paye = False
                c.reste_a_payer = max(0, (c.prix_final or 0) - (c.montant_jc or 0))

        Colis.objects.bulk_update(
            colis_list, ["status", "mode_livraison", "est_paye", "reste_a_payer"]
        )

        # Grouper les notifications
        from notification.tasks import send_notification_async

        by_client = {}
        for c in colis_list:
            if not c.client or not c.client.user:
                continue
            if c.client.id not in by_client:
                by_client[c.client.id] = {"user": c.client.user, "colis": []}
            by_client[c.client.id]["colis"].append(c)

        for cid, data in by_client.items():
            user = data["user"]
            client_colis = data["colis"]
            nb = len(client_colis)

            nom_livre = user.get_full_name() or user.username
            lines = []
            for c in client_colis:
                details = ""
                if c.type_colis == "TELEPHONE":
                    details = f" - {c.nombre_pieces} unité(s)"
                elif c.poids:
                    details = f" - {c.poids} kg"
                lines.append(f"   \u2022 *{c.reference}*{details}")

            liste_str = "\n".join(lines)
            message = (
                f"Bonjour *{nom_livre}*,\n\n"
                f"\u2705 *{'Livraison r\u00e9ussie !' if nb == 1 else f'Livraison r\u00e9ussie pour vos {nb} colis !'}*\n\n"
                f"{'Le colis suivant a' if nb == 1 else 'Les colis suivants ont'} bien \u00e9t\u00e9 livr\u00e9{'s' if nb > 1 else ''} avec succ\u00e8s :\n"
                f"{liste_str}\n\n"
                f"Merci d'avoir choisi TS AIR CARGO pour vos envois !\n"
                f"Nous esp\u00e9rons vous revoir tr\u00e8s prochainement. 😊\n\n"
                f"🌐 Cr\u00e9ez une nouvelle commande : https://ts-aircargo.com/login\n"
                f"\u2014\u2014\n"
                f"*\u00c9quipe TS AIR CARGO* 🇨🇳 🇲🇱 🇨🇮"
            )

            try:
                send_notification_async.delay(
                    user_id=user.id,
                    message=message,
                    categorie="colis_livre",
                    titre=f"Livraison effectuée - {nb} colis",
                    region="mali",
                )
            except Exception as e:
                import logging as _log

                _log.getLogger(__name__).error(
                    f"Erreur notif bulk livraison lot {lot.pk}: {e}"
                )

        if request.headers.get("HX-Request"):
            from django.http import HttpResponse
            import json

            response = HttpResponse("")
            response["HX-Trigger"] = json.dumps(
                {"colisLivreBulk": {"pks": [c.id for c in colis_list]}}
            )
            return response

        messages.success(request, f"{len(colis_list)} colis livrés avec succès.")
        return redirect("mali:lot_arrived_detail", pk=lot.pk)


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

        from django.db.models import F, Case, When, DecimalField

        queryset = (
            Colis.objects.filter(lot__destination=mali, status="LIVRE", est_paye=False)
            .select_related("client", "lot")
            .annotate(
                montant_du=Case(
                    When(reste_a_payer__gt=0, then=F("reste_a_payer")),
                    default=F("prix_final") - F("montant_jc"),
                    output_field=DecimalField(),
                )
            )
            .order_by("-updated_at")
        )

        query = self.request.GET.get("q")
        if query:
            # (Recherche multi-mots gérée par le reste du code)
            queryset = apply_flexible_search(queryset, query)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Calcul du total des impayés basé sur l'annotation
        total_impaye = (
            self.get_queryset().aggregate(total=Sum("montant_du"))["total"] or 0
        )
        context["total_impaye"] = total_impaye
        context["q"] = self.request.GET.get("q", "")
        return context


class ColisEncaissementView(LoginRequiredMixin, DestinationAgentRequiredMixin, View):
    """Encaisser un colis (marquer comme payé) avec mise à jour de la date"""

    def post(self, request, pk):
        colis = get_object_or_404(Colis, pk=pk)

        # Marquer comme payé et solder le reste à payer
        colis.est_paye = True
        colis.reste_a_payer = 0
        # Force update of updated_at to ensure it counts for TODAY's report
        colis.updated_at = timezone.now()
        colis.save()

        messages.success(request, f"Paiement encaissé pour le colis {colis.reference}.")

        # Redirection vers la liste des paiements en attente (ou la page précédente)
        return redirect("mali:colis_attente_paiement")


class RapportJourPDFView(LoginRequiredMixin, DestinationAgentRequiredMixin, View):
    """Génération du rapport journalier en PDF (xhtml2pdf)"""

    def get(self, request):
        # Date du rapport
        date_str = request.GET.get("date")
        if date_str:
            try:
                from datetime import datetime

                target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                target_date = timezone.now().date()
        else:
            target_date = timezone.now().date()

        today = target_date
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
                ).aggregate(total=Sum(F("prix_final") - F("montant_jc") - F("reste_a_payer")))["total"]
                or 0
            )
            # Dépenses cumulées Mali uniquement
            depenses_globales_veille = (
                Depense.objects.filter(
                    pays__code="ML", 
                    date__lt=today,
                    is_china_indicative=False
                ).aggregate(total=Sum("montant"))["total"]
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

            # Dépenses Jour Mali uniquement
            total_depenses = (
                Depense.objects.filter(
                    pays__code="ML", 
                    date=today,
                    is_china_indicative=False
                ).aggregate(total=Sum("montant"))["total"]
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
        solde_final = 0
        if report_type == "global":
            solde_final = (
                solde_veille + encaissements - (total_depenses + total_transferts)
            )
        else:
            solde_final = (
                encaissements  # Pour un rapport spécifique, le solde est le CA généré
            )

        # Calcul du poids total pour le rapport
        total_poids = colis_qs.aggregate(total=Sum("poids"))["total"] or 0

        # Contexte pour le template
        context = {
            "date": today,
            "report_type": report_type,
            "titre_rapport": titre_rapport,
            "colis_list": colis_qs,
            "total_encaissements": encaissements,
            "total_jc": total_jc,
            "total_depenses": total_depenses,
            "total_transferts": total_transferts,
            "total_poids": total_poids,
            "solde_veille": solde_veille,
            "solde_final": solde_final,
            "user": request.user,
        }

        # Génération du PDF avec Playwright
        from core.utils_pdf import render_to_pdf_playwright

        # Vérifier si le template attend 'colis_livres' ou 'colis_list'
        context["colis_livres"] = colis_qs

        filename = f"rapport_jour_{report_type}_{today}.pdf"
        return render_to_pdf_playwright(
            "mali/pdf/rapport_jour.html", context, request, filename=filename
        )


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

        from core.utils_pdf import render_to_pdf_playwright

        filename = f"manifeste_lot_{lot.numero}.pdf"
        # Utilisation de l'orientation paysage si nécessaire pour les manifestes (souvent plus large)
        return render_to_pdf_playwright(
            "mali/pdf/manifeste_lot.html", context, request, filename=filename
        )


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


class MaliNotificationListView(
    LoginRequiredMixin, DestinationAgentRequiredMixin, ListView
):
    """Gestionnaire de notifications WhatsApp pour l'agent Mali (region='mali')"""

    template_name = "mali/notifications/list.html"
    context_object_name = "notifications"
    paginate_by = 50

    def get_queryset(self):
        from notification.models import Notification

        queryset = Notification.objects.filter(region="mali").order_by("-date_creation")

        # Filtres
        status = self.request.GET.get("status")
        date_start = self.request.GET.get("date_start")
        date_end = self.request.GET.get("date_end")
        q = self.request.GET.get("q")

        if status:
            queryset = queryset.filter(statut=status)
        if date_start:
            queryset = queryset.filter(date_creation__date__gte=date_start)
        if date_end:
            queryset = queryset.filter(date_creation__date__lte=date_end)
        if q:
            queryset = queryset.filter(
                Q(telephone_destinataire__icontains=q)
                | Q(message__icontains=q)
                | Q(erreur_envoi__icontains=q)
            )
        return queryset

    def get_context_data(self, **kwargs):
        from notification.models import Notification

        context = super().get_context_data(**kwargs)
        context["stats_notif"] = Notification.objects.filter(region="mali").aggregate(
            total=Count("id"),
            envoye=Count("id", filter=Q(statut="envoye")),
            echec=Count("id", filter=Q(statut="echec")),
            echec_permanent=Count("id", filter=Q(statut="echec_permanent")),
        )
        return context

    def post(self, request, *args, **kwargs):
        from notification.models import Notification

        action = request.POST.get("action")
        selected_ids = request.POST.getlist("selected_ids")

        single_id = request.POST.get("notification_id")
        if single_id and not selected_ids:
            selected_ids = [single_id]

        next_url = request.POST.get("next")
        base_url = reverse_lazy("mali:notification_list")

        if not selected_ids:
            messages.warning(request, "Aucune notification sélectionnée.")
            return redirect(f"{base_url}?{next_url}" if next_url else base_url)

        if action == "delete":
            deleted_count, _ = Notification.objects.filter(
                id__in=selected_ids, region="mali"
            ).delete()
            messages.success(request, f"{deleted_count} notification(s) supprimée(s).")

        elif action == "retry":
            from notification.tasks import retry_failed_notifications_periodic

            updated = Notification.objects.filter(
                id__in=selected_ids, region="mali"
            ).update(
                statut="echec", nombre_tentatives=0, prochaine_tentative=timezone.now()
            )
            retry_failed_notifications_periodic.delay(force_retry_all=True)
            messages.success(request, f"{updated} notification(s) relancée(s).")

        return redirect(f"{base_url}?{next_url}" if next_url else base_url)


class MaliRetryNotificationsView(
    LoginRequiredMixin, DestinationAgentRequiredMixin, View
):
    """Relance toutes les notifications en échec pour la région Mali"""

    def post(self, request):
        from notification.tasks import retry_failed_notifications_periodic

        retry_failed_notifications_periodic.delay(force_retry_all=True)
        messages.success(request, "Les relances WhatsApp Mali ont été déclenchées.")
        return redirect("mali:notification_list")


from django.views.generic import UpdateView
from .forms import ColisUpdateMaliForm


class ColisUpdateMaliView(
    LoginRequiredMixin, DestinationAgentRequiredMixin, UpdateView
):
    """Permet à l'agent Mali de corriger le poids, le CBM ou le prix d'un colis."""

    model = Colis
    form_class = ColisUpdateMaliForm
    template_name = "mali/colis_update.html"

    def get_success_url(self):
        messages.success(
            self.request, f"Colis {self.object.reference} mis à jour avec succès."
        )
        return reverse("mali:lot_transit_detail", kwargs={"pk": self.object.lot.pk})

    def form_valid(self, form):
        # Recalculer le prix_transport et prix_final
        colis = form.instance
        if colis.type_colis == "MANUEL" and colis.prix_kilo_manuel:
            colis.prix_transport = colis.poids * colis.prix_kilo_manuel

        # Le hook save() du modèle Colis contient déjà la logique de calcul de prix final

        return super().form_valid(form)

# --- VUES ADMIN MALI ---

class MaliAdminDashboardView(AdminMaliRequiredMixin, TemplateView):
    template_name = "mali/admin/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        mali = self.request.user.country
        
        # Stats globales
        context["total_agents"] = User.objects.filter(country=mali, role="AGENT_MALI").count()
        context["total_colis_mois"] = Colis.objects.filter(lot__destination=mali, created_at__month=timezone.now().month).count()
        
        # Dernières erreurs potentielles (ex: colis livrés aujourd'hui)
        context["recent_deliveries"] = Colis.objects.filter(lot__destination=mali, status="LIVRE").order_by("-updated_at")[:10]
        
        return context

class MaliAgentListView(AdminMaliRequiredMixin, ListView):
    model = User
    template_name = "mali/admin/agents_list.html"
    context_object_name = "agents"

    def get_queryset(self):
        return User.objects.filter(country=self.request.user.country, role="AGENT_MALI")

class MaliAgentCreateView(AdminMaliRequiredMixin, CreateView):
    model = User
    template_name = "mali/admin/agent_form.html"
    fields = ["username", "first_name", "last_name", "email", "phone", "password"]
    success_url = reverse_lazy("mali:admin_agents")

    def form_valid(self, form):
        user = form.save(commit=False)
        user.role = "AGENT_MALI"
        user.country = self.request.user.country
        user.set_password(form.cleaned_data["password"])
        user.save()
        messages.success(self.request, f"Agent {user.username} créé avec succès.")
        return super().form_valid(form)

class MaliAgentUpdateView(AdminMaliRequiredMixin, UpdateView):
    model = User
    template_name = "mali/admin/agent_form.html"
    fields = ["first_name", "last_name", "email", "phone", "is_active"]
    success_url = reverse_lazy("mali:admin_agents")

    def form_valid(self, form):
        messages.success(self.request, "Profil agent mis à jour.")
        return super().form_valid(form)

class MaliCorrectionListView(AdminMaliRequiredMixin, ListView):
    model = Colis
    template_name = "mali/admin/correction_list.html"
    context_object_name = "colis_list"
    paginate_by = 50

    def get_queryset(self):
        qs = Colis.objects.filter(lot__destination=self.request.user.country).order_by("-updated_at")
        search = self.request.GET.get("q")
        if search:
            qs = apply_flexible_search(qs, search, ["reference", "client__nom", "client__telephone"])
        return qs

class MaliActionRevertView(AdminMaliRequiredMixin, View):
    def post(self, request, pk):
        colis = get_object_or_404(Colis, pk=pk, lot__destination=request.user.country)
        action = request.POST.get("action")
        
        if action == "revert_to_transit" and colis.status == "ARRIVE":
            # Repasser en EXPEDIE (transit)
            colis.status = "EXPEDIE"
            colis.save()
            messages.success(request, f"Le carton {colis.reference} est repassé en TRANSIT.")
            
        elif action == "revert_to_arrive" and colis.status == "LIVRE":
            # Annulation encaissement si existant
            colis.status = "ARRIVE"
            colis.est_paye = False
            colis.save()
            messages.warning(request, f"Le carton {colis.reference} est repassé en ARRIVÉ. Le paiement a été annulé.")
            
        return redirect("mali:admin_correction_list")
